"""The newest cases view (/ladder/new): every case file, newest first, with when and why it was added,
what it tests, and how the leading strategies do on it; the Tests pass rate with and without the
newest cases; and true regressions (a strategy now failing a cell its previous version passed).

    view(strategies?)   {now, leaders, rows, impact, regressions, distilled_source}; cached (see _cache)
    ages()              {file id: when it was added} and the regressions' totals: what the leaderboard needs
    regressions()       the latest result of every (case, variant, strategy) against the strategy's previous
                        version on the same case (case hash): pass -> not pass, or equivalent -> fail/error/timeout

Everything here reads: the summary (api.summary, cached), the case dates (case_dates.py, cached from
git), docs/LADDER.md's "Distilled cases" table (where each distilled case came from) and, for the
regressions, one pass over the result store's statuses, recomputed in the background when a result
is stored.
"""

from __future__ import annotations

import json
import re
import threading
from sys import intern
import time
from datetime import datetime, timezone
from pathlib import Path

from . import api, case_dates, store
from . import cases as casemod

LADDER_MD = Path(__file__).resolve().parents[2] / "docs" / "LADDER.md"
KIND_TAGS = {"distilled", "canonical", "noisy", "realistic", "physics", "particles", "real", "parametric", "frozen-draw", "sweep"}
TEST_KINDS = ("test", "distilled", "noisy", "canonical")       # the kinds in the Tests pass rate
WINDOWS = (6, 24, 168)                                          # hours: "added in the last N hours"
N_LEADERS = 8
GOOD = {"pass": 2, "equivalent": 1}
LETTER = {"pass": "P", "equivalent": "E", "fail": "F", "error": "X", "timeout": "T"}


def kind(c: dict) -> str:
    """test / distilled / noisy / canonical / realistic / physics / particles / real, from a summary case."""
    tags = c["tags"]
    if c.get("real") is not None or "real" in tags:
        return "real"
    if c.get("example") or "realistic" in tags:
        return "realistic"
    if c.get("particles") is not None or "particles" in tags:
        return "particles"
    if c.get("physics") is not None or "physics" in tags:
        return "physics"
    for k in ("distilled", "canonical", "noisy"):
        if k in c["tags"]:
            return k
    return "test"


def capabilities(tags: list[str]) -> list[str]:
    """The motif tags (what the case asks a strategy to be able to do), without the kind tags."""
    return [t for t in tags if t not in KIND_TAGS]


# ---- where the distilled cases came from (docs/LADDER.md) ----

_source: dict = {"mtime": None, "rows": {}}


def distilled_source(path: Path = LADDER_MD) -> dict[str, dict]:
    """{NNN: {hard, mistake}} from the first table under "## Distilled cases": the hard-case failure a
    distilled case came from, and the mistake the strategies make on the small case."""
    try:
        m = path.stat().st_mtime
    except OSError:
        return {}
    if _source["mtime"] == m:
        return _source["rows"]
    rows = parse_distilled(path.read_text())
    _source.update(mtime=m, rows=rows)
    return rows


def parse_distilled(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    sec = re.search(r"^## Distilled cases.*?$(.*?)(?=^## )", text, re.S | re.M)
    if not sec:
        return out
    for line in sec.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 4:
            continue
        m = re.match(r"^(\d{3})-[a-z0-9-]+(?:\s*\((.*)\))?", cols[1])
        if m:
            out.setdefault(m.group(1), {"hard": cols[0], "case": cols[1], "mistake": cols[-1]})
    return out


# ---- regressions ----

_reg: dict = {"version": None, "value": None, "at": 0.0}
REG_EVERY = 60.0                # seconds: regressions are recomputed at most this often (results arrive every few seconds)
_reg_lock = threading.Lock()


_series: dict = {"path": None, "last": 0, "series": {}}


def _max_id() -> int:
    """The newest result's id (an index lookup, unlike store.version's count)."""
    with store.connect(readonly=True) as con:
        return con.execute("SELECT MAX(id) FROM results").fetchone()[0] or 0


def _read_series() -> dict[tuple, list]:
    """Every stored status by (case, variant, strategy), oldest first; only rows newer than the last read
    are fetched (results are never deleted or changed)."""
    if _series["path"] != str(store.path()):
        _series.update(path=str(store.path()), last=0, series={})
    series = _series["series"]
    with store.connect(readonly=True) as con:
        for r in con.execute("SELECT id, case_id, variant, strategy, case_hash, strategy_hash, score_hash, status, at FROM results"
                             " WHERE id > ? ORDER BY id", (_series["last"],)):
            series.setdefault((r[1], r[2], r[3]), []).append((r[0], None, None, None, intern(r[4]), intern(r[5]), intern(r[6]), intern(r[7]), r[8]))
            _series["last"] = r[0]
    return series


def _compute_regressions() -> dict:
    """Each (case, variant, strategy)'s latest result against the strategy's previous version."""
    live_strats = set(api.strategy_names())
    hashes = {}
    series = _read_series()
    out = []
    for (case, variant, strat), rows in series.items():
        if strat not in live_strats:
            continue
        if case not in hashes:
            hashes[case] = casemod.load(case)["hash"] if casemod.known(case) else None
        last = rows[-1]
        if hashes[case] is None or last[4] != hashes[case]:
            continue
        prev = next((r for r in reversed(rows[:-1]) if r[5] != last[5] and r[4] == last[4]), None)
        if prev is None:
            continue
        before, now = GOOD.get(prev[7], 0), GOOD.get(last[7], 0)
        if now < before:
            out.append({"strategy": strat, "case": case, "variant": variant, "from": prev[7], "to": last[7],
                        "prev_id": prev[0], "id": last[0], "prev_at": prev[8], "at": last[8],
                        "prev_hash": prev[5][:10], "hash": last[5][:10], "scorer_changed": prev[6] != last[6]})
    out.sort(key=lambda x: (x["strategy"], x["case"], x["variant"]))
    by: dict[str, dict] = {}
    for x in out:
        b = by.setdefault(x["strategy"], {"fail": 0, "error": 0, "scorer_changed": 0, "n": 0})
        b["n"] += 1
        b["error" if x["to"] in ("error", "timeout") else "fail"] += 1
        b["scorer_changed"] += x["scorer_changed"]
    return {"items": out, "by_strategy": by, "n": len(out),
            "n_fail": sum(1 for x in out if x["to"] not in ("error", "timeout")),
            "n_clean": sum(1 for x in out if x["to"] not in ("error", "timeout") and not x["scorer_changed"]),
            "computed": store.now()}


def regressions(wait: bool = False) -> dict | None:
    """The regressions (see the module docstring), recomputed in one background thread when results were
    stored (at most every REG_EVERY seconds); None while the first computation runs (unless wait)."""
    v = _max_id()
    due = wait or _reg["value"] is None or time.time() - _reg["at"] >= REG_EVERY
    if _reg["version"] != v and due and _reg_lock.acquire(blocking=wait):
        def run():
            try:
                val = _compute_regressions()
                _reg.update(version=v, value=val, at=time.time())
            finally:
                _reg_lock.release()
        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True, name="regressions").start()
    return _reg["value"]


# ---- the view ----

_cache: dict = {}


def _leaders(sm: dict, names: list[str] | None) -> list[dict]:
    """The strategies shown per case: the given ones, or the N_LEADERS available ones with the best Tests
    pass rate over the cells they ran (among those that ran at least half)."""
    out = []
    for s in sm["strategies"]:
        t = (sm["totals"] or {}).get(s["name"]) or {}
        ran = t.get("total", 0) - t.get("missing", 0)
        out.append({"name": s["name"], "available": s["available"], "rate": t.get("pass", 0) / ran if ran else None,
                    "ran": ran, "of": t.get("total", 0)})
    if names:
        return [x for x in out if x["name"] in names]
    ok = [x for x in out if x["available"] and x["rate"] is not None and x["of"] and x["ran"] / x["of"] >= 0.5]
    return sorted(ok, key=lambda x: -x["rate"])[:N_LEADERS]


_view_lock = threading.Lock()


def view(names: list[str] | None = None) -> dict:
    """The view, cached per strategy list. Once a copy exists a request never waits: when the summary or
    the dates changed, the copy is served while one background thread rebuilds it. The regressions'
    brief is attached as it is now."""
    slot = tuple(names or ())
    have = _cache.get(slot)
    if have is None:
        with _view_lock:
            if slot not in _cache:
                _rebuild(slot, names)
        have = _cache[slot]
    elif have["key"] != _key(names) and _view_lock.acquire(blocking=False):
        def run():
            try:
                _rebuild(slot, names)
            finally:
                _view_lock.release()
        threading.Thread(target=run, daemon=True, name="newest-view").start()
    return {**have["value"], "regressions": reg_brief(regressions())}


def view_json(names: list[str] | None = None) -> bytes:
    """view() as JSON bytes: the rows are serialised once per rebuild, the regressions' brief per call."""
    view(names)
    have = _cache[tuple(names or ())]
    if have.get("json") is None:
        have["json"] = json.dumps(have["value"], separators=(",", ":")).encode()
    return have["json"][:-1] + b',"regressions":' + json.dumps(reg_brief(regressions()), separators=(",", ":")).encode() + b"}"


def _key(names: list[str] | None) -> tuple:
    return (id(api.summary()), id(case_dates.dates()), tuple(names or ()), int(time.time() // 300))


def _rebuild(slot: tuple, names: list[str] | None) -> None:
    key = _key(names)
    _cache[slot] = {"key": key, "value": _view(api.summary(), case_dates.dates(), names)}


def _view(sm: dict, dates: dict, names: list[str] | None) -> dict:
    now = datetime.now(timezone.utc)
    leaders = _leaders(sm, names)
    lead = {x["name"] for x in leaders}
    src = distilled_source()
    files: dict[str, dict] = {}
    for c in sm["cases"]:
        base, _ = casemod.split(c["id"])
        f = files.get(base)
        if f is None:
            d = dates.get(base) or {}
            at = case_dates.added_at(d)
            num = base[:3] if base[:3].isdigit() else None
            k = kind(c)
            files[base] = f = {"id": base, "title": c["title"], "level": c["level"], "kind": k, "tags": c["tags"],
                               "capabilities": capabilities(c["tags"]), "tests": c.get("tests") or "",
                               "added": {"at": at, "committed": bool(d.get("commit")), "commit": (d.get("commit") or "")[:10] or None,
                                         "subject": d.get("subject")},
                               "age_hours": round((now - datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds() / 3600, 2) if at else None,
                               "from": src.get(num) if k == "distilled" and num else None,
                               "variants": list(c["variants"]), "draws": [], "leaders": {}, "all": {"ran": 0, "passing": 0, "cells_run": 0, "cells_pass": 0}}
        if "#" in c["id"]:
            f["draws"].append(c["id"])
    per: dict[tuple, dict] = {}
    for cell in sm["cells"]:
        base, _ = casemod.split(cell["case"])
        f = files.get(base)
        if f is None:
            continue
        st = cell["status"]
        a = per.setdefault((base, cell["strategy"]), {"p": 0, "e": 0, "f": 0, "o": 0, "n": 0, "of": 0, "v": {}})
        a["of"] += 1
        if st:
            a["n"] += 1
            a[{"pass": "p", "equivalent": "e", "fail": "f"}.get(st, "o")] += 1
        if not f["draws"] and cell["strategy"] in lead:
            a["v"][cell["variant"]] = LETTER.get(st, ".")
    for (base, name), a in per.items():
        f = files[base]
        if a["n"]:
            f["all"]["ran"] += 1
            f["all"]["passing"] += a["p"] > 0
            f["all"]["cells_run"] += a["n"]
            f["all"]["cells_pass"] += a["p"]
        if name in lead:
            f["leaders"][name] = {k: a[k] for k in ("p", "e", "f", "o", "n", "of")} | (
                {"v": "".join(a["v"].get(v, ".") for v in f["variants"])} if not f["draws"] else {})
    for f in files.values():
        f["fails_everyone"] = f["all"]["ran"] > 0 and f["all"]["passing"] == 0
        f["leaders_pass"] = sum(1 for x in f["leaders"].values() if x["p"])
        f["n_draws"] = len(f["draws"])
        del f["draws"]
    rows = sorted(files.values(), key=lambda f: (f["added"]["at"] or "", f["id"]), reverse=True)
    return {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "leaders": leaders, "rows": rows,
            "impact": impact(sm, files, leaders, now), "windows": list(WINDOWS), "score_hash": sm.get("score_hash")}


def impact(sm: dict, files: dict, leaders: list[dict], now: datetime) -> dict:
    """Per leader, the Tests pass rate (over the cells it ran) on every Tests case, and for each window of
    N hours: without the cases added in the last N hours (oldN), and on those cases alone (newN)."""
    age = {b: f["age_hours"] for b, f in files.items() if f["kind"] in TEST_KINDS}
    lead = {x["name"] for x in leaders}
    acc: dict[str, dict] = {}
    for cell in sm["cells"]:
        if cell["strategy"] not in lead or not cell["status"]:
            continue
        base, _ = casemod.split(cell["case"])
        if base not in age:
            continue
        a = acc.setdefault(cell["strategy"], {"all": [0, 0], **{f"old{w}": [0, 0] for w in WINDOWS}, **{f"new{w}": [0, 0] for w in WINDOWS}})
        ok = cell["status"] == "pass"
        a["all"][0] += ok
        a["all"][1] += 1
        d = age[base]
        for w in WINDOWS:
            k = f"new{w}" if d is not None and d < w else f"old{w}"
            a[k][0] += ok
            a[k][1] += 1
    new_cases = {w: sorted(b for b, d in age.items() if d is not None and d < w) for w in WINDOWS}
    return {"strategies": {n: {k: {"pass": v[0], "ran": v[1], "rate": v[0] / v[1] if v[1] else None} for k, v in a.items()}
                           for n, a in acc.items()},
            "new_cases": {str(w): len(v) for w, v in new_cases.items()}, "test_cases": len(age)}


def reg_brief(reg: dict | None, limit: int = 300) -> dict | None:
    if reg is None:
        return None
    return {**{k: reg[k] for k in ("by_strategy", "n", "n_fail", "n_clean", "computed")}, "items": reg["items"][:limit],
            "truncated": max(0, len(reg["items"]) - limit)}


def ages() -> dict:
    """What the leaderboard needs: {now, added: {file id: when}, regressions: {n, n_fail, n_clean, by_strategy}}."""
    reg = regressions()
    return {"now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "added": {k: case_dates.added_at(v) for k, v in case_dates.dates().items()},
            "regressions": None if reg is None else {k: reg[k] for k in ("n", "n_fail", "n_clean", "by_strategy")}}


def warm() -> None:
    """At server start: the dates (cache or one git log in the background) and the regressions."""
    case_dates.warm()
    regressions()

