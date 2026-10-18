"""The ladder's read API: what a page (or anything else) needs to show the ladder. Read only, every
value JSON-safe. The server exposes it under /api/ladder (sdlab/server.py); see docs/LADDER.md.

    cases()                              every case: id, title, level, tags, tests, hash, variants, tolerance, model
    case(case_id)                        one case (None if unknown)
    strategies()                         every strategy: name, hash, available, reason
    results(case, variant, strategy)     the latest result per (case, variant, strategy), filtered by any given
    result(case, variant, strategy)      the latest result for one, with the found flows (None if never run)
    history(case, variant, strategy)     every result for one, newest first (without found flows)
    result_by_id(id)                     one stored result by its id, with the found flows (None if unknown)
    case_data(case_id, variant, fresh, flows)   the case's data in a variant: t, levels (measured), all_levels, eras, (flows)
    timeline(strategy)                   the strategy's totals after each version (strategy and scorer hash) it ran with
    progress(recent?)                    the current or last run: {run, items}; with recent, a light copy for polling
    summary()                            the matrix: strategies, cases, cells (one per case x variant x
                                         strategy, flattened scores, stale or not) and per-tag and per-strategy totals

A result: {id, case, variant, strategy, case_hash, strategy_hash, score_hash, at, latest, status
("pass" | "equivalent" | "fail" | "error" | "timeout"), seconds, error, scores (score.py), found?}.
"""

from __future__ import annotations

from ..discovery.api import jsonable
from . import cases as casemod
from . import catalog, data, score, store

STATUSES = ("pass", "equivalent", "fail", "error", "timeout")


def _case(cid: str) -> dict:
    c = casemod.load(cid)
    return {**c, "variants": [dict(v) for v in c["variants"]]}


def cases() -> list[dict]:
    return jsonable([_case(i) for i in casemod.case_ids()])


def case(case_id: str) -> dict | None:
    return jsonable(_case(case_id)) if case_id in casemod.case_files() else None


def strategies() -> list[dict]:
    return jsonable(catalog.listing())


def strategy_names() -> list[str]:
    return catalog.names()


def results(case: str | None = None, variant: str | None = None, strategy: str | None = None) -> list[dict]:
    return jsonable(store.latest(case, variant, strategy))


def result(case: str, variant: str, strategy: str) -> dict | None:
    rows = store.latest(case, variant, strategy, found=True)
    return jsonable(rows[0]) if rows else None


def history(case: str, variant: str, strategy: str) -> list[dict]:
    return jsonable(store.history(case, variant, strategy))


def result_by_id(result_id: int) -> dict | None:
    r = store.get(result_id, found=True)
    return jsonable(r) if r else None


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


def summary(strategy_filter: list[str] | None = None) -> dict:
    strats = [s for s in catalog.listing() if not strategy_filter or s["name"] in strategy_filter]
    sh = score.score_hash()
    have = {(r["case"], r["variant"], r["strategy"]): r for r in store.latest()}
    cs = [casemod.load(i) for i in casemod.case_ids()]
    cells, by_tag, totals = [], {}, {}
    for c in cs:
        for v in c["variants"]:
            for s in strats:
                row = have.get((c["id"], v["name"], s["name"]))
                stale = store.staleness(row, c["hash"], s["hash"], sh) if s["available"] else None
                cell = {"case": c["id"], "variant": v["name"], "strategy": s["name"], "stale": stale, **flatten(row)}
                cells.append(cell)
                t = totals.setdefault(s["name"], {**{k: 0 for k in STATUSES}, "missing": 0, "stale": 0, "total": 0, "seconds": 0.0})
                t["total"] += 1
                t[cell["status"] or "missing"] += 1
                t["stale"] += bool(stale and row)
                t["seconds"] += cell.get("seconds") or 0.0
                for tag in c["tags"]:
                    g = by_tag.setdefault(tag, {}).setdefault(s["name"], {**{k: 0 for k in STATUSES}, "missing": 0, "total": 0})
                    g["total"] += 1
                    g[cell["status"] or "missing"] += 1
    return jsonable({"strategies": strats,
                     "cases": [{k: c[k] for k in ("id", "title", "level", "tags", "tests", "hash")} | {"variants": [v["name"] for v in c["variants"]]} for c in cs],
                     "cells": cells, "by_tag": by_tag, "totals": totals, "score_hash": sh})
