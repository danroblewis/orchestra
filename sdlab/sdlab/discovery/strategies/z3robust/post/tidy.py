"""(Copied from milp's tidy.py at a72bb0d for z3robust, post/__init__.py: flow ids "z3robust:", debug flag Z3ROBUST_DEBUG.)

The finished answer's outside inflows read again, and the plain moves they make needless dropped (k8s-316, 2026-10-22).

The program reads every estimated outside inflow and every move together, on a sample of steps, with its noise
scales still settling; where a mechanism it cannot offer (a pool with a constant ceiling, room.py) leaves misfit,
the inflows nearby pick up readers that only stand in for it (counters, the input, a constant), and a small move
between two measured stocks takes a share of an inflow's link. Once the later passes have placed that mechanism,
the program's readers are no longer what the rows need. Here, on the answer as it stands:

1. each estimated outside inflow (not an input's, not an effect's or a counter's) is re-read by exact best subset
   of 1 to room.SUBSET readers on its own row, every other flow at its amount (room._reread: the program's readers
   for an estimated side; judged by BIC on the row, its current numbers and pieces each paying theirs);
0. (first) each MIN the program wrote, MIN(a x S, b x Y) (not a room), is tried as its demand a x S alone: the
   program chose it beside the misfit the missing mechanism left (a capacity that binds where that misfit was), and
   it goes when, with the inflows re-read and the rows' plain flows refitted, its rows' BIC falls;
2. each plain move between measured stocks (not a room, effect or counted move) is tried away: the inflows on its
   two rows are re-read without it, and it goes when the two rows' BIC (their misfit and the numbers of the flows
   on them) falls by more than MARGIN.

The same for every case: no stock, unit or case is named; nothing changes unless a row's BIC falls.
"""

from __future__ import annotations

import re

import numpy as np

from .hinge import FLOOR, _amount, _env, _plain, _rate, _resolution
from .room import _count, _reread, _settle
from .steps import Steps

MARGIN = 2.0        # BIC units a dropped move must win by
_MIN = re.compile(r"^min\(([-\d.e+]+) \* (\w+), ([-\d.e+]+) \* (\w+)\)$")


def _rows_bic(st: Steps, flows: list[dict], env: dict, rows: list[str], scale, floor) -> float | None:
    pos = {s: i for i, s in enumerate(st.ids)}
    out = 0.0
    for s in rows:
        r = pos[s]
        net, p = np.zeros(st.T), 0
        for f in flows:
            if s not in (f.get("from"), f.get("to")):
                continue
            a = _amount(f, st, env)
            if a is None:
                return None
            net += a if f.get("to") == s else -a
            p += _count(f)
        rss = float(np.sum(((st.dy[r] - net) / scale[r]) ** 2))
        out += st.T * np.log(max(rss, st.T * floor[r] ** 2) / st.T) + p * np.log(st.T)
    return float(out)


def _refit(st: Steps, flows: list[dict], env: dict, rows: list[str], scale) -> list[dict]:
    """The plain flows on the rows refitted jointly by least squares, each with its own readers, the rest at their amounts."""
    pos = {s: i for i, s in enumerate(st.ids)}
    at = [i for i, f in enumerate(flows) if {f.get("from"), f.get("to")} & set(rows) and _plain(f) is not None
          and not (f.get("room_fit") or f.get("effects") or f.get("counts") or f.get("input"))]
    target = np.concatenate([st.dy[pos[s]] for s in rows])
    for i, f in enumerate(flows):
        if i in at or not {f.get("from"), f.get("to")} & set(rows):
            continue
        a = _amount(f, st, env)
        if a is None:
            return flows
        target = target - np.concatenate([(a if f.get("to") == s else -a if f.get("from") == s else 0 * a) for s in rows])
    w = np.concatenate([np.full(st.T, 1.0 / scale[pos[s]]) for s in rows])
    cols, keys = [], []
    for i in at:
        f = flows[i]
        for r in _plain(f):
            x = st.series(r)
            cols.append(np.concatenate([(x if f.get("to") == s else -x if f.get("from") == s else 0 * x) for s in rows]) * w)
            keys.append((i, r))
    if not cols:
        return flows
    th, *_ = np.linalg.lstsq(np.column_stack(cols), target * w, rcond=None)
    out = [dict(f) for f in flows]
    new: dict = {}
    for (i, r), v in zip(keys, th):
        new.setdefault(i, {})[r] = float(v)
    for i, d in new.items():
        rate = _rate(d)
        out[i] = {k: v for k, v in out[i].items() if k not in ("byTime", "rates")} | {"rate": rate, "rates": [rate]}
    return out


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or not st.ids:
        return flows, {}
    env = _env(st)
    skip = set(skip)
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    flows = [dict(f) for f in flows or []]
    keep = [f for f in flows if {f.get("from"), f.get("to")} & skip]
    flows = [f for f in flows if not ({f.get("from"), f.get("to")} & skip)]
    notes: dict = {}
    pos = set(st.ids)
    key = lambda f: (f.get("id"), f.get("from"), f.get("to"))  # noqa: E731
    simple = []
    for k0 in [key(f) for f in flows]:
        f0 = next((f for f in flows if key(f) == k0), None)
        m = _MIN.match(str((f0.get("rate") or {}).get("expr") or "").strip()) if f0 else None
        if not m or f0.get("room_fit") or f0.get("effects") or f0.get("byTime") or m.group(2) != f0.get("from"):
            continue
        rows = [x for x in (f0.get("from"), f0.get("to")) if x in pos]
        base = _refit(st, flows, env, rows, scale)
        b0 = _rows_bic(st, base, env, rows, scale, floor)
        demand = {"form": "proportional", "stock": m.group(2), "k": float(m.group(1))}
        trial = [({kk: v for kk, v in f.items() if kk != "rates"} | {"rate": demand, "rates": [demand]}) if key(f) == k0 else f for f in flows]
        trial, _ = _reread(st, trial, env, scale, floor, every=True)
        trial = _refit(st, trial, env, rows, scale)
        b1 = _rows_bic(st, trial, env, rows, scale, floor)
        if b0 is None or b1 is None or not b1 < b0:
            continue
        flows = trial
        simple.append({"flow": f"{k0[1] or 'outside'}->{k0[2] or 'outside'}", "gain": round(b0 - b1, 1)})
    if simple:
        notes["demand_only"] = simple
        flows, settled = _settle(st, flows, env, scale, floor)   # the rooms polished again with the inflows re-read
        if settled:
            notes["settled"] = settled
    flows, rr = _reread(st, flows, env, scale, floor, every=True)
    if rr:
        notes["reread"] = rr
    dropped = []
    for k0 in [key(f) for f in flows if f.get("from") in pos and f.get("to") in pos]:
        f0 = next((f for f in flows if key(f) == k0), None)
        if f0 is None or f0.get("room_fit") or f0.get("effects") or f0.get("counts") or f0.get("effect_fit") or _plain(f0) is None:
            continue
        rows = [f0["from"], f0["to"]]
        base = _refit(st, flows, env, rows, scale)
        b0 = _rows_bic(st, base, env, rows, scale, floor)
        trial = [f for f in flows if key(f) != k0]
        trial, _ = _reread(st, trial, env, scale, floor, every=True)
        trial = _refit(st, trial, env, rows, scale)
        b1 = _rows_bic(st, trial, env, rows, scale, floor)
        if b0 is None or b1 is None or not b1 < b0 - MARGIN:
            continue
        flows = trial
        dropped.append({"flow": f"{rows[0]}->{rows[1]}", "gain": round(b0 - b1, 1)})
    if dropped:
        notes["dropped"] = dropped
    return flows + keep, notes
