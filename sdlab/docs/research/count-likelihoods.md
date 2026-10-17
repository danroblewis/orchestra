# Poisson / negative-binomial likelihoods and count-aware weights

**Status:** idea (not started)

## Why
The data is made of counts: a flow's variance equals its mean. Least squares with equal weights ignores that; calibration practice recommends count likelihoods.

## How it could be tried
Weight each row by its flows' variance (iteratively reweighted least squares / GLM); variance-based drain estimates (see [shared-noise](shared-noise.md) open ideas).

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook M4 (rank 4): count-aware weights plus second moments, combined with [shared-noise](shared-noise.md): move rates from the covariance of two stocks' changes (minus the move), used as the drain where inflow pieces bias the mean fit; co-flows by ratio consistency. Note: the truth draws each flow Poisson around its rate and scales outflows down when a stock cannot cover them, so capped steps are censored, not Poisson.
- Fearnhead, Giagos, Sherlock (2014). Inference for reaction networks using the linear noise approximation. Biometrics 70(2):457-466, doi:10.1111/biom.12152.
- Vardi (1996). Network tomography. JASA 91(433):365-377, doi:10.1080/01621459.1996.10476697 (means under-determine flows; Poisson covariances identify them).
- Al-Osh, Alzaid (1987). First-order integer-valued autoregressive (INAR(1)) process. J. Time Ser. Anal. 8(3):261-275.
- Bretó, He, Ionides, King (2009). Time series analysis via mechanistic models. Ann. Appl. Stat. 3(1):319-348.
- Li, Rahmandad, Sterman (2025). Beyond least squares: estimation of dynamic models with alternative likelihoods and Kalman filtering. SDR 41(2):e70004, doi:10.1002/sdr.70004.
