"""Inference v1: fit each flow's equation from the measured history.

Data: each flow's cumulative counter and its source stock's level, from the metrics store, cut
into steps (an hour by default). A flow's count in a step is treated as a Poisson count whose mean
is the rate × the step's **exposure**:

- ``constant``:      mean = c × running hours in the step
- ``proportional``:  mean = k × the source stock's **item-hours** in the step: the integral of its
  level over the part of the step when the loop was running. The stock's series records every
  change, so the integral is exact; a ticket that passes through a state in five minutes counts
  for a twelfth of an hour, which is what makes this the maximum-likelihood estimate of k for a
  Poisson process (departures ÷ time at risk)

Running hours come from the loop's own start and stop events (``orchestra_events_total`` for
``loop_started`` and ``loop_stopped``): nothing moves while the loop is stopped, so those hours are
left out instead of dragging every rate toward zero. Events counted in steps where the loop was
not running are reported, not hidden.

Both forms have one parameter, fitted by maximum likelihood (rate = events ÷ exposure, standard
error = √events ÷ exposure), and the one with the higher likelihood is kept. Quality is recorded
with every equation: standard error, both log-likelihoods, the number of events and running
hours, and the dispersion (Pearson χ² per degree of freedom; well above 1 means the counts vary
more than either form explains, so a richer form or more data is needed).

These are the simplest strategies; richer ones come from the SD Lab discovery work."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..collectors import EVENTS
from ..metrics import MetricsStore, step_sample
from .model import Equation, Flow, Model


@dataclass
class Grid:
    start: float
    step: float
    n: int

    def times(self) -> list[float]:
        return [self.start + i * self.step for i in range(self.n + 1)]


def running_intervals(store: MetricsStore, project: str, grid: Grid) -> list[tuple[float, float]]:
    """The stretches of time during which the loop was running, from its start and stop events."""
    marks = [(t, True) for t, _ in store.raw(EVENTS, {"project": project, "type": "loop_started"})]
    marks += [(t, False) for t, _ in store.raw(EVENTS, {"project": project, "type": "loop_stopped"})]
    marks.sort()
    end = grid.start + grid.n * grid.step
    intervals, on_since = [], (grid.start if marks and not marks[0][1] else None)   # a stop first: it was running
    for t, started in marks:
        if started and on_since is None:
            on_since = t
        elif not started and on_since is not None:
            intervals.append((on_since, t))
            on_since = None
        elif started and on_since is not None:      # a start without a stop: the previous run died
            intervals.append((on_since, t))
            on_since = t
    if on_since is not None:
        intervals.append((on_since, end))
    if not marks:
        intervals = [(grid.start, end)]
    return intervals


def running_fraction(intervals: list[tuple[float, float]], grid: Grid) -> list[float]:
    """Share of each step during which the loop was running."""
    out = []
    for i in range(grid.n):
        a, b = grid.start + i * grid.step, grid.start + (i + 1) * grid.step
        out.append(sum(max(0.0, min(b, y) - max(a, x)) for x, y in intervals) / grid.step)
    return out


def item_hours(points: list[tuple[float, float]], intervals: list[tuple[float, float]], grid: Grid) -> list[float]:
    """The integral of a step-function series (level held until the next point) over each grid step,
    counting only time inside ``intervals``; in level × hours. Before the first point the level is
    taken to be the first value."""
    out = [0.0] * grid.n
    if not points:
        return out
    end = grid.start + grid.n * grid.step
    # pieces of constant level: (from, to, level)
    pieces, prev_t, prev_v = [], grid.start, points[0][1]
    for t, v in points:
        if t > prev_t:
            pieces.append((prev_t, min(t, end), max(prev_v, 0.0)))
        prev_t, prev_v = max(prev_t, t), v
    pieces.append((prev_t, end, max(prev_v, 0.0)))
    for a, b, lv in pieces:
        if lv <= 0 or b <= a:
            continue
        for x, y in intervals:
            lo, hi = max(a, x), min(b, y)
            while lo < hi:
                i = min(int((lo - grid.start) // grid.step), grid.n - 1)
                step_end = grid.start + (i + 1) * grid.step
                seg = min(hi, step_end) - lo
                out[i] += lv * seg / 3600
                lo += seg
    return out


def _values_at(points: list[tuple[float, float]], times: list[float], before: float = 0.0) -> list[float]:
    got = dict(step_sample(points, times[0], times[-1], times[1] - times[0])) if len(times) > 1 else {}
    return [got.get(t, before) for t in times]


def _loglik(counts: list[int], means: list[float]) -> float:
    ll = 0.0
    for c, m in zip(counts, means):
        if m <= 0:
            if c > 0:
                return -math.inf
            continue
        ll += c * math.log(m) - m - math.lgamma(c + 1)
    return ll


def fit_flow(flow: Flow, model: Model, store: MetricsStore, grid: Grid, running: list[float],
             intervals: list[tuple[float, float]]) -> Equation | None:
    if flow.counter is None:
        return None
    times = grid.times()
    total = _values_at(store.raw(flow.counter.name, flow.counter.labels), times)
    counts = [round(total[i + 1] - total[i]) for i in range(grid.n)]
    src = model.stock(flow.src) if flow.src else None
    exposure = item_hours(store.raw(src.series.name, src.series.labels), intervals, grid) if src and src.series else None
    use = [i for i in range(grid.n) if running[i] > 0]
    outside = sum(counts[i] for i in range(grid.n) if running[i] == 0)
    events = sum(counts[i] for i in use)
    cand = {"constant": [running[i] * grid.step / 3600 for i in use]}
    if exposure is not None:
        cand["proportional"] = [exposure[i] for i in use]
    obs = [counts[i] for i in use]
    fits = {}
    for form, expo in cand.items():
        e = sum(expo)
        if e <= 0:
            continue
        rate = events / e
        means = [rate * x for x in expo]
        chi2 = sum((c - m) ** 2 / m for c, m in zip(obs, means) if m > 0)
        fits[form] = {"rate": rate, "se": (math.sqrt(events) if events else 3.0) / e, "loglik": _loglik(obs, means),
                      "dispersion": chi2 / max(1, len(obs) - 1)}
    if not fits:
        return None
    best = max(fits, key=lambda f: fits[f]["loglik"])
    other = {f"loglik_{f}": v["loglik"] for f, v in fits.items()}
    q = {"se": fits[best]["se"], "loglik": fits[best]["loglik"], **other, "events": float(events),
         "running_hours": sum(running[i] for i in use) * grid.step / 3600, "dispersion": fits[best]["dispersion"],
         "events_while_stopped": float(outside)}
    param = "c" if best == "constant" else "k"
    return Equation(best, {param: fits[best]["rate"]}, "fitted", "poisson-mle",
                    (grid.start, grid.start + grid.n * grid.step), None, q)


def fit_model(model: Model, store: MetricsStore, project: str, step: float = 3600.0) -> Model:
    """Fit every flow with a counter over the whole history; equations are replaced, not appended."""
    stamps = [t for s in model.stocks if s.series for t, _ in store.raw(s.series.name, s.series.labels)]
    if not stamps:
        return model
    start = min(stamps) - min(stamps) % step
    grid = Grid(start, step, math.ceil((max(stamps) - start) / step) or 1)
    intervals = running_intervals(store, project, grid)
    running = running_fraction(intervals, grid)
    for f in model.flows:
        eq = fit_flow(f, model, store, grid, running, intervals)
        f.equations = [eq] if eq else []
    return model
