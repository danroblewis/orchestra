"""The particle engine: individual particles moving under explicit rules, counted by region.

A system (systems.py) keeps its particles in a `Swarm`: one row per particle, with its region and any
other per-particle state (a position on a lattice). Each step it moves them by its own rules and
reports every particle's region before and after (`OUT`, -1, for one that left), so the same run
gives both the measured data (the count in each region after each step) and, over a long run, the
transition frequencies the mean-field model is measured from (meanfield.py).

Determinism: a run is fixed by its seed. Three independent streams are spawned from it, the initial
state, the drivers (inputs, announced injections) and the motion, and each is drawn in order, so a
short run is the start of the long one and the fresh run (seed + 1) starts elsewhere with other
drivers. The motion stream may be overridden alone (`motion_seed`), which gives many particle runs
from the same start and the same drivers: the ensemble the mean-field model is checked against.

Order inside a step t (the same as the SD engine's Euler step): the announced injections of step t
are added first; then every particle present decides its move from the state at the start of the
step (all at once, so nothing moves twice); then the particles arriving from outside in step t are
added (they move from step t + 1). The levels recorded for t are the counts after the step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

OUT = -1


def streams(seed: int, motion_seed: int | None = None) -> tuple[np.random.Generator, np.random.Generator, np.random.Generator]:
    """(initial state, drivers, motion) generators for a run."""
    init, drive, motion = np.random.SeedSequence([int(seed), 1729]).spawn(3)
    if motion_seed is not None:
        motion = np.random.SeedSequence([int(motion_seed), 2718, 1])
    return np.random.default_rng(init), np.random.default_rng(drive), np.random.default_rng(motion)


# ---- drivers ----

def piecewise(rng: np.random.Generator, steps: int, lo: float, hi: float, hold: tuple[int, int]) -> np.ndarray:
    """A level held for a random whole number of steps (hold = [min, max]) and then redrawn in [lo, hi];
    one value per step 1..steps, drawn in order (a longer run continues a shorter one)."""
    out = np.empty(steps)
    i = 0
    while i < steps:
        v, n = float(rng.uniform(lo, hi)), int(rng.integers(hold[0], hold[1] + 1))
        out[i:i + n] = v
        i += n
    return out


def daily(steps: int, amplitude: float, period: float = 24.0, phase: float = 0.0) -> np.ndarray:
    """1 + amplitude x sin(2 pi (t - phase) / period) at the middle of each step t = 1..steps."""
    t = np.arange(1, steps + 1) - 0.5
    return 1.0 + amplitude * np.sin(2 * np.pi * (t - phase) / period)


def batches(rng: np.random.Generator, steps: int, stock: str, gap: tuple[int, int], amount: tuple[int, int]) -> list[dict]:
    """Announced injections: a batch of whole particles into `stock` every `gap` steps (drawn), drawn in order."""
    out, t = [], 0
    while True:
        t += int(rng.integers(gap[0], gap[1] + 1))
        a = int(rng.integers(amount[0], amount[1] + 1))
        if t > steps:
            return out
        out.append({"t": t, "stock": stock, "amount": a})


@dataclass
class Drive:
    """A run's drivers: inputs (the expected arrivals per step, one value per step: what a page is
    given), announced injections, and per-step switches a system reads (e.g. which openings are shut)."""

    inputs: dict[str, np.ndarray] = field(default_factory=dict)
    injections: list[dict] = field(default_factory=list)
    switches: dict[str, np.ndarray] = field(default_factory=dict)
    eras: list[dict] = field(default_factory=list)              # announced: [{start, label}] from step 2 on


# ---- particles ----

@dataclass
class Swarm:
    """The particles: `reg` (region index per particle) and any per-particle arrays in `extra` (kept in step)."""

    reg: np.ndarray
    extra: dict[str, np.ndarray] = field(default_factory=dict)

    def keep(self, alive: np.ndarray) -> None:
        self.reg = self.reg[alive]
        for k in self.extra:
            self.extra[k] = self.extra[k][alive]

    def add(self, reg: np.ndarray, **extra: np.ndarray) -> None:
        self.reg = np.concatenate([self.reg, np.asarray(reg, dtype=np.int32)])
        for k in self.extra:
            self.extra[k] = np.concatenate([self.extra[k], np.asarray(extra[k], dtype=self.extra[k].dtype)])

    def counts(self, n: int) -> np.ndarray:
        return np.bincount(self.reg, minlength=n)[:n]


class Hops:
    """Region-to-region moves with fixed per-step probabilities: a particle in region i goes to j with
    probability P[i, j] (j may be OUT), else stays. `gates`: {region: m}, at most m particles leave
    that region in a step (the others that tried stay, chosen at random): a capacity limit."""

    def __init__(self, n: int, moves: list[tuple[int, int, float]], gates: dict[int, int] | None = None):
        self.n = n
        dest: dict[int, list[tuple[int, float]]] = {}
        for a, b, p in moves:
            if p > 0:
                dest.setdefault(a, []).append((b, float(p)))
        k = max([len(v) for v in dest.values()] or [1])
        self.D = np.full((n, k), OUT, dtype=np.int32)
        self.C = np.full((n, k), 2.0)                     # cumulative probabilities; 2 never reached
        for a, v in dest.items():
            c = 0.0
            for j, (b, p) in enumerate(v):
                c += p
                self.D[a, j], self.C[a, j] = b, c
            if c > 1 + 1e-12:
                raise ValueError(f"region {a}: move probabilities add to {c} > 1")
        self.gates = dict(gates or {})

    def step(self, reg: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """The regions after one step (OUT for a particle that left)."""
        if not len(reg):
            return reg.copy()
        u = rng.random(len(reg))
        idx = (u[:, None] >= self.C[reg]).sum(axis=1)              # u falls in the idx-th move's slice
        k = self.C.shape[1]
        moving = (idx < k) & (self.C[reg, np.minimum(idx, k - 1)] < 2)
        new = reg.copy()
        new[moving] = self.D[reg[moving], idx[moving]]
        for g, m in self.gates.items():
            leave = np.flatnonzero(moving & (reg == g))
            if len(leave) > m:
                stay = rng.choice(leave, size=len(leave) - m, replace=False)
                new[stay] = g
        return new


def stirred_pairs(rng: np.random.Generator, n_a: int, n_b: int, cells: int, bind: float) -> int:
    """A + B in a stirred tank of `cells` cells: every particle lands in a random cell; in each cell
    min(a, b) pairs meet and each binds with probability `bind`. The number of bindings."""
    if n_a == 0 or n_b == 0:
        return 0
    ca = np.bincount(rng.integers(cells, size=n_a), minlength=cells)
    cb = np.bincount(rng.integers(cells, size=n_b), minlength=cells)
    pairs = int(np.minimum(ca, cb).sum())
    return int(rng.binomial(pairs, bind)) if pairs else 0


# ---- a run ----

def record(ids: list[str], counts: np.ndarray, drive: Drive, steps: int) -> dict:
    """The run in data.py's format: {t, levels, all_levels, eras, counters, inputs?, injections?}."""
    levels = {k: [int(x) for x in counts[i, :steps]] for i, k in enumerate(ids)}
    out = {"t": list(range(1, steps + 1)), "levels": levels, "all_levels": {k: list(v) for k, v in levels.items()},
           "eras": [{"start": 1, "label": "Start"}] + [dict(e) for e in drive.eras if 1 < e["start"] <= steps], "counters": {}}
    if drive.inputs:
        out["inputs"] = {k: [round(float(x), 6) for x in v[:steps]] for k, v in drive.inputs.items()}
    inj = [dict(j) for j in drive.injections if j["t"] <= steps]
    if inj:
        out["injections"] = inj
    return out
