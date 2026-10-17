# Rates floored at zero and outflows capped by what a stock holds

**Status:** done (wave 1, benchmark v1)  
**Verdict:** needs a combination (caps a small net gain; hinges work in isolation but no selector suits them)

## Question
Rates like max(0, -40 + 0.2 x bales) and outflows capped by a stock's contents are kinked; a straight
one-step fit biases intercept and slope. Does estimating them in their real form help?

## What was done
Branch `exp/floors`, commit `896c03b` (worktree `.claude/worktrees/agent-aa7b06917dbf529d4`).
Strategy `floors`: caps by EM (`caps.py`: where the found model's outflows wanted more than an
emptied stock held, add the cut-off back and refit; stocks empty on more than half the steps skipped)
and optional hinge columns max(0, +-(x - theta)) per stock (`hinges.py`). Opt-in hooks in `matrix.py`.

## Mechanism tests
| case | matrix | strategy |
|---|---|---|
| floor a -> b = max(0, 0.2a - 30), shut 50% of the time | 0.140 a + 73 spurious inflow pieces; skill@20 -5.4% | max(0, 0.190a - 28.4), threshold 149 vs 150; 93.9% |
| constant sale 15 from a stock empty 36% of steps | 70.1% | cap EM 88.8%; hinge 98.0% |

## Results (baseline python: 70.8% / 68.9% / 18 of 42)
Caps only (default): 72.2% / 69.3% / 18 (sd-orders long 7% -> 84%; sd-ev-fleet long 79% -> 68%,
sd-kanban default 77% -> 69%), 1.5x run time. With hinges: 61.9-73.3% over ten settings, up to 21 of
42 meeting the goal; sd-moderation long 49%/-32% -> 83%/75% (threshold 307 vs 300) but sd-manufacturing
long down to -184%, sd-fishery long to -50% (hinges imitate unannounced seasons). Flipping only a
hinge's side swung sd-manufacturing default from 72.8% to -354%.

## Grader finding (fixed on the main line)
`simulate.Model` did not share an emptied stock's level among its outflows as the engine does, so the
grader's truth moved stuff out of empty stocks; a faithful model of the data scored only 54.8%/79.1% on
sd-supply, ~89% on sd-manufacturing and sd-ev-fleet. Fixed in `simulate.Model` (see
DISCOVERY-EXPERIMENTS.md).

## Open ideas
- A selector that charges for inflow pieces (scoring on steps the pieces were not fitted on).
- Change detection cuts kinks into inflow pieces even for stocks with no outside inflow: test pieces
  before accepting them.
- Multi-term hinges (floors on several stocks at once).
- Unannounced seasons look like kinks to any nonlinear term (sd-fishery).
