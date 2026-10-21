"""Strict pass: a second, stricter verdict beside pass / equivalent / fail. It never replaces pass
(score.py is unchanged, so history stays comparable); it asks more of a pass.

A result **strict-passes** when all of these hold:

1. it is a **pass** (score.py);
2. its complexity is **no greater than the truth's** (complexity.py: found total <= true total, so no
   extra flows, terms, pieces or other parts, however small);
3. its **long-run error** (longrun.py: both models run free from the run's start, no re-anchoring) at
   10 x the truth's slowest time constant (`10tau`; `100k` for a truth without one) is at most the
   cell's long-run threshold, and it does not run away or turn unstable (`hard_fail`);
4. its **fresh-run skill@100** (score.py's behaviour on the fresh run, seed + 1) is at least the
   cell's fresh threshold.

**Thresholds per cell** (case x variant) come from what the truth's own structure achieves on the
same kind of data, never from a fixed number:

- **refits**: the truth's structure with its numbers fitted on the run discovery saw, and on SEEDS
  more runs of the same case and variant (seeds model seed + 1000 + i, the variant's noise laid on
  each as data.py does): by maximum likelihood (fisher.TruthParams.ml_fit) when every stock is
  measured, by the Kalman filter's refit (noise_kf.SSM.refit) for a noisy variant (noise.py) or a
  linear truth with a hidden stock. In a noise-free variant (`none`) the data pin every number to
  their 4 decimals, so the refit is the truth itself (spread 0). A truth no refit covers (effects
  with a hidden stock: the realistic examples) has no reference.
- **edges**: EDGES copies of the truth with every rate number (constant, k, goal, time, linear c and
  k's, in every schedule change) and co-flow `per` moved by +-2% (score.py's `rel_exact`, the
  scorer's own tolerance for exact data) with random signs (fixed per cell): models the scorer would
  count right on every number even without noise. A threshold is never stricter than they do.
- Each refit and edge is graded exactly as a found model is: fresh skill@100 on the case's fresh run,
  long-run error at the same point on the same longrun.Setup.
- **fresh threshold** = min(mean - Z sd over the refits, the worst edge's skill);
  **long-run threshold** = max(mean + Z sd over the refits, the worst edge's error); Z = 3, the
  scorer's z. (sd over 1 + SEEDS refits; 0 in noise-free variants.)
- A criterion the truth's own refits cannot meet is **data-limited** in that cell and not applied:
  long run when a refit runs away or turns unstable (or its error is not finite); fresh when the run
  is too short for skill@100 (fewer than 110 steps), as score.py leaves it out then.

**Not computed** is never a fail: a pass with no extra complexity whose long-run metrics
(`sdlab-ladder longrun`) or reference (`sdlab-ladder strict`) are not in the caches yet has strict
None. A verdict that is already decided (not a pass, extra complexity, a run that diverges) needs
neither.

The references are computed offline, once per (case, case hash, variant, code hash), by
`sdlab-ladder strict` into $SDLAB_LADDER_CACHE/strict.sqlite (by default only for the cells some
stored result needs: a pass with no extra complexity); the server only reads them (refreshed at most
every 10 s), and the per-result verdict is a few comparisons on what the summary already holds
(scores, complexity by result id, long-run metrics by result id), so the summary stays fast and no
discovery re-runs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from . import sqlite_keep
from .data import cache_root

HERE = Path(__file__).resolve().parent
SEEDS = 6                  # refits on more runs than the one discovery saw (the spread)
SEED_BASE = 1000           # their seeds: model seed + SEED_BASE + i (never the fresh run's seed + 1)
EDGES = 4                  # tolerance-edge copies of the truth
Z = 3.0                    # the scorer's z
HORIZON = 100              # fresh skill@100
POINT, FALLBACK = "10tau", "100k"
REASONS = ("extra", "longrun", "fresh")


def code_hash() -> str:
    """The code a reference depends on: this module's reference part (not its docstring or the verdict) and
    the graders and fitters it uses."""
    h = hashlib.sha256()
    src = (HERE / "strict.py").read_text()
    h.update(src[src.index("HERE = Path"):src.index("# ---- the verdict")].encode())
    for p in (HERE / "longrun.py", HERE / "jump.py", HERE / "fisher.py", HERE / "noise_kf.py", HERE / "noise.py",
              HERE / "noise_oracle.py", HERE / "parts.py", HERE / "score.py", HERE.parent / "skill.py", HERE.parent / "discovery" / "simulate.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---- the truth's own achievement on the cell (offline) ----

def _run(case: dict, variant: dict, tm: dict, seed: int) -> dict:
    """A run of the case's variant on another seed, with the variant's noise laid on as data.load does."""
    from ..skill import truth_by_time
    from . import data
    raw = data.simulate(tm, seed, variant["steps"])
    obs = variant.get("observe")
    if obs:
        from .noise import apply
        return apply(raw, obs, seed, truth_by_time(tm, raw["t"])[0])
    return raw


def refit(tm: dict, d: dict, noise: str) -> tuple[list[dict] | None, str]:
    """The truth's structure with its numbers fitted on the run `d` (data.load's dict): (flows in a found
    model's form, how), or (None, why not)."""
    from ..skill import truth_by_time
    from . import noise_kf
    from .fisher import TruthParams
    from .noise_oracle import clean_view
    from .parts import windows
    if d.get("observation"):
        m = noise_kf.model(d, windows(tm, d["t"]))
        if m is None:
            return None, "no refit (the Kalman model does not cover this truth)"
        return m.flows_at(m.refit()), "kalman"
    if noise == "none":
        return truth_by_time(tm, d["t"])[0], "truth (noise-free data)"
    tp = TruthParams(tm, d, noise)
    if tp.ok:
        return tp.flows_at(tp.ml_fit()), "ml"
    view = clean_view({"clean": {**d, "flows": truth_by_time(tm, d["t"])[0]}})
    m = noise_kf.model(view, windows(tm, view["t"]))
    if m is None:
        return None, "no refit (a hidden stock with effects or co-flows)"
    return m.flows_at(m.refit()), "kalman"


def _scale_rate(r: dict | None, rng: np.random.Generator, rel: float) -> dict | None:
    if not isinstance(r, dict):
        return r
    out = dict(r)
    for k in ("value", "k", "goal", "time", "c"):
        if isinstance(out.get(k), (int, float)) and out[k]:
            out[k] = float(out[k]) * (1 + rel * rng.choice((-1.0, 1.0)))
    if out.get("terms"):
        out["terms"] = [{**x, "k": float(x["k"]) * (1 + rel * rng.choice((-1.0, 1.0)))} if isinstance(x.get("k"), (int, float)) else x
                        for x in out["terms"]]
    return out


def edge(tm: dict, rng: np.random.Generator, rel: float) -> dict:
    """The truth with every rate number and co-flow per moved by +-rel (random signs)."""
    m = json.loads(json.dumps(tm))
    for f in m["flows"]:
        f["rate"] = _scale_rate(f.get("rate"), rng, rel)
        for u in f.get("uses") or []:
            if isinstance(u.get("per"), (int, float)):
                u["per"] = float(u["per"]) * (1 + rel * rng.choice((-1.0, 1.0)))
    for ch in (m.get("schedule") or {}).get("changes") or []:
        ch["set"] = {fid: _scale_rate(r, rng, rel) for fid, r in (ch.get("set") or {}).items()}
    return m


class Grader:
    """Grades models on one cell as the ladder grades a found model: fresh skill@100 and the long run."""

    def __init__(self, tm: dict, run: dict, fresh: dict):
        from ..skill import truth_runs
        from . import longrun
        self.tm, self.fresh = tm, fresh
        self.setup = longrun.Setup(tm, run)
        self.point = POINT if POINT in self.setup.points else FALLBACK
        self.truth = truth_runs(tm, fresh, horizon=HORIZON) if len(fresh["t"]) >= HORIZON + 10 else None

    def grade(self, flows: list[dict]) -> dict:
        from ..skill import same_behaviour
        from . import longrun
        lr = longrun.grade(self.setup, flows)
        sk = None
        if self.truth is not None:
            sk = same_behaviour({"flows": flows}, self.tm, self.fresh, horizon=HORIZON, truth=self.truth, own_run=False)["skill"]
        err = lr["err"].get(self.point)
        return {"fresh": _fin(sk), "longrun": None if lr["hard_fail"] or err is None else _fin(err), "hard": bool(lr["hard_fail"])}


def reference(case_id: str, variant_name: str, seeds: int = SEEDS, edges: int = EDGES) -> dict:
    """What the truth's own structure achieves in one cell, and the thresholds (see the module docstring)."""
    from ..skill import truth_by_time
    from . import cases as casemod
    from . import data
    from .score import DEFAULTS
    t0 = time.time()
    c = casemod.load(case_id)
    v = casemod.variant(c, variant_name)
    tm = casemod.truth_model(c, variant_name)
    d = data.load(c, variant_name)
    fr = data.load(c, variant_name, fresh=True)
    run, fresh = d.get("clean") or d, fr.get("clean") or fr                  # behaviour on the run underneath, as runner.py grades it
    g = Grader(tm, run, fresh)
    noise = v["noise"]
    refits, how = [], None
    flows, how = refit(tm, d, noise)
    if flows is not None:
        refits.append(g.grade(flows))
        if noise != "none" or v.get("observe"):
            for i in range(seeds):
                try:
                    f_i, _ = refit(tm, _run(c, v, tm, int(tm["seed"]) + SEED_BASE + i), noise)
                except Exception as e:  # noqa: BLE001 - a seed whose refit fails is left out, and said
                    refits.append({"error": f"{type(e).__name__}: {e}"[:200]})
                    continue
                if f_i is not None:
                    refits.append(g.grade(f_i))
    rng = np.random.default_rng(int(hashlib.sha256(f"{case_id}|{variant_name}".encode()).hexdigest()[:8], 16))
    rel = float((c.get("tolerance") or {}).get("rel_exact", DEFAULTS["rel_exact"]))
    edge_rows = [g.grade(truth_by_time(edge(tm, rng, rel), run["t"])[0]) for _ in range(edges)]
    out = {"how": how, "point": g.point, "refits": refits, "edges": edge_rows, "rel": rel, "seconds": None,
           "fresh_thr": None, "longrun_thr": None, "limited": []}
    ok = [r for r in refits if "error" not in r]
    if not ok:
        out["limited"] = ["no reference"]
        out["seconds"] = round(time.time() - t0, 2)
        return out
    # long run
    errs = [r["longrun"] for r in ok]
    if any(e is None for e in errs) or any(r.get("hard") for r in ok):
        out["limited"].append("longrun")
    else:
        sd = float(np.std(errs, ddof=1)) if len(errs) > 1 else 0.0
        e_edge = [r["longrun"] for r in edge_rows]
        worst_edge = math.inf if any(e is None for e in e_edge) else max(e_edge, default=0.0)
        out["longrun_thr"] = _fin(max(float(np.mean(errs)) + Z * sd, worst_edge))
        if out["longrun_thr"] is None:
            out["limited"].append("longrun")
    # fresh skill@100
    sks = [r["fresh"] for r in ok]
    if g.truth is None or any(s is None for s in sks):
        out["limited"].append("fresh")
    else:
        sd = float(np.std(sks, ddof=1)) if len(sks) > 1 else 0.0
        s_edge = [r["fresh"] if r["fresh"] is not None else -math.inf for r in edge_rows]
        out["fresh_thr"] = _fin(min(float(np.mean(sks)) - Z * sd, min(s_edge, default=1.0)))
        if out["fresh_thr"] is None:
            out["limited"].append("fresh")
    out["seconds"] = round(time.time() - t0, 2)
    return out


def _fin(x):
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


# ---- the verdict of one result (cheap: from what the summary holds) ----

def verdict(status: str | None, fresh100: float | None, cx: dict | None, lr: dict | None, ref: dict | None) -> dict:
    """{strict: True | False | None (not computed), why: [reasons it fails], pending: what is missing,
    limited: criteria not applied in this cell (data-limited)}."""
    if status is None:
        return {"strict": None, "why": [], "pending": "not run"}
    if status != "pass":
        return {"strict": False, "why": ["not a pass"]}
    why, pending = [], []
    if cx is None:
        pending.append("complexity")
    elif cx["extra"] > 0:
        why.append("extra")
    lr_ok = bool(lr) and not lr.get("error")
    if lr_ok and lr.get("hard_fail"):
        why.append("longrun")
    ref_ok = ref is not None and "no reference" not in (ref.get("limited") or [])
    if ref_ok:
        if lr_ok and "longrun" not in why and "longrun" not in ref["limited"]:
            err = (lr.get("err") or {}).get(ref["point"])
            if err is None or err > ref["longrun_thr"]:
                why.append("longrun")
        if "fresh" not in ref["limited"] and (fresh100 is None or fresh100 < ref["fresh_thr"]):
            why.append("fresh")
    if why:
        return {"strict": False, "why": [r for r in REASONS if r in why]}
    if not lr_ok:
        pending.append("longrun")
    if not ref_ok:
        pending.append("reference")
    if pending:
        return {"strict": None, "why": [], "pending": ", ".join(pending)}
    return {"strict": True, "why": [], "limited": list(ref["limited"])}


def cell(v: dict) -> dict:
    """The fields a summary cell carries: strict (1, 0 or None: not computed) and strict_why (the reasons
    a pass fails strict, comma-separated; or what is missing, for None)."""
    s = v["strict"]
    out = {"strict": None if s is None else int(s)}
    if s is False and v["why"] != ["not a pass"]:
        out["strict_why"] = ",".join(v["why"])
    elif s is None and v.get("pending") and v["pending"] != "not run":
        out["strict_why"] = "pending: " + v["pending"]
    elif s and v.get("limited"):
        out["strict_why"] = "data-limited: " + ",".join(v["limited"])
    return out


# ---- the cache: computed by the CLI, read by the server ----

def path() -> Path:
    return cache_root() / "strict.sqlite"


@contextmanager
def connect():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite_keep.connect(p, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS refs (case_id TEXT NOT NULL, case_hash TEXT NOT NULL, variant TEXT NOT NULL,"
                    " code TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (case_id, case_hash, variant, code))")
        yield con
        con.commit()
    finally:
        con.close()


def _compute(case_id: str, case_hash: str, variant: str) -> tuple[tuple, dict]:
    try:
        v = reference(case_id, variant)
    except Exception as e:  # noqa: BLE001 - recorded (as no reference), not retried until the code changes
        v = {"error": f"{type(e).__name__}: {e}"[:300], "limited": ["no reference"]}
    return (case_id, case_hash, variant), v


def _worker_init() -> None:
    try:
        os.nice(10)
    except OSError:
        pass
    os.environ.setdefault("OMP_NUM_THREADS", "1")


def fill(keys: list[tuple[str, str, str]], jobs: int = 3, progress=None) -> int:
    """Compute and keep the reference of every (case id, case hash, variant) not yet known; how many."""
    code = code_hash()
    known = _refresh(code, force=True)
    todo = [k for k in dict.fromkeys(keys) if k not in known]
    done = 0
    if not todo:
        return 0
    with ProcessPoolExecutor(max_workers=max(1, jobs), initializer=_worker_init) as ex:
        futs = [ex.submit(_compute, *k) for k in todo]
        for f in as_completed(futs):
            key, v = f.result()
            with connect() as con:
                con.execute("INSERT OR REPLACE INTO refs VALUES (?, ?, ?, ?, ?)", (*key, code, json.dumps(v)))
            done += 1
            if progress:
                progress(done, len(todo), key, v)
    return done


_lock = threading.Lock()
_state: dict = {"key": None, "known": {}, "rowid": 0, "checked": 0.0}
REFRESH = 10.0


def _refresh(code: str, force: bool = False) -> dict:
    """{(case id, case hash, variant): reference} for this code, read incrementally at most every REFRESH s."""
    key = (str(path()), code)
    with _lock:
        if _state["key"] != key:
            _state.update(key=key, known={}, rowid=0, checked=0.0)
        if not force and time.time() - _state["checked"] < REFRESH:
            return _state["known"]
        _state["checked"] = time.time()
        if path().exists():
            with connect() as con:
                rows = con.execute("SELECT rowid, case_id, case_hash, variant, value FROM refs WHERE code = ? AND rowid > ? ORDER BY rowid",
                                   (code, _state["rowid"])).fetchall()
            for rowid, c, h, v, val in rows:
                _state["known"][(c, h, v)] = json.loads(val)
                _state["rowid"] = rowid
        return _state["known"]


_code: dict = {"at": 0.0, "hash": None}


def _current_code() -> str:
    """The code hash, re-read at most every REFRESH s (it hashes files)."""
    if _code["hash"] is None or time.time() - _code["at"] >= REFRESH:
        _code.update(hash=code_hash(), at=time.time())
    return _code["hash"]


def references() -> dict:
    """Every known reference for the current code (never computes)."""
    return _refresh(_current_code())


def version() -> tuple:
    references()
    return (_state["key"], _state["rowid"])


def needed(rows: list[dict], cx: dict) -> list[tuple[str, str, str]]:
    """The cells whose verdict waits on a reference: a pass with no extra complexity."""
    from . import cases as casemod
    out, hashes = [], {}
    for r in rows:
        x = cx.get(r["id"])
        if r["status"] == "pass" and x is not None and x["extra"] <= 0:
            if r["case"] not in hashes:
                try:
                    hashes[r["case"]] = casemod.load(r["case"])["hash"]
                except Exception:  # noqa: BLE001 - a case that is gone
                    hashes[r["case"]] = None
            if hashes[r["case"]]:
                out.append((r["case"], hashes[r["case"]], r["variant"]))
    return out
