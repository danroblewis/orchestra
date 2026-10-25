"""A copy of combined_misfit/fitcheck.py (CLAUDE.md invariant 11).

Does a model fit the measured changes to their noise? Two tests on its standardized one-step
residuals z = (change - model's mean change) / model's standard deviation (counts: the linear noise
approximation's variance, combined/judge.py):

- **dispersion**: with the right model the mean of z² is 1, with standard error sqrt(2 / (T S));
  `dispersion` is (mean z² - 1) over that standard error (a z-score; large = the changes spread
  more than the model's counting noise allows, i.e. something moves that the model does not have);
- **whiteness**: the Ljung-Box statistic over lags 1..10 of each stock's z, summed over stocks
  (chi-squared with 10 S degrees of freedom when the residuals are white), as a z-score
  (Q - dof) / sqrt(2 dof) (large = the residuals are correlated in time, the signature of
  misspecified dynamics; Ljung and Box 1978, and Bergmeir, Hyndman and Koo 2018 on why one-step
  scores are only trustworthy with uncorrelated residuals).

Only meaningful for counts, where the model states its own noise. Noise-free data are written to a
quantum, so their residuals are rounding, which is neither independent nor of known size.
"""

from __future__ import annotations

import math

import numpy as np

from ._vendored.combined import judge as J

LAGS = 10


def goodness(flows: list[dict], data: J.Data, starts: dict | None = None) -> dict:
    """{dispersion, whiteness} z-scores of the model's one-step residuals (None for non-counts)."""
    if not data.counts or not flows:
        return {"dispersion": None, "whiteness": None}
    mu, cov = J.one_step(flows, data, starts)
    if cov is None:
        return {"dispersion": None, "whiteness": None}
    r = data.dy - mu
    sd = np.sqrt(np.einsum("tii->it", cov) + data.q ** 2 / 6.0)
    z = r / sd
    if not np.all(np.isfinite(z)):
        return {"dispersion": math.inf, "whiteness": math.inf}
    S, T = z.shape
    disp = (float((z ** 2).mean()) - 1.0) / math.sqrt(2.0 / (T * S))
    lags = min(LAGS, T // 4)
    Q = 0.0
    for s in range(S):
        x = z[s] - z[s].mean()
        d = float((x * x).sum())
        if d <= 0:
            continue
        for k in range(1, lags + 1):
            rk = float((x[k:] * x[:-k]).sum()) / d
            Q += T * (T + 2) * rk * rk / (T - k)
    dof = max(1, lags * S)
    return {"dispersion": disp, "whiteness": (Q - dof) / math.sqrt(2.0 * dof)}
