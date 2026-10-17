# Refining rates by multi-step (output) error

**Status:** done (wave 1, benchmark v1)  
**Verdict:** needs a combination: keep as a final step after structural fixes

## Question
Coefficients come from one-step (equation-error) fits; small biases compound over 20-100 steps.
Does fitting the rates by multi-step simulation error fix long-horizon behaviour?

## What was done
Branch `exp/output-error`, commit `41c6f59` (worktree `.claude/worktrees/agent-a35853f76c9497504`).
`discovery/refine.py`: keeps the chosen structure, fits only flow rates with scipy `least_squares` on
5/20/100-step errors from 80 starts (rates >= 0); outside inflows fixed as found; era rates tied where
the matrix found one value. Strategy `output_error`.

## Results (baseline 70.8% / 68.9% / 18 of 42)
**73.5% / 72.7% / 18** (+2.7 / +3.8), +40% run time. sd-moderation long 49%/-32% -> 81%/73%,
sd-population long 50% -> 89%, sd-fishery long @100 31% -> 71%, sd-ci long @100 87% -> 95%; small
losses on sd-restaurant long @20 and sd-reservoirs default.
Rejected variants: re-measuring inflows per candidate rate set (66.6%: rates hand their job to inflows
the bench replaces), free per-era numbers (sd-recycling long 86% -> 26%), refining the best 3 candidates.
Mechanism test: rates off by +50%/-40% are brought back within 0.03; a wrong structure is improved
(100-step error / 3) but stays wrong.

## Lessons
- Never let a refinement re-estimate the outside inflows: internal dynamics leak into them.
- Numbers cannot fix structure; what remains in failing runs is structural.

## Open ideas
- Links driven by a final, ever-growing stock (done -> inbox in sd-pipeline default) are suspect.
- A positive own-coefficient chosen together with a constant inflow is suspect (spurious reinforcing
  loops in sd-population long, sd-fishery long).
- Spurious back-moves (trucks -> bins) and moves read backwards (elderly -> adults).
