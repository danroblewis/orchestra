"""The posterior of a chosen structure's numbers: kalman_lna's state-space likelihood on the flows
(ekf.py), a broad uniform prior on the flows' numbers (each within PRIOR_WIDTH times its found size of
the found value, and a rate's k, a constant and an inflow's pieces not below 0: the engine floors a
rate at 0, so below 0 the likelihood is flat and a flat prior there is improper) and uniform priors on
the log noise numbers. The joint mode is found first (mode()); the flows' numbers are then sampled by
adaptive Metropolis (mcmc.py) with the noise numbers held at it (sample()). The posterior-median
numbers are written into the flows, and every number carries its summary under "<key>_post" (median,
sd, 2.5% and 97.5% quantiles), so that a stored result keeps it."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass

import numpy as np

from .eiv import slots
from .ekf import Likelihood
from .mcmc import ess, hessian, mode as minimum, proposal, sample as metropolis

DRAWS = 10000         # Metropolis iterations after burn-in (fewer when the time runs out)
BURN = 2000
PRIOR_WIDTH = 10.0    # each number's prior: within this many times its found size (at least FLOOR) of it
FLOOR = 1e-6


def _owners(flows: list[dict]) -> dict[tuple, int]:
    out = {}
    for i, f in enumerate(flows):
        for d, k in slots([f]):
            out.setdefault((id(d), k), i)
    return out


def _nonnegative(flows: list[dict]) -> list[bool]:
    """Which numbers may not go below 0: a proportional rate's k, a constant, an inflow's pieces."""
    return [(k == "k" and d.get("form") == "proportional") or k == "value" for d, k in slots(flows)]


@dataclass
class Mode:
    lik: Likelihood
    x: np.ndarray
    nll: float
    found_nll: float
    outliers: int
    lo: np.ndarray
    hi: np.ndarray

    def bic(self) -> float:
        n = int(self.lik.mask.sum())
        return 2 * self.nll + self.lik.dim * math.log(max(n, 2))


def mode(flows: list[dict], stocks: list[dict], run: dict, opts: dict, found: dict, until: float,
         mask: np.ndarray | None = None) -> Mode | None:
    """The joint posterior mode of the flows' numbers and the noise numbers (None when there are no
    numbers, or the likelihood is not finite at the found ones). mask: the reports to use (another
    mode's, so that two structures are weighed on the same reports); else outliers are left out here."""
    lik = Likelihood(flows, stocks, run, opts, found)
    if mask is not None and mask.shape == lik.mask.shape:
        lik.mask = mask.copy()
    if lik.p == 0:
        return None
    th0 = lik.theta0
    width = PRIOR_WIDTH * np.maximum(np.abs(th0), FLOOR)
    lo, hi = th0 - width, th0 + width
    lo = np.where(_nonnegative(lik.flows), np.maximum(lo, 0.0), lo)

    def f(x):
        th = x[: lik.p]
        if np.any(th < lo) or np.any(th > hi):
            return math.inf
        return lik.nll(x)
    x0 = lik.start(found.get("measurement_error"))
    x0[: lik.p] = np.clip(x0[: lik.p], lo, hi)
    f0 = f(x0)
    if not math.isfinite(f0):
        return None
    free = np.zeros(lik.dim, bool)
    free[lik.p:] = True
    left = lambda share: time.monotonic() + share * max(0.0, until - time.monotonic())  # noqa: E731
    x = minimum(f, x0, free, until=left(0.2))                    # the noise numbers at the found flows
    out = lik.leave_out(x) if mask is None else 0
    if out:
        f0 = f(x0)
        x = minimum(f, x, free, until=left(0.2))
    x = minimum(f, x, None, until=left(0.4))                     # the joint mode
    lik.f = f
    return Mode(lik, x, f(x), f0, out, lo, hi)


def sample(m: Mode, until: float, seed: int = 0) -> tuple[list[dict] | None, dict]:
    """The flows at their posterior-median numbers (None when too few draws) and what was found."""
    began = time.monotonic()
    lik, x, f = m.lik, m.x, m.lik.f
    # the flows' numbers sampled with the noise numbers held at the joint mode (empirical Bayes: sampled
    # jointly, the noise numbers at their bounds left the chains with an effective size near 10)
    eta = x[lik.p:]
    g = lambda th: f(np.concatenate([th, eta]))                 # noqa: E731
    H = hessian(g, x[: lik.p], until=began + 0.3 * max(0.0, until - began))
    C = proposal(H, x[: lik.p])
    ch = metropolis(g, x[: lik.p], C, until, n=DRAWS, burn=BURN, seed=seed)
    th = ch["draws"]
    if len(th) < 50:
        return None, {"skipped": f"only {len(th)} draws in the time", "iterations": ch["iterations"]}
    med = np.median(th, axis=0)
    work = copy.deepcopy(lik.flows)                                # the posterior-median flows
    places = slots(work)
    owners = _owners(work)
    numbers = []
    for j, (d, k) in enumerate(places):
        col = th[:, j]
        s = {"median": float(med[j]), "mean": float(col.mean()), "sd": float(col.std(ddof=1)),
             "lo": float(np.quantile(col, 0.025)), "hi": float(np.quantile(col, 0.975)), "found": float(lik.theta0[j]),
             "mode": float(x[j]), "ess": round(ess(col), 1)}
        d[k] = float(med[j])
        d[f"{k}_post"] = {a: round(b, 9) for a, b in s.items() if a in ("median", "sd", "lo", "hi")}
        fl = work[owners.get((id(d), k), 0)]
        numbers.append({"flow": f"{fl.get('from') or 'outside'}->{fl.get('to') or 'outside'}", "key": k,
                        "reads": d.get("stock") if k == "k" else "1", **{a: round(b, 9) for a, b in s.items()}})
    noise = {"tau": {s: float(math.exp(v)) for s, v in zip(lik.states, eta[: lik.S])}, "phi": float(math.exp(eta[lik.S])),
             "alpha": float(math.exp(eta[lik.S + 1])), "rho2": float(math.exp(eta[lik.S + 2]))}
    width = np.maximum(m.hi - m.lo, 1e-300)
    at_bound = int(np.sum((np.abs(med - m.lo) < 1e-3 * width) | (np.abs(med - m.hi) < 1e-3 * width)))
    return work, {"numbers": numbers, "noise": noise, "draws": int(len(th)), "iterations": ch["iterations"],
                  "accept": round(ch["accept"], 3), "outliers_left_out": m.outliers, "evaluations": lik.evals,
                  "nll": {"found": round(m.found_nll, 3), "mode": round(m.nll, 3)}, "at_prior_bound": at_bound,
                  "hessian": H is not None and bool(np.isfinite(np.diag(H)).all()), "seconds": round(time.monotonic() - began, 2)}
