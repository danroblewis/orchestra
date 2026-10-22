"""Conserving rewrites: the same levels written with the moves that conserve, never a new number (k8s-317, 2026-10-22).

Two drawings of one stock's rows give the same levels on every state, and the passes after the program
can leave the one with more numbers or a link standing in for a move:

- a link outside -> D reading k x S, S a measured stock of D's unit that the boundary lets drain to the
  outside at g x S (g >= k), is the move S -> D at k with the drain at g - k (what the link brings into D
  is what the extra drain took out of S): retries that come back to their queue, written as the queue's
  inflow reading the retries and the retries all given up (317: 0.6 x retries into the queue, gave up at 1);
- an outside inflow into D reading -k x D (a gap on its own level) beside D's drain at g x D is the drain
  at g + k (317: cpu's inflow 1.25 inflight + 20 ready - 0.25 cpu, its window 0.25; the truth's 0.5).

The user's rule (2026-10-21): proven algebraic equivalence prefers the conserving move. Each rewrite is
made only where it is exact on the run and off it: the inflow left behind never goes below 0 (the
engine's floor would differ), the rewritten one never did either, and the drain stays positive (a
declared side is always present). Only plain linear rates (no pieces, effects or expressions) are read.
The same rule for every case: nothing reads the case or its truth.
"""

from __future__ import annotations

import numpy as np

from .hinge import _env, _plain, _rate
from .steps import Steps

TINY = 1e-6           # a drain's number left after a rewrite must exceed this share of the original


def _value(d: dict, env: dict, T: int) -> np.ndarray | None:
    out = np.full(T, float(d.get(None, 0.0)))
    for r, k in d.items():
        if r is None:
            continue
        x = env.get(r)
        if x is None:
            return None
        out = out + k * np.asarray(x, dtype=float)[:T]
    return out


def _set(f: dict, d: dict) -> dict:
    rate = _rate(d)
    g = {**f, "rate": rate}
    if "rates" in g:
        g["rates"] = [rate]
    return g


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    st = Steps(stocks, run, opts or {})
    if st.T < 3 or not st.ids:
        return flows, {}
    env = _env(st)
    T = st.T
    flows = [dict(f) for f in flows or []]
    bd = run.get("boundary") or {}
    declared = bool(run.get("boundary_declared"))
    skip = set(skip)
    notes = []

    def drain(s: str) -> int | None:
        """The index of s's one proportional outside drain."""
        ix = [i for i, f in enumerate(flows) if f.get("from") == s and f.get("to") is None]
        if len(ix) != 1:
            return None
        d = _plain(flows[ix[0]])
        return ix[0] if d is not None and set(d) == {s} else None

    def move(s: str, dst: str) -> int | None:
        ix = [i for i, f in enumerate(flows) if f.get("from") == s and f.get("to") == dst]
        if not ix:
            return -1
        d = _plain(flows[ix[0]])
        return ix[0] if len(ix) == 1 and d is not None and set(d) == {s} else None

    for i in range(len(flows)):
        f = flows[i]
        D = f.get("to")
        if f.get("from") is not None or D not in st.ids or D in skip:
            continue
        if declared and "input" in ((bd.get(D) or {}).get("in") or []):
            continue
        d = _plain(f)
        if not d:
            continue
        before = _value(d, env, T)
        if before is None or np.any(before < -1e-12):
            continue
        for S, k in sorted(((r, v) for r, v in d.items() if r is not None), key=str):
            if S not in st.ids or S in skip or S in st.final:
                continue
            if S == D and k < 0:                                         # a gap on its own level: the drain's
                j = drain(D)
                if j is None:
                    continue
                rest = {r: v for r, v in d.items() if r != S}
                after = _value(rest, env, T)
                if after is None or np.any(after < -1e-12) or not rest:
                    continue
                g = _plain(flows[j])[D]
                flows[j] = _set(flows[j], {D: g - k})
                d = rest
                notes.append({"flow": f"outside->{D}", "own": round(-k, 6), "drain": f"{D}->outside", "to": round(g - k, 6)})
                continue
            if S == D or k <= 0 or not st.same_unit(S, D) or st.units.get(S) != st.units.get(D):
                continue
            j = drain(S)
            if j is None:
                continue
            g = _plain(flows[j])[S]
            if g - k <= TINY * g:
                continue
            m = move(S, D)
            if m is None:
                continue
            rest = {r: v for r, v in d.items() if r != S}
            after = _value(rest, env, T)
            if after is None or np.any(after < -1e-12) or not rest:
                continue
            flows[j] = _set(flows[j], {S: g - k})
            if m == -1:
                flows.append({"from": S, "to": D, "ratio": 1, "id": f"milp:conserve:{S}->{D}",
                              "rate": {"form": "proportional", "stock": S, "k": float(f"{k:.6g}")}})
            else:
                flows[m] = _set(flows[m], {S: _plain(flows[m])[S] + k})
            d = rest
            notes.append({"flow": f"outside->{D}", "link": S, "k": round(k, 6), "move": f"{S}->{D}", "drain": round(g - k, 6)})
        flows[i] = _set(f, d)
    return flows, {"rewrites": notes} if notes else {}
