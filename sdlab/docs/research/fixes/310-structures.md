# 310 (k8s-memory-oom): structures, the noise-free and counts variants

**Status:** all four variants still fail. None of them can pass under the current scorer, for any strategy (see the
diagnosis below). One general fix was kept (counted.py). It brings 3 OOM parts right on none-short and none-long.
2026-10-21, agent structures-310. I held the structures lock for the work and released it after the commit.

## Before (store, code a660e75)

`uv run sdlab-ladder show 310 --strategy structures --variant V`:

| variant | status | parts | what was wrong |
|---|---|---|---|
| none-short | FAIL | 12/23 | retries split lost (base combined's `censored` candidate, "floor on oom_kills_total into retries"); `outside -> pending` a constant; mem's rows junk; no `ready -> pending` kill move; `outside -> oom_kills_total = 0.0094` |
| none-long | FAIL | 12/23 | spurious moves `ready <-> desired` (ready is no longer a whole number once OOM kills remove fractions of pods, so the misfit went through `desired`); HPA whole flows wrong; mem junk; no kill move; oom constant-plus-mem |
| counts-short | FAIL | 10/23 | retries split; a hidden chain into mem; no kill move; oom `0.0005 retries` |
| counts-long | FAIL | 7/23 | cpu links off; pending/ready/mem rows blown up (1e11 coefficients); no kill move |

No strategy passes any of the four (store, 41-42 cells each; `scratchpad s310/parts.py` over `store.latest`).

## Diagnosis (rule 4b)

`uv run sdlab-ladder analyse 310-k8s-memory-oom --variant V` says "not analysed: a truth this analysis does not cover"
for all four, so I checked achievability directly (scratchpad `s310/oracle.py`, `score.equations` on the truth's own flows):

- **The truth passes all four variants only while its hidden stock is called `leak`.** Rename it, as any discovered
  hidden stock is named, and the `outside -> mem` expression fails to compile ("reads hX: not a stock, input or
  auxiliary"). With the leak term left out (what a linear found rate reading its own hidden stock contributes on the
  scorer's states: 0), the truth fails `outside -> mem [as a whole]` on every variant: error 0.396 (none-short), 0.452
  (none-long), 0.355 (counts-short), 0.383 (counts-long). The allowed error is 0.02 (none) or 0.10 (counts).
- Why: a whole flow is compared through its amounts on the run's true states (`score._flow_amounts`, `sim.amounts` over
  `data["all_levels"]`). Those states contain the truth's hidden `leak` and none of the found model's hidden stocks,
  and `inferred_levels` are not used there. So the mem inflow (150 + leak + 2 inflight / ready, where the leak ramps
  0..300) cannot be matched by a model whose leak is its own hidden stock. **No variant of 310 is achievable as
  scored.** This is a limit of the harness, not of the data or of the method. I did not change the harness (rule 12).
  The fix needed: evaluate a found flow that reads one of the found model's hidden stocks on that model's
  `inferred_levels` (or its simulated hidden level), as the behaviour score already does.
- The other failures are method faults I could check. On none-short and none-long, `oom_kills_total`'s increments
  equal `ready x table(mem)` exactly. mem stays between 480 and 488 there, on the table's first segment (0 to 0.3 over
  480 to 512), so one hinge reproduces it. The kill move `ready -> pending` carries the same amount. Upstream it was
  invisible: 2.8 pods over 21 steps in none-short.

## Fix kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| counted-effect-move | **A counter's increments fitted as a move with a threshold effect.** Every counter (a final stock, or one whose levels never fall) is examined if it has a declared outside inflow (estimated), no outflow and no move, and moves on at least 3 steps. Its increments y are fitted as A x e(X). A is a measured stock in the counter's unit (what is counted moves out of A). X is any other measured stock or input (an effect: a link, it may cross units). e is a monotone piecewise-linear table: 0 below a threshold, 1-3 segments with knots at the threshold and at quantiles of X where the counter moves, slopes fitted by NNLS (non-negative), capped at 1, since a move takes at most the whole stock in a step. The threshold must bind: the table is 0 on at least 3 steps where A holds something. That keeps a counter fed by a plain or bilinear rate with the fits upstream. A, X, the threshold and the number of segments are chosen on BIC. The fit is offered only when it beats the best plain rate for the counter's row (a constant, or a constant plus one level) by 2 log n. The counter's inflow is then written as `1 x A` with that table effect. The same rate is offered as a move A -> B for every measured B in the same unit (a move needs both ends in one unit). The plain flows touching A and B are refitted under the floors (floor._refit), floor.apply runs again, and the move is kept when combined's judge (judge.score) prefers the model by more than log T. | 5cdb3b2 | `structures/counted.py`, called last in `__init__.identify` (after controller.apply) | copy `counted.py`, which needs scipy's `nnls`, floor.py's `_refit`/`apply` (or an identity for the refit) and a judge with `Data` and `score`. Call `counted.apply(result, stocks, run, opts)` on the final answer. It is inert where no counter has a binding threshold effect, and on counters with moves (e.g. `responses_total`, `errors_total`). |

Found on 310 (pool job 263): `outside -> oom_kills_total = 1 x ready x table(mem)` and `ready -> pending = 1 x ready x
table(mem)`, with none-short's table points `[194.95, 0], [480.007, 0], [480.67, 0.0063], [481.54, 0.0145],
[586.6, 1]`. The truth's table is 0 at 480 and 0.3 at 512, so its slope over that range is 0.0094/MiB; the fitted one
is 0.0095. Unit test: `tests/test_structures_counted.py` (a counted move above a threshold is found with its table; a
counter fed by a plain rate is left alone).

## After (pool job 263, commit 5cdb3b2, node2 and Mac workers)

`uv run sdlab-ladder submit --strategies structures --cases 310-k8s-memory-oom --variants none-short,none-long,counts-short,counts-long --priority 400 --by structures-310 --check-tree strategies`,
`uv run sdlab-ladder job 263 --wait`: 4 fail.

| variant | before | after | parts now right | still wrong |
|---|---|---|---|---|
| none-short | FAIL 12/23 | FAIL 15/23 | ready -> pending, the effect, oom_kills_total | outside -> mem (unachievable as scored); mem -> outside; retries split (base candidate); outside -> pending (a constant) |
| none-long | FAIL 12/23 | FAIL 15/23 | ready -> pending, the effect, oom_kills_total (the `ready <-> desired` spurious moves are gone) | outside -> mem; mem -> outside; HPA whole flows (desired has the floor's junk); pending -> ready missing; ready -> outside 9-11% off |
| counts-short | FAIL 10/23 | FAIL 11/23 | outside -> pending [pending] | the kill move found (error 0.30, allowed 0.10: the table is fitted on Poisson-noisy mem, so it is biased by errors in variables); retries split; a hidden chain into mem |
| counts-long | FAIL 7/23 | FAIL 7/23 | (the kill move found, error 0.21) | cpu links, pending / ready rows, mem |

## Proposed, not made

| type | mechanism | how another strategy adopts it |
|---|---|---|
| scorer: hidden readers (harness) | evaluate a found whole flow, or one compared as a whole, that reads one of the found model's own hidden stocks on that model's `inferred_levels` (or on its simulated hidden level). Without that, rung 310 cannot pass. | harness change (sdlab/ladder/score.py, sim.py); needs the user's approval (rule 5) |
| hidden-ramp | mem's inflow needs a hidden integrator with a constant inflow (1 MiB/step) whose drain carries the same table effect as the counter (the reset): offer, for a row whose residual trends, a hidden stock H with `outside -> H = c` and `H -> outside = H x table(X)` reusing counted.py's table | after counted.py; judged on combined's judge |
| ratio-link | `2 x inflight / max(1, ready)`, a per-unit reading (MiB per pod from requests per pod): offer X / max(1, Y) columns for pairs of measured stocks to a row's link search | the strategy's term library |
| counter-censoring guard | the base's `censored` candidate used `oom_kills_total` (0 for most of the run) as a floor for the queue, inflight and retries rows, and the retries split was lost. A counter should not be offered as a censoring floor for other rows. | vendored combined `censored` candidate |
| eiv-table | on counts the table is fitted on the measured, noisy X, so it comes out flat. Refit its knots by errors in variables (eiv.py instruments) or on the Kalman likelihood | counted.py's `_fit` |
