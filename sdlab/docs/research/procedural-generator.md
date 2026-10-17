# A procedural generator of ground-truth SD models

**Status:** idea (not started)

## Why
31 hand-written examples invite tuning to them. Thousands of random models (chains, loops, hidden stocks, co-flows, effects, eras, unannounced changes) made with the same engine would show whether discovery generalises, and are the training data for [simulation-based-inference](simulation-based-inference.md).

## How it could be tried
A generator with knobs for structure size and features, sized for boundedness and excitation (the checks in [benchmark-excitation](benchmark-excitation.md)); a bench mode that samples N models per feature mix and reports skill by feature.

## Notes
Recommended first: it protects every other experiment from overfitting.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook I2: three pools (development, validation scored every run as a generalisation gap, sealed test with held-out motif families scored only at adoption).
- Cobbe, Hesse, Hilton, Schulman (2020). Leveraging procedural generation to benchmark reinforcement learning. ICML, PMLR 119:2048-2056.
- Dwork et al. (2015). The reusable holdout. Science 349(6248):636-638, doi:10.1126/science.aaa9375.
- Recht, Roelofs, Schmidt, Shankar (2019). Do ImageNet classifiers generalize to ImageNet? ICML, PMLR 97:5389-5400.
- La Cava et al. (2021). Contemporary symbolic regression methods and their relative performance. NeurIPS Datasets and Benchmarks, arXiv:2107.14351 (per-system tuning makes methods look better than they are).
- Kaptanoglu et al. (2023). Benchmarking sparse system identification with low-dimensional chaos. Nonlinear Dynamics 111(14):13143-13164, doi:10.1007/s11071-023-08525-4.
