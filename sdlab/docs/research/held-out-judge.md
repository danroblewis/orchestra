# Choosing candidates on held-out data

**Status:** done (wave 1, benchmark v1)  
**Verdict:** reject
**Copies (2026-10-19, queue item 0c):** `held_out_blend` is now a package carrying its own copy of `held_out` (`held_out_blend/_vendored/held_out.py`, commit 0c7a76b, imports rewritten; CLAUDE.md invariant 11). Found flows byte-identical before and after on 23 cells.

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

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- The failure is a known pitfall: cross-validation on dependent data with an unforecastable exogenous input measures extrapolation, not dynamics. Continuation: [inflow-conditioned-judge](inflow-conditioned-judge.md) (playbook M12).
- Dawid (1984). Statistical theory: the prequential approach. JRSS A 147(2):278-292.
- Racine (2000). hv-block cross-validation. J. Econometrics 99(1):39-61.
- Bergmeir, Hyndman, Koo (2018). CSDA 120:70-83 (k-fold is valid only for one-step autoregressive settings).

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (docs/research/declared-boundary.md; CLAUDE.md invariant
2). `held_out/boundary.py` is a copy of `matrix/boundary.py` at 723f72c (HIDDEN_PRICE 0). Every candidate
fit (each fold and all the data, `fit_one`) is refitted inside the boundary (`earned.refit`: an outside
term only where an estimated one may be, a measured input only where a measured one may be, sources with
no estimated outflow tied) and then guarded, so the held-out score only compares candidates inside the
boundary. A fold's guard refits on that fold's own steps (`_seen` hides the held-out block's levels). The
answer: guard and anti-correlated pairs made moves (declared), or each outside flow priced as a boundary
claim at 2 log T (not declared). The copy's one change: `alternatives()` never pairs an inflow into B with
B's own outflow (the reference's self-move B -> B).

Bounded (so the largest models do not time out; the first version took 316-317 from seconds to
timeouts): the guard prices each alternative with its numbers as they stand and refits only the best 3,
at most 24 refits per guard call (`GUARD_TOP`, `GUARD_FITS`); and `earned_joint.decide` never revisits a
set of ties and stops after 2 x (candidates + 1) steps (from the forced ties it cycled: 317 none-short,
25,000 fits for one candidate).

Results: in progress (paired before/after on Kubernetes 300-305 and 40 stored Tests cells, CPU pool).
