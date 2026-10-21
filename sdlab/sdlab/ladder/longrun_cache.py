"""Long-run metrics (longrun.py) per stored result, computed once and kept by result id.

A stored result's found flows never change, so its long-run metrics depend only on them, its case
variant's truth and data, and the long-run code: they are kept in $SDLAB_LADDER_CACHE/longrun.sqlite
under (result id, code hash). The server never computes them for the summary: `for_results` returns what is in the file (null:
not computed yet), re-reading only new rows at most every 10 s, and `version()` changes when new
ones appear so the summary picks them up. `sdlab-ladder longrun` fills them, in parallel worker
processes (niced); the run page computes one result's on request.
Grading takes ~0.05-0.5 s a result (the truth's side is shared by every result on a case variant).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed  # the CLI's fill only
from contextlib import contextmanager
from pathlib import Path

from . import sqlite_keep
from .data import cache_root

HERE = Path(__file__).resolve().parent
JOBS = int(os.environ.get("SDLAB_LONGRUN_JOBS") or 3)          # default workers of the CLI fill
BATCH = 40                                                       # results per task (one case variant each)


def code_hash() -> str:
    h = hashlib.sha256()
    for p in (HERE / "longrun.py", HERE / "jump.py", HERE / "parts.py", HERE.parent / "skill.py", HERE.parent / "discovery" / "simulate.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def path() -> Path:
    return cache_root() / "longrun.sqlite"


@contextmanager
def connect():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite_keep.connect(p, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS longrun (result_id INTEGER NOT NULL, code TEXT NOT NULL, value TEXT NOT NULL,"
                    " PRIMARY KEY (result_id, code))")
        yield con
        con.commit()
    finally:
        con.close()


# ---- computing (in any process) ----

def compute(case_id: str, variant: str, items: list[tuple[int, str]]) -> list[tuple[int, dict]]:
    """[(result id, metrics)] for results on one case variant ((id, found flows as JSON text))."""
    from . import cases as casemod
    from . import data, longrun
    try:
        c = casemod.load(case_id)
        if c.get("real"):            # a real-data case: graded by held-out prediction (real/score.py), no truth to run far
            return [(i, {"error": "real-data case: graded by real/score.py"}) for i, _ in items]
        if c.get("physics"):         # a physics case's long run is against the ODE (physics/score.py), not its reference model
            return [(i, {"error": "physics case: its long run is graded by physics/score.py"}) for i, _ in items]
        d = data.load(c, variant)
        setup = longrun.Setup(casemod.truth_model(c, variant), d.get("clean") or d)     # noise.py's variants: the run underneath
    except Exception as e:  # noqa: BLE001 - a case that cannot be set up is recorded, not retried
        return [(i, {"error": f"{type(e).__name__}: {e}"}) for i, _ in items]
    out = []
    for i, raw in items:
        try:
            out.append((i, longrun.grade(setup, json.loads(raw))))
        except Exception as e:  # noqa: BLE001
            out.append((i, {"error": f"{type(e).__name__}: {e}"}))
    return out


def _worker_init() -> None:
    try:
        os.nice(10)
    except OSError:
        pass


def _tasks(rows: list[dict]) -> list[tuple[str, str, list[tuple[int, str]]]]:
    from . import store
    found = store.found_flows([r["id"] for r in rows])
    groups: dict[tuple, list] = {}
    for r in rows:
        if found.get(r["id"]):
            groups.setdefault((r["case"], r["variant"]), []).append((r["id"], found[r["id"]]))
    return [(c, v, items[i:i + BATCH]) for (c, v), items in groups.items() for i in range(0, len(items), BATCH)]


def _save(pairs: list[tuple[int, dict]], code: str) -> None:
    with connect() as con:
        con.executemany("INSERT OR REPLACE INTO longrun (result_id, code, value) VALUES (?, ?, ?)",
                        [(i, code, json.dumps(v)) for i, v in pairs])
    with _lock:
        if _state["key"] == (str(path()), code):
            _state["known"].update(dict(pairs))


def fill(rows: list[dict], jobs: int = JOBS, progress=None) -> int:
    """Compute and keep the metrics of every row (stored results) not yet known; how many were made."""
    code = code_hash()
    todo = [r for r in rows if r.get("status") not in ("error", "timeout") and _get(r["id"], code) is _MISSING]
    tasks = _tasks(todo)
    done = 0
    if not tasks:
        return 0
    with ProcessPoolExecutor(max_workers=max(1, jobs), initializer=_worker_init) as ex:
        futs = [ex.submit(compute, *t) for t in tasks]
        for f in as_completed(futs):
            pairs = f.result()
            _save(pairs, code)
            done += len(pairs)
            if progress:
                progress(done, len(todo))
    return done


# ---- reading (the server): never computes, never starts a process ----

_MISSING = object()
_lock = threading.Lock()
_state: dict = {"key": None, "known": {}, "rowid": 0, "checked": 0.0}
REFRESH = 10.0          # seconds between looks at the cache file for metrics the CLI added


def _refresh(code: str) -> dict:
    """{result id: metrics} known for this code, read incrementally from the file (new rows only),
    at most every REFRESH seconds."""
    key = (str(path()), code)
    with _lock:
        if _state["key"] != key:
            _state.update(key=key, known={}, rowid=0, checked=0.0)
        if time.time() - _state["checked"] < REFRESH:
            return _state["known"]
        _state["checked"] = time.time()
        if path().exists():
            with connect() as con:
                rows = con.execute("SELECT rowid, result_id, value FROM longrun WHERE code = ? AND rowid > ? ORDER BY rowid",
                                   (code, _state["rowid"])).fetchall()
            for rowid, i, v in rows:
                _state["known"][i] = json.loads(v)
                _state["rowid"] = rowid
        return _state["known"]


def _get(result_id: int, code: str):
    return _refresh(code).get(result_id, _MISSING)


def version() -> tuple:
    """Changes whenever metrics arrive (for the summary's cache key)."""
    _refresh(code_hash())
    return (_state["key"], _state["rowid"])


def for_results(rows: list[dict]) -> dict[int, dict | None]:
    """{result id: metrics, or None when not computed yet (sdlab-ladder longrun) or nothing was found}."""
    known = _refresh(code_hash())
    return {r["id"]: known.get(r["id"]) for r in rows}


def of_result(row: dict, compute_missing: bool = False) -> dict | None:
    """One result's metrics (a row with its found flows); computed now only with compute_missing."""
    if row is None or row.get("status") in ("error", "timeout") or row.get("found") is None:
        return None
    code = code_hash()
    v = _get(row["id"], code)
    if v is _MISSING:
        if not compute_missing:
            return None
        pairs = compute(row["case"], row["variant"], [(row["id"], json.dumps(row["found"]))])
        _save(pairs, code)
        v = pairs[0][1]
    return v


def attach(row: dict | None) -> dict | None:
    if row is not None:
        row["longrun"] = of_result(row)
    return row


AGG = ("n", "far", "eq", "eq_n", "tau", "tau_n", "bad")


def aggregate(cells: list[tuple[str, str, int, dict | None]]) -> dict:
    """The leaderboard's long-run columns, compact: {strategy: {variant: {level: [n, sum err@100k,
    sum eq err, n eq, sum tau err, n tau, diverging]}}} from (strategy, variant, level, metrics) of
    every result with metrics. Each error is capped at 1; a run that runs away or is unstable counts
    1 for err@100k and eq err, and is "diverging" (as is one that dies out)."""
    out: dict = {}
    for strat, variant, level, m in cells:
        if not m or m.get("error"):
            continue
        a = out.setdefault(strat, {}).setdefault(variant, {}).setdefault(str(level), [0, 0.0, 0.0, 0, 0.0, 0, 0])
        hard = m.get("flag") in ("runaway", "unstable")
        cap = lambda v: 1.0 if hard or v is None else min(1.0, float(v))  # noqa: E731
        a[0] += 1
        a[1] += cap(m.get("far"))
        if hard or m.get("eq_err") is not None:
            a[2] += cap(m.get("eq_err"))
            a[3] += 1
        if m.get("tau_err") is not None:
            a[4] += min(1.0, float(m["tau_err"]))
            a[5] += 1
        a[6] += bool(m.get("flag"))
    for by_v in out.values():
        for by_l in by_v.values():
            for k, a in by_l.items():
                by_l[k] = [round(x, 4) if isinstance(x, float) else x for x in a]
    return out
