# Fix ledger: the kubernetes climb, rungs 307-317 (noise-free and counts variants)

**Status:** first written 2026-10-21 for 307-310. Extended 2026-10-22 to rung 317, with the store read at
2026-10-22 22:40Z (`sdlab.ladder.store.latest`). The climb has reached 317 and finished round 1 there. **Rungs 307-316
pass** on their achievable variants (details below), and **317 does not**.
**Plan (the user, 2026-10-21):** climb kubernetes 307-317 on none-short, none-long, counts-short and counts-long only,
using the top 5 strategies (combined2, milp, structures, kalman_lna, engine_forms). There are no regression runs on
earlier rungs during the climb; one full regression run comes later. Every fix is recorded here so it can be copied
into the other strategies afterwards.
**Sources:** every `docs/research/fixes/30[7-9]-*.md` and `31[0-7]-*.md` (65 docs, round-2 `-r2` docs included),
the per-strategy round reports, `~/.sdlab/rung-progress.log` (FINAL and PROXY lines), pool jobs 244-375, and the
store. **Scorer changes during the climb** (rule 5, each reported with its flips):
- bab9156: "equivalent" only when proven; new status "fits".
- 198baf2: a found model's own hidden stock is credited (`hidden_match.py`), and a time schedule standing in for
  hidden state is "fits, not robust" (flips: kalman_lna 310 none-short and none-long, pass -> fits).
- 5dca817: a step's rates read the levels with that step's announced injections. Offline re-score of the top 5's
  650 rows gives 7 flips, all up: 312 none-long fail -> pass for all five, and 196 none-long fail -> fits for
  kalman_lna and structures (docs/SATURDAY.md). **The store's 312 none-long rows are not re-scored yet** (score hash
  7cf64498, older than 5dca817), so `status` still shows them as fails until the backlog re-scores them.

## Before and after, rung x strategy

Each cell gives the four plan variants in order: none-short, none-long, counts-short, counts-long. P is pass,
~ is fits, E is equivalent (old scorer), F is fail, T is timeout, X is error. "Before" is the code the rung's agent
started from, and "after" is the pool job named in the fix doc (the latest round). Parts right are given where a
variant fails, when the doc or the store records them.

| rung | combined2 | milp | structures | kalman_lna | engine_forms |
|---|---|---|---|---|---|
| 307 before | PPPP | PPPP | EPFP | PPPP | EEPP |
| 307 after | PPPP (no new fix) | PPPP (no new fix) | **EPFP, not fixed** (lock held by C1) | PPPP (no new fix) | **PPPP** (c0c4b12, job 245) |
| 308 before | FFFF | FFFT | FFFF | FFFF | FFFF |
| 308 after | **PPFP** (b0117e0, job 252) | **PPFP** (3bfb6ff, job 249) | **PPFP** (288841e, job 248) | **PPFP** (938a080, job 251) | **PPFP** (6b0d2c5, job 247) |
| 309 before | FTFF | FFFF | FXFF | FFFF | FFFF |
| 309 after | **PPFP** (2a1db63, job 256) | **PPFP** (5787b7f, job 261) | **PPFF** (13122fe, job 259) | **PPFP** (70bc422, job 254; f9e24d4, job 278) | **PPFF** (740ed95, job 255) |
| 310 before (parts /23) | FFFF 14/21/16/13 (c22e751, job 274) | FFFF 21/21/15/20 (573c5a5, job 273) | FFFF 15/15/11/7 (5cdb3b2) | ~~FF 23/23/9/11 (f9e24d4; schedule = fits) | FFFF 21/21/9/11 (ec6265e) |
| 310 after (parts /26 or /23) | **PPFF** 26/26/16/13 (d363245, job 285) | **PPFF** 26/26/15/20 (cd7383f, 9bbd66a, job 284) | **PPFF** 26/26/11/7 (824f241, job 292, node2) | **PPFF** 26/26/9/11 (423dbb6, job 280) | **PPFF** 26/26/7/11 (7e7bd2b, job 291) |
| 311 before (/26 or /23) | FFFF | FFFF 15/14/14/17 | FFFF | FFFF 14/10/7/12 | FFFF |
| 311 after | **PPFF** 26/26/9/15 (afb19cf, job 301) | **PPFF** 26/26/14/17 (ec2164b, job 297) | **PPFF** 26/26/5/14 (542bc3d, jobs 299, 303) | **PPFF** 26/26/5/17 (082119d, job 300) | **PPFF** 26/26/5/3 (4326b3a, job 295) |
| 312 before (/28 or /25) | FFFF | FTXT 17/-/-/- | FFFF 13/-/-/- | FFFF 20/12/7/12 | FFFX 14/12/-/- |
| 312 after, as stored | PFFF 28/27/5/19 (388d15d, job 323) | PFFF 28/27/14/21 (67c8919, job 320) | PFFF 28/27/7/14 (b6f2b6e, jobs 309, 317) | PFFF 28/27/7/8 (6fd4778, job 321) | PFFF 28/27/7/2 (104ee76, job 318) |
| 312 after, re-scored at 5dca817 | **PPFF** | **PPFF** | **PPFF** | **PPFF** | **PPFF** |
| 313 before | PPPP | PPPP | PPPP | PPPP | PPPP |
| 313 after | PPPP (no fix) | PPPP (no fix, job 325) | PPPP (no fix, job 327) | PPPP (no fix, job 329) | PPPP (no fix, job 328) |
| 314 before | PPPP | not run | PPPP | PPPP | PPPP |
| 314 after | PPPP (no fix) | PPPP (no fix, job 332) | PPPP (no fix, job 335) | PPPP (no fix, job 333) | PPPP (no fix, job 334) |
| 315 before (/12) | FPPP 7/-/-/- | PPPF -/-/-/11 | FPPP 9/-/-/- | PPPP | PPPP |
| 315 after | **PPPP** (54987a4, job 341) | **PPPP** (d44d014, job 339) | **PPPP** (ee94317, job 340) | PPPP (no fix, job 338) | PPPP (no fix, job 337) |
| 316 before (/16) | FFFF 13/13/13/13 | FFFF 12/12/12/2 | FFFF 12/-/-/- | FFFF 12/-/-/- | FFFF 12/-/-/9 |
| 316 after | **PPFP** 16/16/14/16 (6b1c269, job 347) | **PPFP** 16/16/14/16 (f01cf7a, job 352) | **PPFP** 16/16/14/16 (b7a1474, job 357) | **PPFP** 16/16/12/16 (4719544, job 351) | **PPPP** 16/16/16/16 (b20e3cc, job 354) |
| 317 before | TTTT (64b5f36, job 362) | TTFT (64b5f36, job 361) | TTFT (64b5f36, job 360) | FFXT 17/17/-/- (64b5f36, job 365) | TTXX (64b5f36, job 360; X = alarm in numba) |
| 317 after (parts vary by hidden credit) | FFFF 49/76, 64/85, 27/82, 36/76 (9d8bfc0, job 375) | FFFT 44/79, 34/79, 23/79, - (a72bb0d, job 370) | **P**FFF 85/85, 41/76, 23/76, 30/76 (dd9d8d1, job 374) | FFXX 38/76, 17/76, -, - (9d3ca8e, job 371) | FTTT 38/85, -, -, - (2bca23f, job 368) |

`X` on 317 kalman_lna counts and engine_forms counts-long is the runner's alarm firing inside numba (`oefit._sens`),
in effect a timeout.

**Cells fixed in the climb by strategy code: 75.** 307: 2. 308: 15. 309: 13. 310: 10 (2 per strategy; kalman_lna's
earlier schedule passes became "fits" under 198baf2 and were earned again with a real hidden stock). 311: 10. 312: 5
(none-short for all five; none-long's 5 more came from the scorer fix 5dca817, not from strategy code). 313 and 314: 0
(nothing to fix). 315: 3. 316: 16 (engine_forms also passes the data-limited counts-short). 317: 1 (structures
none-short). On 317, 10 cells went from timeout or error to a scored result; one of them (structures none-short) passes.

**Data-limited, so not targets:** 308 counts-short (`analyse` p 0.094), 309 counts-short (p 0.010) and counts-long
(p 0.25), 316 counts-short (p 0.407). `analyse` does not cover the hidden-stock truths of 310, 311, 312 and the
counts variants of 317 ("not analysed"). On 310-312 the counts variants were shown data-limited by measured bounds
that five agents took independently: the Cramér-Rao bound with the truth's knots given (P(kill flow within 10%)
0.22-0.39), Fisher information (relative error 0.20-0.35 against the 0.10 tolerance), and free-knot Poisson ML fits
(the OOM move 11.6-33.5% off). On 312 the node events add their own bound (3 and 14 joins: the delay's relative SE
about 58% and 27%).

## Rung verdicts and what was left partly passed

The gate in `~/.sdlab/rung-progress.log` counts a variant as achievable unless `analyse` labels it data-limited or
unidentifiable. Where `analyse` says "not analysed", the gate keeps the variant as a target, so a FINAL line can say
"all-achievable: none" for a rung the agents' measurements pass. Those rungs were moved on by a PROXY decision (the
agent acting for the user) or by a round-2 re-measurement.

| rung | gate (FINAL line) | verdict used for the climb | why |
|---|---|---|---|
| 307 | 4 strategies pass all four | passed | structures still E/F on none-short and counts-short (lock held during the round) |
| 308 | none passes all four | passed | counts-short is data-limited (p 0.094); all five pass the other three |
| 309 | all four variants excluded | passed (vacuous) | none-* unidentifiable (retries->queue move vs link, p 0.000), counts data-limited |
| 310 | round 2: all-achievable none | **passed by PROXY** (2026-10-22 07:48Z) | all five pass none-* 26/26 with the leak credited (R² 1.0); counts data-limited by the three measured bounds above. PROXY asked for `analyse` to cover hidden-leak truths |
| 311 | round 2: all five | passed | round 2 re-measured the counts bound (free-knot ML 15.4% / 17.2% off) |
| 312 | round 2: all-achievable none | **passed once re-scored**; no PROXY line was written | none-long failed only `outside -> oom_kills_total [as a whole]` (2.018% vs 2%); the truth's own counter failed it too. 5dca817 fixed the scorer and the offline re-score passes none-long for all five. counts data-limited (kill and node-event bounds). The store still shows the old fails until the backlog re-scores them |
| 313, 314, 315 | all five pass all four | passed | |
| 316 | all five | passed | counts-short DATA-LIMITED (p 0.407) |
| 317 | round 1: all-achievable none | **not passed** | structures passes none-short 85/85; nothing passes none-long or counts. `analyse` labels no 317 variant excluded. combined2 judged none-* unidentifiable because the db pool MIN never binds, but structures' none-short pass contradicts that for none-short, so all four stay targets. Counts are probably data-limited on the OOM kills (2-5 kill steps per service on counts-short, 31-39 on counts-long, against 310 counts-long's 44), but nobody has measured it |

## Regressions found and fixed during the climb

- **engine_forms 307 counts-long: ERROR -> PASS** (5630b43, job 276). `reread._table` returned no knot start when
  none lay inside the data range; it now returns None.
- **kalman_lna 309 none-short and counts-long: FAIL -> PASS** (b373e39 and f9e24d4, job 278). Cause A: 065afa3 had
  taken the floored term's readers from `cols`, which drops a stock's own column once its drain is fixed. Cause B: on
  node2 the 310 derived-column search ran out the whole 90 s budget, so the rebuild was lost. A derived round cut
  short by the clock is now undone whole, and the rebuild has its own 40 s budget (`BUILD_TIME`).
- No other regression has been looked for: earlier rungs were not re-run (per the plan). The risks are listed at the
  end.

**The other 40 roster survivors**: none of them passes any plan variant
of 308-312, 316 or 317 (fail, timeout or error). On 313 and 314, 10 and 11 of them pass all four plan variants
(archetypes, gap_prior, shared_noise, sindy, the lna family; z3robust too on 314); on 315 only archetypes, gap_prior,
lna and lna_levels do. The common 313-315 miss is an invented move `caller_inflight -> callee_queue` where the truth
has a link on the callee's declared estimated inflow (26-29 strategies per rung, `diff --summary`). So every fix type
from 308 onward is new to them, except where noted below.

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
  `_counter_rate` and `_table` for exact row readers. `reread._table`'s `best is None` crash was fixed in
  5630b43; copy from that commit or later.
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

### 8. Hidden drive written as a schedule (rung 310; superseded by type 11)

**Superseded.** Since 198baf2 a fitted schedule standing in for hidden state is scored "fits, not robust", and
kalman_lna (423dbb6) writes the integrator as a hidden stock instead (type 11). Kept for the record.


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

### 11. Hidden integrator written as the model's own stock (rung 310; replaces type 8)

- **What:** a measured stock S with a declared estimated inflow whose row its readers leave unexplained reads a hidden
  integrator H that fills at 1 a step and drains by nothing, a constant, or the per-unit fraction of a table-effect
  flow the model already has (310: the OOM kill share, so the leak leaves with the killed pods). Writing H as
  `h0 x P + Q` makes S's row linear. It is kept only where it beats both the model's own sides and the same search
  without H by a BIC margin. No constant drain earns a stock (it would be a fixed curve in time, a schedule). It is
  written as `outside -> H = 1`, `H -> outside` (proportional, with the borrowed table as an effect), S's inflow as
  an expression reading H, and H's levels as `inferred_levels`, which `hidden_match.py` matches to the truth up to
  scale and offset.
- **Used (all five, 2 cells each on 310):**
  - combined2 `hiddenrow.py`, c437a7d (golden section on the drain multiple; BIC gate 2 log n against both).
  - milp `hidden.py` `refine()`, cd7383f, plus `_polish` (the borrowed table refitted on S's row by one value scale
    and one level shift; a 1% slope error had put a spurious constant on `leak -> outside`) and a share test above
    the noise floor (9bbd66a).
  - structures `hidden.py`, 7e7ed5c (psi and phi columns; must beat the start-transient-only search) and 824f241
    (counters are never readers: a running total is a trend that runs away off the run).
  - kalman_lna `rows.py`, 423dbb6 (the integrator's numbers kept and written as a stock, replacing the 30/200-piece
    schedule that became "fits") and 082119d (the switch threshold and drain refitted together on the integrator's own
    row: the leak drain went from 15.9% off to exact on 311).
  - engine_forms `hidden.py`, 7e7bd2b (exact data only; smallest exact column set by backward elimination).
  - combined2 98b6324 (312): hiddenrow skips only the stocks that exchange with an existing hidden stock.
- **Cells fixed:** 10 on 310, kept on 311 and 312.
- **Port:** the most self-contained copies are structures' `hidden.py` (numpy and a quantum) and milp's `hidden.py`
  (with its `hinge.py` and `steps.py`). Call it last, after the stage that writes table effects (type 6). Include the
  drain polish and the counter-not-a-reader rule.
- **Others likely to benefit:** all 40 (none passes 310). hidden_transit and loop_transit already search hidden
  stocks and need only the write-out as a stock with `inferred_levels`; effect_hats, inflow_effects and own_tables
  have the table machinery for the drain.
- **Open:** on the counts variants no strategy writes the hidden stock (milp: it wins BIC but explains only 0.33 of the
  misfit above the Poisson floor). The proposed mechanism is a likelihood over the hidden path (a Kalman filter on H)
  or an output-error refit of the hidden row (combined2 310 round 2: drain 0.49-0.53 instead of 0.29).

### 12. Room-limited move: MIN(a X, max(0, b Y - Z)) (rung 311; extended on 312, 316, 317)

- **What:** a same-unit move whose rate is capped by the room left in a pool: `min(0.5 pending, max(0, 4 nodes -
  ready))` on 311. Y is a capacity in any unit and Z an occupant in X's unit. Five implementations:
  - combined2 `capmin.py` headroom offer (2c902c6; beta from quantiles of Z/Y plus golden section), with
    **several-limits** (up to 3, later 4 in 98b6324), **limit-refit** (`minrefit.py`: limits and the block's free flows
    refitted by active-set least squares over the regimes, then backward elimination), **limits-in-repair**
    (`counted._refit_limits`), and **limit-placement** (afb19cf: an offered series is read only by the move it limits).
  - milp `room.py` (ec2164b): every same-unit move against every non-counter ceiling, grid plus least squares plus a
    soft-L1 polish, the best 3 rechecked with the outside flows floored; each arm must bind on 5+ steps; polished after
    every later pass. Also **counted-move-after-room** (the room re-polished with the kill move in and out) and
    **gap-side-unblock** (`hinge.refine` reruns without a side whose gap cannot act).
  - structures `room.py` (542bc3d; trimmed fit, kept on 6 log n), extended in f76b167/b6f2b6e to replace a plain
    stand-in move and reach the rare binding regime (`_free_basis`, `_theta_q`, untrimmed OBJ).
  - kalman_lna capped move (`derived.py` section 4 and `rows._capped`, 082119d): the amount read as the lower bound
    `max(0, dy_T, -dy_X)` and fitted by alternating regimes; on 312 the offered capmin limit becomes a capped column
    the rows read (febd195).
  - engine_forms MIN move from a row pair (`reread._pair`, 4326b3a; exact data only): in the pair's sum the move
    cancels, so the sum is read as linear plus hinges, and each row minus its hinge as `lin + s max(0, min(u, v))`.
    On 312, a rare MIN branch (18e29e8) and "hinge pair is a move" (two equal and opposite hinges on one unit are one
    MIN move).
- **Extensions:**
  - **Rare regime (312):** the cap binds on 1.4-4.6% of steps (7 of 299). The theta grid and the share test take at
    least 5-6 steps instead of 5% of the steps: combined2 `capmin._lo` (f75e454), structures `capmin` (f76b167),
    kalman_lna `capsteps.py` (febd195), engine_forms relaxed pieces (18e29e8).
  - **Fixed pool (316):** a constant capacity less what occupies it, `min(k X, c - d Z)`: combined2 (6b1c269, beta
    grid to 10 x Z's top), milp `room.py` ceiling None with free receiver weight (2846e1f; `max(0, .)` written only
    if the room goes negative on the run), structures `capmin._pool` (58b44f3), kalman_lna `_pool_seed` and the cap
    read off a floored row (0c2e796, 4719544), engine_forms fixed-pool arm and `pool.py` (7cdd811, 6034c4e).
  - **Shared room (317, structures only):** a family of moves `A_i -> B_i` limited by one room shared in proportion
    to demand, `min(k_i A_i, k_i theta max(0, c Y - sum B) A_i / max(1, sum A))` (`room._family`, 942bf2d; found the
    three services' pod starts on none-short, c 4.0016). This is the biggest mechanism the other four lack on 317.
- **Cells fixed:** 10 on 311; part of the 5 on 312 none-short; with type 13, 15 on 316; 1 on 317.
- **Port:** milp `room.py` (needs milp's `hinge.py` and `steps.py`) or combined2 `capmin.py` + `minrefit.py`. For
  strategies with a capmin copy, adding the headroom and fixed-pool columns to the offer is the smallest change;
  structures `room.py` at 942bf2d for the shared room.
- **Others likely to benefit:** all 40 (none passes 311, 312, 316 or 317). All 43 capmin copies can take the
  headroom offer, the rare-regime grid and the fixed-pool column.

### 13. Boundary-forced cross-unit move (rung 316)

- **What:** the user's rule is that a move needs both stocks in one unit. 316's truth moves queries into connections
  (`db_waiting -> db_active`), which no same-unit search can write. All five admit a cross-unit move only where the
  declared boundary leaves no other drawing: A and B are each the only non-final stock of their unit, A has no
  declared outside outflow, and B has no declared outside inflow. Elsewhere the rule stands (312's `nodes -> ready`
  is still dropped). This is the agents' reading of the rule, recorded in each 316 doc for the user to confirm.
- **Used:** combined2 `capmin.forced_pairs` + `one_unit_moves` + a second `sparseblock` run over the joined units
  (6b1c269); milp `Steps.same_unit` (2846e1f, tightened in 2a2e196 after the one-side version offered every queue a
  move into the pool); structures **limited-move** (58b44f3: a move reading the offered capacity between the two ends
  the offer names); kalman_lna `rows.movable` (0c2e796); engine_forms `capmin.forced_pairs` + `reread._bridges`
  (7cdd811).
- **Cells fixed:** with type 12's fixed pool, 15 on 316 (3 per strategy) plus engine_forms counts-short.
- **Port:** `forced_pairs` is about 20 lines and needs only the units and the declared boundary. Apply it where the
  strategy enforces one unit per move; join the two units into one block for row re-readers; refit a limit on both
  units' rows.
- **Others likely to benefit:** all 40 (none passes 316; 42 errors and 13 timeouts there).

### 14. Hidden delay stage: DELAY1 into a measured stock (rung 312)

- **What:** a stock whose declared estimated inflow is a first-order delay of an order: `H' = u - H/tau`, the stock
  gains `H/tau`, and `u = max(0, c + w.X)` reads levels, inputs and the model's own floored terms (312: the order is
  `0.075 x (pending - room)`, tau 2). Its outflow is fitted jointly, often as a floored gap with its own floor
  (`max(0, min(0.05 nodes - 0.1, 0.05 nodes - 0.025 ready - 0.025 pending))`). Kept where it beats both the current
  row and the same search without a stage. Written as the hidden stock `outside -> H -> S`, scored as a hidden path.
- **Used:** combined2 `lagrow.py` (f75e454; tau-bound guard 98b6324) with **two-arm-floor**; milp `delay.py`
  (d0e2b96; drives include each room move's unmet demand); structures `delay.py` (f76b167, b6f2b6e) with
  **subterm columns** (the answer's own `max(0, ...)` terms as readers) and **goal-floor gap**; kalman_lna
  `delayed.py` (febd195; the order read by inverting the delay, chosen on the trimmed one-step error) with
  **two-floor outflow**; engine_forms `delay.py` (18e29e8; the decay read as the fraction x keeps on consecutive
  pairs).
- **Cells fixed:** part of 312 none-short (5) and of none-long's 27/28 (which the scorer fix turned into passes).
- **Port:** structures' `delay.py` or engine_forms' `delay.py` (exact data); for noisy data kalman_lna's
  `delayed.fit`. The core ideas port alone: invert the delay to read its input, and offer the model's own floored
  terms as columns.
- **Others likely to benefit:** all 40 (none passes 312). hidden_transit, loop_transit and delay-aware strategies
  can add "a first-order stage between a drive column and the stock" as one more shape.
- **Open:** not found on counts (node events too few); 317 needs it per service and milp scores its stage at delay
  1.649 against 2.

### 15. Injection-aware rows and expression-aware evaluation (rung 311)

- **What:** two blind spots that showed on the first rung with announced node failures and MIN expressions.
  (a) A step's rates read the levels with that step's injections in, and the row is the change less what was
  injected, so a node failure is not read as flow. (b) The shared `simulate.Model` reads every `expr` rate as 0, so a
  judge or row check running it does not see MIN, controller or room flows.
- **Used:** combined2 `hinge.columns` Levels/`.inj` and `hinge.delta` in every pass, plus `expr_amount` (2c902c6);
  structures `steps.injected/adjust` in every post-stage and `exprs.py` in the vendored judge (542bc3d; the counted
  OOM move then pays); engine_forms `hidden._change` in the re-read checks (4326b3a). The scorer got the same fix in
  5dca817 (312 none-long).
- **Cells fixed:** counted with type 12 on 311 (they were needed together).
- **Port:** any `hinge.py` copy: `np.diff(levels[x])` -> `hinge.delta(levels, x, n)` and rates read `cols`. Any
  judge on `simulate.Model` after writing expressions: swap in an expression rate (structures `exprs.Rate`). Post
  stages that return early on `opts['injections']` (switch.py, controller.py, tracker.py, quantized.py copies) should
  adjust instead.
- **Others likely to benefit:** every strategy that writes MIN or controller expressions (all 43 capmin copies) and
  every one with injection cases (35 cases have announced injections).

### 16. Best-subset row and block re-read (rungs 311, 312, 315, 317)

- **What:** greedy forward stepwise misses rows whose truth is a small set among many collinear proxies (fan-out
  callees, fast equilibria, crossed moves between co-driven stocks). Each row is read by exhaustive or batched best
  subset (at most 4 columns), the terms are joined into moves (source row -A, receiver +A) and outside terms on
  allowed sides, fitted together (NNLS or active set), pruned while the block stays exact (outside terms first, so the
  conserving move is preferred), and the block is replaced only when exact and far better than the pick.
- **Used:**
  - structures `rebuild.py` (542bc3d, 311 cpu's equilibrium), `moves.py` (f76b167, 312: rows rebuilt together and
    paired), `rowwise.best_subset` in the search seed (ee94317, 315), and the every-row rebuild with each row refitted
    without its 2 worst steps (c6fa9ea, 942bf2d, 317: 20 crossed rows became the truth's flows).
  - combined2 `sparseblock.py` (54987a4, 315: lna's crossed callee moves); second run with a held MIN (6b1c269,
    316); `_rare` (9d8bfc0, 317: a block linear on all but at most 1% of steps is re-read on the rest; none-short
    31 -> 49/76).
  - combined2 `blocks.compose` (7f6fb41, 312): a unit block some other candidate explains exactly replaces the pick's.
  - milp `room._reread/_settle` and `tidy.py` (2846e1f, 2a2e196, f01cf7a, 316): every estimated inflow re-read by
    exact best subset.
  - engine_forms per-step exactness (7cdd811, 316): an exact reader judged by rms let a slope that shows on 1 step
    in 300 be dropped; every step must now hold within the rounding.
- **Cells fixed:** structures 311 none-short (1), 312 none-short (1), 315 none-short (1); combined2 315 none-short (1);
  part of 316 for milp and engine_forms (2 each); 317 none-short for structures (with types 12 and 17).
- **Port:** structures `rowwise.best_subset` is self-contained and numpy-only; combined2 `sparseblock.py` needs about
  30 lines of hinge/counted helpers. Batch the subset fits (type 10 batched-subsets, engine_forms subset-screen) or
  wide records hit the C(38,4) = 73,815 wall.
- **Others likely to benefit:** the earned family (matrix-style fits give exact but crossed rows on wide records),
  archetypes and combined2's own `_vendored/structures` copy, the lna family and the exact solvers (as a pre-screen).
  The 313-315 invented `caller_inflight -> callee_queue` moves in 26-29 strategies are this blind spot plus type 18.

### 17. Spurious flows must earn their place (rungs 310, 312, 316, 317)

- **What:** after the flows are placed, each optional flow is tried removed with the rest refitted, and it stays
  removed where the rows' BIC does not rise by the margin. Declared sides are exempt.
- **Used:** structures controller replaces spurious moves (7e7ed5c, 310) and coflow-earn (f76b167, b6f2b6e, 312);
  combined2 `minrefit._earn` (2f4462c, 312: a junk limit held the pods' start at 0.508/4.02), `idle_dropped` and
  `one_unit_moves` (98b6324); milp `refit.pair_drops` (d44d014, 315: two cancelling counter terms only leave
  together) and `tidy.py` step (2) (316); engine_forms `earn.py` (6034c4e, b20e3cc, 316 counts-long: cancelling
  caller -> callee moves); kalman_lna simpler-row margin (4719544, 316: a plain row with fewer numbers needs 2 log T,
  not 6 log T); structures limit guards with a trimmed gain (c6fa9ea, 317).
- **Cells fixed:** milp 315 counts-long (with net-gross, type 19), engine_forms and kalman_lna 316 counts-long (with
  the pool seed), structures 310 none-long, 312 none-short (coflow-earn). This is the ledger's earlier
  **flow-earn** proposal (308-structures), now made.
- **Port:** engine_forms `earn.py` (self-contained apart from the change simulator) or milp `tidy.py`; pair-drop is a
  few lines in any backward elimination.
- **Others likely to benefit:** the 26-29 strategies that invent caller -> callee moves on 313-316, and every
  strategy whose counts fits carry tiny noise-fit extras (kalman_lna 314/315 counts still pass with them).

### 18. Conserving drawing preferred (rungs 312, 316, 317)

- **What:** the user's rule: when a link-plus-drain and a move are algebraically the same, the conserving move is
  preferred. milp `conserve.py` (a72bb0d, 317): a link `k S` on `outside -> D` beside S's proportional drain g >= k
  becomes the move `S -> D` at k with the drain g - k; an own-level gap `-k D` on D's inflow joins D's drain. Applied
  only where exact. engine_forms "hinge pair is a move" (18e29e8, 312); kalman_lna closed-receiver move (4719544,
  316: what a closed receiver gains from a same-unit stock is a move, its source's drain fixed at the moves' total).
  The 313-315 docs give the opposite check for links: a move is preferred over a declared outside side only when its
  source row is reproduced with the move's outflow (summed over every callee).
- **Cells fixed:** 0 counted alone (milp 317 none-short: 9 flows right, cell still fails); part of engine_forms 312
  and kalman_lna 316.
- **Port:** copy milp `conserve.py` (needs hinge `_env`, `_plain`, `_rate`) and run it last.
- **Others likely to benefit:** all; the user decided this rule (2026-10-21) and only milp applies it generally.

### 19. Count-noise weighting and share tests (rungs 310, 315, 316)

- **What:** gates and weights on counts data measured against the Poisson floor, not the raw misfit. milp
  noise-floor share (9bbd66a, 310), **net-gross** (d44d014, 315: the Poisson scale from each flow's net amount, not
  the sum of its terms' sizes; two cancelling ~1830-a-step counter terms had flattened cart_queue's weights), and
  the noise-aware room share gate (2a2e196, 316: the right room won by 1711 BIC but had share 0.353 < 0.5; 1.29
  after). milp effect guards (d0e2b96: quiet rows and a materiality floor).
- **Cells fixed:** milp 315 counts-long (with pair-drop), milp 316 counts-long.
- **Port:** any share gate: subtract the expected count noise first. Any `sqrt(amount)` weight: use net amounts.
- **Others likely to benefit:** every strategy with a counts likelihood or share gate (effects.py SHARE copies,
  kalman_lna's Poisson scale, combined2/structures counts weights); needed for the deferred noise round.

### Additions to types 0-10 (rungs 310-317)

| type | fix | rung, strategy, commit | what | cells |
|---|---|---|---|---|
| 0 boundary | input-side-held | 310 combined2 c437a7d | `hinge.allowed_sides` never refits a side declared only `input` (the floored refit had made queue's inflow `0.89 traffic - 0.56 queue`) | 0 |
| 0 boundary | input side fixed | 312 kalman_lna febd195 | rebuilt rows hold the 1 x input flow and subtract it | 0 |
| 0 boundary | limit-series-not-input / series-not-input | 311 combined2 f6ac855; 316 structures d7cfa79 | an offered capacity series is never a declared measured input | 0 |
| 0 boundary | per-side split | 316 engine_forms 7cdd811 | a side declared n times with exactly n plain terms becomes n flows | 0 |
| 0 boundary | declared last | 317 structures 7959beb | a declared side later stages dropped is filled again at the end, at its fitted 0 where the data give it nothing (84 -> 85/85) | 1 |
| 2 controller | switch-final-partner | 312 combined2 388d15d | a final counter is a partner like any other when the switch drops moves | 0 |
| 2 controller | few-event controller | 317 milp bb82235 | 3-4 events accepted when the whole rule misses no step (cart's HPA) | 0 |
| 3 floored | one-piece profile is a constant | 310 structures 7e7ed5c | a one-piece outside profile may be refitted under the floor | 1 |
| 3 floored | hinge reread | 311 kalman_lna 082119d | floored-reader subsets refitted on their own active steps (true readers from rank 108 to 1) | 1 |
| 3 floored | gap-reader-fallback | 312 milp d0e2b96 | above MAX_READS a gap uses its own-unit levels only | 0 |
| 3 floored | two-arm / two-floor / goal-floor | 312 combined2 f75e454, kalman_lna febd195, structures b6f2b6e | `max(0, min(arm1, arm2))` outflows: a threshold with its own floor | 0 |
| 3 floored | unbound floor | 316 engine_forms 7cdd811 | `max(0, .)` written only where it binds on the run, so the model is not "fits" | 0 |
| 5 capmin | limit-receiver-unit, limit-sign-kept | 312 combined2 f75e454 | a limit's receiver has the source's unit; it must still take from its source after the refine | 0 |
| 5 capmin | limit guards (trimmed gain) | 317 structures c6fa9ea | one limit per source; refused when its gain without the 2 worst steps is below the price | 0 |
| 5 capmin | pool-min kink | 316 structures 58b44f3 | a pool offer must beat the plain offer's kink by log T | 0 |
| 6 counted | counted-replaces-schedule | 310 milp 9bbd66a | a counter's stepped inflow may be replaced, the schedule charged per piece | 0 |
| 6 counted | onset knots | 311 engine_forms 4326b3a | the table screen gets knots at the counter's onset (mem above 480 on 26 of 299 steps) | 1 |
| 6 counted | stand-in move and free knots | 312 structures b6f2b6e | a plain move into a counter is a rate to beat, not a blocker; inner knots refined | 0 |
| 6 counted | joint polish with tables | 312 milp 67c8919 | table heights refitted with the gaps, rooms and plain flows (23 -> 27/28 on one program answer) | 0 |
| 7 derived | weighted threshold refit, duplicate-switch guard | 311 kalman_lna 082119d | rows reading a switch weighted by 1/SSE; a second switch needs 5% of the range | 0 |
| 7 derived | derived columns scale with size | 317 kalman_lna 9d3ca8e | rounds and capped moves per 12 stocks | 0 |
| 9 repair | block-repair-nnls, bare-trigger | 310 combined2 c437a7d, d363245 | moves a block lacks fitted by NNLS, only on a block with a bare stock | 1 |
| 9 repair | row repair | 310 structures 7e7ed5c, 498c81d | bad rows' plain flows refitted jointly; candidates added on 2 log n | 2 |
| 9 repair | pair-revision, joint-polish | 312 milp d0e2b96 | each MIN re-judged on every step (the program reads a 150-step sample); one floored least squares over all rows | 0 |
| 9 repair | block refit | 317 milp bb82235 | least squares per connected block (program 1386 -> 214 s; lower BIC than the unconverged joint fit) | 0 |
| 10 guards | precision guard (COND) | 311, 312 engine_forms 4326b3a, 18e29e8 | column sets with condition > 1e6 read nothing (collinear counters inflated the tolerance) | 1 |
| 10 guards | rebuild budget | 309 kalman_lna f9e24d4 | a clock-cut derived round is undone; the rebuild has its own 40 s | 1 |
| 10 guards | oefit-guard, refit-guard widened | 312 engine_forms 104ee76 | every later pass keeps its input on LinAlgError/FloatingPointError (counts-long ERROR -> scored) | 0 |
| 10 guards | step-budget | 312 milp 67c8919 | change points capped before the joint refit (program 528 -> 288 s) | 0 |
| 10 guards | rows budget, Gram ranking | 312 kalman_lna ac5443e | rows TIME 600 s; subsets ranked by a k x k Gram solve | 0 |
| 10 guards | oefit-skip | 316 structures 470e0dd | oefit leaves an answer reading a fixed-pool series alone (it had searched 30 min) | 1 |
| 10 guards | best-so-far | 316 structures b7a1474 | a time-capped search returns its best fit, not None (counts-long already had the 16 flows) | 1 |
| 10 guards | seed-only cross-unit search | 316 kalman_lna 4719544 | cross-unit pairs try only two seeds (counts-short 436 -> 1015 s otherwise) | 0 |
| 10 guards | wide-record budgets + pass deadline | 317 combined2 b3728e6 | above 24 columns: screened capmin candidates, beam hinge search, seen-set lagrow, every pass within the runner's time less 45 s (offer 40 min -> 14 s) | 0 |
| 10 guards | stage budget | 317 structures c6fa9ea, 942bf2d, dd9d8d1 | each post-stage under the timer less 90 s; oefit at most 25% of what is left; counted tries 2 receivers | 0 |
| 10 guards | staged row budget | 317 kalman_lna 9d3ca8e | cheap pass over every stock first, then rich forms by misfit with a time slice | 0 |
| 10 guards | subset-screen | 317 engine_forms 2bca23f | exact()/floored() rank all column sets in one batch and check the best 64 (4.0 -> 0.1 s a row) | 0 |

On 317 the type-10 rows turned 10 timeout or error cells into scored results; with types 0, 12 and 16, one of them
(structures none-short) passes.

### Proposed, not made

| proposal | from | what |
|---|---|---|
| ~~scorer: hidden readers~~ | all 310 docs | made as 198baf2 (hidden-stock credit) |
| ~~scorer: injections in step levels~~ | all 312 docs | made as 5dca817 |
| ~~flow-earn~~ | 308-structures | made as type 17 (engine_forms earn.py, milp tidy.py, combined2 _earn) |
| ~~`reread._table` None check~~ | this ledger | made as 5630b43 |
| capmin-readers | 307-structures | see type 1 (structures 307 still E/F) |
| chain-guard | 309-structures | a hidden chain may replace a measured link only by beating it on the judge |
| ratio-link, counter-censoring guard, eiv-table | 310-structures | `X / max(1, Y)` columns, no counter as a censoring floor, tables fitted by errors in variables |
| Poisson-weighted switch / room / delay fits, two-corner table | 309-312 kalman_lna, milp | for the counts variants |
| hidden-row output-error refit | 310-combined2-r2 | mem's drain on counts 0.29 -> 0.49-0.53 (downstream of the data-limited kill fraction) |
| hidden-path likelihood | 310-milp-r2 | a Kalman filter on H so the hidden stock is written on counts |
| headroom beta price | 311-combined2 | charge the headroom limit's extra number (weak limits offered first on counts-short) |
| coefficient / condition guard or ridge in row refits | 310/311 engine_forms, kalman_lna | counts pods blocks blow up (`outside -> pending = -1.5e12 x pending`) |
| zero-term prune, noise-share prune | 314-combined2, 314/315-kalman_lna | float-floor constants and noise-fit extras that still pass |
| shared-room limit for the other four | 317 combined2, milp, kalman_lna, engine_forms | type 12's family form (structures 942bf2d) |
| gap flows with blocked stocks / many readers | 317-milp | `hinge.refine` stops at "a flow cannot be evaluated" when any flow reads a hidden stock; pods sides have 9 readers against MAX_READS 4 |
| hidden and delay stages per service | 317 all | several leaks, each drained by its own table, and the provisioning DELAY1 |
| per-step budgets on oefit and floor | 317-engine_forms, 317-structures | oefit's BUDGET counts steps, not stock-steps; floor.apply takes 661 s on 2000 steps |
| work budgets instead of seconds | 312-kalman_lna, 312-milp | results should not depend on the machine (node2 is up to 3x slower; HiGHS stops on a 60 s limit) |
| runner: SystemError at the alarm is a timeout | 317-engine_forms, 317-kalman_lna | harness; the X cells on 317 are really timeouts |
| analyse coverage of hidden-stock truths | 310 PROXY | so the gate itself labels 310-312 and 317 counts data-limited |

## What is left

- **317 does not pass.** Only structures passes a cell (none-short 85/85). The misses are 310-312's mechanisms per
  service: the shared-room pod starts (structures only), each service's hidden leak and its own OOM table, the
  provisioning DELAY1 and removal rule, the pod gap flows, db_waiting's two query links, and cart's OOM move.
  Every strategy runs near the 1800 s limit on none-long and counts. Next: port structures' approach (every-row
  rebuild, shared room, declared last, stage budget) to the other four, and budget per service.
- 317's counts variants need a measured bound before they can be called data-limited.
- The store's 312 none-long rows wait for the backlog's re-score at 5dca817.

## Open risks for the later regression run

- Every new post-pass runs on every case: hinge, floor, rows, reread, counted, effects, derived, hiddenrow/hidden,
  rowrepair/repair, room/capmin offers (up to 4 limits at as few as 5-6 steps, headroom, fixed pool), lagrow/delay,
  sparseblock (including `_rare`, which has no column-count gate), moves (every-row), earn/tidy/conserve, blocks.compose,
  the forced cross-unit move and the expression-aware judges. Earlier rungs (306-316) were not re-run on the final
  code, per the plan. Each 31x doc lists its own risks; the largest are structures' expression-aware judge,
  engine_forms' stricter per-step exactness (311, 312), milp's tidy.py and net-gross (309-312 counts), and
  kalman_lna's simpler-row margin.
- Run times: milp 312 none-long was estimated at 1100-1300 s on node2; kalman_lna 316 counts-long 1119 s on the Mac
  (1232-1503 s on node2); engine_forms 316 counts-long 1036 s; all against the 1800 s limit.
- Results depend on the machine where searches are capped in seconds (structures, combined2's judge pick, kalman_lna
  rows, milp's HiGHS). structures 310 none-long failed on node2 once (fixed in 498c81d).
- `tests/test_capmin.py::test_copies_identical` fails because strategies now edit their own capmin copies (312).
- The meas (noise) variants are deferred; nothing in this ledger was tested on them.
