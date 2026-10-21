"""Each case's summary over the strategies (/api/ladder/casestats, the Cases view's list), computed on the
server from the summary (api.summary) so the page never fetches every cell to colour its list.

    verdict(statuses)   one strategy's verdict on a case from its run variants' statuses (None: not run)
    row(case, cells)    [ran, pass, equivalent, fits, fail, error or timeout, cells run, cells passing, cells]
    view()              {version, strategies, fields, rows: [[case id, set, kubernetes, level, *row]]}, cached

A strategy's verdict on a case: "pass" when every variant it ran passes, "equivalent" when every one
is pass or equivalent (and not all pass), "fits" when every one is pass, equivalent or fits (2026-10-21:
the data cannot tell it from the truth, not proven equivalent), "fail" when any is a fail, otherwise "error" (an error or a
timeout, which counts as not passing). Variants it has not run are left out; a strategy with no run
variant has not run the case and is not counted ("not run" is never a fail or a pass). The pass rate
the page shows is pass / ran: equivalent is shown beside it, not counted as a pass.

Rows are kept per case with the cells they came from: summary_build.py keeps a cell that did not
change as the same object, so a new summary adds up again only the cases whose cells changed.
"""

from __future__ import annotations

import threading

from . import leaderboard

FIELDS = ("ran", "pass", "equivalent", "fits", "fail", "other", "cells_run", "cells_pass", "cells")


def verdict(statuses: list) -> str | None:
    run = [s for s in statuses if s]
    if not run:
        return None
    if all(s == "pass" for s in run):
        return "pass"
    if all(s in ("pass", "equivalent") for s in run):
        return "equivalent"
    if all(s in ("pass", "equivalent", "fits") for s in run):
        return "fits"
    return "fail" if "fail" in run else "error"


def row(cells: list[dict]) -> list[int]:
    """A case's numbers over its cells (one per variant x strategy)."""
    per: dict[str, list] = {}
    for c in cells:
        per.setdefault(c["strategy"], []).append(c["status"])
    n = {"pass": 0, "equivalent": 0, "fits": 0, "fail": 0, "error": 0}
    for sts in per.values():
        v = verdict(sts)
        if v:
            n[v] += 1
    run = [c for c in cells if c["status"]]
    return [sum(n.values()), n["pass"], n["equivalent"], n["fits"], n["fail"], n["error"], len(run),
            sum(1 for c in run if c["status"] == "pass"), len(cells)]


_memo: dict = {}                     # case id -> (its cells, its row)
_cache: dict = {"sm": None, "value": None}
_lock = threading.Lock()


def rows(sm: dict) -> list[list]:
    names = {s["name"] for s in sm["strategies"]}
    by: dict[str, list] = {c["id"]: [] for c in sm["cases"]}
    for c in sm["cells"]:
        if c["case"] in by and c["strategy"] in names:
            by[c["case"]].append(c)
    out = []
    for c in sm["cases"]:
        mine = by[c["id"]]
        had = _memo.get(c["id"])
        if had and len(had[0]) == len(mine) and all(a is b for a, b in zip(had[0], mine)):
            r = had[1]
        else:
            r = row(mine)
            _memo[c["id"]] = (mine, r)
        out.append([c["id"], leaderboard.kind_of(c), leaderboard.is_k8s(c), c["level"], *r])
    for gone in set(_memo) - set(by):
        _memo.pop(gone, None)
    return out


def view() -> dict:
    sm, version = leaderboard.summary_now()
    with _lock:
        if _cache["sm"] is sm:
            return _cache["value"]
        value = {"version": version, "strategies": len(sm["strategies"]), "fields": ["case", "set", "kubernetes", "level", *FIELDS],
                 "rows": rows(sm)}
        _cache.update(sm=sm, value=value)
        return value
