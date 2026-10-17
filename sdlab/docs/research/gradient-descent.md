# Gradient descent through a differentiable SD simulator

**Status:** running (wave 2, benchmark v2)

## Hypothesis
The SD simulation written in an autodiff framework (smooth floors in training; learnable effect tables,
co-flow ratios, hidden-stock rates and initial levels), fitted by multi-step error (multiple shooting,
horizon curriculum), with a generous optional structure pruned by sparsity, recovers what one-step fits
cannot. Compares matrix numbers, matrix structure + gradient numbers, generous structure + sparse fit.

Branch `exp/gradient`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
