# Hidden stocks from delayed copies of levels

**Status:** running (wave 1, benchmark v1)

## Hypothesis
In most failing examples the truth has unmeasured stocks (a delay between two measured ones). Offering
first-order-delayed copies of each stock's level as regressors, and turning a chosen one into a hidden
stock (A -> hidden -> B), recovers them. Includes a grader extension: a found model's own inferred
stocks are simulated from its own estimate of their levels.

Branch `exp/hidden-delays`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
