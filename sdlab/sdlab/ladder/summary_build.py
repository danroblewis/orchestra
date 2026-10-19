"""The ladder's summary (api.summary) built incrementally: the same value as building it from scratch,
but a rebuild redoes only what changed since the last one.

- The latest result per (case, variant, strategy) is kept in memory per store and topped up with the
  results stored since (store.after), instead of reading and parsing every result again.
- Each cell is kept with what it was made from (its result's id, the case's and the strategy's hash,
  the scorer's hash, the cell's analysis, long-run metrics and strict reference). A cell is made
  again only when one of those changed; the analysis of a (case, variant) is read once, not once per
  strategy.
- A strategy's totals (tests, per tag, realistic, physics, particles, real data, long run) are added
  up again only when one of its cells changed.

The cells go out JSON-safe (jsonable) once, when they are made; the aggregates are made from the raw
cells, as before, so every number is the one a full build gives (tests/test_ladder_summary_build.py).
"""

from __future__ import annotations

import itertools
import threading

from ..discovery.api import jsonable
from . import analysis, complexity, longrun_cache, particles, physics, realistic, score, store, strict
from . import sim as _sim
from . import cases as casemod
from .real import case as _real_case
from .real import score as _real_score

_stores: dict = {}               # store path -> {"rows": {key: row}, "last": id, "last_key": its key, "cells": {...}, "aggs": {...}}
_lock = threading.Lock()
_serial = itertools.count(1)


def _state() -> dict:
    where = str(store.path())
    st = _stores.get(where)
    if st is None:
        st = _stores[where] = {"rows": None, "last": 0, "last_key": None, "cells": {}, "aggs": {}}
    return st


def latest_rows() -> dict[tuple, dict]:
    """{(case, variant, strategy): the latest result} (without found flows), read incrementally: only
    the results stored since the last read (results are never changed or deleted, only added)."""
    st = _state()
    if st["rows"] is not None and (not st["last"] or store.key_of(st["last"]) == st["last_key"]):
        for r in store.after(st["last"]):
            key = (r["case"], r["variant"], r["strategy"])
            st["rows"][key] = r
            st["last"], st["last_key"] = r["id"], key
        return st["rows"]
    rows = store.latest()                                   # the first read, or the store was replaced
    have = {(r["case"], r["variant"], r["strategy"]): r for r in rows}
    top = max(rows, key=lambda r: r["id"], default=None)
    st.update(rows=have, last=top["id"] if top else 0, last_key=(top["case"], top["variant"], top["strategy"]) if top else None,
              cells={}, aggs={})
    return latest_rows()


def _group(c: dict) -> str:
    if c.get("example"):
        return "realistic"
    if c.get("real"):
        return "real"
    if particles.is_particles(c):
        return "particles"
    if physics.is_physics(c):
        return "physics"
    return "tests"


def _make(c: dict, v: str, s: dict, row: dict | None, stale, an: dict, cx, lr, ref, group: str) -> dict:
    """One cell, exactly as api._summary always made it."""
    from .api import flatten
    cell = {"case": c["id"], "variant": v, "strategy": s["name"], "stale": stale, **flatten(row),
            **complexity.cell(row, cx), **an}
    if row:                                                   # strict.py: a pass that also behaves (not computed: None)
        cell.update(strict.cell(strict.verdict(row["status"], cell.get("fresh100"), cx, lr, ref)))
    if group == "realistic":
        cell["goal"] = realistic.meets_goal(cell["status"], cell["skill20"], cell["skill100"]) if row else None
        cell["goal_fresh"] = realistic.meets_goal(cell["status"], cell["fresh20"], cell["fresh100"]) if row else None
    elif group == "real":
        cell.update(_real_score.cell(row))
    elif group == "particles":
        cell.update(particles.cell(row))
    elif group == "physics":
        cell.update(physics.cell(row))
    return cell


def _aggregate(name: str, items: list[tuple]) -> dict:
    """One strategy's totals from its cells [(case, group, raw cell, stale, row, long-run metrics, position
    in the whole matrix)]; lr_first: the position of its first cell with long-run metrics (the order a
    full build lists the long-run aggregate in)."""
    from .api import STATUSES
    t = None
    tags: dict = {}
    real, phys, parts, realdata, lr_cells, lr_first = [], [], [], [], [], None
    for c, group, cell, stale, row, lr, at in items:
        if group == "realistic":
            real.append(cell)
            continue
        if group == "real":
            realdata.append(cell)
            continue
        if group == "particles":
            parts.append(cell)
            continue
        if group == "physics":
            phys.append(cell)
            continue
        if row and lr:
            lr_cells.append((name, cell["variant"], c["level"], lr))
            if lr_first is None and not lr.get("error"):
                lr_first = at
        if t is None:
            t = {**{k: 0 for k in STATUSES}, "missing": 0, "stale": 0, "total": 0, "seconds": 0.0,
                 "achievable": 0, "achievable_pass": 0, "data_limited": 0, "unidentifiable": 0, "strict": 0, "strict_known": 0}
        t["total"] += 1
        lab = cell.get("analysis")                            # analysis.py: what the data can deliver in this cell
        t["achievable"] += lab == "achievable"
        t["achievable_pass"] += lab == "achievable" and cell["status"] == "pass"
        t["data_limited"] += lab == "data-limited"
        t["unidentifiable"] += lab == "unidentifiable"
        t[cell["status"] or "missing"] += 1
        t["strict"] += cell.get("strict") == 1
        t["strict_known"] += cell.get("strict") is not None
        t["stale"] += bool(stale and row)
        t["seconds"] += cell.get("seconds") or 0.0
        for tag in c["tags"]:
            g = tags.setdefault(tag, {**{k: 0 for k in STATUSES}, "missing": 0, "total": 0})
            g["total"] += 1
            g[cell["status"] or "missing"] += 1
    return {"totals": t, "by_tag": tags,
            "realistic": realistic.aggregate(real) if real else None, "physics": physics.aggregate(phys) if phys else None,
            "particles": particles.aggregate(parts) if parts else None, "real": _real_score.aggregate(realdata) if realdata else None,
            "longrun": longrun_cache.aggregate(lr_cells).get(name), "lr_first": lr_first}


def build(strategy_filter: list[str] | None, listing: list[dict]) -> dict:
    """The summary (api.py's module docstring), from what changed since the last build."""
    with _lock:
        return _build(strategy_filter, listing)


def _build(strategy_filter: list[str] | None, listing: list[dict]) -> dict:
    from .api import draw_brief, parametric
    strats = [s for s in listing if not strategy_filter or s["name"] in strategy_filter]
    sh = score.score_hash()
    have = latest_rows()
    st = _state()
    rows = list(have.values())
    cx = complexity.for_results(rows)
    lr = longrun_cache.for_results(rows)                      # read only: what `sdlab-ladder longrun` computed
    refs = strict.references()                                # read only: what `sdlab-ladder strict` computed
    cs = [casemod.load(i) for i in casemod.case_ids()]
    cache, seen = st["cells"], set()
    out_cells, draw_cells = [], []
    per: dict[str, list] = {s["name"]: [] for s in strats}
    sig: dict[str, list] = {s["name"]: [] for s in strats}
    for c in cs:
        group = _group(c)
        shc = particles.score_hash(sh) if particles.is_particles(c) else physics.score_hash(sh) if physics.is_physics(c) else sh
        shc = _sim.code_hash(shc) if _sim.uses_new(c.get("model") or {}) else shc       # a truth with 2d's engine features: sim.py too
        for v in c["variants"]:
            an = analysis.cell(c["id"], v["name"], c["hash"])
            ref = refs.get((c["id"], c["hash"], v["name"]))
            for s in strats:
                key = (c["id"], v["name"], s["name"])
                row = have.get(key)
                rid = row["id"] if row else None
                lrr = lr.get(rid) if row else None
                cxr = cx.get(rid) if row else None
                dep = (rid, c["hash"], s["hash"], s["available"], shc, group, an, cxr, lrr, ref if row else None)
                got = cache.get(key)
                if got is None or got[0] != dep:
                    stale = store.staleness(row, c["hash"], s["hash"], shc) if s["available"] else None
                    raw = _make(c, v["name"], s, row, stale, dict(an), cxr, lrr, ref, group)
                    got = cache[key] = (dep, raw, jsonable(raw), stale, next(_serial))
                seen.add(key)
                _, raw, js, stale, n = got
                out_cells.append(js)
                if c.get("draw"):
                    draw_cells.append(raw)
                per[s["name"]].append((c, group, raw, stale, row, lrr, len(out_cells)))
                sig[s["name"]].append(n)
    names = set(per)
    for k in [k for k in cache if k[2] in names and k not in seen]:                # cells of cases or variants that are gone
        del cache[k]
    aggs = st["aggs"]
    blocks = {}
    for s in strats:
        name, key = s["name"], tuple(sig[s["name"]])
        got = aggs.get(name)
        if got is None or got[0] != key:
            got = aggs[name] = (key, jsonable(_aggregate(name, per[name])))
        blocks[name] = got[1]
    tag_order: list = []
    for c in cs:
        if _group(c) == "tests":
            tag_order += [t for t in c["tags"] if t not in tag_order]
    by_tag = {}
    for tag in tag_order:
        g = {n: b["by_tag"][tag] for n, b in blocks.items() if tag in b["by_tag"]}
        if g:
            by_tag[tag] = g
    pick = lambda part: {n: b[part] for n, b in blocks.items() if b[part] is not None}   # noqa: E731
    return {"strategies": jsonable(strats),
            "cases": jsonable([{k: c[k] for k in ("id", "title", "level", "tags", "tests", "hash")} | {"variants": [v["name"] for v in c["variants"]]} | draw_brief(c)
                               | ({"example": c["example"]} if c.get("example") else {}) | ({"real": _real_case.describe(c)} if c.get("real") else {})
                               | ({"physics": {k: c["physics"][k] for k in ("system", "differs")}} if c.get("physics") else {})
                               | ({"particles": {**{k: c["particles"][k] for k in ("system", "tier", "equations", "regions", "particles", "mean_field")},
                                                   "check": {k: c["particles"]["check"][k] for k in ("z_rms", "rel", "runs", "steps")}}} if c.get("particles") else {})
                               for c in cs]),
            "cells": out_cells, "by_tag": by_tag, "totals": pick("totals"), "realistic": pick("realistic"),
            "physics": pick("physics"), "particles": pick("particles"), "real": pick("real"), "score_hash": sh,
            "parametric": jsonable(parametric(cs, draw_cells)),
            "longrun": {n: b["longrun"] for n, b in sorted(blocks.items(), key=lambda x: x[1]["lr_first"] or 0) if b["longrun"] is not None}}
