# Discovery experiments

Every attempt to improve discovery, newest first: what was tried, why, what it did to the numbers,
and whether it was kept. Numbers come from the evaluation CLI (`uv run python tests/bench/evaluate.py`; before the port, `node tests/bench/evaluate.mjs`) unless noted (headline:
mean skill@20; see [DISCOVERY-LOOP.md](DISCOVERY-LOOP.md)). Record failures as carefully as
successes.

## Current state (baseline "start", 2026-10-17)

`identify` (the matrix method), all 11 ground-truth examples at default and long lengths:
**parts 70.1%, mean skill@20 23.3%, mean skill@100 26.1%.**

| example | what it tests | parts (long) | skill@20 (default / long) | notes |
|---|---|---|---|---|
| sd-saas | links, funnel, budget released in eras | 9/10 | 99.6% / 99.8% | hidden "lapsed" stock seen as an outside inflow into trials |
| sd-hidden-chain | two hidden stocks in a row | 3/4 | 97.6% / 97.5% | the hidden stages appear as outside flows (no hidden-stock search yet) |
| sd-hospital | moves, a hidden lab, day/night arrivals | 5/5 | 83.7% / 98.3% | |
| sd-pipeline | plain moves, rework, changing intake | 4/5 | 47.4% / 97.8% | short run too short for the intake's changes |
| sd-reservoirs | releases toward a target level (linear with a negative constant) | 5/6 | 92.3% / 90.6% | |
| sd-kanban | moves, a loop, hidden defects, one-day sprint spikes | 6/8 | 92.7% / 80.7% | spikes bias the backlog row |
| sd-supply | a rate set by a third stock (gap on the shop) | 2/3 | 60.3% / 44.2% | form not in the method |
| sd-orders | goal-seeking orders (inflow falls as stock and orders rise) | 3/4 | 29.5% / -600% | negative-coefficient links read as "drains faster" |
| sd-services | fan-out links between services, a queue and workers | 8/16 | -791% / -757% | links misread; runs away |
| sd-population | a reinforcing loop (births from adults) | 4/7 | -576% / -9499% | found model's loop runs away |
| sd-eras | announced machine changes (internal rates change by era) | 4/4 | -176% / -197% | eras not modelled: one rate for all eras |

## Log

### 2026-10-17: experiment gradient - numbers and structure by gradient descent through a differentiable simulator - NEEDS A COMBINATION (mechanism works; bench held back by the matrix's inflows and the judge)
**Hypothesis.** The matrix method fits one step at a time and only rates linear in the levels.
Writing the simulation itself in an autodiff framework and fitting a candidate structure's numbers
on multi-step error from many start moments (multiple shooting, horizons 5 then 20) recovers what
one-step regression cannot: effect curves, hidden-stock rates, co-flow ratios; and a generous
structure (an effect table of every measured stock on every flow, a co-flow of every measured stock
on every flow), pruned by sparsity during the fit, lets gradient descent choose structure too.
**Building blocks** (branch `exp/gradient`): `sdlab/discovery/diffsim.py` (JAX copy of
`simulate.Model`: rates as c + k.levels per distinct era rate, found inflow pieces, effects as
tables - a linear clamp is a two-point table -, co-flows sharing what a stock holds in Model's order,
floors; softplus floors while training; `to_flows` writes numbers back in their original forms),
`gradfit.py` (masks of what moves, sign-keeping bounds, L-BFGS-B on scaled numbers, curriculum,
group lasso on effect tables, L1 on co-flow ratios and optionally on the structure's own rates,
penalties or total variation on learned inflow pieces, hidden stocks stepped through the data from
a fitted starting level), `structure.py` (the generous candidates; a matrix "s drains faster when a
is high" link becomes a co-flow seed), `hidden.py` (a hidden stock on a move, tried move by move),
strategy `gradient` (`SDLAB_GRADIENT=<attempt>` picks the bench attempt). `tests/test_diffsim.py`:
the JAX simulator equals `simulate.Model` to 1e-9 on 12 random models with every feature (byTime,
inflow pieces, gap/linear/proportional/constant, linear and table effects, co-flows with sharing,
ratio 2), smooth parts off; written-back numbers give the same model. `matrix` unchanged (sd-saas,
sd-eras, sd-pipeline default: zero deltas).
**Mechanism tests** (`tests/test_strategy_gradient.py`, 2000 steps, counting noise):
- (a) a -> b at 0.3 x a x table(c), c moved by unannounced eras: the generous fit (links dropped,
  inflows learned from flat under a total-variation price, L1 on rates) recovers the curve: rms
  error 9.8% of its mean over c's 5-95% range (max 0.032 per unit of a), no leak out of a left;
  skill@20/@100 0.97/0.99. Matrix: no effect form; a -> b 0.081 plus links c -> b, "a drains faster
  with c", a leak a -> outside 0.084 and inflow pieces into a that follow c's eras; its linear
  reading of the curve is 29% off (73% for its flat k); skill 0.36/0.82. **From the matrix's model
  with its inflows fixed, the effect is not found** (skill 0.37-0.47 whatever the sparsity): the
  matrix's inflow pieces into a already absorb what the effect does, and spurious flows sit in the
  local optimum. Only starting the inflows flat and letting the data pull them apart works. From the
  true structure with the table flat at 1 the fit recovers it to skill 0.999 - the simulator and the
  descent are not the limit; the starting structure is.
- (b) a -> hidden (0.2) -> b (0.1): routing the matrix's move through a hidden stock and fitting
  gives 0.196 and 0.104, b's drain 0.2985 (truth 0.3), the leak a -> outside 0.157 -> 0.020. Matrix:
  a -> b 0.06, a -> outside 0.157, b -> outside 0.093. **Not usable on the bench**: the grader (and
  `simulate.Model`) step only the truth's stock ids, so a found hidden stock is silently dropped;
  `hidden.collapse` hands it on as a direct move. Not in the bench attempts.
- (c) a -> b at 0.4 x a using 0.5 kg of c per unit: the matrix's link "c drains faster with a"
  (0.229 x a, ratio 0.52 to the move) becomes a co-flow, refitted ~0.53, the link gone. Matrix: the
  same ratio as a link, no co-flow. Where c actually runs out (restock slowed by an era) the matrix
  is lost (skill@20 -3.3, @100 -20.7; inflow pieces of +-20 absorb the stoppage); the generous fit
  reaches 0.78/0.86 but as an effect of c on the move, not as a co-flow.
**Bench vs v2** (62 runs; v2: mean skill@20 31.6%, skill@100 32.1%, 17 meet the goal, 326 s summed):
- **refined** (matrix structure, every number refitted on 5- and 20-step error, inflows fixed, kept
  only if identify()'s judge prefers it): **skill@20 34.5% (+2.9), skill@100 33.3% (+1.2), parts
  55.4% (=), 18 meet the goal (+1)**; 757 s summed (max 49 s). Better: brewery 79/92 -> 94/98 and
  88/96 -> 96/99 (both now meet), ci long 88/91 -> 93/95 (meets), cloud-credits default -859/-1648 ->
  -38/11 and long -16/54 -> 61/84, print-shop default -547/-2330 -> -241/-243 and long -159/-197 ->
  -117/-87, population long 50/92 -> 83/84, orders default 67/87 -> 82/93, kanban long 55/57 -> 63/78,
  eras long 49/74 -> 59/79, manufacturing long 82/88 -> 88/93, restaurant default 64/59 -> 72/72,
  support-tiers long 42/-13 -> 50/6, clinic-doses long -1106/-2704 -> -838/-1938, webshop default
  -156/-224 -> -123/-170, bakery both (still far below 0), emergency both (+6), moderation long @100
  -249 -> -131, pipeline default @100 -122 -> -83. Worse: hospital 96/98 -> 70/67 and 93/91 -> 75/69
  (both lose the goal), ev-fleet 59/64 -> 42/54 and 76/79 -> 52/69, fishery long 35/25 -> 23/-19,
  restaurant long 68/-39 -> 57/-147, reservoirs default 93/94 -> 90/91, recycling long 93/96 ->
  91/94, sawmill both (-1 to -11).
- **clean** (refined, plus generous-nolinks: effects and co-flows on every flow, links dropped,
  inflow pieces learned from flat under total variation 0.02, L1 on rates, lambda 0.1, 500
  iterations, 500 starts; best of matrix/refined/generous by the judge): **skill@20 34.5% (+2.9),
  skill@100 29.5% (-2.6), parts 57.3% (+1.9), 16 meet the goal (-1)**; 22,365 s summed (max 3,460 s,
  on a machine at load 80-160), i.e. 70x the matrix. Against refined it gains where the generous
  model wins the judge: webshop-stock default -123/-170 -> 23/-139, clinic-doses long -838/-1938 ->
  -256/-741, population default 69/87 -> 88/94, recycling default 73/97 -> 84/88, farm-soil default
  @100 48 -> 80; and loses: recycling long 91/94 -> 63/66 and reservoirs default 90/91 -> 88/88
  (both lose the goal), kanban default 43/32 -> 0/-35, cloud-credits default -38/11 -> -979/-1744,
  bakery default -662/-1844 -> -1009/-10177, sawmill default -352/-131 -> -390/-159, brewery long
  @100 99 -> 87.
**Dependency**: `jax` 0.11.2 (+ jaxlib, ml_dtypes, opt_einsum): 273 MB in the venv, ~1 s import, CPU
only, float64; one XLA thread per process (set in diffsim).
**Verdict: needs a combination; do not adopt as is.** The refined attempt repeats the output-error
experiment's gain on v2 (+2.9 / +1.2, one more run meets the goal) at 2.3x the run time, and repeats
its failure mode: the data judge, which feeds models their own fitted inflow pieces, prefers refits
that track the data's realised noise and then behave worse with the truth's inflows (hospital,
ev-fleet: the truth's own judge error is often higher than the found model's - on the effect
synthetic 0.146 vs 0.138). The mechanism is real - given a starting structure whose inflows do not
already explain the nonlinearity, the descent recovers table effects (9.8% curve error), hidden
stocks (rates within 5%) and co-flow ratios (within 7%) - but on the bench the generous fit mostly
loses to, or is mis-chosen over, simpler models: the effects it keeps on real examples are often
noise-fitting (at 0.1 x the error, the group lasso keeps several 5-30% tables besides the true one even on the synthetic models), dropping all links
removes true ones, and it costs 70x. What would make it pay: (1) a held-out or truth-free judge that
does not reward fitted inflow pieces (exp/held-out-judge), (2) inflow pieces chosen jointly with
nonlinear structure instead of before it (flat start + total variation was the only thing that let
an effect be found), (3) a grader and simulator that step found hidden stocks (initialised from
the model's own estimate), without which hidden-stock recovery cannot show on the bench.

### 2026-10-17: discovery ported to Python (`sdlab/discovery/`) - KEPT
The matrix method, its judge, the grader and the evaluation CLI moved from JavaScript to Python
(numpy; the change scan in numba). Every one of the 42 runs gives the same parts and skill as the
JavaScript (baseline "python" = the last JavaScript best), in 30 s instead of ~2 minutes (CPU 223 s vs
900 s). The JavaScript engine (`identify.js`, `evaluate.mjs`, `identify.test.mjs`) is gone; the
recovery tests are in `tests/test_discovery.py`. From here on, ideas are tried as experiments, each a
strategy on its own branch (docs/DISCOVERY-LOOP.md).
Found while porting the tests: **the pipeline lock fails** since "inflow re-measured after
conservation". The inbox row has always carried a spurious +0.026 x working (read as a link working
-> inbox); the intake's pieces used to be measured beside the row's own, larger, drain, which by luck
put the intake at 6.02 (truth 5.75, tolerance 0.6). Measured consistently with the row's numbers it
is 4.88. Behaviour is unaffected (sd-pipeline long 99%); the test is marked as a known failure and the
spurious term is an experiment target. Also: the change scan at its price of 1 x log n per change
finds chance changes in plain noise (two in a 4-piece test series); at the textbook 2 x log n it
finds exactly the true ones.

### 2026-10-17: a level in place of inflow pieces - KEPT
A level that changes slowly looks like a series of changes in a stock's outside inflow, and the fine
pieces of the first pass take it before the level is ever tried. After the passes, the two levels
whose means over the pieces best follow the pieces' values are each tried in place of pieces: the
row is refitted with the level, its pieces found again, and the level kept if the whole row (levels
plus pieces) is better by more than log T. Best -> now: **meeting the goal 17 -> 18, mean skill@20
70.5% -> 70.8%, skill@100 68.2% -> 68.9%**: sd-hospital default 84%/65% -> 98%/98%; sd-university
default @100 98% -> 96%. Trying every level instead of the best two: the same numbers, 40% slower.
Run time (summed over the parallel bench) 410 s -> 900 s.
- **A constant per configuration** (an announced change may set a goal or a budget: columns "1 while
  configuration c holds" beside the per-configuration levels): no change on sd-support-tiers (the
  staffing goal), sd-eras default 96.5% -> 37% (an era's constant competes with its rate). REVERTED.
- Not solved, sd-support-tiers default: new tickets arrive at 0.012 x customers, but new tickets settle
  at ~0.024 x customers within days, so a slowly drifting inflow explains the row as well and no
  level pays; the goal grader feeds the true (bug-spike) inflow, and the found model, with no
  customers link, starves.

### 2026-10-17: outside inflow re-measured after conservation; trusting receivers must pass a test - KEPT
**Bug fix**: when conservation changed a row's own drain (to what the receivers take), the outside
inflow's pieces kept the values measured beside the row's own, biased, drain (sd-eras: raw drained
0.62 in its own fit, 0.556 after conservation, so deliveries came out ~12 a step instead of 10). The
pieces are now measured again with the numbers the row ends with. And the "trust receivers" rule
(raise a changing row's drain to what same-unit stocks receive from it) is no longer unconditional:
like lowering it, it must pass the refit test (BIC within log T) or be within 30%. Without that, the
re-measured inflow absorbed the change: sd-population long read births as a move (adults -> children)
with 151 inflow pieces averaging 6685 a step (truth: constant 800), fitting the data and graded
-7701%. Best -> now: **mean skill@20 66.3% -> 70.5%, skill@100 65.4% -> 68.2%, meeting the goal 16 ->
17**: sd-eras default -200% -> 96.5%, sd-ci long 77% -> 93.5%, sd-orders default 30% -> 79%,
sd-university default 75% -> 84%, sd-recycling long 77% -> 86%; sd-support-tiers default 37% -> -652%
(changing inflow pieces into internal stocks: resolved 10, reopened 16), sd-kanban long 78% -> 74%.

### 2026-10-17: announced eras as per-configuration columns in one regression - KEPT
Each distinct era label is a configuration. A stock's row is fitted once on all steps; after the
first stepwise pass, every level the row uses (and its own) gets one extra column per configuration
("level of j while configuration c holds"), which joins the stepwise search and stays only if it
pays by BIC. Structure is shared; a number differs in a configuration only where the data says so.
Flows are read off each configuration's matrix and merged into byTime rates. Conservation is tested
for all configurations together. Best -> now: **mean skill@20 58.2% -> 66.3%, skill@100 52.8% ->
65.4%, parts 58.8% -> 59.6%; meeting the goal 13 -> 16 of 42**. sd-eras long -1748% -> 50% (stage 1
0.31/0.56 vs truth 0.3/0.55, stage 2 0.40/0.19 vs 0.4/0.2), sd-fishery default 27% -> 97%,
sd-support-tiers default -74% -> 37%, sd-recycling long 59% -> 77%, sd-ci 89%/74% -> 92%/77%;
sd-ev-fleet long 87% -> 79%. sd-eras default still -200%: the chosen candidate (constant inflows)
reads the unannounced "busy deliveries" as a recycle finished -> raw 0.05, so fed the true deliveries
it overfills raw.
Steps on the way:
- **Fitting each label on its own steps (mask), merging into byTime**: per-label numbers noisy
  (stage 1 0.23/0.50/0.60/0.48/0.29) and spurious links nonzero in one era only; sd-eras still
  -1277%. A configuration's inflow pieces first overlapped other eras (fixed by clipping to its
  spans). REPLACED by the shared regression.
- **Configuration columns added after the first change scan**: the scan had already cut the raw
  inflow at every era boundary (the drain's change looks like an inflow change), so the columns
  never paid. Adding them before the first scan fixed it.
- **A change in the outside inflow priced at 2 parameters (its value and its place) in the inflow's
  form decision**: removes chance 5-step "pieces" (sd-fishery default 97%, sd-ci default 95%) but sd-pipeline
  long 98% -> 45% (its intake really changes every 30 days) and sd-restaurant long 85% -> 61%.
  Mean skill@20 62.8%. REVERTED.

### 2026-10-17: choose among candidate models by behaviour on the data - KEPT
identify() now builds several candidate models and keeps the one that predicts the measured data
best when run forward from ~80 moments (its own estimated outside inflows feed it; only the data is
used), averaged over 5, 20 and 100 steps. Candidates: forward or backward search x changing or
constant outside inflows x trusting the receivers or the rows where stocks are seen receiving more
than a stock's own row says it loses. Baseline start21 -> now: **mean skill@20 15.5% -> 58.2%,
skill@100 17.9% -> 52.8%, runs meeting the goal 9 -> 13 of 42** (parts 62.6% -> 58.8%: structure is
not the target, behaviour is). Big movers: sd-services -791% -> 97-99% (the API's calls are links,
not moves; trusting rows), sd-housing 48%/-9789% -> 95%/97%, sd-university -748%/67% -> 75%/98%,
sd-population -576%/-9499% -> 69%/50%, sd-fishery -622%/-388% -> 27%/30%. Worse: sd-eras -176% ->
-1244% (eras are not modelled; the chosen variant fits the data's mix of eras worst when fed the
truth's inputs), sd-kanban default 93% -> 78%.
Steps on the way:
- **Backward elimination alone** (start each row from every level): children's row right (births
  0.020 vs 0.022 x adults, growing up -0.051 vs -0.056: two levels that only explain the row together)
  but overall mean skill@20 15.5% -> 10.4%: collinear stocks pull weight onto the wrong level.
  As a candidate only. KEPT as a variant.
- **Judging at 20 steps only**: picked models where downstream loops mimic the frontend's outside
  traffic (data error 0.74, graded -62000%: fed the real traffic, the loops double it and explode).
  Judging at 5, 20 and 100 steps (loops that mimic an input drift apart later) fixed the pick.
- **The "trust receivers" rule** (a changing row's drain set to what receivers take) made the API lose
  2.7 x its requests a step (its calls are links); as a candidate, behaviour picks per example.


### 2026-10-17: the matrix method (`identify.js`) - KEPT
Replace the combinatorial search with per-stock least squares on single steps (each stock's change
on every stock's previous level), outside inflow as pieces with detected changes, flows read off the
matrix with conservation and units. On the first five ground-truth examples, parts went from 0-2/5,
2-6/10, 1-3/5, 0-3/8, 0/3 (old search) to 4/5, 9/10, 5/5, 6/8, 2/3; SaaS drift 0.04 (skill 99.8%).
Steps that mattered, each checked on sd-pipeline (truth: inbox->working 0.3, working->review 0.2,
review->done 0.25, review->working 0.05, intake changing every 30 days):
- **Single steps, no windows.** Summing steps into windows biases the fit when stocks turn over within
  a few steps (5-step windows: working->review 0.08 instead of 0.2; rework negative). KEPT.
- **No links in the search.** Links (B's arrivals follow A, nothing leaves A) let non-conserving
  models outscore the truth (found score -966 vs truth -228 on 1500 steps). The matrix method reads
  links off only where conservation cannot explain a gain. KEPT.
- **Outside inflow in pieces (PELT, optimal partitioning).** Binary segmentation found no changes in
  an intake alternating 5/9/3/6 (no single split helps); optimal partitioning finds them. KEPT.
- **Fine pieces first, then the usual price.** Fitting without pieces biases the drain (inbox -0.12 vs
  -0.30), which hides the changes; a fine first pass gives unbiased numbers, later passes use price
  1 per change. A price of 2 per change spiralled (fewer pieces -> more bias -> fewer pieces). KEPT
  (schedule 0.5, then 1).
- **Pieces only for a stock that has an outside inflow.** A scan over thousands of places finds a few
  chance changes anywhere (working got 15 pieces averaging 0.19). A stock gets pieces only if a
  constant inflow beats none, or the pieces average well above their own spread (the ad budget's
  release steps 600-2500 fit a constant no better than none, but averages 1400). KEPT.
- **Choose the outside inflow's form with the levels fixed.** Re-running the stepwise search per form
  drifted on collinear stocks (SaaS: trials->churned instead of trials->paying). KEPT.
- **Conservation first.** A stock's drain is what same-unit stocks are seen to receive from it unless
  the data clearly says otherwise; a row fed by a changing inflow cannot separate its drain from the
  changes (inbox drain 0.36 vs moves 0.30), so there the moves are trusted within 30%, and always when
  the moves exceed the drain (hospital waiting->treatment: split 0.20 move + 0.15 link -> 0.35 move).
  KEPT.
- **Units.** A gain in a stock of another unit is a link, never a move (SaaS: "ad budget -> visitors"
  would turn dollars into people; with the rule, the ads link 0.116 and the spending 0.1431 vs 1/7). KEPT.
- **Robust IV on second differences** (to estimate a row's drain without detecting the outside
  changes): right for the ad budget (-0.148 vs -0.143), better for the waiting room (-0.27 vs -0.35),
  but exploded on the pipeline inbox (weak instruments: 29.0). REVERTED.
- **Wrapper around the old search that subtracts detected outside changes and searches again**: did
  not converge (each pass landed elsewhere). REVERTED.

### Before: the old search (`discover.js`)
See docs/DISCOVERY.md. On the long-run bench of the first nine (non-SD) examples, every example
peaked early and got worse with more data (window cap: windows widened with run length), ending at
0 parts for four of them. On sd-pipeline it recovered 0-2 of 5 parts at any length. Changes made to it
along the way (links, links-first second pass, step-by-step link screen for the shop, per-era link
numbers, the cache key fix) are described in DISCOVERY.md.
