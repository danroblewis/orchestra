"""The posterior of a chosen structure's numbers: kalman_lna's state-space likelihood on the flows
(ekf.py), flat priors on the flows' numbers and uniform priors on the log noise numbers. The joint
mode is found first; the flows' numbers are then sampled by adaptive Metropolis (mcmc.py) with the
noise numbers held at it. The posterior-median numbers are written into
the flows, and every number carries its summary under "<key>_post" (median, mean, sd, 2.5% and
97.5% quantiles), so that a stored result keeps it."""

from __future__ import annotations

import copy
import math
import time

import numpy as np

from .eiv import slots
from .ekf import Likelihood
from .mcmc import ess, hessian, mode, proposal, sample

DRAWS = 10000         # Metropolis iterations after burn-in (fewer when the time runs out)
BURN = 2000


def _owners(flows: list[dict]) -> dict[tuple, int]:
    out = {}
    for i, f in enumerate(flows):
        for d, k in slots([f]):
            out.setdefault((id(d), k), i)
    return out


def posterior(flows: list[dict], stocks: list[dict], run: dict, opts: dict, found: dict, until: float, seed: int = 0) -> tuple[list[dict] | None, dict]:
    """The flows at their posterior-median numbers (None when no posterior could be made) and what
    was found."""
    began = time.monotonic()
    lik = Likelihood(flows, stocks, run, opts, found)
    if lik.p == 0:
        return None, {"skipped": "no numbers to sample"}
    f = lik.nll
    x0 = lik.start(found.get("measurement_error"))
    if not math.isfinite(f(x0)):
        return None, {"skipped": "the likelihood is not finite at the found numbers"}
    free = np.zeros(lik.dim, bool)
    free[lik.p:] = True
    left = lambda share: time.monotonic() + share * max(0.0, until - time.monotonic())  # noqa: E731
    x = mode(f, x0, free, until=left(0.15))                      # the noise numbers at the found flows
    out = lik.leave_out(x)
    if out:
        x = mode(f, x, free, until=left(0.15))
    x = mode(f, x, None, until=left(0.3))                       # the joint mode
    # the flows' numbers sampled with the noise numbers held at the joint mode (empirical Bayes: sampled
    # jointly, the noise numbers at their bounds left the chains with an effective size near 10)
    eta = x[lik.p:]
    g = lambda th: f(np.concatenate([th, eta]))                 # noqa: E731
    H = hessian(g, x[: lik.p], until=left(0.3))
    C = proposal(H, x[: lik.p])
    ch = sample(g, x[: lik.p], C, until, n=DRAWS, burn=BURN, seed=seed)
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
    return work, {"numbers": numbers, "noise": noise, "draws": int(len(th)), "iterations": ch["iterations"],
                  "accept": round(ch["accept"], 3), "outliers_left_out": out, "evaluations": lik.evals,
                  "nll": {"found": round(f(x0), 3), "mode": round(f(x), 3)}, "hessian": H is not None and bool(np.isfinite(np.diag(H)).all()),
                  "seconds": round(time.monotonic() - began, 2)}
