"""The reference for a physics case: the best model SD Lab's forms can write for the physics, fitted
by an oracle that knows the physics' structure.

The system gives the reference's flows with free numbers, one per physical term (systems.py: a
sqrt outflow becomes a proportional one, a product a proportional rate times a linear effect, the
thermostat's on/off heater a proportional controller floored at 0), and starting numbers from the
physics. They are fitted on the case's long noise-free run (its own seed) by least squares on the
model's predictions 20 and 100 steps ahead from 150 moments each (scipy least_squares, the
residuals each stock's error over its spread), the same predictions skill@20 and skill@100 grade.
One reference per case: what the best SD model of this physics achieves, whatever the variant.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from ...discovery.simulate import Model, levels_array, starts_for

HORIZONS = (20, 100)
STARTS = 150


def fit(system, p: dict, data: dict) -> dict:
    """{flows, theta, how, cost0, cost}: the reference's flows fitted on `data` (a clean run)."""
    make, theta0, bounds, how = system.reference(p)
    ids = list(data["levels"])
    A = levels_array(data["levels"], ids)
    t = np.asarray(data["t"], dtype=float)
    inputs = {"t": data["t"], "values": data["inputs"]} if data.get("inputs") else None
    sd = A.std(axis=1)
    sd[sd == 0] = 1
    plans = []
    for h in HORIZONS:
        s0 = starts_for(A.shape[1], h, STARTS)
        plans.append((s0, t[s0[None, :] + np.arange(h)[:, None]], A[:, s0 + h - 1]))

    def residuals(th):
        flows = make(th)
        out = []
        for s0, times, end in plans:
            got = Model(flows, ids, inputs=inputs).run(A[:, s0 - 1], times, data.get("injections"))
            r = (got - end) / sd[:, None] / np.sqrt(len(s0))
            out.append(np.nan_to_num(r, nan=1e3, posinf=1e3, neginf=-1e3).ravel())
        return np.concatenate(out)

    lo, hi = np.asarray(bounds[0], dtype=float), np.asarray(bounds[1], dtype=float)
    x0 = np.clip(np.asarray(theta0, dtype=float), lo, hi)
    c0 = float(0.5 * np.sum(residuals(x0) ** 2))
    best = least_squares(residuals, x0, bounds=(lo, hi), x_scale="jac", xtol=1e-10, ftol=1e-10, max_nfev=400)
    th = best.x if best.cost <= c0 else x0
    return {"flows": make(th), "theta": [float(x) for x in th], "how": how, "cost0": c0, "cost": float(min(best.cost, c0))}
