"""What the strategy page (/ladder/strategy?name=S) shows of one strategy: compact, per strategy, so the
page paints from one small response and fetches the heavy parts (found flows, the long-run error
series) only for the cards on screen.

    overview(name)        {strategy, latest, totals {tests, realistic}, cases, cells, timeline}
    details(name, ids)    {results: {id: {case, variant, status, found, scores, repairs}}, models: {case: true model}}
    errors(ids)           {id: {t, stocks, err, run_end, flag}}: (found - true) / the truth's range per measured
                          stock, both models run free from the start (longrun.py), at log-spaced steps to 100k

A cell: one (case, variant) with the strategy's latest result: id, status, the analysis label, the repairs'
count by type (repairs.py), err@100k and the long-run flag (longrun_cache.py, as computed by
`sdlab-ladder longrun`), complexity and Occam (complexity.py, from the summary), and the strict verdict (strict.py, from the
summary: 1, 0 or None when not computed, with strict_why). Totals are over the cells
the strategy has run (coverage = ran / of), as on the leaderboard. The timeline is one point per version
(strategy hash and scorer hash) with the totals over the tests just after it and the git commit it ran from.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict

import numpy as np

from ..discovery.api import jsonable
from . import analysis, api, catalog, explain, longrun_cache, store
from . import merge as _merge
from . import cases as casemod
from .repairs import repairs

FAR = 100_000
POINTS = 56
_overviews: dict = {}
_analyses: dict = {}
_errors: OrderedDict = OrderedDict()
_lock = threading.Lock()
_refreshing: set = set()


def _kind(c: dict) -> str:
    if c.get("real"):
        return "real"
    if c.get("example") or "realistic" in (c.get("tags") or []):
        return "realistic"
    if c.get("physics"):
        return "physics"
    return "draw" if c.get("draw") else "test"


def _analysis(case_id: str, variant: str, h: str | None = None) -> dict | None:
    """The cached analysis of a cell (never computed here), kept in memory until the case changes."""
    h = h or casemod.load(case_id)["hash"]
    key = (case_id, variant, h)
    if key not in _analyses:
        try:
            _analyses[key] = analysis.get(case_id, variant, compute=False)
        except (OSError, ValueError, KeyError):
            _analyses[key] = None
    return _analyses[key]


def _round(x, d: int = 4):
    return None if x is None or not math.isfinite(x) else round(float(x), d)


def _hard(m: dict | None) -> bool:
    return bool(m) and m.get("flag") in ("runaway", "unstable")


def _far(m: dict | None) -> float | None:
    """err@100k as the leaderboard counts it: capped at 1, a run that runs away or is unstable counts 1."""
    if not m or m.get("error"):
        return None
    if _hard(m):
        return 1.0
    return None if m.get("far") is None else min(1.0, float(m["far"]))


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    return sum(xs) / len(xs) if xs else None


def _totals(cells: list[dict]) -> dict:
    ran = [c for c in cells if c["status"]]
    count = lambda st: sum(c["status"] == st for c in ran)  # noqa: E731
    ach = [c for c in ran if c.get("analysis") == "achievable"]
    out = {st: count(st) for st in api.STATUSES}
    out.update(ran=len(ran), of=len(cells), achievable=len(ach), achievable_pass=sum(c["status"] == "pass" for c in ach),
               pass_rate=out["pass"] / len(ran) if ran else None,
               achievable_rate=sum(c["status"] == "pass" for c in ach) / len(ach) if ach else None,
               occam=_mean([c.get("occam") or 0.0 for c in ran]) if ran else None,
               far=_mean([c.get("far") for c in ran]), far_n=sum(c.get("far") is not None for c in ran),
               skill20=_mean([max(-1.0, c["skill20"]) if c.get("skill20") is not None else None for c in ran]),
               repairs=_mean([c.get("n") for c in ran]), stale=sum(bool(c.get("stale")) for c in ran),
               strict=sum(c.get("strict") == 1 for c in ran), strict_known=sum(c.get("strict") is not None for c in ran))
    out["strict_rate"] = out["strict"] / out["strict_known"] if out["strict_known"] else None
    return out


def _timeline(name: str, live: set) -> list[dict]:
    """One point per version (strategy hash, scorer hash) in the order they first ran: the totals over the
    live test cells just after its last result, its git commits, and whether the strategy's code changed."""
    with store.connect(readonly=True) as con:
        rows = con.execute("SELECT id, case_id, variant, strategy_hash, score_hash, at, status, code_commit, code_dirty FROM results"
                           " WHERE strategy = ? ORDER BY id", (name,)).fetchall()
    versions: dict[tuple, dict] = {}
    for r in rows:
        key = (r["strategy_hash"], r["score_hash"])
        v = versions.setdefault(key, {"strategy_hash": key[0], "score_hash": key[1], "first": r["at"], "first_id": r["id"], "ran": 0, "commits": []})
        v["ran"] += 1
        v["last"], v["last_id"] = r["at"], r["id"]
        c = (r["code_commit"] or "")[:10] + ("+patch" if r["code_dirty"] else "")
        if c and c not in v["commits"]:
            v["commits"].append(c)
    now: dict[tuple, str] = {}
    snap: dict[tuple, dict] = {}
    marks = sorted(versions.values(), key=lambda v: v["last_id"])
    i = 0
    for v in marks:
        while i < len(rows) and rows[i]["id"] <= v["last_id"]:
            if (rows[i]["case_id"], rows[i]["variant"]) in live:
                now[(rows[i]["case_id"], rows[i]["variant"])] = rows[i]["status"]
            i += 1
        counts = {k: 0 for k in api.STATUSES}
        for st in now.values():
            counts[st] = counts.get(st, 0) + 1
        snap[(v["strategy_hash"], v["score_hash"])] = counts
    out, prev = [], None
    for v in sorted(versions.values(), key=lambda x: x["first_id"]):
        out.append({"strategy_hash": v["strategy_hash"][:10], "score_hash": v["score_hash"][:10], "first": v["first"], "last": v["last"],
                    "ran": v["ran"], "commits": v["commits"][:6], "totals": snap[(v["strategy_hash"], v["score_hash"])], "of": len(live),
                    "code_changed": prev is not None and v["strategy_hash"] != prev})
        prev = v["strategy_hash"]
    return out


def overview(name: str) -> dict:
    """See the module docstring. Cached; once a copy exists a request never waits: a copy made before a
    result was stored (or the long-run metrics, analyses or summary changed) is served while one
    background thread makes a new one."""
    sm = api.summary()
    key = (name, store.version(), longrun_cache.version(), analysis.version(), id(sm))
    have = _overviews.get(name)
    if have:
        if have[0] != key and name not in _refreshing:
            _refreshing.add(name)
            threading.Thread(target=_refresh, args=(name, sm, key), daemon=True).start()
        return have[1]
    with _lock:
        if name not in _overviews:
            _overviews[name] = (key, _overview(name, sm))
    return _overviews[name][1]


def _refresh(name: str, sm: dict, key: tuple) -> None:
    try:
        _overviews[name] = (key, _overview(name, sm))
    finally:
        _refreshing.discard(name)


def _overview(name: str, sm: dict) -> dict:
    listing = {s["name"]: s for s in catalog.listing()}
    s = listing.get(name) or {"name": name}
    kinds = {c["id"]: _kind(c) for c in sm["cases"]}
    hashes = {c["id"]: c["hash"] for c in sm["cases"]}
    cells_sm = {(c["case"], c["variant"]): c for c in sm["cells"] if c["strategy"] == name}
    rows = store.latest(strategy=name)
    lr = longrun_cache.for_results(rows)
    by = {(r["case"], r["variant"]): r for r in rows if r["case"] in kinds}
    cells = []
    for (cid, v), c in cells_sm.items():
        r = by.get((cid, v))
        cell = {"case": cid, "variant": v, "status": c.get("status"), "stale": c.get("stale") if r else None,
                "analysis": c.get("analysis"), "occam": _round(c.get("occam")), "cx": [c.get("cx_true"), c.get("cx_found")],
                "skill20": _round(c.get("skill20")), "strict": c.get("strict"), "strict_why": c.get("strict_why")}
        if r:
            rp = repairs(r.get("scores"), _analysis(cid, v, hashes.get(cid))) if r["status"] not in ("error", "timeout") else None
            m = lr.get(r["id"])
            cell.update(id=r["id"], n=rp["count"] if rp else None, by=rp["by"] if rp else {}, far=_round(_far(m)), flag=(m or {}).get("flag"))
        cells.append(cell)
    newest = max(rows, key=lambda r: r["id"]) if rows else None
    live_tests = {(c["case"], c["variant"]) for c in cells if kinds.get(c["case"]) not in ("realistic", "physics", "real")}
    return jsonable({
        "strategy": {"name": name, "hash": s.get("hash"), "available": s.get("available"), "reason": s.get("reason"), "about": explain.about(name)},
        "latest": {k: newest[k] for k in ("id", "at", "strategy_hash", "code_commit", "code_dirty")} if newest else None,
        "current_hash": s.get("hash"),
        "behind": sum(1 for r in rows if s.get("hash") and r["strategy_hash"] != s.get("hash")),
        "totals": {"tests": _totals([c for c in cells if kinds.get(c["case"]) not in ("realistic", "physics", "real")]),
                   "realistic": _totals([c for c in cells if kinds.get(c["case"]) == "realistic"]), "real": _totals([c for c in cells if kinds.get(c["case"]) == "real"]),
                   "physics": _totals([c for c in cells if kinds.get(c["case"]) == "physics"])},
        "cases": [{k: c[k] for k in ("id", "title", "level", "tags", "tests", "variants")} | {"kind": kinds[c["id"]]} for c in sm["cases"]],
        "cells": cells,
        "timeline": _timeline(name, live_tests),
        "made": time.time(),
    })


def details(name: str, ids: list[int]) -> dict:
    """The found flows, the scorer's parts and the repairs of some results of one strategy, and the true
    models of their cases: what a card's diagram and repair list need."""
    out, models = {}, {}
    for i in ids:
        r = store.get(i, found=True)
        if r is None or r["strategy"] != name or not casemod.known(r["case"]):
            continue
        s = r.get("scores") or {}
        an = _analysis(r["case"], r["variant"])
        out[i] = {"id": i, "case": r["case"], "variant": r["variant"], "status": r["status"], "found": r.get("found"),
                  "error": (r.get("error") or "")[:400] or None,
                  "scores": {k: s.get(k) for k in ("status", "parts", "spurious", "recall", "precision", "right", "of", "windows", "behaviour")} if s else None,
                  "repairs": repairs(s, an) if s and r["status"] not in ("error", "timeout") else None,
                  "analysis": {"label": an.get("label"), "p": an.get("p"), "why": an.get("why"), "equivalences": an.get("equivalences")} if an else None}
        merged = _merge.flows(r.get("found") or [])         # the same-pair flows as one (merge.py), as the scorer reads them
        if merged is not (r.get("found") or []) and r.get("found"):
            out[i]["found_merged"] = merged
        if r["case"] not in models:
            models[r["case"]] = casemod.load(r["case"])["model"]
    return jsonable({"results": out, "models": models})


def _series(row: dict) -> dict | None:
    from . import longrun_series
    s = longrun_series.setup(row["case"], row["variant"])
    ftraj = s.found(row["found"])[0]
    nm = len(s.measured)
    ts = np.unique(np.geomspace(s.t1, FAR, POINTS).round().astype(np.int64))
    ts = np.unique(np.concatenate([ts, [s.n_run]]))
    tr, fd = s.traj.at(ts)[s.m], ftraj.at(ts)[:nm]
    scale = np.maximum(np.asarray(s.scale)[s.m], 1e-12)[:, None]
    err = (fd - tr) / scale
    lists = [[None if not math.isfinite(x) else round(float(x), 5) for x in row_] for row_ in err]
    m = longrun_cache.of_result(row)
    return {"t": ts.tolist(), "stocks": list(s.measured), "err": lists, "run_end": int(s.n_run), "flag": (m or {}).get("flag")}


def errors(ids: list[int]) -> dict:
    """{id: the normalised error series} (see the module docstring), cached per result."""
    out = {}
    code = longrun_cache.code_hash()
    for i in ids:
        key = (i, code)
        if key not in _errors:
            r = store.get(i, found=True)
            if r is None or r.get("found") is None or r["status"] in ("error", "timeout") or not casemod.known(r["case"]):
                _errors[key] = None
            else:
                try:
                    _errors[key] = _series(r)
                except Exception as e:                              # noqa: BLE001  (a card shows the reason)
                    _errors[key] = {"error": f"{type(e).__name__}: {e}"[:200]}
            while len(_errors) > 4000:
                _errors.popitem(last=False)
        out[i] = _errors[key]
    return jsonable(out)


def parse_ids(text: str | None, limit: int) -> list[int]:
    try:
        return [int(x) for x in (text or "").split(",") if x.strip()][:limit]
    except ValueError:
        return []

