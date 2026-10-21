"""Choosing, stock by stock, between the base strategy's flows and a form the engine can write
(engine_forms).

For a measured stock x, the base's flows that can be replaced are x's exchange with the outside
(inflows from and drains to the outside) and the moves into x. A move into x that is replaced
becomes a drain of its source with the same rate, so the source changes exactly as before. The
moves out of x and the co-flows that use x are kept; what they change in x is taken off its
one-step change (the target y). Each family (forms.py) fits y; the base's own reading of y is the
change its replaced flows make. A form is also tried beside the base's outside inflow pieces and
eras (kept as they are: an inflow that changes unannounced). A form replaces the flows when its BIC
beats the base's by MARGIN (every piece and era counted as numbers; rows weighted by counting
noise, weights()) and it leaves at most RATIO of the base's residual.
"""

from __future__ import annotations


import numpy as np

from . import fit as F
from .forms import FAMILIES, Fit, best_linear
from .steps import Steps

MARGIN = 10.0        # BIC points a form must gain over the base's flows
RATIO = 1.05         # and it may leave at most this much of the base's (weighted) residual: a form
                     # that fits worse than the base's pieces is not let in by their price alone
QUIET = 0.05         # a weighted mean square below this is far below counting noise (about 1): the
EXACT = 0.05         # data are near exact, and a form must then leave at most EXACT of the base's
                     # residual (a right form fits near exactly; a wrong one only trims a misfit)
MOST_STOCKS = 12     # beyond this many measured stocks the pass is not tried (time)


def numbers(f: dict) -> int:
    """How many numbers a found flow uses (pieces and eras count)."""
    def of(r):
        r = r or {}
        form = r.get("form")
        if form == "constant" or form == "proportional":
            return 1
        if form == "gap":
            return 2
        if form == "linear":
            return 1 + len(r.get("terms") or [])
        return 2
    n = of(f.get("rate"))
    if f.get("inflow") and len(f["inflow"]) > 1:
        n = 2 * len(f["inflow"]) - 1
    if f.get("byTime"):
        n = sum(of(g.get("rate")) + 1 for g in f["byTime"])
    for e in f.get("effects") or []:
        n += 2 * len(e.get("points") or []) if e.get("shape") == "table" else 2
    n += len(f.get("uses") or [])
    return n


def replaceable(flows: list[dict], x: str, ids: list[str]) -> list[int]:
    out = []
    for i, f in enumerate(flows):
        src, dst = f.get("from"), f.get("to")
        if f.get("via") or (src is not None and src not in ids) or (dst is not None and dst not in ids):
            continue                                   # a hidden stock's flows stay as they are
        if (src == x and dst is None) or (src is None and dst == x) or (dst == x and src is not None):
            out.append(i)
    return out


def touches_hidden(flows: list[dict], x: str, ids: list[str]) -> bool:
    """Does a flow join x to a stock nobody measures (a hidden stage of the base's)? Its levels are
    not in the data, so x's change cannot be read without them."""
    for f in flows:
        ends = (f.get("from"), f.get("to"))
        if x in ends and (f.get("via") or any(e is not None and e not in ids for e in ends)):
            return True
    return False


def rewrite_as_move(new: list[dict], x: str, z: str) -> list[dict] | None:
    """The form's flows with what flows into x reading z written as a move from z (a table of z on a
    constant rate; a term k z of a linear inflow); None when no inflow of x reads z."""
    out, hit = [], False
    for f in new:
        r = f.get("rate") or {}
        if f.get("from") is None and f.get("to") == x:
            eff = f.get("effects") or []
            if len(eff) == 1 and eff[0].get("stock") == z and r.get("form") == "constant":
                out.append({**f, "from": z})
                hit = True
                continue
            if r.get("form") == "linear" and any(t.get("stock") == z and t.get("k", 0) > 0 for t in r.get("terms") or []) and not eff:
                terms = [t for t in r["terms"] if t.get("stock") != z]
                kz = sum(t["k"] for t in r["terms"] if t.get("stock") == z)
                out.append({**f, "from": z, "rate": {"form": "proportional", "stock": z, "k": float(kz)}})
                if terms or r.get("c"):
                    out.append({**f, "rate": {"form": "linear", "c": r.get("c", 0.0), "terms": terms}})
                hit = True
                continue
        out.append(f)
    return out if hit else None


def is_pieces(f: dict) -> bool:
    """An outside inflow in pieces or eras."""
    return f.get("from") is None and (len(f.get("inflow") or []) > 1 or bool(f.get("byTime")))


def as_drain(f: dict) -> dict:
    """A move written as a drain of its source (the same rate, effects and co-flows)."""
    return {**f, "to": None, "engine_forms_was": f"move to {f.get('to')}"}


def weights(flows: list[dict], x: str, st: Steps) -> np.ndarray:
    """1 / the standard deviation of x's one-step change under counting noise: every flow a
    Poisson draw, so the variance is the gross amount through x (the base's flows' amounts), with
    a floor of 5% of its mean so a quiet step does not weigh without bound."""
    i = st.ids.index(x)
    touch = [f for f in flows if x in (f.get("from"), f.get("to")) or any(u.get("stock") == x for u in f.get("uses") or [])]
    gross = sum((np.abs(st.change([f])[i]) for f in touch), np.zeros(st.n))
    g0 = 0.05 * float(np.mean(gross)) + 1e-9
    return 1.0 / np.sqrt(gross + g0)


def candidates(x: str, y: np.ndarray, st: Steps, floor: float, families) -> list[Fit]:
    out = []
    for name in families:
        try:
            got = FAMILIES[name](x, y, st, floor)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError):
            got = None
        if got is not None:
            out.append(got)
    return out


def improve(flows: list[dict], st: Steps, families=tuple(FAMILIES), trace: list | None = None, outside=None) -> list[dict]:
    """The base's flows with each stock's exchange replaced by a form where one wins (module).

    outside(flows) -> int (the declared boundary, _kalman/boundary.py): how many flows lie outside it;
    a form that would leave more of them than the flows it replaces is not offered (with its moves
    into x written as drains of their sources, or as moves where the form reads them), and a stock's
    rewrite that ends with more of them is undone."""
    trace = trace if trace is not None else []
    outside = outside or (lambda _: 0)
    if len(st.ids) > MOST_STOCKS:
        trace.append(f"skipped: {len(st.ids)} stocks")
        return flows
    flows = list(flows)
    for x in st.ids:
        i = st.ids.index(x)
        rep = replaceable(flows, x, st.ids)
        if not rep or touches_hidden(flows, x, st.ids):
            continue
        kept = [f for j, f in enumerate(flows) if j not in rep]
        base_fit = st.change([flows[j] for j in rep])[i]
        y_all = st.D[i] - st.change(kept)[i]
        v = weights(flows, x, st)
        floor = F.floor_of(y_all * v)
        low = -st.S[i] if np.min(st.S[i]) >= 0 and np.min(st.E[i]) >= 0 else np.full(st.n, -np.inf)
        p_base = sum(numbers(flows[j]) for j in rep)
        b_base = F.bic((y_all - base_fit) * v, p_base, floor)
        s_base = F.sse((y_all - base_fit) * v, floor)
        # the form replaces every replaceable flow, or all but the base's outside inflow pieces
        # and eras (an inflow that changes when nothing announced it: the form fits the rest)
        pieces = [j for j in rep if is_pieces(flows[j])]
        best = None
        for keep in ([], pieces) if pieces else ([],):
            drop = [j for j in rep if j not in keep]
            held = st.change([flows[j] for j in keep])[i] if keep else 0.0
            y = y_all - held
            st.w = st.free(x) * v
            p_keep = sum(numbers(flows[j]) for j in keep)
            # a curve (table, MIN) must also beat the plain straight line in the same readers, refitted
            # here: a base that only misses a little of a straight line is not a curve's evidence
            readers = [x] + sorted(st.U) + [o for o in st.ids if o != x]
            coef, lyh, _ = best_linear(y, st, readers, floor)
            lyh = np.maximum(lyh + held, low)
            b_lin = F.bic((y_all - lyh) * v, len(coef) + p_keep, floor)
            s_lin = F.sse((y_all - lyh) * v, floor)
            for c in candidates(x, y, st, floor, families):
                if outside(_shape(flows, drop, c, x, st.ids)) > outside(flows):
                    trace.append(f"{x}: {c.family} leaves the declared boundary")
                    continue
                yh = np.maximum(c.yhat + held, low)        # nothing leaves a stock that is not there
                b = F.bic((y_all - yh) * v, c.p + p_keep, floor)
                s = F.sse((y_all - yh) * v, floor)
                trace.append(f"{x}: {c.family}{' (pieces kept)' if keep else ''} bic {b:.1f} vs base {b_base:.1f} "
                             f"(p {c.p + p_keep} vs {p_base}), sse ratio {s / s_base:.3g}")
                chi2 = s / max(1, int(np.sum(st.w > 0)))
                exact = chi2 < QUIET                       # far below counting noise: the data are near exact
                ratio = EXACT if exact else RATIO
                curve_ok = c.family == "linear" or (b < b_lin - MARGIN and s <= ratio * s_lin)
                if b < b_base - MARGIN and s <= ratio * s_base and curve_ok and (best is None or b < best[0]):
                    best = (b, c, drop)
        if best is None:
            continue
        _, c, drop = best
        before = flows
        moves_in = [flows[j] for j in drop if flows[j].get("to") == x and flows[j].get("from") in st.ids]
        rest = [f for j, f in enumerate(flows) if j not in drop]
        new = list(c.flows)
        outside = rest + [as_drain(f) for f in moves_in] + new
        flows = outside
        # a dropped move from z, and the form reads z: is it a move from z after all? z's own change
        # tells (a move takes what it reads out of z; an outside inflow beside z's drain does not)
        for z in dict.fromkeys(f["from"] for f in moves_in):
            as_move = rewrite_as_move(new, x, z)
            if as_move is None:
                continue
            k = st.ids.index(z)
            others = [f for f in moves_in if f["from"] != z]
            trial = rest + [as_drain(f) for f in others] + as_move
            vz = weights(flows, z, st)
            s_out = F.sse((st.D[k] - st.change(outside)[k]) * vz, 0.0)
            s_move = F.sse((st.D[k] - st.change(trial)[k]) * vz, 0.0)
            trace.append(f"{x}: the part reading {z} as a move from {z}: {z}'s residual {s_move:.4g} vs {s_out:.4g} as an outside inflow")
            if s_move < s_out:
                new, flows, moves_in = as_move, trial, others
        flows = [{"id": f"engine_forms:{c.family}:{f.get('from') or 'outside'}->{f.get('to') or 'outside'}:{n}", **f}
                 if f.get("engine_forms") and "id" not in f else f for n, f in enumerate(flows)]
        if outside(flows) > outside(before):
            flows = before
            trace.append(f"{x}: {c.family} undone (it leaves the declared boundary)")
            continue
        trace.append(f"{x}: {c.family} chosen{' (pieces kept)' if len(drop) < len(rep) else ''} {c.detail}")
    return flows


def _shape(flows: list[dict], drop: list[int], c, x: str, ids: list[str]) -> list[dict]:
    """The structure a form would leave (for the boundary check): the flows it replaces dropped, the
    moves into x among them written as drains of their sources, or as moves where the form reads
    their source (rewrite_as_move), whichever keeps more inside."""
    moves_in = [flows[j] for j in drop if flows[j].get("to") == x and flows[j].get("from") in ids]
    rest = [f for j, f in enumerate(flows) if j not in drop]
    new = list(c.flows)
    for z in dict.fromkeys(f["from"] for f in moves_in):
        as_move = rewrite_as_move(new, x, z)
        if as_move is not None:
            new, moves_in = as_move, [f for f in moves_in if f["from"] != z]
    return rest + [as_drain(f) for f in moves_in] + new
