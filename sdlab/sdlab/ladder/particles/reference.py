"""The reference a found model is compared with on a particle case: the mean-field model.

  exact, measured tiers   the mean-field model as derived (meanfield.py). For the exact tier it is the
                          conditional expectation of the counts one step on, so its forecasts are the
                          best any model can make from the counts (minimum mean squared error): the
                          particles' own randomness is what it cannot predict
  prediction tier         no SD model is exact, so the measured mean-field model's numbers (its moves'
                          rates and kappa; the inflows are known) are refitted by least squares on its
                          forecasts 20 and 100 steps ahead from 150 moments of a separate particle run
                          (physics/reference.py's fit, started at the measured numbers): the best model
                          of the mean-field's structure, not a bound on what any model can do
"""

from __future__ import annotations

from ..physics import reference as _physics_reference
from . import meanfield

FIT_STEPS = 3000


class _Fit:
    """physics/reference.py's `system.reference(p)` for a mean-field model: its moves' numbers and kappa free."""

    def __init__(self, system, p: dict, mf: dict, steps: int):
        self.system, self.p, self.mf, self.steps = system, p, mf, steps

    def reference(self, p):
        moves = [tuple(m) for m in self.mf["moves"]]
        kappa = self.mf.get("kappa")
        theta0 = [q for *_, q in moves] + ([kappa] if kappa else [])
        hi = [min(1.0, 3 * q + 0.01) for *_, q in moves] + ([3 * kappa] if kappa else [])

        def make(th):
            mv = [(a, b, float(x)) for (a, b, _), x in zip(moves, th)]
            mf = meanfield.assemble(self.system, self.p, mv, float(th[len(moves)]) if kappa else None, self.mf["how"])
            return meanfield.timed(mf, self.steps)

        return make, theta0, ([0.0] * len(theta0), hi), "fitted"


def fitted(system, p: dict, mf: dict, data: dict, steps: int) -> dict:
    """{flows (timed over `steps`), theta, moves, kappa, how}: the mean-field model refitted on `data`."""
    fit = _physics_reference.fit(_Fit(system, p, mf, steps), p, data)
    moves = [(a, b, float(x)) for (a, b, _), x in zip(mf["moves"], fit["theta"])]
    kappa = float(fit["theta"][len(moves)]) if mf.get("kappa") else None
    how = (f"the mean-field model ({mf['how']}) with its numbers refitted by least squares on its forecasts 20 and 100 "
           f"steps ahead over {len(data['t']):,} steps of a separate particle run")
    out = meanfield.assemble(system, p, moves, kappa, how)
    out["cost"], out["cost0"] = fit["cost"], fit["cost0"]
    return out
