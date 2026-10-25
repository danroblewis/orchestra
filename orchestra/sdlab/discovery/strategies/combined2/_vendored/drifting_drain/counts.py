# Vendored for combined2 from sdlab/discovery/strategies/drifting_drain/counts.py at commit 453358e (HEAD ebe9a4f); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""A model priced by the likelihood of the per-step changes under counting noise.

When the levels are whole numbers (things counted), each flow moves a random whole number of things
around its rate, so a step's change has a variance as large as what moved through the stock (in +
out; Poisson), plus the rounding of the levels (1/6, as lna's likelihood takes it). A stock near a
moving balance barely changes, and the one-step least squares cannot tell a model with large flows
in and out from one with none (121-drifting-drain counts-long: the main line returned no flows); the
size of the noise can. Each stock's row is priced on its own (no covariance between rows), and the
price is a BIC: 2 x the negative log-likelihood plus log T per number.
"""

from __future__ import annotations

import math

import numpy as np

from orchestra.sdlab.discovery.simulate import Model
from . import onestep

ROUNDING = 1 / 6


def whole(levels: np.ndarray) -> bool:
    """Whether the levels are counts: whole numbers, and not all the same."""
    return bool(np.ptp(levels) > 0 and np.all(np.abs(levels - np.round(levels)) < 1e-9))


def bic(flows: list[dict], ids: list[str], t: list, prev: np.ndarray, dy: np.ndarray, inputs: dict | None = None) -> float:
    T = prev.shape[1]
    times = np.asarray(t, dtype=float)[1 : T + 1]
    mean = onestep.changes(flows, ids, t, prev, inputs)
    gross = np.zeros_like(prev)
    if flows:
        model = Model(flows, ids, inputs=inputs)
        for (src, dst, ratio, *_), a in zip(model.parts, model._amounts(prev, times)):
            a = np.abs(np.nan_to_num(np.asarray(a, dtype=float)))
            if src is not None and src < len(ids):
                gross[src] += a * ratio
            if dst is not None and dst < len(ids):
                gross[dst] += a
    var = gross + ROUNDING
    r = dy - mean
    nll = 0.5 * float(np.sum(np.log(2 * math.pi * var) + r * r / var))
    return 2 * nll + onestep.params(flows) * math.log(T)
