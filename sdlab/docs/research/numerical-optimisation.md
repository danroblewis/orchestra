# Numerical gradients and derivative-free optimisers

**Status:** running (wave 2, benchmark v2)

## Hypothesis
The same fitting problem as [gradient-descent](gradient-descent.md), solved on the exact
(non-differentiable) simulator: finite-difference gradients (least_squares, L-BFGS-B), derivative-free
(Nelder-Mead, Powell, CMA-ES), Bayesian optimisation for small parameter sets; optional terms switched
on by forward selection with the optimiser in the loop. Optimisers compared on equal budgets.

Branch `exp/numerical-opt`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
