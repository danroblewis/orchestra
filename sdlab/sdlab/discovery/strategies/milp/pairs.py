"""Same-pair revision on every step (k8s-312, 2026-10-22).

The program reads a sample of the steps (SAMPLE, evenly spaced). A capacity that binds on a few short stretches (the
dispatch limit 40 x ready while pods are lost to a node failure: 24 of 2,000 steps) is mostly outside the sample, so
the program may write the move between two stocks as several flows (a plain move and MINs whose capacities read other
levels: queue -> inflight as min(0.11 queue, 0.034 cpu) + min(0.49 queue, 119 nodes)) where one MIN reads the right
level.

The mechanism, the same for every pair of measured stocks S -> D of one unit that the answer joins by a MIN flow or by
more than one flow:
- the rows of S and D are compared as room.py does (_Rows): the flows on the pair replaced, the plain flows with both
  ends on the two rows refitted with the candidate (profiled), the others held at their amounts; the answer's side has
  the pair's flows (plain ones refitted, the others at their amounts and charged their numbers);
- the candidates are the plain move a S and MIN(a S, b Y) for every capacity reader Y (a measured level that is not a
  counter, not S or D, or an input): (a, b) from a grid, polished by least squares;
- the best by BIC over the two rows replaces the pair's flows when it beats the answer by MARGIN (a MIN only when
  each arm is the smaller on at least EVENTS steps where it moves something).
"""

from __future__ import annotations

import re

import numpy as np
from scipy.optimize import least_squares

from .hinge import _amount, _env, _resolution
from .room import FLOOR, _Rows
from .steps import Steps

MARGIN = 10.0
EVENTS = 5
A_GRID = np.geomspace(0.01, 1.0, 13)
B_QUANTILES = np.linspace(0.0, 1.0, 11)
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))
_MIN = re.compile(r"^min\(([-\d.e+]+) \* (\w+), ([-\d.e+]+) \* (\w+)\)$")


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _fit_min(rw: _Rows, S: np.ndarray, Y: np.ndarray) -> tuple[float, float, np.ndarray]:
    """(a, b, residual) of MIN(a S, b Y) on the two rows (the free flows profiled)."""
    pick = None
    ratio = S / np.maximum(Y, 1e-12)
    for a in A_GRID:
        for q in B_QUANTILES:
            b = a * float(np.quantile(ratio, q))
            if b <= 0:
                continue
            e = rw.resid(np.minimum(a * S, b * Y))
            v = float(e @ e)
            if pick is None or v < pick[0]:
                pick = (v, a, b)
    if pick is None:
        return 0.0, 0.0, rw.r0
    f = lambda p: rw.resid(np.minimum(p[0] * S, p[1] * Y))  # noqa: E731
    r = least_squares(f, [pick[1], pick[2]], bounds=([1e-9, 1e-9], [np.inf, np.inf]), method="trf", x_scale="jac", max_nfev=300)
    return float(r.x[0]), float(r.x[1]), f(r.x)


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    st = Steps(stocks, run, opts)
    if st.T < 20 or not st.ids:
        return flows, {}
    env = _env(st)
    flows = [dict(f) for f in flows or []]
    scale = np.sqrt(np.mean(st.dy ** 2, axis=1)) + 1e-12
    res = np.zeros(len(st.ids)) if st.counts else np.array([_resolution(st.L[i]) for i in range(len(st.ids))])
    floor = np.maximum(FLOOR, res / np.sqrt(6.0) / scale)
    skip = set(skip)
    pos = {s: i for i, s in enumerate(st.ids)}
    ceilings = [y for y in st.ids if y not in st.final] + sorted(st.inputs)
    notes = []
    pairs = []
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if a in pos and b in pos and (a, b) not in pairs and not ({a, b} & skip) and a not in st.final and st.same_unit(a, b):
            on = [g for g in flows if (g.get("from"), g.get("to")) == (a, b)]
            if not any(g.get("effects") or g.get("room_fit") or g.get("byTime") for g in on) and (
                    len(on) > 1 or any(_MIN.match(str((g.get("rate") or {}).get("expr") or "").strip()) for g in on)):
                pairs.append((a, b))
    for src, dst in pairs:
        amounts = [_amount(f, st, env) for f in flows]
        rw = _Rows(st, flows, amounts, src, dst, scale, floor, extend=False)
        if not rw.ok:
            continue
        S = st.series(src)
        tried = []
        c = (np.array([-1.0, 1.0])[:, None] * S[None, :] * rw.w[:, None]).ravel()
        cpp = c - rw.Q @ (rw.Q.T @ c)
        den = float(cpp @ cpp)
        if den > 0:
            a = max(0.0, float(cpp @ rw.r0) / den)
            e = rw.resid(a * S)
            tried.append((rw.bic(e, rw.p0 + 1, rw.n, rw.floor), "plain", a, None, None))
        for y in ceilings:
            if y in (src, dst):
                continue
            Y = st.series(y)
            if not np.all(Y > 0):
                continue
            a, b, e = _fit_min(rw, S, Y)
            amt = np.minimum(a * S, b * Y)
            moves = amt > 1e-9 * (np.abs(amt).max() + 1e-300)
            cap = b * Y < a * S
            if int(np.sum(moves & cap)) < EVENTS or int(np.sum(moves & ~cap)) < EVENTS:
                continue
            tried.append((rw.bic(e, rw.p0 + 2, rw.n, rw.floor), "min", a, b, y))
        if not tried:
            continue
        tried.sort(key=lambda z: z[0])
        bic, kind, a, b, y = tried[0]
        if DEBUG:
            print("pairs", src, dst, "current", round(rw.base, 1), [(round(t[0], 1), t[1], t[4], round(t[2], 4), t[3] and round(t[3], 4)) for t in tried[:4]])
        if not bic < rw.base - MARGIN:
            continue
        rate = ({"form": "proportional", "stock": src, "k": _num(a)} if kind == "plain"
                else {"form": "expr", "expr": f"min({_num(a)!r} * {src}, {_num(b)!r} * {y})"})
        new = {"from": src, "to": dst, "ratio": 1, "id": f"milp:pair:{src}->{dst}", "rate": rate}
        flows = [f for i, f in enumerate(flows) if i not in rw.drop] + [new]
        notes.append({"flow": f"{src}->{dst}", "kind": kind, **({"ceiling": y, "b": _num(b)} if y else {}), "a": _num(a),
                      "gain": round(float(rw.base - bic), 1), "replaced": len(rw.drop)})
    return flows, ({"pairs": notes} if notes else {})
