# Bayesian structure learning and bootstrap ensembles

**Status:** the cheap ensemble and MCMC on the numbers tried as [kalman_bayes](kalman_bayes.md) (2026-10-20): reject as an answer, keep as uncertainty; reversible-jump MCMC over structures not started.

## Why
A posterior over models (how often each flow appears) instead of one answer; uncertainty to show on the page.

## How it could be tried
Cheap: bootstrap resamples of discovery (E-SINDy style). Full: MCMC over structures (reversible jump), PyMC/NumPyro for numbers.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook M10: block-bootstrap inclusion probabilities and a bagged candidate.
- Fasel, Kutz, Brunton, Brunton (2022). Ensemble-SINDy. Proc. R. Soc. A 478:20210904.
- Meinshausen, Bühlmann (2010). Stability selection. JRSS B 72(4):417-473.
- Dogan (2007). Bootstrapping for confidence interval estimation and hypothesis testing for parameters of SD models. SDR 23(4):415-436.
