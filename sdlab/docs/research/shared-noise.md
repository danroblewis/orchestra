# Shared noise: telling moves, links and co-flows apart

**Status:** done (wave 1, benchmark v1 + co-flow engine)  
**Verdict:** needs a combination (with a fix for drain bias)

## Question
Each flow's amount per step is one random draw seen by every stock it touches: a move makes source and
destination residuals mirror each other, a link is independent, a co-flow mirrors at ratio `per`.
Does the residual covariance across rows recover structure the averages cannot?

## What was done
Branch `exp/shared-noise`, commit `d104d53` (worktree `.claude/worktrees/agent-ae075aeeeeac77e7d`),
rebased onto the co-flow engine. `discovery/shared_noise.py`: each same-unit gain read as move or
link by which reading predicts the residual covariance matrix best (decided only when flipping costs
> 9); links do not count as receivers of their source's drain; a "C drains faster when A is high"
term becomes `uses` on A's flow when C's residual shares A's draw at a steady ratio.
Mechanism tests: move + link at equal rates read correctly (matrix reads the link as a move);
population births read as a link; co-flow `per` recovered within 0.08 on engine data, 0.49-0.56 for a
true 0.5 on hand-made series; a control without shared draws gets no `uses`.

## Results (baseline 70.8% / 68.9% / 18 of 42, parts 59.9%)
v5 (committed): **parts +3.5, skill@20 -0.4, skill@100 -0.1, 17 meet the goal.** 14 relationships
gained, 1 lost. sd-services default 97% -> 80%: with the API calls correctly read as links, the
frontend keeps its own biased drain (0.893 vs 0.80); the wrong "move" reading had fixed it by luck.
sd-population unsolved (births and growing up have nearly equal variance; the long run's adults row is
misfit).

## Open ideas
- Under counting noise a flow's variance equals its mean: residual variances could estimate a drain
  without inflow-piece bias (the sd-services problem).
- Third co-moment (Poisson skewness) gives a move's direction for small flows.
- Regress per-step products of residuals on levels to tell a move driven by A from one driven by B.
- A joint fit of all rows with conservation built in (see joint-constrained-fit).
