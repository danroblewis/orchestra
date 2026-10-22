"""The ladder's read API: what a page (or anything else) needs to show the ladder. Read only, every
value JSON-safe. The server exposes it under /api/ladder (sdlab/server.py); see docs/LADDER.md.

    cases()                              every case: id, title, level, tags, tests, hash, variants, tolerance, model,
                                         and boundary ({stock: {in, out}}) when the case declares one (2026-10-20)
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
    diff(case, variant, strategy, id?)   the found model as a git diff of the truth (diff.py): stat, lines, hunk, per-flow verdicts
    run_graph(id, at?, window?)          one result's true vs found levels run free from the start, far ahead (longrun_series.py)
    summary()                            the matrix: strategies, cases, cells (one per case x variant x
                                         strategy, flattened scores, stale or not) and per-tag and per-strategy totals

A result: {id, case, variant, strategy, case_hash, strategy_hash, score_hash, at, latest, status
("pass" | "equivalent" | "fits" | "fail" | "error" | "timeout"; fits: the data cannot tell it from the truth, not proven equivalent), seconds, error, scores (score.py), found?}; one read
with its found flows also has found_merged when some of its flows share both ends (merge.py: one flow per
pair of stocks, as the scorer and the drawings read them), complexity (complexity.py: true vs found) and longrun (longrun.py: long-horizon
metrics, computed once per result id by longrun_cache.py), and summary cells carry both, and strict (strict.py: 1, 0,
or None when not computed yet) with strict_why (the reasons a pass fails strict, or what is pending).
"""

from __future__ import annotations

import threading
import time

from ..discovery.api import jsonable
from . import cases as casemod
from . import analysis, catalog, complexity, data, explain, longrun_cache, merge, score, store, strict
from .real import data as _real_data

STATUSES = ("pass", "equivalent", "fits", "fail", "error", "timeout")


def _case(cid: str) -> dict:
    c = casemod.load(cid)
    return {**c, "variants": [dict(v) for v in c["variants"]]}


def cases() -> list[dict]:
    return jsonable([_case(i) for i in casemod.case_ids()])


def case(case_id: str) -> dict | None:
    return jsonable(_case(case_id)) if casemod.known(case_id) else None


def strategies() -> list[dict]:
    """Every strategy, with its standing: retired (retired.yaml), parked (parked.yaml) or "" (active),
    and the competitions that eliminated it ({roster: {rung, kind, reason}}, rosters/*.yaml)."""
    from . import runner

    gone, park = runner.retired(), runner.parked()
    rosters = {p.stem: runner.roster(p.stem) for p in sorted(runner.ROSTERS.glob("*.yaml"))}
    return jsonable([{**s, "about": explain.about(s["name"]),
                      "standing": "retired" if s["name"] in gone else "parked" if s["name"] in park else "",
                      "why": gone.get(s["name"]) or park.get(s["name"]) or "",
                      "eliminated": {k: v[s["name"]] for k, v in rosters.items() if s["name"] in v}} for s in catalog.listing_nowait()])


def glossary() -> dict:
    return jsonable(explain.glossary())


def strategy_names() -> list[str]:
    return catalog.names()


def results(case: str | None = None, variant: str | None = None, strategy: str | None = None) -> list[dict]:
    return jsonable(store.latest(case, variant, strategy))


def result(case: str, variant: str, strategy: str) -> dict | None:
    rows = store.latest(case, variant, strategy, found=True)
    return jsonable(_merged(longrun_cache.attach(complexity.attach(rows[0])))) if rows else None


def _merged(row: dict | None) -> dict | None:
    """The row with found_merged: its found flows with the same-pair ones merged (merge.py), what the
    scorer cuts into parts and the page draws; only when some were merged (found stays as stored)."""
    if row is not None and row.get("found"):
        got = merge.flows(row["found"])
        if got is not row["found"]:
            row["found_merged"] = got
    return row


def history(case: str, variant: str, strategy: str) -> list[dict]:
    return jsonable(store.history(case, variant, strategy))


def result_by_id(result_id: int) -> dict | None:
    r = store.get(result_id, found=True)
    return jsonable(_merged(longrun_cache.attach(complexity.attach(r)))) if r else None


def diff(case_id: str, variant: str, strategy: str, result_id: int | None = None) -> dict | None:
    """The found model as a git diff of the truth (diff.py; what the page draws and `sdlab-ladder diff`
    prints): the latest result of the cell, or result_id when it is one of the cell's (None otherwise)."""
    from . import diff_report
    if result_id is None:
        rows = store.latest(case_id, variant, strategy, found=True)
        row = rows[0] if rows else None
    else:
        row = store.get(result_id, found=True)
        if row and (row["case"], row["variant"], row["strategy"]) != (case_id, variant, strategy):
            row = None
    return jsonable(diff_report.of_row(diff_report.case_view(case_id), row)) if row else None


def run_graph(result_id: int, at: list[int] | None = None, window: int | None = None) -> dict | None:
    """What the run page plots for one result (longrun_series.graph), or None if it found nothing."""
    from . import longrun_series
    return jsonable(longrun_series.graph(result_id, at, window))


def case_data(case_id: str, variant: str, fresh: bool = False, flows: bool = False) -> dict:
    """What the detector sees (levels of the measured stocks) and what it does not (all_levels: every
    stock, hidden ones too), for a page to plot; with flows, also every true flow's amount per step
    (`flows`, which discovery never sees)."""
    c = casemod.load(case_id)
    d = _real_data.load(c, variant, full=True) if c.get("real") else data.load(c, variant, fresh=fresh)    # real/: the whole series
    measured = [s["id"] for s in c["model"]["stocks"] if s.get("measured", True)]
    out = {"case": case_id, "variant": variant, "fresh": bool(fresh), "t": d["t"], "levels": d["levels"], "all_levels": d["all_levels"],
           "measured": measured, "eras": d.get("eras") or [], "injections": d.get("injections") or []}
    if d.get("inputs"):
        out["inputs"] = d["inputs"]                         # measured inputs: {name: value per step}, a page input
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
    rows = [r for r in store.latest(strategy=strategy, found=True) if names is None or r["variant"] in names or r["variant"] in ("real", "twin")]
    known = set(casemod.case_ids())
    return jsonable({"strategy": strategy, "variant": variant, "best": best_strategy(),
                     "cases": [_case(i) for i in casemod.case_ids()],
                     "results": [_merged(complexity.attach(r)) for r in rows if r["case"] in known]})


def progress(recent: int | None = None) -> dict:
    """The current or last run. With recent, a light copy for polling: only the running items and the
    `recent` most recently finished ones, plus `counts` (finished items by status) and `queued`."""
    p = store.progress()
    pool = _pool_progress(recent if recent is not None else 1000)
    last_local = max([x for i in p["items"] for x in (i.get("started"), i.get("finished")) if x] + [(p.get("run") or {}).get("started") or ""], default="")
    if pool and pool["last"] > last_local:              # the CPU pool runs the tests now: follow what it does
        pool.pop("last")
        return jsonable(pool)
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


def _pool_progress(recent: int) -> dict | None:
    """What the CPU pool is doing, in progress()'s shape (the Now page's follow, the runs strip): the items its
    workers hold now (running) and its most recent results (done), across every job still open or finished in
    the last hour. None when the pool has nothing."""
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{store.path()}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        running = [{"case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"], "state": "running", "reason": f"pool job {r['job_id']}",
                    "started": r["leased_at"], "finished": None, "status": None, "job": r["job_id"], "by": r["by"], "worker": r["worker"],
                    "timeout": r["timeout"] or 300, "mode": r["mode"]}
                   for r in con.execute("SELECT i.job_id, i.case_id, i.variant, i.strategy, i.leased_at, i.worker, i.timeout, i.mode, j.by"
                                        " FROM pool_items i JOIN pool_jobs j ON j.id = i.job_id WHERE i.state = 'leased' ORDER BY i.leased_at DESC LIMIT 200")]
        done = [{"case": r["case_id"], "variant": r["variant"], "strategy": r["strategy"], "state": "done", "reason": f"pool job {r['job_id']}",
                 "started": None, "finished": r["at"], "status": r["status"], "seconds": r["seconds"], "machine": r["machine"], "id": r["promoted_id"]}
                for r in con.execute("SELECT job_id, case_id, variant, strategy, status, at, seconds, machine, promoted_id FROM pool_results ORDER BY id DESC LIMIT ?", (max(1, recent),))]
        # the timing chart: the last 120 results' times (also when the caller asked for fewer items)
        times = [{"case": r[0], "variant": r[1], "strategy": r[2], "status": r[3], "seconds": r[4], "timeout": r[5] or 300, "id": r[6]}
                 for r in con.execute("SELECT p.case_id, p.variant, p.strategy, p.status, p.seconds, i.timeout, p.promoted_id FROM pool_results p"
                                      " LEFT JOIN pool_items i ON i.id = p.item_id ORDER BY p.id DESC LIMIT 120")][::-1]
        hour = con.execute("SELECT status, count(*) FROM pool_results WHERE at > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 hour') GROUP BY status").fetchall()
        queued = con.execute("SELECT count(*) FROM pool_items WHERE state = 'queued'").fetchone()[0]
        jobs = con.execute("SELECT count(*), min(started) FROM pool_jobs WHERE state IN ('queued', 'running', 'planning')").fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not running and not done:
        return None
    last = max([i["finished"] for i in done if i["finished"]] + [i["started"] for i in running if i["started"]] + [""])
    counts = {st: n for st, n in hour}
    active = bool(running or queued)
    run = {"id": "pool", "command": f"CPU pool: {jobs[0]} open job{'s' if jobs[0] != 1 else ''}" if jobs[0] else "CPU pool",
           "started": jobs[1] or last, "finished": None if active else last, "total": sum(counts.values()) + len(running) + queued,
           "done": sum(counts.values()), "running": len(running)}
    return {"run": run, "items": running + done, "counts": counts, "queued": queued, "last": last, "times": times}


def _here() -> str:
    from .machines import here
    return here()


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
    if row.get("machine") and row["machine"] != _here():
        out["machine"] = row["machine"]                       # run on another machine (exchange.py); this one's: left out
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
        from . import head_hashes                             # the sdlab HEAD's hashes are what "current" means
        have = _summaries.get(slot)
        listing = catalog.listing()
        key = (store.version(), tuple((s["name"], s["hash"], s["available"]) for s in listing),
               tuple((i, casemod.load(i)["hash"]) for i in casemod.case_ids()), score.score_hash(), longrun_cache.version(), analysis.version(), strict.version(),
               head_hashes.version())
        if not have or have["key"] != key:
            have = {"key": key, "value": _summary(strategy_filter, listing)}
        _summaries[slot] = {**have, "at": time.time()}
    finally:
        if release:
            _summary_lock.release()


def _summary(strategy_filter: list[str] | None, listing: list[dict]) -> dict:
    """The summary, rebuilt from what changed since the last build (summary_build.py)."""
    from . import summary_build
    return summary_build.build(strategy_filter, listing)


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
