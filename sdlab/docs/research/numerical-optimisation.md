# Numerical gradients and derivative-free optimisers

**Status:** done (wave 2, benchmark v2)  
**Verdict:** needs a combination (the optimiser is not the bottleneck; the judging criterion is)

## Question
Does fitting a candidate structure's numbers (rates, effect curves, co-flow ratios, hidden-stock delays) by
multi-step error on the exact simulator, with numerical or derivative-free optimisers, recover what
one-step fits miss? Which optimiser works best?

## What was done
Branch `exp/numerical-opt`, commit `aac65a0` (worktree `.claude/worktrees/agent-a97d255b1ccc308b5`).
Modules `numopt.py`, `terms.py`, `outerror.py`, `optimisers.py`; strategies `numopt_fd`, `numopt_lbfgs`,
`numopt_powell`, `numopt_nm`, `numopt_cma`, `numopt_bo`. Optional terms (effects, hidden stocks, co-flows)
offered on top of the matrix result and kept by forward selection with the optimiser in the loop.

## Mechanism tests
- Table effect: curve shape recovered within 2-3% RMS over the observed range (with scale 9% / 36% on two
  seeds: the rate trades with the re-measured inflow); found by the full strategy on one seed only.
- Hidden stock: delay 10.3 / 9.6 (truth 10), flow 0.191 / 0.179 (0.2); but the grader on this branch
  cannot start a found hidden stock (since added by mass-balance-hidden).
- Co-flow ratio: 0.502 / 0.560 (truth 0.5); the judge cannot tell it from matrix's model (<0.7% apart).

## Results (baseline v2: 31.6% / 32.1% / 17 of 62)
| strategy | skill@20 | skill@100 | goal | evaluations per run |
|---|---|---|---|---|
| fd (least_squares) | 32.6% | 34.2% | **20** | 639 |
| lbfgs | 32.1% | 33.3% | 18 | 691 |
| powell | 32.7% | 35.3% | 19 | 654 |
| nelder-mead | 32.7% | 33.8% | 18 | 659 |
| cma | 31.6% | 33.6% | 15 | 704 |
| bayesian optimisation | 32.3% | 32.4% | 17 | 249 |
| fd, inflows profiled | 31.0% | 31.9% | 18 | 685 |
| fd, coarse learnable inflows | 29.2% | 31.8% | 17 | 876 |
About 8x the run time. Finite differences best at 30-60 evaluations for every parameter type; CMA-ES lags;
BO good on a single delay, poor on curves. Gains: sd-brewery (both) and sd-ci long meet the goal; losses:
sd-hospital long 92.8% -> 10.5% (a rate-only refit the judge passed).

## Lessons
- The optimiser is not the bottleneck (fd, Powell, Nelder-Mead within 0.6 points).
- The criterion (multi-step error with the model's own inflow pieces) often cannot tell right from wrong
  structure: the pieces replay the data.

## Open ideas
- Accept a rate-only refit only behind a stability or held-out check.
- Offer "outflow to outside becomes a move" with the target's inflow re-measured.
- A co-flow's ratio is only identifiable relative to the used stock's inflow unless it sometimes runs empty.


## Measured inputs (2026-10-20)
The shared `numopt.py`/`outerror.py` ran every model and judged the searched model with the run's
measured inputs missing (`Model(flows, ids)` with no `inputs=`; `judge(...)` without `opts["inputs"]`).
On kubernetes 300 none-long the matrix base was exact (judge 0 with inputs), the search drove the drain
to 0 and traffic to 1.5, and the blind judge preferred it (1.0 vs 17.0 blind; 5775 with inputs).
`numopt_bo`, `numopt_cma`, `numopt_nm` and `numopt_powell` are now packages with their own copies of both
modules (from aac65a0) that pass the inputs to the objective, the flow probes, the profiled inflows and
the judge (commit f6643bf; `tests/test_strategy_numopt_inputs.py`). `numopt_fd`, `numopt_fd_coarse`,
`numopt_fd_profile` and `numopt_lbfgs` still use the shared copies and keep the bug.
Ladder (each of the four, same seeds, before vs after): 300/301 0/10 -> 9/10 passing (300 meas-short
still fails: errors-in-variables bias 27%, the matrix base has it too); 96 other paired cells with an
unchanged scorer: fail -> pass 10-12 (062, 302-305), pass -> fail 0.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (docs/research/declared-boundary.md; the user's approval,
CLAUDE.md invariant 2). Each of `numopt_bo`, `numopt_cma`, `numopt_nm`, `numopt_powell` carries its own copy of
`matrix/boundary.py` at 723f72c (`HIDDEN_PRICE = 0`: a hidden stock pays only for its numbers; `CLAIM_PRICE = 2`)
and the same hooks as matrix at 67f5b9e, applied to its own copies of `earned.py`, `earned_rows.py`,
`earned_joint.py` (which were identical to matrix's before that commit):

- the base model is fitted inside the boundary from the start: a row has an outside term only on a declared
  `estimate` side, reads a measured input only on a declared `measured` side, reads a stock of another unit
  only on an `estimate` side; a source with no `estimate` outflow is tied (its drain is all moves);
- every candidate is guarded before the judge chooses (`boundary.apply(..., final=False)`);
- the numerical search itself (`numopt.py`) adds effects, co-flows and hidden stocks on the base's flows, never
  an outside flow, so it needs no candidate filter; the searched model is still guarded before the judge
  compares it with the base;
- the final answer (after the errors-in-variables refit) goes through `boundary.apply`: the guard and
  anti-correlated pairs tried as moves where a boundary is declared, each outside flow priced as a boundary
  claim (and listed in `boundary_claims`) where none is. The optional passes stop after `MAX_FITS = 120`
  refits.

Tests: `tests/test_numopt_boundary.py`. A later commit (ab73e30) gives the guard copy its own budget
(`GUARD_FITS = 160` refits; past it a flow outside the boundary is dropped untried, never kept).

Paired results (CPU pool, 2026-10-20, same cells for all four: before = fc7d3f9, jobs 90, 101-111; after =
7d2a370, jobs 20, 23, 25, 27, 29, 33, 96-100; 272 items, all paired, no errors). The 40 Tests cells are
25 where numopt_bo's stored answer had an outside flow the declared boundary lacks and 15 stored passes,
picked evenly from the sorted list.

| set | numopt_bo | numopt_cma | numopt_nm | numopt_powell |
|---|---|---|---|---|
| Kubernetes 300-305 (28 cells), pass | 27 -> 27 | 26 -> 27 | 27 -> 27 | 27 -> 27 |
| 40 Tests cells, pass | 18 -> 23 | 18 -> 23 | 18 -> 23 | 18 -> 23 |
| cells with an invented boundary | 16 -> 0 | 16 -> 0 | 16 -> 0 | 15 -> 0 |

- fail -> pass, all four: 047#1 none-short (equivalent -> pass for powell), 047#6 counts-short, 080 outliers-short,
  083 counts-short, 087 lag-long, 305 none-long; cma also 305 counts-long.
- pass -> fail, all four: 303 meas-long. The structure is still right (recall and precision 1); the move
  inflight -> responses_total comes out at 0.568 against 0.5 (error 13.5%, se 0.019).
- 195 counts-long: a timeout before, a fail after.
- The longest item took 72.5 s before and 43.9 s after. The pool has no numopt results for 313-317. Run by
  hand, numopt_powell on 317 none-long took more than 30 minutes both before and after the change, so 317
  times out either way.
