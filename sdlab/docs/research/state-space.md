# Kalman filtering and state-space EM

**Status:** idea (not started)

## Why
Recommended first by the [tools survey](tools-survey.md): score candidates by one-step Kalman likelihood with process noise shared by a flow's two stocks; estimate hidden stocks with EM (dynamax, statsmodels).

## How it could be tried
A likelihood-based judge in place of (or beside) multi-step error; EM for hidden-stock delays compared with [hidden-stocks](hidden-stocks.md).

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook conflict C1: with every measured stock observed exactly, the Kalman one-step likelihood of a model without hidden stocks is the weighted one-step regression (covariance S·diag(q)·Sᵀ), which playbook M4 takes now; filtering matters for hidden-stock candidates (playbook M14, after [delay-deconvolution](delay-deconvolution.md)).
- Li, Rahmandad, Sterman (2025). SDR 41(2):e70004.
- Peterson (1976). Statistical tools for system dynamics. MIT (FIMLOF; the 1980 book chapter could not be confirmed).
- Fearnhead, Giagos, Sherlock (2014). Biometrics 70(2):457-466.
