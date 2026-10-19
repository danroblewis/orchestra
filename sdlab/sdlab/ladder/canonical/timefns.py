"""Numbers from the reader's expressions (read.py): an expression in TIME evaluated with PySD's own
semantics, and an outside driver (an expression of TIME only) written as an SD Lab input formula.

    evaluate(expr, t, dt, lookups) -> float          (the placeholders F_step, F_pulse, LK_n, ... as PySD runs them)
    formula(expr, grid) -> [input terms] or None     (step/pulse/ramp/pulse_train/sin/constant, checked on the grid)

PySD's STEP is on from the Euler step whose time is within dt/2 of the step's time; PULSE and PULSE
TRAIN use a tolerance of 1e-6. An input term of SD Lab's engine (sdtruth.input_value) is evaluated at
tau = t + j x dt in sub-step j of recorded step t. A formula is accepted only if it gives the same value
as PySD at every grid point (a Grid maps model time to tau), so a switching time that falls between
Euler steps is placed half a step before the first step it is on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import sympy as sp

from .read import TIME, Blocked

SMALL_VENSIM = 1e-6


class _Clock:
    def __init__(self, t: float, dt: float):
        self.t, self.dt = t, dt

    def __call__(self):
        return self.t

    def time_step(self):
        return self.dt


def _fns(t: float, dt: float) -> dict:
    from pysd.py_backend import functions as pf

    clock = _Clock(t, dt)
    f = lambda x: float(x)
    return {
        # time functions carry TIME as their first argument (read.py); PySD reads the clock instead
        "F_step": lambda _t, h, ts: f(pf.step(clock, h, ts)),
        "F_pulse": lambda _t, start, width: f(pf.pulse(clock, start, width=width)),
        "F_pulse_train": lambda _t, start, every, width, end: f(pf.pulse(clock, start, repeat_time=every, width=width, end=end)),
        "F_ramp": lambda _t, slope, start, end=None: f(pf.ramp(clock, slope, start, end)),
        "F_Xpulse": lambda _t, start, magnitude: f(pf.pulse(clock, start, magnitude=magnitude)),
        "F_Xpulse_train": lambda _t, start, every, magnitude: f(pf.pulse(clock, start, repeat_time=every, magnitude=magnitude)),
        "F_Xramp": lambda _t, slope, start: f(pf.ramp(clock, slope, start)),
        "F_min": min, "F_max": max, "F_abs": abs, "F_sqrt": math.sqrt, "F_exp": math.exp, "F_ln": math.log,
        "F_log": lambda a, b: math.log(a) / math.log(b), "F_power": lambda a, b: a ** b,
        "F_sin": math.sin, "F_cos": math.cos, "F_tan": math.tan, "F_arcsin": math.asin, "F_arccos": math.acos,
        "F_arctan": math.atan, "F_sinh": math.sinh, "F_cosh": math.cosh, "F_tanh": math.tanh,
        "F_integer": lambda x: float(int(x)), "F_modulo": lambda a, b: f(pf.modulo(a, b)),
        "F_quantum": lambda a, b: f(pf.quantum(a, b)),
        "F_xidz": lambda a, b, x: f(pf.xidz(a, b, x)), "F_zidz": lambda a, b: f(pf.zidz(a, b)),
        "F_if_then_else": lambda c, a, b: a if c else b,
        "F_cmp_eq": lambda a, b: float(a == b), "F_cmp_ne": lambda a, b: float(a != b), "F_cmp_lt": lambda a, b: float(a < b),
        "F_cmp_le": lambda a, b: float(a <= b), "F_cmp_gt": lambda a, b: float(a > b), "F_cmp_ge": lambda a, b: float(a >= b),
        "F_cmp_and": lambda a, b: float(bool(a) and bool(b)), "F_cmp_or": lambda a, b: float(bool(a) or bool(b)),
        "F_cmp_not": lambda a: float(not a), "F_active_initial": lambda x, _init: x,
    }


def lookup(points, x: float) -> float:
    """A lookup as PySD interpolates it: linear between points, held at the ends."""
    xs, ys = points
    return float(np.interp(x, xs, ys))


def evaluate(expr, t: float, dt: float, lookups: dict, env: dict | None = None) -> float:
    """expr at model time t (its other symbols from env)."""
    fns = _fns(t, dt)

    def ev(e):
        if e is TIME or e == TIME:
            return t
        if e.is_Number or e in (sp.pi, sp.E):
            return float(e)
        if e.is_Symbol:
            if env is None or e.name not in env:
                raise Blocked("a value that is not known at the start", e.name)
            return float(env[e.name])
        if e.is_Add:
            return sum(ev(a) for a in e.args)
        if e.is_Mul:
            out = 1.0
            for a in e.args:
                out *= ev(a)
            return out
        if e.is_Pow:
            return ev(e.args[0]) ** ev(e.args[1])
        if isinstance(e, sp.Function) or hasattr(e, "func"):
            name = type(e).__name__
            if name in lookups:
                return lookup(lookups[name], ev(e.args[0]))
            if name in fns:
                if name == "F_if_then_else":
                    return ev(e.args[1]) if ev(e.args[0]) else ev(e.args[2])
                return float(fns[name](*[ev(a) for a in e.args]))
            raise Blocked(f"the function {name.removeprefix('F_').upper()}", str(e)[:60])
        raise Blocked("an expression that cannot be evaluated", str(e)[:60])

    return ev(expr)


def time_only(e) -> bool:
    """An outside driver: reads TIME and nothing else (no stock, no delay or smoothing)."""
    from .read import DELAY, SMOOTH
    return TIME in e.free_symbols and e.free_symbols == {TIME} and not e.has(DELAY, SMOOTH)


@dataclass
class Grid:
    """Model time and SD Lab time: recorded step t (1, 2, ...) and sub-step j are model time
    t0 + (t - 1 + j dt_sd) x scale, and tau = t + j dt_sd."""
    t0: float
    scale: float          # model time units per recorded step
    dt_sd: float          # sub-step, in recorded steps
    steps: int            # recorded steps to check

    def points(self):
        n = round(1 / self.dt_sd)
        for t in range(1, self.steps + 1):
            for j in range(n):
                yield t + j * self.dt_sd, t, self.t0 + (t - 1 + j * self.dt_sd) * self.scale


def series(expr, grid: Grid, dt: float, lookups: dict) -> list[float]:
    """The driver's value at each recorded step's start (for an input given as values; exact when a
    recorded step is one Euler step)."""
    return [evaluate(expr, grid.t0 + (t - 1) * grid.scale, dt, lookups) for t in range(1, grid.steps + 1)]


def formula(expr, grid: Grid, dt: float, lookups: dict) -> list[dict] | None:
    """The driver as SD Lab input terms, or None when it is not a sum of numbers times STEP, PULSE,
    PULSE TRAIN, RAMP, SIN and COS of an affine time, or the terms disagree with PySD on the grid."""
    from ...sdtruth import input_value

    terms = []
    for part in sp.Add.make_args(sp.expand(expr, mul=True, multinomial=False, power_exp=False, log=False)):
        coef, rest = part.as_coeff_Mul()
        if rest == 1:
            terms.append({"fn": "constant", "value": float(coef)})
            continue
        t = _term(rest, float(coef), grid, dt, lookups)
        if t is None:
            return None
        terms.append(t)
    spec = {"terms": terms}
    for tau, t, T in grid.points():
        want = evaluate(expr, T, dt, lookups)
        got = input_value(spec, tau, t)
        if not math.isclose(want, got, rel_tol=1e-9, abs_tol=1e-9):
            return None
    return terms


def _on(fn, grid: Grid) -> list[float]:
    """The grid's tau where fn(model time) is true."""
    return [tau for tau, _, T in grid.points() if fn(T)]


def _term(e, k: float, grid: Grid, dt: float, lookups: dict) -> dict | None:
    name = type(e).__name__
    args = e.args[1:] if name in ("F_step", "F_pulse", "F_pulse_train", "F_ramp") else e.args
    if any(a.free_symbols for a in args) and name not in ("F_sin", "F_cos"):
        return None
    vals = [float(a) for a in args] if name not in ("F_sin", "F_cos") else []
    half = grid.dt_sd / 2
    if name == "F_step":
        on = _on(lambda T: evaluate(e, T, dt, lookups) != 0, grid)
        if not on:
            return {"fn": "constant", "value": 0.0}
        return {"fn": "step", "height": k * vals[0], "start": on[0] - half}
    if name == "F_pulse":
        on = _on(lambda T: evaluate(e, T, dt, lookups) != 0, grid)
        if not on:
            return {"fn": "constant", "value": 0.0}
        height = evaluate(e, grid.t0 + (on[0] - 1) * grid.scale, dt, lookups)
        return {"fn": "pulse", "height": k * height, "start": on[0] - half, "width": on[-1] - on[0] + grid.dt_sd}
    if name == "F_pulse_train":
        _start, every, _width, end = vals
        on = _on(lambda T: evaluate(e, T, dt, lookups) != 0, grid)
        if not on:
            return {"fn": "constant", "value": 0.0}
        run = 1
        while run < len(on) and math.isclose(on[run] - on[run - 1], grid.dt_sd, abs_tol=1e-9):
            run += 1
        out = {"fn": "pulse_train", "height": k, "first": on[0] - half, "width": run * grid.dt_sd, "every": every / grid.scale}
        horizon = grid.t0 + grid.steps * grid.scale
        if end is not None and end < horizon:                       # it stops within the run (else it goes on)
            out["last"] = on[-1] + half
        return out
    if name == "F_ramp":
        slope, start = vals[0], vals[1]
        out = {"fn": "ramp", "slope": k * slope * grid.scale, "start": (start - grid.t0) / grid.scale + 1}
        if len(vals) > 2:
            out["end"] = (vals[2] - grid.t0) / grid.scale + 1
        return out
    if name in ("F_sin", "F_cos"):
        a = sp.Poly(args[0], TIME) if args[0].free_symbols == {TIME} else None
        if a is None or a.degree() != 1:
            return None
        b, c = (float(x) for x in a.all_coeffs())
        if b == 0:
            return None
        # sin(b T + c), T = t0 + (tau - 1) scale: sin(2 pi (tau - phase) / period)
        period = 2 * math.pi / (b * grid.scale)
        shift = c + (math.pi / 2 if name == "F_cos" else 0.0) + b * (grid.t0 - grid.scale)
        return {"fn": "sin", "amplitude": k, "period": period, "phase": -shift / (b * grid.scale)}
    return None
