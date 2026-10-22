# 310 (k8s-memory-oom): structures, the noise-free and counts variants

**Status (2026-10-22, round 2, agent structures-310-r1): none-short and none-long PASS, 26/26 parts each (pool job
287, commit 498c81d, Mac workers). counts-short fails (12/23, data-limited, not a target). counts-long fails (9/23,
borderline at best, not reached this round).** The found hidden stock `h_mem` is matched to the truth's `leak`
(R^2 1.0000, level = 0 + 1.000 x leak), so mem's block is scored as a stock, not as a time schedule: these are passes,
not "fits". I held the structures lock for the work and released it after the commit.

## Before and after

`uv run sdlab-ladder show 310 --strategy structures --variant V` (before: code 5cdb3b2, job 263, re-scored by the
hidden-stock scorer 198baf2, so the parts are out of 26 on the none variants):

| variant | analyse | before (5cdb3b2) | job 286 (7e7ed5c) | after (job 287, 498c81d) |
|---|---|---|---|---|
| none-short | not analysed* | FAIL 15/23 | **PASS 26/26** (node2) | **PASS 26/26** (Mac, 114 s) |
| none-long | not analysed* | FAIL 15/23 | FAIL 20/26 (node2: no `pending -> ready`, no kill move) | **PASS 26/26** (Mac, 274 s) |
| counts-short | data-limited | FAIL 11/23 | FAIL 11/23 | FAIL 12/23 |
| counts-long | borderline | FAIL 7/23 | FAIL 7/23 | FAIL 9/23 |

\* `analyse` says "a truth this analysis does not cover". I judged achievability as kalman_lna's 310 doc does:
counts-short has 3 kill steps in 300 (`oom_kills_total` reaches 6), so the kill rate's relative SE is about 40%
against the allowed 10%: data-limited. counts-long has 44 kill steps (91 kills), relative SE about 10.5% against
10%, and mem reaches 682, past the table's 512 and 560 corners: borderline at best.

## Diagnosis (rule 4b), from `diff` at 5cdb3b2

- **mem's block (none-short and none-long): a method fault.** `outside -> mem` reads the hidden leak and
  `inflight / max(1, ready)`; the answer read mem's change off queue, retries and ready. Since 198baf2 the scorer
  credits a found hidden stock that matches the truth's, so this is achievable as a stock.
- **requests block (none-short): a method fault.** `retries -> outside = max(0, -0.41 - 0.0002 retries)` never
  moves, nothing into retries, no `retries -> queue`: the base (combined's `censored` candidate) put a floor on
  `oom_kills_total` into retries, and no later stage repaired the row. A guard against a counter as a censoring
  floor (tried, reverted) made the vendored censored candidate run away and combined pick `lna_pulses`, much worse
  everywhere (15/26): the base on this case is weak in every candidate, so the repair belongs at the end.
- **pending's inflow (none-short): a method fault.** `outside -> pending = 0.0407` was a one-piece inflow profile,
  which floor.py held as a profile; the true row is exactly the floored gap max(0, desired - pending - ready) on the
  steps where it binds (checked: max |error| 1e-4).
- **pods block (none-long): a method fault.** desired's HPA controller was not written because the answer had
  spurious moves `desired <-> ready` (controller.py refused any stock with a move), and the OOM move went
  `ready -> desired`. With them gone, the answer still lacked `pending -> ready`, so the OOM move could not be placed;
  on node2 (job 286), where the time-capped search differs, `pending -> ready` also did not pay on its own until the
  kill move was in.

## Fixes kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| hidden-integrator row (ledger type 8, as a stock) | **A row reads a hidden integrator H and per-unit columns.** For each measured non-counter stock S with a declared outside inflow (estimate) whose row the answer leaves more than 100 quanta from exact, and whose flows are all readable (constant, proportional, linear, table effects): candidate columns are the other levels and inputs and `X / max(1, Y)` for every pair of measured non-counter stocks. H is filled from outside at 1 a step and drained at d_t x H, d_t a constant (24-point log grid, then golden section) or a table effect the answer already carries (counted.py's threshold tables); H is linear in its start, so the row reads two columns per drain (response to the inflow, psi, and to the start, phi). For each drain the row is seeded with [1, S, psi, phi] and the other columns are chosen by forward selection (each must gain 2 log n on the residuals' effective length, n (1 - rho) / (1 + rho)). It is kept only when (a) it beats the answer's row by 2 log n in BIC, (b) it beats the same search seeded with [1, S, phi] (the start transient alone: a constant drain's integrator is a constant plus that transient, so it never earns a stock) by 2 log n, net of its extra numbers, and (c) its start is at most n (a start beyond what the inflow fills over the run is a transient standing in for a misfit). Written as `outside -> S` (an expression with the ratio columns, or a linear rate), `S -> outside = k S` where the boundary has that side, `outside -> H = 1` and `H -> outside = 1 x H x table(X)` (or `a x H`); H's level goes out as `inferred_levels`. | 7e7ed5c | `structures/hidden.py`, called after counted.py | copy `hidden.py` (needs only numpy and a quantum: judge.quantum). Call `hidden.apply(result, stocks, run, opts)` after any stage that writes table effects. Synthetic test: `tests/test_structures_hidden.py` (a table-drained hidden stock and a per-unit column found; a constant drain is not a stock; an exact row left alone). |
| row repair (ledger type 9) | **Unexplained rows repaired with the plain moves and outflows they lack.** Bad rows: measured non-counters, every flow readable, residual rms above 100 quanta. Free flows: the plain flows on a bad row that are not on a side declared fixed (`input` / `measured`); their numbers are refitted jointly on every row they touch by active-set least squares (a flow's columns count only where its rate is positive; started unfloored). Candidates, one at a time: a proportional move A -> B in one unit with both ends bad rows (a move repairs two rows; never out of a counter), or a bad row's proportional outflow on a declared side. BIC over every readable row (rows the candidate does not touch cancel). A candidate is kept when it gains 2 log n; the repair is kept when it beats the answer's own rows by 2 log n. | 7e7ed5c, 498c81d | `structures/repair.py`; called before counted.py, inside counted.py on each candidate move (after its floor refit), and last | copy `repair.py` (with hidden.py's `_amount`). Call it on the final answer, and inside any stage that inserts a flow, before that stage judges. Test: `tests/test_structures_repair.py`. |
| controller replaces spurious moves | controller.py wrote a controller form only for a stock with no move. Now a stock with moves gets its form too when the form alone reproduces the stock's whole change on every step, given at least 10 steps of change (on a few steps some form always fits); its moves go with its fitted flows, and the other stock's row is left to the repair. | 7e7ed5c | `structures/controller.py` | the same test in any controller detector: exact on the total change means the moves on the stock are spurious |
| one-piece profile is a constant | floor.py held any outside inflow written as a profile (`inflow` segments) as fixed. A one-piece profile is a constant: its side may be refitted under the floor (the stale profile is dropped when the numbers are set). | 7e7ed5c | `structures/floor.py` (`_profile`) | wherever a stage skips "profiles", count pieces |
| counted move with its rows repaired | counted.py's candidate move A -> B is judged after its rows are repaired (repair.py), so a move the rows also lack (none-long: `pending -> ready`) is added back in the same candidate | 498c81d | `structures/counted.py` | as above |

Kept from round 1: counted.py (5cdb3b2), the counted move with a threshold effect.

Found on 310 none-short (local runs at the same code as job 287; `sdlab-ladder show` gives the stored ones): the request block exact (`queue -> retries = 0.08 queue`, `retries -> queue =
0.6 retries`, `retries -> outside = 0.4 retries`), `outside -> pending = desired - pending - ready` (floored),
`ready -> pending = 1 x ready x table(mem)` with its counter, `outside -> mem = 75.49 + 1.00003 x inflight / max(1,
ready) - 0.042 x oom_kills_total + 0.49997 x h_mem`, `mem -> outside = 0.49998 mem`, `outside -> h_mem = 1`,
`h_mem -> outside = 1 x h_mem x table(mem)`. On none-long the mem inflow is `75.03 + 0.99974 x inflight / max(1,
ready) + 0.50007 x h_mem` (h_mem starting at 0.96).

## Risks and what is not done

- **No regression run** (the plan: current rung first). hidden.py and repair.py run on every answer; both are gated
  (100 quanta of residual, 2 log n gains, the transient baseline, both ends bad), and the counter guard on
  censored was reverted. combined2 saw a looser repair trigger hurt its 310 counts-long (d363245); my repair moved
  structures' counts-long from 7 to 9/23, but other rungs are untested.
- **Machine dependence:** structures' own search has a wall-clock cap, so node2 and the Mac start from different
  answers (job 286 none-long). The fix in counted.py made node2's answer pass when re-run locally from its stored
  flows; job 287 ran on the Mac only.
- The junk term `-0.042 x oom_kills_total` in none-short's mem inflow (a counter's level standing in for the table's
  small misfit) is within tolerance. Excluding counters as readers would remove it; not done.
- counts-long: cpu's links, the pods block and mem are off (9/23); the kill move is 21% off against 10% (an
  errors-in-variables fit of the table, or a Poisson-weighted one, is the next step: `eiv-table` below).

## Proposed, not made

| type | mechanism | how another strategy adopts it |
|---|---|---|
| counter-censoring guard | no censoring floor on a counter's level. Tried in the vendored censored candidate: on 310 that candidate then ran away and combined chose lna_pulses (none-short 15/26), so it needs the downstream repair in place and a regression run first | vendored combined `censored` candidate |
| eiv-table | on counts the table is fitted on the measured, noisy X, so it comes out flat. Refit its knots by errors in variables (eiv.py instruments) or on the Kalman likelihood | counted.py's `_fit` |

## Round 1 (2026-10-21, agent structures-310, commit 5cdb3b2, job 263)


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
