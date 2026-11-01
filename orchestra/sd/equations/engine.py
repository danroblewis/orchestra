"""Running a model's equations, written in the equation language, for many states at once.

The stepping is SD Lab's simulator's (``orchestra.sdlab.discovery.simulate``, which ``sd.simulate``
uses), so a model runs here as it runs on the Dynamics page: Euler steps of ``step_s``; each
flow's rate evaluated from the levels and inputs at the start of the step, below 0 taken as 0;
a stock's outflows sharing what it holds (each cut by the same share when together they want more
than there is); levels floored at 0 after every step; a measured input held at its value at or
before the step (its first value before its first point). What is new: any equation the language
writes, ``smooth`` and ``delay``, a flow's measured rate (``observed()``), and parameters that
differ per column, so a band's members or an inverse solver's candidates run in one pass.

A rate that is not a number (``log(0)``) is taken as 0, and counted per flow (``nonfinite``)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..model import Model
from .compile import Frame, compile_rate
from .forms import Names, flow_text, measured_inputs
from .language import parse


@dataclass
class Flow:
    id: str
    src: str | None
    dst: str | None
    text: str
    params: dict[str, float]
    fn: object
    observed: bool
    reads: list[str] = field(default_factory=list)


class Series:
    """A series held between its points: the value at or before a time, else its first."""

    def __init__(self, points):
        pts = sorted((float(t), float(v)) for t, v in points or [])
        self.t = np.array([t for t, _ in pts])
        self.v = np.array([v for _, v in pts])

    def at(self, t: float) -> float:
        if not len(self.t):
            return 0.0
        i = int(np.searchsorted(self.t, t, side="right")) - 1
        return float(self.v[max(0, i)])


class Rate:
    """A flow's measured rate (per time unit): over the stretch that contains ``t``, as the
    history's rates are each over the stretch that ends at their time; ``hold`` from the end."""

    def __init__(self, points, hold: float | None = None):
        pts = sorted((float(t), float(v)) for t, v in points or [])
        self.t = np.array([t for t, _ in pts])
        self.v = np.array([v for _, v in pts])
        self.hold = hold

    def at(self, t: float) -> float:
        if self.hold is not None and (not len(self.t) or t >= self.t[-1]):
            return self.hold
        if not len(self.t):
            return 0.0
        i = int(np.searchsorted(self.t, t, side="right"))
        return float(self.v[min(i, len(self.v) - 1)])


def compiled(model: Model, extra_inputs=()) -> list[Flow]:
    """Every flow of the model, its equation checked and compiled. Raises EquationError naming
    the flow whose equation does not parse."""
    from .language import EquationError

    names = Names.of(model, extra_inputs)
    out = []
    for f in model.flows:
        try:
            text, params = flow_text(f, names)
            p = parse(text, stocks=names.stocks, inputs=names.inputs, params=params)
        except EquationError as e:
            raise EquationError(f"flow {f.id}: {e}") from None
        out.append(Flow(f.id, f.src, f.dst, p.text, dict(p.params), compile_rate(p, f.id), p.observed, p.reads()))
    return out


@dataclass
class Run:
    t: np.ndarray                 # the times of the levels: t0 and the end of every step
    levels: np.ndarray            # columns x stocks x (steps + 1)
    rates: np.ndarray             # columns x flows x steps: what each flow moved per time unit, after the stocks shared
    stocks: list[str]
    flows: list[str]
    nonfinite: dict[str, int]


def run(model: Model, *, t0: float, steps: int, step_s: float, unit_s: float, levels: dict[str, object],
        inputs: dict[str, list] | None = None, observed: dict[str, Rate] | None = None, columns: int = 1,
        factors: dict[str, np.ndarray] | None = None, params: dict[str, dict[str, object]] | None = None,
        flows: list[Flow] | None = None) -> Run:
    """The model run from ``t0`` for ``steps`` of ``step_s``, from ``levels`` (a number or one per
    column; a stock not given starts at 0), with the measured ``inputs`` (``{name: [[t, v]]}``),
    each flow's measured rate (``observed``), ``columns`` states at once, each flow's rate times
    ``factors[flow]`` (one per column) and parameters set per column (``params[flow][name]``)."""
    flows = flows if flows is not None else compiled(model, list(inputs or {}))
    ids = [s.id for s in model.stocks]
    names = list(dict.fromkeys([*measured_inputs(model), *(inputs or {})]))
    index = {f"stock:{s}": i for i, s in enumerate(ids)}
    index.update({f"input:{n}": len(ids) + j for j, n in enumerate(names)})
    g = step_s / unit_s
    M = columns
    fr = Frame(index, g, M)
    for f in flows:
        fr.params[f.id] = {k: np.broadcast_to(np.asarray(v, dtype=float), (M,)) if np.ndim(v) else float(v)
                           for k, v in {**f.params, **((params or {}).get(f.id) or {})}.items()}
    series = {n: Series((inputs or {}).get(n)) for n in names}
    seen = {f.id: (observed or {}).get(f.id) or Rate([]) for f in flows if f.observed}
    k = {f.id: np.broadcast_to(np.asarray((factors or {}).get(f.id, 1.0), dtype=float), (M,)) for f in flows}
    src = [ids.index(f.src) if f.src in ids else None for f in flows]
    dst = [ids.index(f.dst) if f.dst in ids else None for f in flows]
    takers = {c: [j for j, s in enumerate(src) if s == c] for c in range(len(ids))}
    takers = {c: js for c, js in takers.items() if js}
    S = len(ids)
    L = np.zeros((S, M))
    for i, sid in enumerate(ids):
        v = levels.get(sid)
        L[i] = np.broadcast_to(np.asarray(0.0 if v is None else v, dtype=float), (M,))
    out_levels = np.empty((M, S, steps + 1))
    out_rates = np.empty((M, len(flows), steps))
    out_levels[:, :, 0] = L.T
    bad = {f.id: 0 for f in flows}
    times = t0 + step_s * np.arange(steps + 1)
    with np.errstate(all="ignore"):
        for i in range(steps):
            t = float(times[i])
            fr.R[:S] = L
            for n in names:
                fr.R[index[f"input:{n}"]] = series[n].at(t)
            for fid, r in seen.items():
                fr.observed[fid] = r.at(t)
            amounts = []
            for j, f in enumerate(flows):
                v = np.broadcast_to(np.asarray(f.fn(fr), dtype=float), (M,))
                ok = np.isfinite(v)
                if not ok.all():
                    bad[f.id] += int((~ok).sum())
                    v = np.where(ok, v, 0.0)
                amounts.append(np.maximum(0.0, v) * k[f.id] * g)
            for c, js in takers.items():                 # a stock's outflows share what it holds
                want = sum(amounts[j] for j in js)
                cut = np.where((want > L[c]) & (L[c] > -1), np.maximum(0.0, L[c]) / np.where(want > 0, want, 1), 1.0)
                for j in js:
                    amounts[j] = amounts[j] * cut
            nxt = L.copy()
            for j, a in enumerate(amounts):
                if src[j] is not None:
                    nxt[src[j]] -= a
                if dst[j] is not None:
                    nxt[dst[j]] += a
                out_rates[:, j, i] = a / g if g > 0 else 0.0
            L = np.where(nxt >= 0, nxt, 0.0)
            out_levels[:, :, i + 1] = L.T
            fr.advance()
    return Run(times, out_levels, out_rates, ids, [f.id for f in flows], {k: v for k, v in bad.items() if v})
