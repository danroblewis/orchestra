# Fix ledger: the kubernetes climb, rungs 307-310 (noise-free and counts variants)

**Status:** ledger written 2026-10-21 (store read 2026-10-22 00:45Z). The climb reached rung 310. No top-5
strategy has run 311 since the climb began.
**Plan (the user, 2026-10-21):** climb kubernetes 307-311 on none-short, none-long, counts-short and counts-long only,
using the top 5 strategies (combined2, milp, structures, kalman_lna, engine_forms). There are no regression runs on
earlier rungs during the climb, and one full regression run comes later. Every fix is recorded here so it can be copied
into the other strategies afterwards.
**Sources:** every `docs/research/fixes/30[7-9]-*.md` and `310-*.md` (20 docs), the per-strategy reports for 309 and
310, and the store (`sdlab.ladder.store.latest` / `history`, read 2026-10-22 00:45Z). Pool jobs 273 (milp 310,
573c5a5) and 274 (combined2 310, c22e751) are **queued, not run** (`uv run sdlab-ladder job 273|274`).

## Before and after, rung x strategy

Each cell gives the four plan variants in order: none-short, none-long, counts-short, counts-long. P is pass,
E is equivalent (old scorer), F is fail, T is timeout, X is error. "Before" is the code the rung's agent started
from, and "after" is the pool job named in the fix doc. Parts right are given where no variant passes.

| rung | combined2 | milp | structures | kalman_lna | engine_forms |
|---|---|---|---|---|---|
| 307 before | PPPP | PPPP | EPFP | PPPP | EEPP |
| 307 after | PPPP (no new fix) | PPPP (no new fix) | **EPFP, not fixed** (lock held by C1) | PPPP (no new fix) | **PPPP** (c0c4b12, job 245) |
| 308 before | FFFF | FFFT | FFFF | FFFF | FFFF |
| 308 after | **PPFP** (b0117e0, job 252) | **PPFP** (3bfb6ff, job 249) | **PPFP** (288841e, job 248) | **PPFP** (938a080, job 251) | **PPFP** (6b0d2c5, job 247) |
| 309 before | FTFF | FFFF | FXFF | FFFF | FFFF |
| 309 after | **PPFP** (2a1db63, job 256) | **PPFP** (5787b7f, job 261) | **PPFF** (13122fe, job 259) | **PPFP** (70bc422, job 254) | **PPFF** (740ed95, job 255) |
| 310 before (parts /23) | FFFF 8/14/16/10 | FTFT 13/-/16/- | FFFF 12/12/10/7 | FFFF 13/12/9/11 | FFFF 13/10/9/11 |
| 310 after (parts /23) | FFFF 14/15/16/10 (job 270; job 274 not run) | FTFT 21/-/14/- (job 267; job 273 not run) | FFFF 15/15/11/7 (job 263) | **PPFF** 23/23/9/7 (c058aae, job 269) | FFFF 21/21/9/8 (job 265) |
| 311 | not reached | not reached | not reached | not reached | not reached |

**Cells fixed in the climb: 32.** There were 2 on 307, 15 on 308, 13 on 309 and 2 on 310. Of the 20 target cells on
308 and 309 (none-short and none-long), all 20 pass.

**Data-limited, so not targets:** 308 counts-short (`analyse` p 0.094), 309 counts-short (p 0.010) and 309
counts-long (p 0.25), which combined2, milp and kalman_lna passed anyway. 310 counts-short has only 3 kill steps, so
the kill rate's relative SE is about 40% against an allowed 10%. `analyse` does not cover 310 ("not analysed").

**Regressions the store shows since the fixes (main-line re-runs at bab9156, 2026-10-22 00:01-00:07Z):**
- **kalman_lna 309 counts-long: PASS -> FAIL (13/18), 60 s -> 262 s, on node2.** The pod flows are lost:
  `outside -> pending = 0.033`, `ready -> outside = 0.0028 ready`, and desired's flows are missing. This came after
  065afa3 and c058aae (310's derived columns and hidden integrator in rows.py) and the bab9156 scorer change. Not
  diagnosed. The cell is data-limited, so it is not a target, but it had passed.
- **engine_forms 307 counts-long: PASS -> ERROR.** The cause is `TypeError: 'NoneType' object is not subscriptable`
  at `reread.py:194` (`_table`, from ec6265e). `best` stays None when no knot start lies strictly inside
  `(z.min(), z.max())`. The fix is to return None from `_table` when `best is None`. It is not made here, because
  this task edits no strategy code.
- engine_forms 308 counts-long, flagged as a possible regression in 309-engine_forms.md, **passes** at bab9156.

**The other 40 roster survivors:** none of them passes any plan variant of 308, 309 or 310 (store: fail, timeout or error, and z3exact/z3robust
some not run).
Most pass 307, apart from master_eq, z3exact and z3robust on counts-short and the lna family's equivalents. So every
fix type below from 308 onward is new to them.

## Fix types

Each section covers what the fix is, who used it (rung, strategy, commit), the cells it fixed, how to port it, and
which other survivors would likely benefit. "Families" below means the bases the packages carry. The **earned family**
(a matrix-style earned refit: matrix, matrix_v2, blockwise, censored, coflow_hats, drifting_drain, held_out,
hidden_transit, latent_eras, loop_transit, mass_balance, master_eq, numopt_bo/cma/nm/powell, odefit, own_tables,
periodic_inflows, realistic_flows, realistic_hats, recession, starved_coflows). The **vendored-combined family**
(archetypes; also combined2, structures and kalman_lna). The **lna family** (lna, lna_levels, lna_loops,
lna_products, lna_pulses, lna_stack, gap_prior). The **exact solvers** (z3exact, z3robust, sindy). Plus
common_cause, earned_pieces, effect_hats, inflow_effects and shared_noise.

### 0. Carried in before the climb (306 and k8s-307 C1; listed for completeness)

| type | what | commits | where |
|---|---|---|---|
| boundary-fill | a declared outside flow is always in the model (`fill_declared`) | 1403d66 | every `boundary.py` copy |
| min-form | capmin.py's data-only `MIN(X, theta Y)` offer, restored after the fit | f8883c5, 6e18658 | 43 copies |
| input-kind / one-per-side | a declared `input` side is fixed at 1 x series; same-side outside flows are merged | 284de71, c7cade0 | `boundary.py` |
| oe-row-revise + sens-fit | output-error refit of rows (oefit.py), with derivatives and a 4e8 budget | 08d0733, 1b31e14 | 39+ copies |

These turned 307 for combined2, milp and kalman_lna, so the climb needed no new fix there. They are already in
nearly every survivor.

### 1. Zero-term prune (rung 307)

- **What:** a term of a `linear` rate whose largest contribution over the record is below 1e-4 of the flow's
  largest amount is dropped, with no refit. It runs **before** `capmin.restore`, so a float-floor coefficient on the
  offered MIN series is never written back as a MIN expression, which would make the flow an `expr` that is
  "equivalent" rather than a pass.
- **Used:** engine_forms `tidy.py`, c0c4b12, which fixed 2 cells (307 none-short and none-long, E -> P). It was
  proposed for structures (307 none-short is still E), together with **capmin-readers** (`capmin.restore` enforces
  that only the limited flow's rows read the offered series) and **coflow-earn** (a co-flow `uses` term must pay its
  BIC price, which would fix structures 307 counts-short). Neither was made, because C1 held the lock.
- **Port:** copy `engine_forms/tidy.py` and call `tidy.apply(result, run, o)` just before `_capmin.restore`.
- **Others likely to benefit:** every strategy with a capmin copy that is E on 307 none: the lna family (lna,
  lna_levels, lna_pulses, lna_stack are E on none-long; lna_loops and lna_products on none-short) and archetypes
  (EE). Under bab9156's proven-equivalent rule these cells need re-scoring first.

### 2. Quantized controller: a whole-number stock driven to a target (rung 308)

- **What:** a measured stock whose levels are whole numbers, still on most steps, and changes by exact steps
  otherwise (the HPA's `ready`, later `desired`) has its declared outside sides written as a discrete rule rather than
  a linear rate. Up is `max(0, min(H, ceil(X/a)) - S)` or `1 x (S < T)`, and down is the mirror image. X is any
  measured stock or input (a link, so it may cross units). The threshold comes from the interval that separates the
  move steps exactly. The clamps H and L are written only where the data show them binding. Five independent
  implementations:
  - combined2 `switch.py`: a max-margin LP half-plane over one or two columns, `s x ((c + w.X) > 0)`, plus level
    bounds. Commits 9a5ee5c and b0117e0 (switch before oefit, then again after capmin; `readable=` keeps it off the
    offered series).
  - engine_forms `controller.py`: exact reproduction of every step, last in identify. Commit 6b0d2c5.
  - kalman_lna `tracker.py`: an exact interval search over the breakpoints X_t/m, priced by BIC + 6 log T, skipped on
    lag/scale/filter answers, with a 20 s budget. Commit 938a080.
  - milp `quantized.py`: a sorted-ratio cut. The stock's **row is taken out of the program** before the search and put
    back after oefit, which also cured milp's 308 counts-long timeout. Commit 3bfb6ff.
  - structures `controller.py`: the consistent interval of a, fewest significant digits. Commit 288841e.
- **Cells fixed:** 15 (308 none-short, none-long and counts-long for all five).
- **Ordering rule (part of the fix):** run the controller **after** every pass that rewrites rates (oefit, tidy,
  capmin.restore), or before oefit and again after it. An oefit that cannot simulate `ceil` must never see the
  controller's flows. On 308 none-long, combined2's oefit bent cpu's correct row to absorb the smeared HPA.
- **Port:** the smallest self-contained copies are `structures/controller.py` (numpy only) and
  `kalman_lna/tracker.py` (self-contained). Call it on the final answer. Port milp's row removal where the strategy's
  search is slow on the rows the rule explains.
- **Others likely to benefit:** **all 40**, since every one fails 308 on the HPA flows. The earned family, lna family
  and exact solvers take the numpy-only `controller.py` most easily. The exact solvers (z3exact, sindy) also gain the
  search-time saving from removing the row, as milp did.

### 3. Floored rate: outside sides fitted as max(0, c + w.X) (rung 309)

- **What:** the engine floors every rate at 0. A gap flow such as `desired - pending - ready` or `ready - desired`
  moves nothing where it is negative, and a plain least-squares fit smears it into shrunken pieces or drifts. Each
  declared estimated outside side is refitted as one floored linear rate on its stock's row, with the fit counting a
  rate's columns only where the rate is positive (active-set least squares, Gauss-Newton on the hinge, or censored
  least squares). It is written as an ordinary linear rate, which the engine floors. Five implementations:
  - combined2 `hinge.py` (2a1db63): at most 3 readers; BIC on the row with the SSE floored at 1e-9 of scale; the
    rate must sit at its floor on at least 10% of steps; kept only when the row's BIC falls by more than 2 log n.
  - milp `hinge.py` `refine()` (239a97f): candidates are refitted jointly with the plain moves and the absent
    same-unit moves, stepwise by BIC, and kept when they win by more than 10. Guards in 2eb3828 and 5787b7f: a gap
    must bind on 5 or more steps (for an outflow, only while its stock is nonempty); the answer is unchanged unless a
    gap or move is new; the misfit floor is the rounding/sqrt(6). The guards removed false gaps on 039/044/045
    none-short and 056#6 counts-long, found by re-scoring.
  - structures `floor.py` (3bf52d6, 13122fe): forward/backward BIC whose first step also tries pairs (a gap binds
    only with both sides); offered only when the floored fit beats the same columns unfloored by 2 log n and binds on
    at least 3 steps; accepted on combined's judge by more than log T.
  - kalman_lna `rows.py` (70bc422): each stock's row is rebuilt from the data (best sparse linear, or linear plus one
    floored term, by trimmed least squares). Moves are paired by unit and drain. The gate is BIC + 6 log T. Rows
    needing an undeclared side are refitted without it.
  - engine_forms `reread.py` (740ed95): noise-free only. An exact best-subset row, or a linear part plus one floored
    flow reproducing every step; columns are joined into moves; the block is replaced only if the simulator
    reproduces the rows.
- **Cells fixed:** 13 on 309. Each strategy fixed none-short and none-long, and combined2, milp and kalman_lna also
  fixed counts-long. kalman_lna and engine_forms counted the row rebuild and the re-read under this type.
- **Port:** combined2's `hinge.py` is the most compact (call `hinge.apply` after each switch pass and before oefit).
  structures' `floor.py` needs a combined-style judge. kalman_lna's `rows.py` is numpy-only and also rebuilds moves.
  engine_forms' `reread.py` suits exact data only.
- **Others likely to benefit:** **all 40**. censored already carries `floor.py`/`gap.py` of its own and is the most
  likely to need only wiring. The vendored-combined family (archetypes) can take structures' `floor.py` with its
  judge. The earned family and blockwise, common_cause and earned_pieces (which have their own `rows.py`) are best
  served by kalman_lna's `rows.py` or combined2's `hinge.py`. The exact solvers can take engine_forms' `reread.py`.

### 4. Removing an actuator's smeared moves (rung 309)

- **What:** a stock that holds exactly still on most steps cannot carry a smooth move. When the switch's residual is
  not sparse and quantized, it is retried with that stock's moves to other measured stocks dropped. Each partner's row
  is then repaired with the floored refit, and the change is kept only if no partner's row SSE worsens. structures
  does the same inside `floor.py`, where each candidate is also tried with one of the stock's moves dropped.
- **Used:** combined2 `switch.py` `_try(drop=True)`, 2a1db63, 2 cells (309 none). It removed the spurious move
  `desired -> ready` at 0.08 x desired. structures used it via floor.py in 3bf52d6.
- **Port:** copy the new `switch.py` together with `hinge.py`.
- **Others likely to benefit:** every strategy that ports type 2. Without it, a fit that already put a smooth move on
  the actuator keeps the controller from firing, as seen in structures on 309.

### 5. capmin guards (rung 309)

- **What:** the **source-row guard** accepts `MIN(X, theta Y)` only when X's own row gains more than PRICE x log T
  from it. The **unit guard** requires the MIN's receiver (the move) to have the source's unit. On 309 a false
  `MIN(desired, ready)`, whose kink was really the pod floors, broke the whole fit.
- **Used:** engine_forms `capmin.py`, 740ed95. No cell is counted to it alone, because it enabled the re-read's 2
  cells.
- **Port:** one line plus `_same_unit` in any capmin copy.
- **Others likely to benefit:** all 43 capmin copies, since the offer is identical everywhere. **Check 308 counts-long
  in the regression run:** engine_forms passed it at 6b0d2c5 with a cross-unit offer. It still passes at bab9156.

### 6. Counted flow: a counter read as A x table(X), placed as the move it counts (rung 310)

- **What:** a measured final counter fed only from outside (`oom_kills_total`) counts another flow. Its increase is
  fitted as `k x A x table(X)`. A is a stock of the counter's unit. X is any measured column (an effect, which may
  cross units). The table is monotone piecewise-linear with NNLS heights, and its threshold must bind. The same rate
  is then placed as a move `A -> B` in the same unit (here `ready -> pending`), as `A -> outside` on a free declared
  side, or nowhere, by the BIC of the repaired rows. Five implementations:
  - combined2 `counted.py`: 8720834 (counted flows), a379a3a (joint active-set refit), c22e751 (add a missing move).
  - milp `effects.py`'s **counted-move** candidate (8ff75a7): the move and the counter are fitted as one column.
    Without it, greedy search took `ready -> oom_kills_total`.
  - structures `counted.py` (5cdb3b2): 1-3 segments, capped at 1, kept on combined's judge by more than log T.
  - engine_forms `reread.py` (ec6265e): the counter's change becomes one more column the exact rows may read.
  - kalman_lna `rows.py` **derived-move** (065afa3): a switch column one stock loses and a same-unit stock gains is
    a move, and the counter gets the link.
- **Cells fixed:** 2 (kalman_lna 310 none, with types 7 and 8). Parts gained without a pass: combined2 none-long
  14 -> 21 (job 268, re-score), structures +3 per none variant, and engine_forms none 13/10 -> 21/21.
- **Port:** structures' or combined2's `counted.py` (call it last, followed by the floored refit), or engine_forms'
  `_counter_rate` and `_table` for exact row readers. **Fix `reread._table`'s `best is None` crash before copying**
  (see Regressions).
- **Others likely to benefit:** all 40 on 310. effect_hats, inflow_effects and own_tables already fit tables or
  effect curves, so they can most easily take the counted-move pairing.

### 7. Table effects and derived columns (rung 310)

- **What:** rates of the form `R x effect(X)`, or derived columns `X x max(0, Y - theta)` and `X / max(1, Y)`.
  - milp `effects.py` (8ff75a7): ramps on a 40-quantile hinge grid, polished, with an optional second hinge. Every
    flow the boundary allows is a candidate. Kept on BIC > 10 when the flow moves something on 5 or more steps and
    explains half of one row's misfit. Also **effect-polish** (refit after the gaps, then again),
    **effects-in-amounts** (hinge._amount multiplies by effects), and **table-amounts** in combined2 `hinge.py`
    (8720834).
  - kalman_lna `derived.py` (065afa3): candidates are scored on what they add beyond the row's span; theta is refitted
    by golden section. A flow that is k x one switch is written as the engine's own effect form, so the scorer sees
    its parts.
- **Cells fixed:** part of kalman_lna's 2 on 310 (the per-unit ratio `inflight / max(1, ready)` in mem's inflow).
- **Port:** milp `effects.py` with its `hinge.py` and `steps.py`, or kalman_lna `derived.py` with the c058aae
  `rows.py`.
- **Others likely to benefit:** effect_hats, inflow_effects, own_tables and realistic_hats (existing effect/table
  machinery), and structures (proposed **ratio-link**, not made).

### 8. Hidden drive written as a schedule (rung 310)

- **What:** an inflow row whose readers leave a residual 100 x above rounding may read a hidden integrator
  `h' = 1 - a s h`, or fall back to a piecewise-linear schedule. Because the scorer cannot read a found hidden stock,
  it is **written out as 10-step byTime segments** (on 310 none-short, `outside -> mem = c_block + 1.0 x inflight /
  max(1, ready)` in 30 blocks).
- **Used:** kalman_lna `rows.py` / `derived.py`, 065afa3 and c058aae, 2 cells (310 none-short and none-long, 23/23).
- **Note for the user:** the other four agents report 310 as "not achievable as scored", because a whole flow reading
  the truth's hidden leak cannot be matched by a found hidden stock. kalman_lna's pass shows that a time schedule can
  match it. A schedule fitted to this record cannot predict another record, and it costs complexity. Whether that
  should count as a pass is a scoring question (rule 5). The harness change all four propose would let the
  integrator be written as a stock: evaluate a found flow that reads the found model's own hidden stock on that
  model's inferred or simulated levels.
- **Port:** `_hidden`, `_schedule`, `_with` and `_ratio_hidden` in kalman_lna `rows.py`, plus `derived.integrator`,
  `decays`, `golden` and `basis`.
- **Others likely to benefit:** hidden_transit and loop_transit, which model hidden stocks already but would need the
  schedule write-out. After the harness change, any strategy with a hidden-stock search.

### 9. Joint active-set refit and missing-move repair (rung 310)

- **What:** after a flow is inserted or removed, every linear flow on the touched rows is refitted jointly by
  active-set least squares, with each flow's columns active only where its rate is positive. This alternates with the
  per-row floored refit. A proportional same-unit move the model lacks is then added back one at a time when the
  rows' BIC falls by more than 2 log n. milp's **move-bound** limits a move's own-source number to 0 or above (an
  unbounded start sent `pending -> ready` to -42).
- **Used:** combined2 `counted.py`, a379a3a and c22e751 (the local re-score of job 270's none-long gave 15 -> 21/23;
  job 274 has not run). milp `hinge.py`, 8ff75a7.
- **Port:** `counted._refit_moves`, `_repair_once` and `_repair`, and a lower bound of 0 for (move, reader ==
  source) in any least-squares refit.
- **Others likely to benefit:** every strategy that ports types 3 or 6, since both insert flows and need the rows
  repaired.

### 10. Guards and budgets that keep a cell from erroring or timing out

| fix | strategy, commit | what |
|---|---|---|
| refit-guard | structures 3bf52d6 | if oefit raises, keep its input (309 none-long had errored with a numba SystemError) |
| oefit-guard | combined2 7539346 | `oefit._weights` keeps the previous weights on a non-finite run or an SVD failure (310 counts-long LinAlgError) |
| gap-avoid | milp 8ff75a7 | rerun the gap search without a side whose gap cannot act and whose answer flow is not plain |
| precision-snap | engine_forms ec6265e | a joined term's remainder below the row's tolerance is no flow (a 2e-4 leftover had refused the whole block) |
| prune-budget | milp 8ff75a7, 573c5a5 | refit.prune stops after counted work sum(T x stocks x numbers^2) >= 1.5e10, which keeps the run deterministic |
| one-per-side | milp 573c5a5 | on a declared side holding a MIN beside its plain flow, BIC keeps one |
| batched-subsets | kalman_lna 6fd4778 (312 round 2) | `subsets.py`: every subset of a size fitted at once (scaled Gram stack), scored on its own residuals, the best 3 refitted by least squares, so the choice is unchanged (found models byte-identical on 312); discovery 30-50% faster (312 none-long 527 -> 369 s); docs/research/fixes/312-kalman_lna-r2.md |
| pipeline-order | combined2 2a1db63 | floored refit right after each switch pass, before oefit, so oefit no longer fires; 309 none-long > 300 s -> 252 s |

- **Cells fixed:** 1 counted to pipeline-order (combined2 309 none-long). The rest prevent errors and timeouts.
- **Others likely to benefit:** the refit-guard and oefit-guard apply to every one of the 39 oefit copies (a
  one-line try/except). The prune-budget idea applies to the slow searchers that time out on 309-311 (numopt_cma,
  numopt_nm, sindy, latent_eras, common_cause). One-per-side applies to any search that can put two flows on one
  declared side.

### Proposed, not made

| proposal | from | what |
|---|---|---|
| scorer: hidden readers (harness, needs the user) | all 310 docs | score a found flow that reads its own hidden stock on its inferred levels |
| capmin-readers, coflow-earn | 307-structures | see type 1 (structures 307 still E/F) |
| flow-earn | 308-structures | drop each non-boundary flow in turn and keep it dropped on BIC (declared sides exempt) |
| chain-guard | 309-structures | a hidden chain may replace a measured link only by beating it on the judge |
| hidden-ramp, ratio-link, counter-censoring guard, eiv-table | 310-structures | mem's hidden integrator, `X / max(1, Y)` columns, no counter as a censoring floor, tables fitted by errors in variables |
| Poisson-weighted switch fit, two-corner table | 309/310-kalman_lna | for the counts variants |
| proxy guard | 310-milp | effects that replace stepped flows admitted proxies on none-short's mem row; both tries reverted |
| `reread._table` None check | this ledger | the engine_forms 307 counts-long error |

## Open risks for the later regression run

- Every new post-pass runs on every case: hinge, floor, rows, reread, counted, effects, derived. Earlier rungs were
  not re-run, per the plan. The two regressions above are the first signs of side effects.
- combined2 309 none-long uses 252 s and milp 266 s of the 300 s limit (the timeout is now 900 s since 6be1560).
- milp's HiGHS answers differ between node2 and the Mac (time limits). The structures counts-short spurious move on
  308 was likewise node2-only.
- `tests/test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone` fails, as it did before the
  climb.
