# Choosing candidates on held-out data

**Status:** done (wave 1, benchmark v1)  
**Verdict:** reject

## Question
identify() keeps the candidate with the lowest multi-step error on the data it was fitted on;
flexible candidates (many inflow pieces) win in-sample but fail when graded. Does judging out of sample
pick better?

## What was done
Branch `exp/held-out-judge`, commit `08dd9e1` (worktree `.claude/worktrees/agent-abe6f16cf8eec4328`).
`identify_one` gained a `steps` mask; blocked cross-validation (`discovery/holdout.py`); strategies
`held_out` and `held_out_blend`. Mechanism test: a trap candidate (births read as a move, paid back by
inflow pieces) is ranked worst by `held_out` and picked by `matrix`.

## Results (baseline 70.8% / 68.9% / 18 of 42; best-graded candidate picked 31 of 42)
| | skill@20 | skill@100 | goal | best candidate picked |
|---|---|---|---|---|
| held_out (5 blocks) | -4.8% | -6.3% | 3 | 9 of 42 |
| held_out_blend | 70.5% | 68.1% | 20 | 30 of 42 |
| always the best-graded candidate (oracle) | 78.3% | 76.2% | | 42 |

Also tried: forward splits, many CV settings, information criteria counting pieces, held-out vetoes:
none beats in-sample. **Why:** a held-out judge must also forecast the outside inflow, which changes
unannounced in most examples; a stale last piece dominates the error, so constant-inflow candidates win.

## Lessons
- The in-data judge is already good (31 of 42 best picks; an oracle reaches only 78%): the headroom
  is in models no candidate represents, not in the picking.

## Open ideas
- A judge of dynamics given inflows: on held-out data, fix the coefficients and re-estimate only a
  coarse outside inflow (asks the bench's question; needs a decision on using held-out data that way).
- Flag pieces into an internal stock that track another stock's level.
- More candidates (e.g. a link variant per changing row).
