# Symbolic regression for rate equations and effect curves

**Status:** done (wave 2, benchmark v2)  
**Verdict:** needs a combination (finds effects; the judge cannot tell true effects from spurious ones)

## Question
After the linear fit, does a search over curves of a third stock (rate term x f(level of C)) find
effects, translated into SD Lab table effects?

## What was done
Branch `exp/symbolic-regression`, commit `b917b0f` (worktree `.claude/worktrees/agent-a9c884b9568329f6b`).
A grammar of 55 curve shapes (saturating, logistic, decaying, caps, ...). Every column "level of A (or 1)
x curve of C" is screened against each matrix row's residual: kept only if it explains both rows a
flow would touch, and each half of the data on its own; at most 3, greedily. Kept columns join the
matrix as "virtual stocks" in those rows only (`matrix.py` option `only_rows`); links and drains become a
flow of A with a 12-point table effect of C. The main line's judge picks between the plain and effect
models. Modules: `curves.py`, `effects.py`, `onestep.py`, strategy `symbolic`.
Unconstrained SR (gplearn, `tests/bench/sr_compare.py`): no better than a linear fit, 18-29 s per row,
expressions not readable as flow x curve. PySR not tried.

## Mechanism tests (a -> b at k x a x table(c))
| case | recovered curve, max error | matrix (one constant rate) | skill@20 effects vs matrix |
|---|---|---|---|
| steep table | 6.8% of k | 72% of k | 46% vs -56% |
| exponent-shaped saturating | 4.4% of k | 37% of k | 50% vs -95% |
Both need arrivals that vary out of step with c; through the full strategy the judge still keeps
matrix on the steep case (its 60 inflow pieces imitate the effect).

## Results (baseline v2: 31.6% / 32.1% / 17 of 62)
| version | skill@20 | skill@100 | parts | goal | time |
|---|---|---|---|---|---|
| v3 | 50.1% | 47.8% | 55.5% | 21 | 822 s |
| **v5 (final)** | **50.5%** | **47.7%** | 55.8% | 19 | 2072 s |
Effect examples (skill@20/@100): sd-sawmill -331/-126 -> 65/71 (default), -276/-42 -> 73/77 (long);
sd-webshop-stock -156/-224 -> 86/84, -26/-83 -> 94/92; sd-learning-curve long 45/49 -> 99/100;
sd-emergency unchanged (effects found, judge keeps matrix); sd-farm-soil long 97/77 -> 74/-89 (its effect
multiplies a seasonal inflow). Gains on co-flow examples too (a stock running dry acts like a curve):
bakery, print-shop default, cloud-credits long; housing long, moderation long, orders default.
Losses: manufacturing default 79 -> -58, support-tiers long 43 -> -77, eras default 96.5 -> 60, ev-fleet,
restaurant long @100. 6.4x run time.

## Lessons
- Effects can be found by screening curve columns against row residuals, with a split-half check.
- Free-form SR is not useful here; a constrained SD grammar is.
- The judge (own inflow pieces) cannot tell true from spurious effects: small ablations move a dozen
  examples by 50-1000 points.

## Open ideas
- A judge inflow pieces cannot fool (the common blocker).
- Effects on a changing inflow (farm-soil): fit the curve on the piece values.
- A dedicated co-flow search for flows limited when the used stock runs dry.
- A stability check on each candidate before judging.

