# lna: flows chosen by the likelihood of per-step changes under counting noise

**Status:** done on the ladder (link, loop, co-flow, rework and merge rungs); benchmarks run (below)
**Strategy:** `sdlab/discovery/strategies/lna/` (latest commit `f3270a8`; the examples and generated
benches ran on `186a798`), tests `tests/test_ladder_lna.py`
**Verdict:** adopt the mechanism for structure (the ladder's best strategy by far: 578 pass of 912
against matrix's 378); not as the main line for behaviour: on the examples it is 13.8 points worse
at skill@20 (9 better, 14 worse of 62), neutral on generated models, and 8 points worse on the
realistic cases, losing on hidden stocks, unannounced inputs and self-reinforcing readings.

## Why the existing strategies failed on links, loops and co-flows

The averages of the per-step changes identify only the linear system (one matrix B and the outside
inflows). A move A -> B at k and a link A => B at k plus an outflow of A at k give the same B, so
`matrix` reads every gain as a move whenever the source's drain can pay for it ("equivalent" on 007,
008, 010, 016). With counting noise the data *can* tell them apart: a move's draw leaves A and
arrives in B in the same step (their changes covary at -k A), a link's does not; a co-flow mirrors
in its used stock at ratio `per`; births and deaths add in the variance though they cancel in the
mean. `shared_noise` reads these covariances, but (`sdlab-ladder show 008 --strategy shared_noise`):

- it decides on the residuals of the matrix's own rows, and in the noisy variants those rows are
  already wrong: the fine PELT pass prices pieces as if the noise were homoscedastic, so Poisson
  noise whose size follows the level reads as changes in the inflow (008 counts-short: 11 pieces
  in A, 10 in B), and the pieces swallow the slowly-varying link B => A, which never enters the row.
  The covariance test cannot choose a reading of a gain that is not there;
- the test is a post-hoc binary relabelling with the numbers held at the matrix's (unweighted)
  estimates, so a wrong number or a missing term cannot be repaired by the noise;
- without noise its covariance test is noise on noise: it relabels true moves as links (EE on every
  chain, 003-006, 012-014), while 007 noise-free passes only by that luck.

So the noisy variants were not easier because the noise was used only to *label*, after a fit that
the noise itself had broken.

## What it does

All rows are fitted together, with each flow a shared column (an *atom* with one number >= 0):
inflow, outflow, move, link, growth, drain of c driven by a, goal gap (an inflow c - k x a: one
draw), and moves that use up another stock (co-flows). The likelihood is the linear noise
approximation of counting noise (`likelihood.py`):

    dy_t ~ Normal(V q_t, V diag(q_t) V' + delta I + diag(tau)),   q_f(t) = theta_f z_f(t)

with V the stoichiometry (a co-flow's column carries -per at the used stock), z_f the driver's level,
delta the rounding of levels to whole things (1/6), and tau a variance beyond counting noise per
stock, freed only where fixing it at 0 costs more than the BIC price (otherwise flows that cancel in
the mean could buy variance). An outside inflow and the gap terms that lower it are pooled into one
draw whose variance is their net rate.

Search (`run.py`):
1. noise check: half the variance of the residuals' differences over the counting variance, median
   over steps (counting noise ~ 1; smooth misfit and a few jumps ~ 0). Below 0.2 the data has no
   noise to read and the matrix's result is returned unchanged;
2. a superset of atoms: every pair for up to 4 stocks; beyond, only the entries the matrix found or a
   regression of each row on every level shows (|t| > 2.5); numbers per announced era where an era
   holds at least 50 steps (shorter eras share one set);
3. a fine pass of outside-inflow pieces (PELT on the residual standardised by its counting noise)
   beside every flow; co-flow atoms offered where a drain of c driven by a sits beside a move from a
   (per = drain / move, 0.01-100);
4. backward elimination by BIC (log T / 2 per number, a co-flow's per counts): removals ranked by the
   Fisher information (Wald), the cheapest three refitted; then, until nothing changes, drain <-> gap
   swaps (a gap must win by 2), pieces re-cut afresh (or merged to one constant) and pruning;
   co-flow ratios refined by golden-section search; era numbers merged where the data does not tell
   them apart;
5. the same search without the fine pieces pass; the lower BIC wins (the fine pass can lock in pieces
   that a gap or a level explains: 011);
6. guard: the matrix's model is returned instead if the found one is judged (the main line's judge,
   with the measured inputs) more than 4x worse or not finite.

Measured inputs (`opts["inputs"]`) are rows after the levels: each may drive an inflow (k x input,
its own draw) or a drain of any stock; flows reading one carry `"input"`. 062 (a tank fed by a
measured pump) passes in all four variants.

Limits for realistic models: runs longer than 3000 steps are read at a stride (each step's change
given its start is its own observation); at most 4 era sets (the longest-held labels; the rest
pooled); an early exit to the matrix when even the full superset leaves the changes spreading more
than twice beyond counting noise; and a 40 s search budget (`opts["lna_budget"]`) past which the
matrix's answer is returned. The budget is wall time, so on a loaded machine a run may fall back
where an idle one would not.

**Hooks for variants** (`run.discover(..., hooks=...)`, also `identify(stocks, run, opts, hooks)`):
`data(prev, dy, ctx) -> (prev, dy)`, `atoms(atoms, d, ctx) -> atoms`, `before_search(full, d, ctx)
-> Fitted`, `after_search(cur, d, ctx) -> Fitted`, `flows(flows, cur, d, ctx) -> flows`, run in
that order; `ctx` carries stocks, ids, t, opts, base, unit, final, group, conf, bucket, inputs,
keep, d, at, and `names` (set it when adding rows to prev). With no hooks the output is unchanged
(byte-identical JSON on seven cases before and after the hooks were added, checked by hand; the
test `tests/test_ladder_lna.py::test_identity_hooks_change_nothing` checks identity hooks against
none on three).

Speed (for the ladder's fast iteration): per-step Cholesky in numba (`small.py`), covariance terms as
matrix products, pieces handled as series with their gradient summed by cumulative sums, trial fits
loose and warm-started and polished only when kept, Wald screening of removals. A full ladder run of
lna alone went from 124 s wall for 104 items to about 20-40 s for 472-720 items on the shared
machine (load 60-110); summed discovery time is about 2x matrix's.

## Ladder

At `f3270a8` (`uv run sdlab-ladder run --strategies lna --jobs 4`, then `status`, 2026-10-19 ~03:50Z):
lna 578 pass, 123 equivalent, 211 fail of 912 cells, 0 errors, 0 timeouts (the ladder now includes
the realistic cases; matrix 378 / 121 / 413 but 717 of its cells were stale then, so that column
mixes versions). The rung letters below are unchanged from `186a798`; 062 (measured pump) is PPPP.

**Realistic cases** (the 31 examples as ladder cases, counts short and long, `--cases tag:realistic`,
`f3270a8`): no timeouts (max 106 s on a loaded machine, mean 21 s); skill@20 (in sample, clipped at
-100%) mean 21.3% against matrix's 29.6% (matrix cells possibly stale), median 45.6% against 62.2%;
5 runs better, 8 worse by more than 2 points, 49 the same (most fall back to the matrix). All 62 fail
on equations, as they do for the other strategies.

### At `186a798` (`uv run sdlab-ladder run --strategies lna`, then `status --strategies lna,matrix,shared_noise`, 2026-10-19)

Whole ladder, 720 items: **lna 527 pass, 113 equivalent, 80 fail, 0 errors, 0 timeouts**; matrix
345 / 116 / 259; shared_noise 93 / 74 / 114 with 439 not run (its column is stale for the newer
cases). Letters: none-short, none-long, counts-short, counts-long.

| case | lna | matrix | shared_noise |
|---|---|---|---|
| 007-link | EEPP | EEFF | PPFF |
| 008-link-loop | EEPP | EEFF | EEFF |
| 009-births-and-deaths | EEPP | EEEF | EEEF |
| 010-loop-branch | EEEP | EEFF | EEFF |
| 011-goal-gap | EEPP | EEFE | EEFE |
| 012-rework | PPPP | PPFP | EEFP |
| 013-merge | PPPP | PPFF | EEFF |
| 016-coflow | EEEP | EEFF | EEFF |
| 002 ... 006 chains, 014 split | all PPPP | 002 PPPF, 003 PPPP, others PPF. | E on noise-free |
| 019-announced-era | FPPP | FPFP | FEFP |
| 020-unannounced-step | PPPP | PPFP | EEFP |
| 023-injection | PPPP | PPPP | EEPP |
| 015, 017, 018, 021, 022, 024, 025, 026 | FFFF | FFFF | FFFF |
| 028-038, 057-061 (common cause, twins) | 027 PPPF, 033 PPFF, 059 PPFF; twins FFPP; rest PPPP | mostly PPFF / FFFF | - |

Every noisy variant of the target rungs passes except two, both at the data's limit:

- **010 counts-short (E):** the link B => A (0.05) is worth 0.36 in the log-likelihood on these
  300 steps (fitting the true structure and dropping the link); the BIC price is 2.85. The data
  cannot support it; the linear system found is right.
- **016 counts-short (E):** per is found at 0.39 for a true 0.5; the true per costs 1.6 in the
  log-likelihood, about 1.8 standard errors. The oracle gives no standard error for a co-flow's per,
  so the 10% tolerance applies (see proposed shared changes).

Noise-free variants of 007-011 and 016 are equivalent, and that is the best possible answer: without
noise there is no covariance, and each pair of readings has the same averages and the same number of
flows (a link plus an outflow vs a move; a link B => A vs a move B -> A in the loop; a co-flow vs a
drain of R driven by A while R never runs dry; a gap vs an inflow plus a drain). 009 counts now
passes: the variance separates births from deaths, which the case file calls unidentifiable (true
for the averages only).

Remaining fails (out of these rungs): hidden stocks and effects (not in the atoms), the daily inflow
and pulses (pieces of 5+ steps), floors and caps (not modelled), 033 counts (a common cause: other
stocks' levels stand in for the shared steps; the true structure has a much better likelihood, so
it is the search: backward elimination from the full superset sticks), and the twins' noise-free
variants (left to the matrix).

## Bench: the examples (commit `186a798`, run 2026-10-19T01:38Z, saved as `2026-10-19T01-38-01-191Z-lna.json`)

`OMP_NUM_THREADS=1 ... uv run python tests/bench/evaluate.py --strategy lna --baseline v2.1 --jobs 3`

| | lna | v2.1 (matrix) |
|---|---|---|
| parts | 58.6% (+5.0) | 53.6% |
| mean skill@20 / @100 | 15.8% / 13.2% (-13.8 / -16.2) | 29.6% / 29.3% |
| runs meeting the goal | 10 of 62 | 12 of 62 |
| paired skill@20 | 9 better, 14 worse, 39 same; sign p=0.41, Wilcoxon p=0.13 | |

39 runs are unchanged: there the guard handed back the matrix's model, or lna's equals it in behaviour.
The means are dominated by a few runaways (sd-population long -117838%, -117888 points).

- **Better:** bakery default (+1119 at @20), cloud-credits default/long (+868 / +50), print-shop
  default/long (+569 / +184), kanban long (+13), reservoirs (+5 / +6), supply default (+7). These are
  co-flows and moves read from the shared draws, and drains not biased by spurious pieces.
- **Worse:** hidden-chain (-242 / -1108: a hidden stock is not an atom; the linear model without it
  runs away), population (-262 / -117888: births read as growth of a stock with itself, a
  reinforcing loop that the one-step likelihood accepts and multi-step behaviour does not), webshop
  (-822 / -542), pipeline long (-65; a stock "growing with itself" stands in for its inflow's
  changes), orders (-30 / -52: a gap with two terms and a co-flow on an inflow, outside the atoms),
  supply long (-53), bakery long (-172).
- Run time: 2-12x the matrix on long runs (sd-restaurant long 1141 s, sd-services long 1099 s), as
  each likelihood evaluation is linear in the steps.

The guard (the main line's judge, 4x) does not catch the losses: on hidden-chain, population and
webshop the found model is judged as well as or better than the matrix's (`own` judge), and the
`mean`, `common` and `window` judges also disagree with the grade there. A misfit guard (fall back
when a stock's changes spread more than 0.3 of its counting variance beyond counting noise) was
tried: the losers fit counting noise well (misfit 0), so it only removed gains (print-shop, supply,
kanban); it is off.

## Bench: generated models (commit `186a798`, `--generated 100 --jobs 3`, run 2026-10-19T02:46Z)

200 runs (100 models x 2 lengths). Mean skill@20 -51.8%, @100 -50.1% (each clipped at -100% by
the bench), 6 of 200 meeting the goal. Against the matrix's run of the same pool earlier that day
(`2026-10-19T01-08-56-027Z-dev-n100-matrix-generated-for-earned-pieces-.json`, a slightly older
shared code): matrix -52.4% / -48.1%, 7 of 200; paired at skill@20, lna better in 44 runs and worse
in 56. Neutral within noise; worst motifs for lna: inflow_season, branch, floor.

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (`run["boundary"]`; docs/research/declared-boundary.md).
lna carries its own copy of `matrix/boundary.py` (at `723f72c`, HIDDEN_PRICE 0) as `lna/boundary.py`,
with two additions: `atom_side`/`inside`/`claim`, which read an lna atom's outside end (`in`, `grow`,
`gap`, `link`: an inflow; `out`, `drain`: an outflow; "measured" when it reads a measured input's row,
else "estimate"), and a bound on the guard's refits (`GUARD_FITS`). Wired into lna's own search:

- **declared:** atoms with an outside end on a side, or of a kind, the case does not declare are never
  offered (run.py, after the atoms hook), and `fit` holds at 0 any that a stage offers later (levels,
  loops, products, the gap/drain swaps); the moves between stocks stay in the superset, so an outflow
  from A and an inflow into B that track each other are read as the move by the counting-noise
  likelihood itself (which tells a move from a link plus an outflow, as least squares cannot). The
  matrix's model is guarded (`apply(..., final=False)`) before the judge compares it.
- **not declared:** each outside end (a stock's inflow, or outflow, whatever its form) is a boundary
  claim priced at `CLAIM_PRICE x log T` in lna's own BIC (`fit.prune`, `run.bic`).
- **the answer:** `boundary.apply` after eiv: the guard (declared), and `boundary_claims` listed; the
  least-squares passes (paired moves, priced claims) run only when the answer is the matrix's model,
  not lna's own reading (`searched=True`; on lna's reading they turned 007-link's link into a move).

The same code is in the lna copies of lna_levels, lna_loops, lna_products, lna_pulses and lna_stack;
lna_pulses and lna_stack also keep a pulse only on a declared estimated side (`inside_pulses`). Tests:
`tests/test_lna_boundary.py`. Ladder results: see the commit after this one (in progress).

## Proposed shared changes

- `ladder/oracle.py`: a standard error for a co-flow's `per` (and for a gap's terms) from the
  counting-noise likelihood; 016 counts-short is otherwise judged at 10% when the data gives ~25%.
- `discovery/judges.py` / the main line's judge: a judge that does not let a model's own inflow
  pieces carry its dynamics. On the ladder's short noisy runs the matrix's spurious pieces make its
  models look 1.5-2.4x better than lna's correct ones (`own` judge), so the guard has to be loose
  (4x); the `window` judge ranks them right on the ladder, but not on the examples.
- The ladder's 009 case text says births and deaths are only identifiable as their difference: true
  without noise, not with counting noise (both counts variants pass).

## Open ideas

- Search: forward selection or several starts instead of backward elimination from the superset (033).
- The co-flow cap (the used stock running dry) inside the likelihood: the step's draws are then
  censored (`starved-coflows`); the examples' co-flows bind often.
- Effects as multiplicative atoms (the variance is the flow's rate, so effects are as identifiable as
  links), and hidden stocks as a state in a Kalman filter with the LNA covariance (state-space).
- Use lna only to decide the kinds (move/link, co-flow/drain, gap/drain, births/deaths) within the
  matrix's chosen mean structure, as a lower-risk combination for the examples.
- Third moments (Poisson skewness) for the direction of small moves.
