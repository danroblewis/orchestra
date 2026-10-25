"""Whole-unit controllers: a stock counted in whole units that a rule steps up and down (k8s-308, 2026-10-21).

A controller (an autoscaler, an order-up-to rule, anything that acts on a count) moves a stock S that only
ever holds whole numbers, in rare whole steps, when a reading X of another stock crosses a line drawn in
units of S: it adds what is missing below a target ceil(X / a), or removes what is above ceil(X / b). Such
a rate is a step function of the levels; no linear rate (nor a MIN) fits it, and the program's linear
answer for S's outside flows misses every step.

The mechanism, the same for every stock and every reader:
- a stock qualifies when every level is a whole number and it changes in at most half of the steps;
- for S a whole number, S < ceil(X / a) exactly when S / X < 1 / a, so "the inflow acts this step" is a
  threshold on S / X; and S > ceil(X / b) exactly when (S - 1) / X >= 1 / b. Each threshold is the one
  that misclassifies the fewest steps (a sort and a running count), over every other measured stock X
  that is positive on the whole run;
- the target may be clipped at S's highest level seen (the inflow never acts there: nothing took S above
  it) or, for the outflow, its lowest (it never acted there): a clip is kept only where it removes
  misclassified steps;
- the amount is one unit a step ("1 * (S < target)") or the whole gap ("max(0, target - S)"), whichever
  fits the changes better (one unit on a tie);
- the rule is kept only where its changes match S's measured changes within MISS of their total, with
  at least EVENTS steps each way it claims (k8s-317: or at least FEW, where the rule then misses no step:
  a quiet service's autoscaler on a short run moves 3 times up and 5 down), on sides where S may have an outside flow (the boundary
  declares the side, or none is declared). Then S's changes are the rule's: the program fits the other
  stocks with S's row taken out (its changes less the rule's, no flow into or out of S offered), and
  S's flows are the rule's (__init__.identify).

A count stock moved by ordinary rates (counts noise: Poisson amounts) is not a threshold rule: its steps
fall on both sides of every line and the rule is rejected by MISS.
"""

from __future__ import annotations

import numpy as np

SPARSE = 0.5       # a controlled stock changes in at most this share of the steps
EVENTS = 5         # ... and acts at least this many steps on each side the rule claims
FEW = 3            # (k8s-317) or at least this many, where the whole rule then reproduces every step exactly
MISS = 0.05        # the rule's changes match the measured ones within this share of their total


def _cut(score: np.ndarray, ev: np.ndarray) -> tuple[int, float]:
    """The threshold u for "event iff score < u" misclassifying the fewest steps: (errors, u)."""
    o = np.argsort(score, kind="stable")
    s, e = score[o], ev[o].astype(int)
    n = len(s)
    if n == 0:
        return 0, 0.0
    cum = np.concatenate([[0], np.cumsum(e)])
    errs = (np.arange(n + 1) - cum) + (cum[-1] - cum)          # predicted but no event, plus events missed
    i = int(np.argmin(errs))
    lo = s[i - 1] if i > 0 else s[0] - abs(s[0]) - 1.0
    hi = s[i] if i < n else s[-1] + abs(s[-1]) + 1.0
    return int(errs[i]), float((lo + hi) / 2)


def _g(x: float) -> str:
    return f"{x:.6g}"


def _side(S: np.ndarray, dS: np.ndarray, X: np.ndarray, up: bool, edge: float):
    """The best rule on one side reading X: (amount per step, errors, (a, clip or None, unit step?))."""
    ev = dS > 0 if up else dS < 0
    if int(ev.sum()) < FEW:
        return None
    best = None
    for clip in (None, edge):
        keep = np.ones_like(S, bool) if clip is None else (S < clip if up else S > clip)
        score = S / X if up else -(S - 1.0) / X                  # up: S / X < 1/a; down: (S - 1) / X >= 1/b
        miss, u = _cut(score[keep], ev[keep])
        miss += int((ev & ~keep).sum())
        if best is None or miss < best[0]:
            best = (miss, u, clip)
    _, u, clip = best
    inv = u if up else -u
    if inv <= 0:
        return None
    a = 1.0 / inv
    target = np.ceil(X / a)
    if clip is not None:
        target = np.minimum(clip, target) if up else np.maximum(clip, target)
    gap = np.maximum(0.0, target - S) if up else np.maximum(0.0, S - target)
    unit = (gap > 0).astype(float)
    want = np.maximum(0.0, dS) if up else np.maximum(0.0, -dS)
    eu, eg = float(np.abs(unit - want).sum()), float(np.abs(gap - want).sum())
    return (unit, eu, (a, clip, True)) if eu <= eg else (gap, eg, (a, clip, False))


def _expr(s: str, x: str, a: float, clip, unit: bool, up: bool) -> str:
    t = f"ceil({x} / {_g(a)})"
    if clip is not None:
        t = f"min({_g(clip)}, {t})" if up else f"max({_g(clip)}, {t})"
    if up:
        return f"1 * ({s} < {t})" if unit else f"max(0, {t} - {s})"
    return f"1 * ({s} > {t})" if unit else f"max(0, {s} - {t})"


def find(stocks: list[dict], run: dict, opts: dict | None = None) -> tuple[dict, list[dict]]:
    """From the data alone: {stock: {"amount": its rule's change per step, "flows": the rule's outside
    flows}} for every stock a controller rule explains (the module's mechanism), and notes on the
    stocks tried."""
    ids = [s["id"] for s in stocks]
    final = {s["id"] for s in stocks if s.get("final")}
    t = np.asarray(run.get("t") or [], dtype=float)
    L = {i: np.asarray(run["levels"].get(i, []), dtype=float) for i in ids}
    n = len(t)
    if n < 3 * EVENTS or any(len(v) != n or not np.all(np.isfinite(v)) for v in L.values()):
        return {}, []
    declared = bool(run.get("boundary_declared"))
    bd = run.get("boundary") or {}
    at = {float(x): k for k, x in enumerate(t[1:])}
    notes, known = [], {}
    for s in ids:
        v = L[s]
        if s in final or np.any(np.abs(v - np.round(v)) > 1e-9):
            continue
        dS, S = np.diff(v), v[:-1].copy()
        for j in (opts or {}).get("injections") or []:            # an announced injection is not the rule's
            k = at.get(float(j["t"]))
            if j.get("stock") == s and k is not None:
                dS[k] -= float(j["amount"])
                S[k] += float(j["amount"])
        if not np.any(dS) or np.mean(dS != 0) > SPARSE:
            continue
        e = bd.get(s) or {}
        sides = {k: (not declared) or (bool(e.get(k)) and "input" not in (e.get(k) or [])) for k in ("in", "out")}
        found = {}
        for side, up in (("in", True), ("out", False)):
            if not sides[side]:
                continue
            cands = []
            for x in ids:
                X = L[x][:-1]
                if x == s or np.any(X <= 0):
                    continue
                r = _side(S, dS, X, up, float(v.max() if up else v.min()))
                if r is not None:
                    cands.append((r[1], x, r))
            if cands:
                _, x, r = min(cands, key=lambda c: (c[0], c[1]))
                found[side] = (x, r)
        if not found:
            continue
        pred = sum((r[0] if side == "in" else -r[0]) for side, (x, r) in found.items())
        miss, total = float(np.abs(pred - dS).sum()), float(np.abs(dS).sum())
        unexplained = ((dS > 0).any() and "in" not in found) or ((dS < 0).any() and "out" not in found)
        few = any(int(((dS > 0) if side == "in" else (dS < 0)).sum()) < EVENTS for side in found)
        if unexplained or miss > MISS * total or (few and miss > 0):
            notes.append({"stock": s, "used": False, "miss": round(miss, 3), "total": total})
            continue
        flows = []
        for side, (x, r) in sorted(found.items()):
            up = side == "in"
            flows.append({"from": None if up else s, "to": s if up else None, "ratio": 1, "id": f"milp:quantized:{s}:{side}",
                          "rate": {"form": "expr", "expr": _expr(s, x, *r[2], up)}})
        known[s] = {"amount": pred, "flows": flows}
        notes.append({"stock": s, "used": True, "miss": round(miss, 3), "total": total, "rules": [f["rate"]["expr"] for f in flows]})
    return known, notes


def put(flows: list[dict], known: dict) -> list[dict]:
    """flows with each known stock's outside flows (and any move touching it) replaced by its rule's."""
    out = [f for f in flows if not (f.get("from") in known or f.get("to") in known)]
    return out + [g for k in sorted(known) for g in known[k]["flows"]]
