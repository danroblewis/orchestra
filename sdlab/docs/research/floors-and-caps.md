# Rates floored at zero and outflows capped by what a stock holds

**Status:** running (wave 1, benchmark v1)

## Hypothesis
Rates like max(0, -40 + 0.2 x bales) and outflows capped by a stock's contents are kinked; a straight
one-step fit biases intercept and slope. Estimating them in their real form (censored / hinge
regression, fitting active steps) improves behaviour near the kink.

Branch `exp/floors`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
