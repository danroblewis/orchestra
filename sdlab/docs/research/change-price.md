# Pricing outside-inflow changes honestly

**Status:** done (wave 1, benchmark v1)  
**Verdict:** reject (a narrower gate is neutral)

## Question
Outside-inflow changes are found by PELT at a price of 1 x log n x noise variance per change, below the
textbook BIC price (2 x log n: a change has a value and a place). Do cheap chance pieces let internal
dynamics hide as outside inflows (sd-support-tiers' resolved/reopened pieces, sd-eras' short pieces in
finished, sd-population's 151 pieces), and does an honest price fix it?

## What was done
Branch `exp/change-price`, commit `c40b6c0` (worktree `.claude/worktrees/agent-a294f3bb7bc2ffc92`).
Strategy `change_price`, mechanism test `tests/test_strategy_change_price.py` (chain inbox -> b -> c,
intake changing every 30 steps: matrix gives c 9 chance pieces; the strategy none, keeping the inbox's 62).

## Results (mean skill@20 / skill@100 / runs meeting goal; baseline 70.8% / 68.9% / 18 of 42)
| attempt | skill@20 | skill@100 | goal |
|---|---|---|---|
| 2 x log n in every pass | 52.4% | 43.8% | 17 |
| + long-run variance + each change pays alone | 57.8% | 50.1% | 17 |
| long-run variance at 1 x log n | 68.0% | 62.7% | 13 |
| each change pays alone, usual price | no change | | 18 |
| level-for-pieces test charged 2 per change | 64.2% | 58.7% | 16 |
| **gate** (2 x log n x long-run variance only at the first pass, only for stocks without an inflow) | 71.0% | 69.5% | 18 |
| minimum piece length 10 | 73.2% | 71.2% | 18 |
| minimum piece length 20 | 57.1% | 51.2% | 12 |

Why the honest price fails on sd-pipeline: the intake's 200 real changes are each weak at the true
drain; missing some biases the drain, which hides more (drain 0.25 -> 23 pieces, 0.20 -> 1; settles at
0.135 with one piece), and BIC then prefers that. 2 x log n assumes a fixed number of changes; an
intake that changes at a steady rate violates it.

## Open ideas
- Short pieces bias a row's own coefficient (within-piece demeaning, ~(1+a)/(m-1) for m-step pieces):
  explains why a 10-step minimum gives sd-pipeline default 58% -> 99%. A minimum tied to each row's time
  constant, or a bias correction.
- Estimate the levels beside the cheap pieces and never refit them on the reported pieces (the spiral
  needs the refit).
- Choose the inflow form per stock by behaviour, not globally per candidate.
