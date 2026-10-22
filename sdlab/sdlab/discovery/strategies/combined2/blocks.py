"""A block of rows another candidate explains exactly replaces the pick's (docs/research/fixes/312-combined2-r2.md,
2026-10-22).

The judge picks one candidate's whole model, and its runaway guard compares whole models run through the record.
On kubernetes 312 none-long every candidate's pods and nodes rows are still wrong at this stage (the later passes
write them), and the one whose wrong rows run away least (common_cause, multi-step error 21 against lna's 376)
set aside every candidate whose request rows were exact (lna, censored, odefit: queue <-> retries, inflight's two
exits, all to the levels' rounding). The pick had no queue -> retries move; its retries row read desired twice,
in and out, cancelling, and no later pass rebuilds a row that already fits.

A move carries one thing (both stocks in one unit), so the measured stocks of one unit form a block whose one-step
rows depend only on the flows that touch them: the blocks are separable in the rows. Here, for each unit, when a
candidate's flows on the block explain every one of its rows to the levels' rounding (block SSE within EXACT (100) times
the rounding's variance, rowrepair.resolution) and the pick's do not (its SSE over FAR times that candidate's), the
pick's flows on the block are replaced by that candidate's (the most exact one; then fewest numbers). A block
touched by a hidden stock in either model is left alone (its rows are not known here). Nothing changes where no
candidate is exact: on noisy levels this pass is idle.

Adopting it: copy this file (it needs hinge.py's columns/delta, counted.py's _row_sse and rowrepair.resolution) and
call `compose(pick_result, [candidate results], stocks, run, opts)` on the pick, before any pass that refits rows.
"""

from __future__ import annotations

import numpy as np

from . import counted, hinge, rowrepair

EXACT = 100.0         # a block is exact when its SSE is within this many times the rounding's variance (the truth's own request rows on 312 none-long: 6 x)
FAR = 1e3             # the pick's block is replaced only when its SSE is over this many times the exact one's


def _touch(f: dict, rows: set) -> bool:
    return f.get("from") in rows or f.get("to") in rows


def _sse(flows: list[dict], rows: set, levels, cols, n) -> float | None:
    tot = 0.0
    for x in rows:
        v = counted._row_sse(x, flows, levels, cols, n)
        if v is None:
            return None
        tot += v
    return tot


def compose(result: dict, others: list[dict], stocks: list[dict], run: dict, opts: dict | None) -> dict:
    flows = (result or {}).get("flows")
    if not flows or not others:
        return result
    levels, cols, n = hinge.columns(run, opts)
    if n < 10:
        return result
    unit = {s["id"]: s.get("unit") for s in stocks if s["id"] in levels and s.get("unit")}
    out, notes = list(flows), []
    for u in sorted(set(unit.values())):
        rows = {x for x, v in unit.items() if v == u}
        q = rowrepair.resolution(levels, rows)
        if q <= 0:
            continue
        exact = EXACT * len(rows) * n * q * q / 6

        def ok(fl):                                      # only measured stocks (or outside) on the block's flows
            return all(x is None or x in levels for f in fl if _touch(f, rows) for x in (f.get("from"), f.get("to")))
        if not ok(out):
            continue
        mine = _sse(out, rows, levels, cols, n)
        best = None
        for o in others:
            fl = (o or {}).get("flows") or []
            if not fl or not ok(fl):
                continue
            s = _sse(fl, rows, levels, cols, n)
            if s is None or s > exact:
                continue
            k = counted._nums(fl, rows)
            if best is None or (s, k) < (best[0], best[1]):
                best = (s, k, fl, o.get("name"))
        if best is None or (mine is not None and mine <= FAR * max(best[0], 1e-300)):
            continue
        out = [f for f in out if not _touch(f, rows)] + [dict(f) for f in best[2] if _touch(f, rows)]
        notes.append({"unit": u, "rows": sorted(rows), "from": best[3], "sse_pick": mine, "sse_taken": best[0]})
    if not notes:
        return result
    return {**result, "flows": out, "blocks_taken": notes}
