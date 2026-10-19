"""The ladder's read API: what a page (or anything else) needs to show the ladder. Read only, every
value JSON-safe. The server exposes it under /api/ladder (sdlab/server.py); see docs/LADDER.md.

    cases()                              every case: id, title, level, tags, tests, hash, variants, tolerance, model
    case(case_id)                        one case (None if unknown)
    strategies()                         every strategy: name, hash, available, reason, about (explain.py)
    glossary()                           the ladder's words in plain language (explain.py)
    results(case, variant, strategy)     the latest result per (case, variant, strategy), filtered by any given
    result(case, variant, strategy)      the latest result for one, with the found flows (None if never run)
    history(case, variant, strategy)     every result for one, newest first (without found flows)
    result_by_id(id)                     one stored result by its id, with the found flows (None if unknown)
    case_data(case_id, variant, fresh, flows)   the case's data in a variant: t, levels (measured), all_levels, eras, (flows)
    timeline(strategy)                   the strategy's totals after each version (strategy and scorer hash) it ran with
    progress(recent?)                    the current or last run: {run, items}; with recent, a light copy for polling
    board(strategy, variant?)            every case with one strategy's latest results (found flows included)
    best_strategy()                      the available strategy with the highest pass rate
    run_graph(id, at?, window?)          one result's true vs found levels run free from the start, far ahead (longrun_series.py)
    summary()                            the matrix: strategies, cases, cells (one per case x variant x
                                         strategy, flattened scores, stale or not) and per-tag and per-strategy totals

A result: {id, case, variant, strategy, case_hash, strategy_hash, score_hash, at, latest, status
("pass" | "equivalent" | "fail" | "error" | "timeout"), seconds, error, scores (score.py), found?}; one read
with its found flows also has complexity (complexity.py: true vs found) and longrun (longrun.py: long-horizon
metrics, computed once per result id by longrun_cache.py), and summary cells carry both.
"""

from __future__ import annotations

import threading
import time

from ..discovery.api import jsonable
from . import cases as casemod
from . import analysis, catalog, complexity, data, explain, longrun_cache, score, store

STATUSES = ("pass", "equivalent", "fail", "error", "timeout")


def _case(cid: str) -> dict:
    c = casemod.load(cid)
    return {**c, "variants": [dict(v) for v in c["variants"]]}


def cases() -> list[dict]:
    return jsonable([_case(i) for i in casemod.case_ids()])


def case(case_id: str) -> dict | None:
    return jsonable(_case(case_id)) if casemod.known(case_id) else None


def strategies() -> list[dict]:
    return jsonable([{**s, "about": explain.about(s["name"])} for s in catalog.listing()])


def glossary() -> dict:
    return jsonable(explain.glossary())


def strategy_names() -> list[str]:
    return catalog.names()


def results(case: str | None = None, variant: str | None = None, strategy: str | None = None) -> list[dict]:
    return jsonable(store.latest(case, variant, strategy))


def result(case: str, variant: str, strategy: str) -> dict | None:
    rows = store.latest(case, variant, strategy, found=True)
    return jsonable(longrun_cache.attach(complexity.attach(rows[0]))) if rows else None


def history(case: str, variant: str, strategy: str) -> list[dict]:
    return jsonable(store.history(case, variant, strategy))


def result_by_id(result_id: int) -> dict | None:
    r = store.get(result_id, found=True)
    return jsonable(longrun_cache.attach(complexity.attach(r))) if r else None


def run_graph(result_id: int, at: list[int] | None = None, window: int | None = None) -> dict | None:
    """What the run page plots for one result (longrun_series.graph), or None if it found nothing."""
    from . import longrun_series
    return jsonable(longrun_series.graph(result_id, at, window))


def case_data(case_id: str, variant: str, fresh: bool = False, flows: bool = False) -> dict:
    """What the detector sees (levels of the measured stocks) and what it does not (all_levels: every
    stock, hidden ones too), for a page to plot; with flows, also every true flow's amount per step
    (`flows`, which discovery never sees)."""
    c = casemod.load(case_id)
    d = data.load(c, variant, fresh=fresh)
    measured = [s["id"] for s in c["model"]["stocks"] if s.get("measured", True)]
    out = {"case": case_id, "variant": variant, "fresh": bool(fresh), "t": d["t"], "levels": d["levels"], "all_levels": d["all_levels"],
           "measured": measured, "eras": d.get("eras") or [], "injections": d.get("injections") or []}
    if flows:
        out["flows"] = d.get("counters") or {}
    return jsonable(out)


def timeline(strategy: str) -> list[dict]:
    """One point per version of a strategy (its strategy hash and the scorer's hash, in the order they
    first ran): when it first ran, how many results it made, and the ladder's totals just after it
    (for each case and variant, the newest result up to then; cases no longer in the ladder are left out)."""
    rows = store.statuses(strategy)
    live = {(c, v["name"]) for c in casemod.case_ids() for v in casemod.load(c)["variants"]}
    versions: dict[tuple, dict] = {}
    for r in rows:
        key = (r["strategy_hash"], r["score_hash"])
        v = versions.setdefault(key, {"strategy_hash": key[0], "score_hash": key[1], "first": r["at"], "first_id": r["id"], "ran": 0})
        v["ran"] += 1
        v["last"], v["last_id"] = r["at"], r["id"]
    out = []
    for v in sorted(versions.values(), key=lambda x: x["first_id"]):
        now: dict[tuple, str] = {}
        for r in rows:
            if r["id"] <= v["last_id"] and (r["case"], r["variant"]) in live:
                now[(r["case"], r["variant"])] = r["status"]
        counts = {k: 0 for k in STATUSES}
        for st in now.values():
            counts[st] = counts.get(st, 0) + 1
        out.append({**{k: v[k] for k in ("strategy_hash", "score_hash", "first", "last", "ran")}, "totals": counts, "of": len(live)})
    return jsonable(out)


def best_strategy() -> str | None:
    """The available strategy with the highest pass rate over the whole ladder (then pass + equivalent)."""
    sm = summary()
    ok = [x["name"] for x in sm["strategies"] if x["available"]]
    if not ok:
        return None
    t = sm["totals"]
    return max(ok, key=lambda n: ((t.get(n) or {}).get("pass", 0), (t.get(n) or {}).get("equivalent", 0), n == "matrix"))


def board(strategy: str, variant: str | None = None) -> dict:
    """Every case with one strategy's latest result in a variant (every variant when None), found
    flows included: what the all-cases view shows. {strategy, variant, best, cases, results}."""
    names = None if variant is None else {variant}
    rows = [r for r in store.latest(strategy=strategy, found=True) if names is None or r["variant"] in names]
    known = set(casemod.case_ids())
    return jsonable({"strategy": strategy, "variant": variant, "best": best_strategy(),
                     "cases": [_case(i) for i in casemod.case_ids()],
                     "results": [complexity.attach(r) for r in rows if r["case"] in known]})


def progress(recent: int | None = None) -> dict:
    """The current or last run. With recent, a light copy for polling: only the running items and the
    `recent` most recently finished ones, plus `counts` (finished items by status) and `queued`."""
    p = store.progress()
    if recent is None:
        return jsonable(p)
    items = p["items"]
    counts: dict[str, int] = {}
    for i in items:
        if i["state"] == "done":
            counts[i["status"]] = counts.get(i["status"], 0) + 1
    done = sorted((i for i in items if i["state"] == "done" and i["finished"]), key=lambda i: i["finished"], reverse=True)[:max(0, recent)]
    return jsonable({"run": p["run"], "items": [i for i in items if i["state"] == "running"] + done, "counts": counts,
                     "queued": sum(i["state"] == "queued" for i in items)})


def flatten(row: dict | None) -> dict:
    """The numbers a matrix cell shows, from a result."""
    if row is None:
        return {"status": None}
    s = row.get("scores") or {}
    b = s.get("behaviour") or {}

    def sk(where, h):
        x = (b.get(where) or {}).get(str(h)) or {}
        return x.get("skill"), x.get("ci")

    out = {"status": row["status"], "recall": s.get("recall"), "precision": s.get("precision"), "right": s.get("right"), "of": s.get("of"),
           "spurious": len(s.get("spurious") or []), "seconds": row.get("seconds"), "at": row.get("at"), "error": row.get("error")}
    for where, tag in (("in_sample", "skill"), ("fresh", "fresh")):
        for h in score.HORIZONS:
            out[f"{tag}{h}"], out[f"{tag}{h}_ci"] = sk(where, h)
    return out


_summaries: dict = {}
_summary_lock = threading.Lock()
FRESH_FOR = 10.0          # seconds a summary is served before it is checked again


def summary(strategy_filter: list[str] | None = None) -> dict:
    """The matrix (see the module docstring), cached in memory until a result is stored, a case or
    a strategy changes, or the scorer changes. A request never waits for a recomputation once a copy
    exists: a stale copy (older than FRESH_FOR seconds) is served while one background thread
    refreshes it. Only the very first request computes it in line."""
    slot = (tuple(strategy_filter or ()), str(store.path()))
    have = _summaries.get(slot)
    if have:
        if time.time() - have["at"] >= FRESH_FOR and _summary_lock.acquire(blocking=False):
            threading.Thread(target=_refresh, args=(slot, strategy_filter, True), daemon=True).start()
        return have["value"]
    with _summary_lock:
        if slot not in _summaries:
            _refresh(slot, strategy_filter, False)
    return _summaries[slot]["value"]


def _refresh(slot: tuple, strategy_filter: list[str] | None, release: bool) -> None:
    """Recompute one summary slot if anything it depends on changed (the caller holds the lock;
    release=True: this thread releases it)."""
    try:
        have = _summaries.get(slot)
        listing = catalog.listing()
        key = (store.version(), tuple((s["name"], s["hash"], s["available"]) for s in listing),
               tuple((i, casemod.load(i)["hash"]) for i in casemod.case_ids()), score.score_hash(), longrun_cache.version(), analysis.version())
        if not have or have["key"] != key:
            have = {"key": key, "value": _summary(strategy_filter, listing)}
        _summaries[slot] = {**have, "at": time.time()}
    finally:
        if release:
            _summary_lock.release()


def _summary(strategy_filter: list[str] | None, listing: list[dict]) -> dict:
    strats = [s for s in listing if not strategy_filter or s["name"] in strategy_filter]
    sh = score.score_hash()
    have = {(r["case"], r["variant"], r["strategy"]): r for r in store.latest()}
    cx = complexity.for_results(list(have.values()))
    lr = longrun_cache.for_results(list(have.values()))            # read only: what `sdlab-ladder longrun` computed
    lr_cells = []
    cs = [casemod.load(i) for i in casemod.case_ids()]
    cells, by_tag, totals = [], {}, {}
    for c in cs:
        for v in c["variants"]:
            for s in strats:
                row = have.get((c["id"], v["name"], s["name"]))
                stale = store.staleness(row, c["hash"], s["hash"], sh) if s["available"] else None
                cell = {"case": c["id"], "variant": v["name"], "strategy": s["name"], "stale": stale, **flatten(row),
                        **complexity.cell(row, cx.get(row["id"]) if row else None),
                        **analysis.cell(c["id"], v["name"], c["hash"])}
                cells.append(cell)
                if row and lr.get(row["id"]):
                    lr_cells.append((s["name"], v["name"], c["level"], lr[row["id"]]))
                t = totals.setdefault(s["name"], {**{k: 0 for k in STATUSES}, "missing": 0, "stale": 0, "total": 0, "seconds": 0.0,
                                                  "achievable": 0, "achievable_pass": 0, "data_limited": 0, "unidentifiable": 0})
                t["total"] += 1
                lab = cell.get("analysis")                        # analysis.py: what the data can deliver in this cell
                t["achievable"] += lab == "achievable"
                t["achievable_pass"] += lab == "achievable" and cell["status"] == "pass"
                t["data_limited"] += lab == "data-limited"
                t["unidentifiable"] += lab == "unidentifiable"
                t[cell["status"] or "missing"] += 1
                t["stale"] += bool(stale and row)
                t["seconds"] += cell.get("seconds") or 0.0
                for tag in c["tags"]:
                    g = by_tag.setdefault(tag, {}).setdefault(s["name"], {**{k: 0 for k in STATUSES}, "missing": 0, "total": 0})
                    g["total"] += 1
                    g[cell["status"] or "missing"] += 1
    return jsonable({"strategies": strats,
                     "cases": [{k: c[k] for k in ("id", "title", "level", "tags", "tests", "hash")} | {"variants": [v["name"] for v in c["variants"]]} | draw_brief(c) for c in cs],
                     "cells": cells, "by_tag": by_tag, "totals": totals, "score_hash": sh, "parametric": parametric(cs, cells),
                     "longrun": longrun_cache.aggregate(lr_cells)})


def draw_brief(c: dict) -> dict:
    """A draw's numbers for a listing: {draw: {base, i, of, lines (its drawn lines), values {label: value}}}
    ({} for a case that is not a draw)."""
    d = c.get("draw")
    if not d:
        return {}
    return {"draw": {"base": d["base"], "i": d["i"], "of": d["of"], "lines": list(dict.fromkeys(x["line"] for x in d["values"])),
                     "values": {x["label"]: x["value"] for x in d["values"]}}}


def parametric(cs: list[dict], cells: list[dict]) -> dict:
    """Each parametric case over its draws: {file id: {title, level, tags, draws: [ids], strategies: {name:
    {pass, equivalent, fail, error, timeout, missing, total (cells: draws x variants), rate (pass / total),
    draws_passing (draws that pass in every variant), draws_run (draws run in every variant)}}}}."""
    out: dict[str, dict] = {}
    by_case: dict[str, list] = {}
    for x in cells:
        by_case.setdefault(x["case"], []).append(x)
    for c in cs:
        d = c.get("draw")
        if not d:
            continue
        g = out.setdefault(d["base"], {"title": c["title"], "level": c["level"], "tags": c["tags"], "draws": [], "strategies": {}})
        g["draws"].append(c["id"])
        per: dict[str, list] = {}
        for x in by_case.get(c["id"], []):
            per.setdefault(x["strategy"], []).append(x)
        for name, xs in per.items():
            t = g["strategies"].setdefault(name, {**{k: 0 for k in STATUSES}, "missing": 0, "total": 0, "draws_passing": 0, "draws_run": 0})
            for x in xs:
                t["total"] += 1
                t[x["status"] or "missing"] += 1
            t["draws_run"] += all(x["status"] for x in xs)
            t["draws_passing"] += all(x["status"] == "pass" for x in xs)
    for g in out.values():
        for t in g["strategies"].values():
            t["rate"] = t["pass"] / t["total"] if t["total"] else None
    return out
