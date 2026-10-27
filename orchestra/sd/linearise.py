"""The model's equations as a linear system around an operating point: d(levels)/dt ≈ A·levels.

Every flow moves material from one stock to another (or from or to outside), so the change of the
levels is ``S · r(levels, inputs)``: ``S`` the stoichiometry (−1 at a flow's source, +1 at its
destination) and ``r`` the flows' rates. Around an operating point, ``A = S · R`` with ``R`` the
rates' slopes on each stock (``R[f, i] = ∂r_f / ∂level_i``), taken by finite differences of the
rate exactly as the simulator computes it: SD Lab's forms (constant, proportional, linear, gap, a
sum of them, an expression), its effects, and the floor at 0. For a rate linear in the levels the
slopes are its coefficients wherever it is above 0; for anything else (an effect, an expression, a
rate floored at 0 here) they hold only near this point, and ``nonlinear`` says which flows.

A stock at 0 (a hidden stock, whose level nothing measures, is taken as 0) is differentiated
forward only, as a level never goes below 0. What the simulator also does and this does not:
share what an empty stock holds between its outflows, and cap a full one."""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Equation, Model

SPEC_FORMS = {"constant", "proportional", "linear", "gap", "sum", "expr"}


def rate_of(e: Equation | None, src: str | None) -> dict | None:
    """A flow's equation as an SD Lab rate per time unit (its spec, or its own form), or None when
    there is none to evaluate."""
    if e is None:
        return None
    if e.spec and e.spec.get("form"):
        return dict(e.spec) if e.spec["form"] in SPEC_FORMS else None
    from .simulate import _rate

    return _rate(e, src)


def reads(rate: dict) -> set[str]:
    """Every name a rate reads: stocks and inputs (an expression's names included)."""
    from .rates import reads as _reads

    out = set(_reads(rate))
    if rate.get("form") == "expr" and rate.get("expr"):
        from ..sdlab.sdtruth_expr import names, parse

        out |= set(names(parse(rate["expr"])))
    return out


def _effects(effects: list[dict], view: dict) -> float:
    """SD Lab's effect multipliers (as ``sdlab.discovery.simulate._Effects``)."""
    import numpy as np

    m = 1.0
    for e in effects:
        x = float(view.get(e.get("stock"), 0.0))
        if e.get("shape") == "table" and e.get("points"):
            pts = sorted((float(a), float(b)) for a, b in e["points"])
            m *= max(0.0, float(np.interp(x, [a for a, _ in pts], [b for _, b in pts])))
        else:
            lo = float(e["min"]) if e.get("min") is not None else 0.0
            hi = float(e["max"]) if e.get("max") is not None else 1.0
            m *= min(hi, max(lo, x / max(1e-9, float(e.get("normal") or 1))))
    return m


def value(rate: dict, view: dict) -> float:
    """A rate's value per time unit with the levels and inputs in ``view``, floored at 0."""
    form = rate.get("form")
    get = lambda x: float(view.get(x, 0.0))
    if form == "constant":
        v = float(rate.get("value") or 0.0)
    elif form == "proportional":
        v = float(rate.get("k") or 0.0) * get(rate.get("stock"))
    elif form == "linear":
        v = float(rate.get("c") or 0.0) + sum(float(t.get("k") or 0.0) * get(t.get("stock")) for t in rate.get("terms") or [])
    elif form == "gap":
        v = (float(rate.get("goal") or 0.0) - get(rate.get("stock"))) / max(1e-9, float(rate.get("time") or 1.0))
    elif form == "sum":
        v = sum(value(p, view) for p in rate.get("parts") or [])
    elif form == "expr":
        from ..sdlab.sdtruth_expr import compile_expr, parse

        tree = parse(rate["expr"])
        full = {n: get(n) for n in reads(rate)}
        try:
            v = float(compile_expr(tree)(full, _Zero())) / float(rate.get("per_step_of_time_unit") or 1.0)
        except (ZeroDivisionError, ValueError, OverflowError):
            v = 0.0
    else:
        v = 0.0
    v = max(0.0, v)
    return v * _effects(rate["effects"], view) if rate.get("effects") else v


class _Zero(dict):
    """Another flow's rate, read by an expression: taken as 0 (not linearised)."""

    def __missing__(self, key):
        return 0.0


@dataclass
class Linear:
    """The linearised model: ``A = S · R`` over ``stocks``, with each flow's rate and slopes."""

    stocks: list[str]
    flows: list[str]
    S: object                                   # stocks × flows
    R: object                                   # flows × stocks: ∂rate/∂level at the operating point
    pattern: object                             # flows × stocks: which stocks each rate reads at all (bool)
    rates: dict[str, float]                     # each flow's rate at the operating point
    view: dict[str, float]                      # the operating point: levels and inputs
    outside: list[str] = field(default_factory=list)       # flows with no equation to read: outside inputs here
    nonlinear: dict[str, str] = field(default_factory=dict)  # flow → why its slopes hold only near this point
    linear_in: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # flow → (parameter, what it multiplies)

    @property
    def A(self):
        return self.S @ self.R


def _params(rate: dict) -> list[tuple[str, str]] | None:
    """A rate linear in its numbers, as (parameter, what it multiplies: "1" or a name); None otherwise."""
    if rate.get("effects"):
        return None
    form = rate.get("form")
    if form == "constant":
        return [("constant", "1")]
    if form == "proportional":
        return [(f"k on {rate.get('stock')}", str(rate.get("stock")))]
    if form == "linear":
        return [("constant", "1")] + [(f"k on {t.get('stock')}", str(t.get("stock"))) for t in rate.get("terms") or []]
    if form == "sum":
        parts = [_params(p) for p in rate.get("parts") or []]
        return None if any(p is None for p in parts) else [(f"part {i + 1} {n}", x) for i, p in enumerate(parts) for n, x in p]
    return None


def linearise(model: Model, levels: dict[str, float] | None = None, inputs: dict[str, float] | None = None) -> Linear:
    """The model linearised at ``levels`` (stock id → level; a stock not given is taken as 0) with
    the measured ``inputs`` (name, with or without ``input:``, → value)."""
    import numpy as np

    ids = [s.id for s in model.stocks]
    at = {i: k for k, i in enumerate(ids)}
    view: dict[str, float] = {}
    for k, v in (inputs or {}).items():
        if v is not None:
            view[k.removeprefix("input:")] = float(v)
            view[f"input:{k.removeprefix('input:')}"] = float(v)
    view.update({i: float((levels or {}).get(i) or 0.0) for i in ids})
    fids = [f.id for f in model.flows]
    S = np.zeros((len(ids), len(fids)))
    R = np.zeros((len(fids), len(ids)))
    P = np.zeros((len(fids), len(ids)), dtype=bool)
    lin = Linear(ids, fids, S, R, P, {}, view)
    for j, f in enumerate(model.flows):
        if f.src in at:
            S[at[f.src], j] -= 1.0
        if f.dst in at:
            S[at[f.dst], j] += 1.0
        rate = rate_of(f.current(), f.src)
        if rate is None:
            lin.outside.append(f.id)
            continue
        r0 = value(rate, view)
        lin.rates[f.id] = r0
        read = reads(rate)
        why = []
        if rate.get("effects"):
            why.append("its effects are curves")
        if rate.get("form") in ("expr",):
            why.append("it is an expression")
        if (ps := _params(rate)) is not None:
            lin.linear_in[f.id] = ps
        for name in read:
            if name not in at:
                continue
            i = at[name]
            P[j, i] = True
            x = view[name]
            h = 1e-6 * max(1.0, abs(x))
            up = dict(view, **{name: x + h})
            if x - h < 0:                                     # a level never goes below 0: the slope as it rises
                R[j, i] = (value(rate, up) - r0) / h
            else:
                R[j, i] = (value(rate, up) - value(rate, dict(view, **{name: x - h}))) / (2 * h)
        if r0 <= 0.0 and read & set(at) and not np.any(R[j]):
            why.append("its rate is floored at 0 here, so locally it does not depend on the levels it reads")
        if why:
            lin.nonlinear[f.id] = "; ".join(why)
    return lin
