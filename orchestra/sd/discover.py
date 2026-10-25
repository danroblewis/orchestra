"""Discovery v1: build the model from the metrics store, without being told what anything is.

Given every series of a project over a window, it finds stocks, the flows between them, the
equation of each flow, and the machine behind each flow:

1. **Sample** every series onto a grid of steps (the last value at or before each step).
2. **Find stocks by conservation.** A level whose changes are explained by counters, added or
   subtracted, is a stock, and those counters are its inflows and outflows:
   ``Δlevel ≈ Σ inflows − Σ outflows`` in every step. The counters (each with a coefficient of +1
   or −1) are found by a local search that keeps a counter only if it explains a real share. A level is
   kept only if the balance fits (R² ≥ ``MIN_R2``); everything else is left out, with the reason.
3. **Connect flows.** A counter that is an outflow of one stock and an inflow of another is a flow
   between them; otherwise it comes from or goes to outside.
4. **Fit each flow's equation** by maximum likelihood, choosing by AIC among:
   - ``constant``: rate = c;
   - ``proportional``: rate = k × the source stock (its exact time-average over the step);
   - ``linear``: rate = c + k × X, for X any stock found. When X is not the flow's own source,
     that is an **influence**: one stock changing the rate of another's flow, the link that
     closes feedback loops.

   Forms are scored with the exact point-process likelihood (each event against the levels just
   before it), not counts per step, which favour spurious forms (see ``fit_flow``).
5. **Attribute** each flow to the machine named by its counter's ``machine`` label, and each stock
   to the machine that writes it.

Structure is discovered and parameters are fitted, so equations record ``origin: fitted`` with
``method: poisson-mle`` and the model records how it was found (``Model.discovery``).

What this cannot do yet: stocks no series measures (hidden stocks), delays, non-linear forms,
eras. Those are the SD Lab strategies' job, and they are still unproven on real data."""

from __future__ import annotations

import math
import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise

from ..metrics import step_sample
from .model import Equation, Flow, Machine, Model, SeriesRef, Stock

MIN_R2 = 0.9            # how well a balance must fit for a level to count as a stock
MIN_GAIN = 0.01         # each added counter must explain at least this share of the level's variance
MAX_TERMS = 8
UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}


@dataclass
class Series:
    name: str
    labels: dict[str, str]
    points: list[tuple[float, float]]
    values: list[float]                     # at each grid time
    counter: bool

    @property
    def key(self) -> str:
        inner = ",".join(f'{k}="{v}"' for k, v in sorted(self.labels.items()) if k not in ("project", "machine"))
        return f"{self.name}{{{inner}}}" if inner else self.name

    @property
    def deltas(self) -> list[float]:
        return [b - a for a, b in pairwise(self.values)]


def _slug(s: Series) -> str:
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return "_".join([s.name, *[re.sub(r"\W+", "_", v) for v in extra]])


def _title(s: Series) -> str:
    base = re.sub(r"_total$", "", s.name).replace("_", " ")
    extra = [v for k, v in sorted(s.labels.items()) if k not in ("project", "machine")]
    return base + (f" ({', '.join(extra)})" if extra else "")


def machine_of(s: Series) -> str | None:
    """The machine a series belongs to: its ``machine`` label, or, for Orchestra's event counters,
    the ``source`` that emitted the events (``unknown`` is no machine)."""
    who = s.labels.get("machine") or s.labels.get("source")
    return who if who and who != "unknown" else None


def _is_counter(name: str, values: list[float]) -> bool:
    return name.endswith("_total") and all(b >= a for a, b in pairwise(values))


def sample(dump, start: float, step: float, n: int) -> list[Series]:
    """Every series on the grid; leading steps before its first point take its first value."""
    out = []
    times = [start + i * step for i in range(n + 1)]
    for name, labels, pts in dump:
        if not pts:
            continue
        got = dict(step_sample(pts, start, times[-1], step))
        first = next((v for t, v in pts if t >= start), pts[-1][1])
        vals, last = [], None
        for t in times:
            last = got.get(t, last)
            vals.append(first if last is None else last)
        out.append(Series(name, dict(labels), pts, vals, _is_counter(name, vals)))
    return out


class LeastSquares:
    """Ordinary least squares of any level's changes on every counter's changes at once. The
    normal matrix is the same for every level, so it is factored once (Cholesky, lightly
    regularised so collinear counters don't break it)."""

    def __init__(self, xs: list[list[float]]):
        self.xs = xs
        m = len(xs)
        g = [[sum(a * b for a, b in zip(xs[i], xs[j])) for j in range(m)] for i in range(m)]
        ridge = 1e-6 * (sum(g[i][i] for i in range(m)) / max(1, m)) + 1e-12
        for i in range(m):
            g[i][i] += ridge
        self.L = [[0.0] * m for _ in range(m)]
        for i in range(m):
            for j in range(i + 1):
                v = g[i][j] - sum(self.L[i][k] * self.L[j][k] for k in range(j))
                self.L[i][j] = math.sqrt(max(v, 1e-18)) if i == j else v / self.L[j][j]

    def solve(self, y: list[float]) -> list[float]:
        m, L = len(self.xs), self.L
        b = [sum(a * v for a, v in zip(x, y)) for x in self.xs]
        z = [0.0] * m
        for i in range(m):
            z[i] = (b[i] - sum(L[i][k] * z[k] for k in range(i))) / L[i][i]
        c = [0.0] * m
        for i in reversed(range(m)):
            c[i] = (z[i] - sum(L[k][i] * c[k] for k in range(i + 1, m))) / L[i][i]
        return c


def balance(level: Series, counters: list[Series], ls: LeastSquares | None = None
            ) -> tuple[list[tuple[Series, int]], float, float]:
    """The counters (each +1 or −1) that best explain the level's changes; and the balance's R²
    and the share of steps it explains exactly.

    The objective is the squared error plus a penalty of ``MIN_GAIN`` × the level's variance per
    counter used, so a counter must explain a real share to be kept. The search starts from least
    squares on all counters, each coefficient rounded to +1, −1 or 0, and then repeatedly applies
    the change that lowers the objective most (any counter to +1, −1 or 0, or one chosen counter
    swapped for another), until none does. Starting from least squares matters: one term of a balance alone often makes the fit
    worse (inflow without its outflows), so a search that adds terms one at a time misses it."""
    y = level.deltas
    mean = sum(y) / len(y)
    sst = sum((v - mean) ** 2 for v in y) or 1e-12
    pen = MIN_GAIN * sst
    xs = [c.deltas for c in counters]
    live = [j for j, x in enumerate(xs) if any(x)]
    coef: dict[int, int] = {}
    if ls is not None:
        for j, v in enumerate(ls.solve(y)):
            if abs(v) >= 0.5 and j in live:
                coef[j] = 1 if v > 0 else -1
        if len(coef) > MAX_TERMS:
            coef = {}
    resid = [v - sum(sign * xs[j][i] for j, sign in coef.items()) for i, v in enumerate(y)]
    sse = sum(r * r for r in resid)
    for _ in range(4 * MAX_TERMS):
        best = None                                   # (gain, changes {j: new coefficient}, sse after)
        for j in live:                                # change one counter's coefficient
            old = coef.get(j, 0)
            for new in (-1, 0, 1):
                if new == old or (new and not old and len(coef) >= MAX_TERMS):
                    continue
                d = new - old
                e = sum((r - d * v) ** 2 for r, v in zip(resid, xs[j]))
                gain = (sse - e) - pen * ((new != 0) - (old != 0))
                if gain > 1e-9 and (best is None or gain > best[0]):
                    best = (gain, {j: new}, e)
        for j, sign in list(coef.items()):            # swap a chosen counter for another, same sign:
            for k in live:                            # near-identical counters can't be swapped one step at a time
                if k in coef:
                    continue
                e = sum((r + sign * a - sign * b) ** 2 for r, a, b in zip(resid, xs[j], xs[k]))
                gain = sse - e
                if gain > 1e-9 and (best is None or gain > best[0]):
                    best = (gain, {j: 0, k: sign}, e)
        if best is None:
            break
        _, changes, e = best
        for j, new in changes.items():
            d = new - coef.get(j, 0)
            resid = [r - d * v for r, v in zip(resid, xs[j])]
            if new:
                coef[j] = new
            else:
                coef.pop(j, None)
        sse = e
    chosen = [(counters[j], sign) for j, sign in sorted(coef.items())]
    exact = sum(1 for r in resid if abs(r) <= 0.5) / len(resid)
    return chosen, 1 - sse / sst, exact


def _average(points: list[tuple[float, float]], a: float, b: float) -> float:
    """Time-average of a step-function series over [a, b)."""
    before = [v for t, v in points if t <= a]
    level = before[-1] if before else (points[0][1] if points else 0.0)
    total, t0 = 0.0, a
    for t, v in points:
        if t <= a:
            continue
        if t >= b:
            break
        total += level * (t - t0)
        t0, level = t, v
    total += level * (b - t0)
    return total / (b - a)


def _loglik(y: list[float], mu: list[float]) -> float:
    ll = 0.0
    for c, m in zip(y, mu):
        if m <= 1e-12:
            if c > 0:
                return -math.inf
            continue
        ll += c * math.log(m) - m - math.lgamma(c + 1)
    return ll


def _nelder_mead(f, x0: list[float], scale: list[float], iters: int = 400) -> list[float]:
    """Minimise f over a few parameters; small and dependency-free."""
    n = len(x0)
    pts = [list(x0)] + [[x0[i] + (scale[i] if i == j else 0.0) for i in range(n)] for j in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        cen = [sum(p[i] for p in pts[:-1]) / n for i in range(n)]
        ref = [cen[i] + (cen[i] - pts[-1][i]) for i in range(n)]
        fr = f(ref)
        if fr < vals[0]:
            exp = [cen[i] + 2 * (cen[i] - pts[-1][i]) for i in range(n)]
            fe = f(exp)
            pts[-1], vals[-1] = (exp, fe) if fe < fr else (ref, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = ref, fr
        else:
            con = [cen[i] + 0.5 * (pts[-1][i] - cen[i]) for i in range(n)]
            fc = f(con)
            if fc < vals[-1]:
                pts[-1], vals[-1] = con, fc
            else:
                pts = [pts[0]] + [[pts[0][i] + 0.5 * (p[i] - pts[0][i]) for i in range(n)] for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
        if max(vals) - min(vals) < 1e-9:
            break
    return pts[min(range(n + 1), key=lambda i: vals[i])]


@dataclass
class Path:
    """A stock's level over the window, as the fitter needs it: the level just before any instant,
    and how long it spent at each level (in the model's time unit)."""

    times: list[float]
    values: list[float]
    time_at: dict[float, float]

    @classmethod
    def of(cls, points: list[tuple[float, float]], start: float, end: float, unit_s: float) -> Path:
        times, values = [p[0] for p in points], [p[1] for p in points]
        time_at: dict[float, float] = defaultdict(float)
        i = bisect_right(times, start) - 1
        level = values[i] if i >= 0 else (values[0] if values else 0.0)
        t0 = start
        for t, v in points[max(0, i + 1):]:
            if t >= end:
                break
            time_at[level] += (t - t0) / unit_s
            t0, level = t, v
        time_at[level] += (end - t0) / unit_s
        return cls(times, values, dict(time_at))

    def before(self, t: float) -> float:
        """The level just before ``t``: what an event at ``t`` saw."""
        i = bisect_left(self.times, t) - 1
        return self.values[i] if i >= 0 else (self.values[0] if self.values else 0.0)

    def integral(self, c: float, k: float) -> float:
        """∫ max(0, c + k × level) dt over the window."""
        return sum(d * max(0.0, c + k * x) for x, d in self.time_at.items())


def events_of(points: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    """A counter's increments inside the window, as (time, count)."""
    out, prev = [], None
    for t, v in points:
        if prev is not None and start < t <= end and v > prev:
            out.append((t, v - prev))
        prev = v
    return out


def fit_flow(events: list[tuple[float, float]], window: float, paths: dict[str, Path], src: str | None) -> list[dict]:
    """Every candidate form for one flow, best (lowest AIC) first, scored with the exact
    point-process likelihood: each event against the rate just before it, the rate integrated
    over the stocks' actual paths:

        log L = Σ count × log rate(t⁻)  −  ∫ rate dt        (rate = c + k × X, never below zero)

    Scoring counts per step instead is biased for outflows: a step's average level is lowered by
    the very outflow being counted, which makes the rate look higher at low levels and favours a
    spurious intercept. The estimates of the constant and proportional forms are the same either
    way (events ÷ time, events ÷ level × time)."""
    total = sum(d for _, d in events)
    at = {sid: [p.before(t) for t, _ in events] for sid, p in paths.items()}

    def ll(c: float, k: float, sid: str | None) -> float:
        xs = at[sid] if sid else [0.0] * len(events)
        out = 0.0
        for (_, d), x in zip(events, xs):
            r = c + k * x
            if r <= 1e-12:
                return -math.inf
            out += d * math.log(r)
        return out - (paths[sid].integral(c, k) if sid else max(0.0, c) * window)

    cands = []
    c0 = total / window
    cands.append({"form": "constant", "params": {"c": c0}, "inputs": [], "loglik": ll(c0, 0.0, None), "k": 1})
    if src in paths:
        expo = paths[src].integral(0.0, 1.0)
        if expo > 0:
            k = total / expo
            cands.append({"form": "proportional", "params": {"k": k}, "inputs": [src], "loglik": ll(0.0, k, src), "k": 1})
    for sid, p in paths.items():
        xs = list(p.time_at)
        if not xs or max(xs) - min(xs) < 1e-9:
            continue
        span = max(xs) - min(xs)

        def nll(q, sid=sid):
            v = ll(q[0], q[1], sid)
            return -v if math.isfinite(v) else 1e18
        cc, kk = _nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span])
        cands.append({"form": "linear", "params": {"c": cc, "k": kk}, "inputs": [sid], "loglik": ll(cc, kk, sid), "k": 2})
    for cand in cands:
        cand["aic"] = 2 * cand["k"] - 2 * cand["loglik"] if math.isfinite(cand["loglik"]) else math.inf
    return sorted(cands, key=lambda c: c["aic"])


def dispersion(y: list[float], dt: float, form: dict, levels: dict[str, list[float]]) -> float:
    """Pearson χ² per degree of freedom of the counts per step against the chosen form: near 1
    when the form explains the variation, well above 1 when something it lacks drives the flow."""
    p, xs = form["params"], (levels[form["inputs"][0]] if form["inputs"] else [0.0] * len(y))
    mu = [max(1e-9, (p.get("c", 0.0) + p.get("k", 0.0) * x) * dt) for x in xs]
    return sum((v - m) ** 2 / m for v, m in zip(y, mu)) / max(1, len(y) - form["k"])


def discover(dump, *, start: float, end: float, step: float, time_unit: str = "minute") -> Model:
    """The model the metrics imply over [start, end], with how it was found in ``model.discovery``."""
    n = max(2, int((end - start) // step))
    dt = step / UNITS[time_unit]
    series = sample(dump, start, step, n)
    counters = [s for s in series if s.counter and any(s.deltas)]
    left_out: dict[str, str] = {}
    for s in series:
        if s.counter and not any(s.deltas):
            left_out[s.key] = "a counter that did not move in the window"
    found: list[tuple[Series, list[tuple[Series, int]], float, float]] = []
    ls = LeastSquares([c.deltas for c in counters]) if counters else None
    for s in series:
        if s.counter:
            continue
        if not any(s.deltas):
            left_out[s.key] = "a level that did not change in the window"
            continue
        terms, r2, exact = balance(s, counters, ls)
        if terms and r2 >= MIN_R2:
            found.append((s, terms, r2, exact))
        else:
            why = f"no counters balance it (best R² {r2:.2f}" + (f" with {', '.join(c.key for c, _ in terms)}" if terms else "") + ")"
            left_out[s.key] = why

    stocks, sid_of = [], {}
    for s, terms, r2, exact in found:
        sid = _slug(s)
        sid_of[s.key] = sid
        stocks.append(Stock(sid, _title(s), "items", SeriesRef(s.name, s.labels),
                            {"balance_r2": round(r2, 4), "exact_steps": round(exact, 4), "steps": n,
                             "machine": machine_of(s),
                             "balance": [{"series": c.key, "sign": sign} for c, sign in terms]}))
    ends: dict[str, dict] = defaultdict(lambda: {"src": None, "dst": None, "series": None})
    for s, terms, _, _ in found:
        for c, sign in terms:
            e = ends[c.key]
            e["series"] = c
            e["dst" if sign > 0 else "src"] = sid_of[s.key]
    used = set(ends)
    for c in counters:
        if c.key not in used:
            left_out[c.key] = "a counter no stock's balance needed"

    end = start + n * step
    unit_s = UNITS[time_unit]
    # fit only over the time every series involved has existed: a window that begins before a
    # machine started would count its silence as a rate of zero
    firsts = [s.points[0][0] for s, _, _, _ in found] + [e["series"].points[0][0] for e in ends.values()]
    i0 = min(n - 1, max(0, math.ceil((max([start, *firsts]) - start) / step)))
    fit_start = start + i0 * step
    levels = {sid_of[s.key]: [_average(s.points, start + i * step, start + (i + 1) * step) for i in range(i0, n)]
              for s, _, _, _ in found}
    paths = {sid_of[s.key]: Path.of(s.points, fit_start, end, unit_s) for s, _, _, _ in found}
    flows, by_machine = [], defaultdict(list)
    for e in ends.values():
        c = e["series"]
        y = c.deltas[i0:]
        best, *rest = fit_flow(events_of(c.points, fit_start, end), (end - fit_start) / unit_s, paths, e["src"])
        best["dispersion"] = dispersion(y, dt, best, levels)
        alt = {f"aic_{x['form']}" + (f"_{x['inputs'][0]}" if x["form"] == "linear" else ""): round(x["aic"], 2) for x in rest[:4]}
        alt.update({f"{x['form']}_k": round(x["params"]["k"], 6) for x in [best, *rest] if x["form"] == "proportional"})
        q = {"events": float(sum(y)), "loglik": round(best["loglik"], 3), "aic": round(best["aic"], 3),
             "dispersion": round(best["dispersion"], 3), "steps": float(n - i0), **alt}
        fid = _slug(c)
        flows.append(Flow(fid, _title(c), e["src"], e["dst"], SeriesRef(c.name, c.labels),
                          [Equation(best["form"], {k: round(v, 6) for k, v in best["params"].items()}, "fitted", "poisson-mle",
                                    (fit_start, end), None, q, best["inputs"])]))
        who = machine_of(c)
        if who:
            by_machine[who].append(fid)
    owners = {st.evidence.get("machine") for st in stocks} - {None}
    machines = [Machine(m, m, "program", "Seen in the metrics store: it writes the series these flows are bound to.",
                        sorted(by_machine.get(m, [])), [SeriesRef(s.name, s.labels) for s in series if machine_of(s) == m])
                for m in sorted(set(by_machine) | owners)]
    model = Model("system", "The system",
                  "Discovered from the metrics store: stocks are levels that counters balance; flows are those "
                  "counters, with equations fitted by Poisson maximum likelihood.",
                  time_unit, stocks, flows, machines)
    model.discovery = {"start": start, "end": end, "fit_start": fit_start, "step": step, "series": len(series),
                       "stocks": len(stocks), "flows": len(flows), "min_r2": MIN_R2,
                       "left_out": dict(sorted(left_out.items()))}
    return model
