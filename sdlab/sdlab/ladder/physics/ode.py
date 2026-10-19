"""A physics case's data: its ODE solved in continuous time (scipy's LSODA, rtol 1e-10) and sampled
once per step, in exactly the format the ground-truth engine's data have (data.py):

    {"t": [1..N], "levels": {stock: level at the end of each step}, "all_levels": the same (no hidden
     stocks), "eras": [{"start": 1, "label": "Start"}], "inputs"?: {name: the input's mean over each
     step}, "injections"?: [{t, stock, amount}], "counters": {} (there are no flows to count)}

Conventions are the engine's: the level reported at t is the state at the end of step t (time t,
from time 0); an input's value for step t is its mean over (t - 1, t]; an injection at t is added at
the start of step t (time t - 1). The solver restarts at every jump of a driver and at every
injection; a switching system (the thermostat) also stops at each switch (an event) and goes on in
its new mode. Levels are rounded to 4 decimals, as the engine's are.

Seeds: the case's seed draws any parameter given as a range (params, here not per run); the run's
seed (the case's, or + 1 for the fresh run) draws the initial state and the drivers, each from its
own stream and in order, so a run of N steps is the first N steps of a longer run on the same seed.
"""

from __future__ import annotations

import zlib

import numpy as np
from scipy.integrate import solve_ivp

from .systems import Drive, System, levels_for

RTOL, ATOL = 1e-10, 1e-10
SUB = 16                                   # points per step for an input's mean over the step (midpoint rule)


def params(system: System, given: dict | None, seed: int) -> dict:
    """The system's parameters: its defaults, overridden by the case's; a range [lo, hi] is drawn
    (uniform) from the case's seed, the same for every run of the case."""
    out = dict(system.params)
    rng = np.random.default_rng([int(seed), 7001])
    for k in sorted(given or {}):
        v = given[k]
        if k not in out:
            raise ValueError(f"{system.name} has no parameter {k!r} (has: {', '.join(out)})")
        out[k] = round(float(rng.uniform(float(v[0]), float(v[1]))), 6) if isinstance(v, (list, tuple)) else float(v)
    return out


def _rng_for(seed: int):
    return lambda name: np.random.default_rng([int(seed), 7002, zlib.crc32(name.encode())])


def drive(system: System, p: dict, seed: int, steps: int) -> Drive:
    return system.drive(_rng_for(seed), p, steps)


def simulate(system: System, p: dict, seed: int, steps: int, keep_modes: bool = False) -> dict:
    """One run of `steps` steps on a run seed: the data dict (module docstring)."""
    x0 = np.asarray(system.initial(_rng_for(seed)("initial"), p), dtype=float)
    d = drive(system, p, seed, steps)
    states, modes = _solve(system, p, d, x0, steps)
    lv = (levels_for(system, p) or (lambda x: x))(states)
    levels = {s: [round(float(v), 4) for v in lv[i]] for i, s in enumerate(system.ids)}
    out = {"t": list(range(1, steps + 1)), "levels": levels, "all_levels": {k: list(v) for k, v in levels.items()},
           "eras": [{"start": 1, "label": "Start"}], "counters": {}}
    if system.inputs:
        out["inputs"] = {k: [round(float(v), 6) for v in input_means(d, k, steps)] for k in system.inputs}
    if d.injections:
        out["injections"] = [dict(j) for j in d.injections if j["t"] <= steps]
    if keep_modes and modes is not None:
        out["modes"] = modes
    return out


def input_means(d: Drive, name: str, steps: int) -> np.ndarray:
    """The input's mean over each step (t - 1, t], t = 1..steps."""
    t = np.arange(steps)[:, None] + (np.arange(SUB)[None, :] + 0.5) / SUB
    return np.asarray(d.value(name, t), dtype=float).mean(axis=1)


def _solve(system: System, p: dict, d: Drive, x0: np.ndarray, steps: int):
    """The state at times 1..steps (stocks x steps), and the switching system's mode at each."""
    inject = {}
    for j in d.injections:
        if j["t"] <= steps:
            inject.setdefault(float(j["t"] - 1), []).append(j)
    breaks = sorted({b for b in d.jumps if 0 < b < steps} | {b for b in inject if 0 < b < steps})
    edges = [0.0] + breaks + [float(steps)]
    ids = system.ids
    out = np.zeros((len(x0), steps))
    modes = np.zeros(steps, dtype=bool) if system.hybrid else None
    x = x0.copy()
    mode = system.hybrid[0](x, p, d) if system.hybrid else None
    for a, b in zip(edges[:-1], edges[1:]):
        for j in inject.get(a, []):                          # at the start of step a + 1
            i = ids.index(j["stock"])
            x[i] = max(0.0, x[i] + float(j["amount"]))
        want = np.arange(int(np.floor(a)) + 1, int(np.floor(b)) + 1, dtype=float)
        want = want[(want > a) & (want <= b)]
        t0 = a
        while True:
            if b - t0 <= 1e-9:                               # a switch a hair before the segment's end
                for tk in want[want > t0 - 1e-9]:
                    out[:, int(round(tk)) - 1] = x
                    if modes is not None:
                        modes[int(round(tk)) - 1] = mode
                break
            events = None
            if system.hybrid:
                g = system.hybrid[1](p, d, mode)
                direction = 1 if mode else -1
                if direction * g(t0, x) >= 0:                # already past the switch (a setpoint that jumped): switch now
                    mode = system.hybrid[2](mode)
                    continue
                ev = (lambda gg: (lambda t, y: gg(t, y)))(g)
                ev.terminal, ev.direction = True, direction
                events = [ev]
            ts = want[want > t0 + 1e-12]
            sol = solve_ivp(lambda t, y: system.rhs(t, y, p, d, mode), (t0, b), x, method="LSODA", t_eval=ts if len(ts) else None,
                            rtol=RTOL, atol=ATOL, events=events, dense_output=False)
            if not sol.success:
                raise RuntimeError(f"{system.name}: the solver failed at t = {t0}: {sol.message}")
            for k, tk in enumerate(sol.t if len(ts) else []):
                if tk in ts:
                    out[:, int(round(tk)) - 1] = sol.y[:, k]
                    if modes is not None:
                        modes[int(round(tk)) - 1] = mode
            if system.hybrid and sol.status == 1 and len(sol.t_events[0]):
                te = float(sol.t_events[0][0])
                x = np.asarray(sol.y_events[0][0], dtype=float)
                for tk in ts[(np.abs(ts - te) < 1e-9) & ~np.isin(ts, sol.t)]:     # a switch exactly at a sample time
                    out[:, int(round(tk)) - 1] = x
                    if modes is not None:
                        modes[int(round(tk)) - 1] = mode
                mode = system.hybrid[2](mode)
                t0 = te
                continue
            x = np.asarray(sol.y[:, -1], dtype=float) if len(ts) and sol.t[-1] >= b - 1e-12 else _end(system, p, d, mode, t0, b, x)
            break
    return out, modes


def _end(system: System, p: dict, d: Drive, mode, t0: float, b: float, x: np.ndarray) -> np.ndarray:
    """The state at b when no sample time fell at b (a segment ending between steps)."""
    sol = solve_ivp(lambda t, y: system.rhs(t, y, p, d, mode), (t0, b), x, method="LSODA", rtol=RTOL, atol=ATOL)
    return np.asarray(sol.y[:, -1], dtype=float)
