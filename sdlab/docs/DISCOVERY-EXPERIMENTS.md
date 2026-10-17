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

### 2026-10-17: PySINDy with SD-shaped libraries and conservation constraints (exp/pysindy) - REJECTED as a replacement; parts worth combining
**Hypothesis**: sparse regression (PySINDy) over a library of levels and products of two levels (a
product A x C in a flow out of A is a linear effect of C), with the outside inflow found in pieces by
our own `changes.pelt` and taken out, announced eras as per-configuration level columns, and
conservation imposed as equality constraints across rows (ConstrainedSR3), recovers structure and
behaviour better than stepwise BIC, especially on the effect and co-flow examples.
**What was built** (strategy `sindy`; `opts["sindy"]` or `$SDLAB_SINDY` picks the ablation):
`library.py` (PySINDy `PolynomialLibrary`, degree 2, products only of levels that move; era terms),
`sparse.py` (per row: STLSQ threshold path and SSR elimination path run on the Cholesky factor of the
demeaned Gram matrix - one row per term instead of one per step - support picked by extended BIC
(Chen & Chen, gamma 1), polished by single swaps; a product kept only if it beats each of its
factors' plain levels by > log T; inflow none / constant / pieces each with its own support; first
pass levels only), `conserve_joint.py` (rows fitted jointly, each scaled by its noise, sparsity held
by equality constraints, one equality "loss of a term = receipts in same-unit rows" per term kept if
it costs < log T; solved by ConstrainedSR3 with lam 0), `term_flows.py` (terms -> flows: moves,
links, outside flows; a flow's level and product terms joined into one rate x linear or two-point table
effects; a loss in a stock of another unit read as `uses` on the source's main flow). Needs pysindy
2.1 and cvxpy (ConstrainedSR3 imports only with cvxpy).
**Mechanism tests** (`tests/test_strategy_sindy.py`, all pass):
- (a) plain chain: a -> b 0.2827, b -> out 0.1927, nothing else, skill@20 0.955; matrix 0.2835 /
  0.1927 plus a spurious 0.0067 x b out of a, skill@20 0.996 (the spurious term happens to offset
  the low drain).
- (b) cut = 0.3 x logs x sharp/100 with sharp moving 20-60 by its own changing inflow: found as the
  product logs x sharp and read as logs -> planks with a linear effect of sharp, 0.00278 per log per
  point (truth 0.003); skill@20 0.86, @100 0.95. Matrix: no effect, logs -> planks 0.08 x logs plus
  links from sharp; skill@20 -2.6, @100 0.57. Needs the change scan at 2 x log n here: at 1 x log n
  (matrix's price) sharp's inflow is cut into ~30 pieces and sharp x sharp stands in for the rest
  (skill@20 0.08).
- (c) a -> b 0.3 into a noisy receiver (b: 60 a step in and out; a's inflow changes): joint fit keeps
  conservation, a -> b 0.2997, no other flows; without the constraint b's reading leaves a link
  beside the move; matrix (trusting the receiver because a's inflow changes) a -> b 0.3294, b drain
  0.551; skill@20 sindy 0.87, matrix 0.39.
**Bench vs v2** (31 examples x 2 lengths; v2 = parts 55.4%, skill@20 31.6%, skill@100 32.1%, 17/62
meet the goal, 326 s summed run time). First round with the change scan at 2 x log n, single models:

| attempt | parts | skill@20 | skill@100 | meet goal | time (s, summed) |
|---|---|---|---|---|---|
| plain PySINDy (levels + constant, one STLSQ threshold by summed BIC) | 55.0% | -34.3% | -49.6% | 0 | 12 |
| levels, per-row paths, inflow pieces (2 x log n) | 54.5% | 8.9% | 6.9% | 11 | 80 |
| + products | 51.3% | -3.1% | -14.6% | 9 | 273 |
| + conservation constraints | 52.1% | -3.9% | -15.0% | 9 | 270 |
| + co-flows (any loss in a third stock) | 56.7% | -42.4% | -51.1% | 6 | 262 |
| + candidates judged by behaviour (products/levels x inflow forms x eras) | 56.5% | 4.5% | -3.3% | 7 | 1406 |

Second round: change scan at 1 x log n (2 x log n collapsed sd-hidden-chain long's 328 inflow pieces
to 1, -857%), co-flows only into another unit:

| attempt | parts | skill@20 | skill@100 | meet goal | time (s) |
|---|---|---|---|---|---|
| uses (single model) | 60.2% | -21.6% | -27.0% | 8 | 331 |
| full: judged over products/levels x {pieces at 1 and 2 x log n, constant} x eras | 59.3% | 20.5% | 16.2% | 8 | 3296 |
| combo: matrix's chosen model + the product candidates, judged together | 56.7% | 29.7% | 33.4% | 17 | 3377 |

Full (round 2), examples that moved more than 2 points at skill@20 (deltas clipped at -100% like
the means): better - sd-webshop-stock default +195 (95.0% / 93.6%: meets the goal; packing -> out
uses shelf at 0.96 per order, truth 1) and long +86, sd-cloud-credits default +155, sd-moderation
default +154, sd-print-shop long +112, sd-bakery long +76 (95.3%, orders -> shelf with a flour effect
and use) and default +22, sd-population default +28, sd-eras long +21, sd-orders default +19,
sd-restaurant default +15, sd-pipeline default +13, sd-brewery default +4, sd-manufacturing default +4;
worse - sd-reservoirs long -191, sd-services long -196 and default -49, sd-population long -150,
sd-learning-curve long -145, sd-support-tiers long -142, sd-housing default -131, sd-emergency default
-104 and long -49 (round 1's single products model had it at +81/+135; the judge picked another),
sd-fishery default -70, sd-cloud-credits long -49, sd-moderation long -41, sd-eras default -40,
sd-manufacturing long -30, sd-brewery long -26, sd-recycling long -25, sd-university -24/-23, sd-ci
default -17, sd-hospital -13/-17, sd-kanban default -12, sd-learning-curve default -9, sd-farm-soil
default -8, sd-ev-fleet long -8, sd-reservoirs default -7, sd-recycling default -4, sd-ci long -4.
Combo moved: sd-webshop-stock default +195, sd-cloud-credits default +155, sd-bakery long +76 and
default +22, sd-population default +28, sd-recycling default +23, sd-orders default +19, sd-pipeline
default +13; sd-population long -150, sd-learning-curve long -145, sd-support-tiers long -142,
sd-housing default -131, sd-eras default -40 and long -19, sd-hospital default -13, sd-reservoirs
default -7, sd-ci long -4.
**Verdict**: rejected as a replacement for matrix (full: skill@20 20.5% vs 31.6%, 8 vs 17 runs meeting
the goal, 10x the run time); the combination with matrix is a wash on the means (29.7% / 33.4%, 17 of
62, a different 17) and 10x slower, so not adopted either. Why: (1) the base machinery (sparse paths
+ EBIC) is no better than stepwise BIC on linear rows and lacks matrix's refinements (receivers'
trust, level-in-place-of-pieces), so linear examples lose; (2) products are flexible enough to
stand in for unexplained inputs and floors (sharp x sharp for a mis-cut inflow, logs x logs and
logs x planks beside the true product), and several product models run away under the true inflows
although the judge, fed the models' own inflows, ranks them best - the judge and the goal disagree
most on exactly these models; (3) reading every loss in a third stock as a co-flow is wrong more
often than right (round 1, -38 points); restricted to another unit it pays on webshop, bakery,
cloud-credits. **What mattered from PySINDy**: STLSQ + SSR paths (SSR's elimination path finds
supports STLSQ's thresholds skip, but both still miss the best one when a product and a level are
collinear - the swap polish was needed), PolynomialLibrary, ConstrainedSR3 for the joint
conservation fit (equality only; inequality needs cvxpy and was not needed). Not useful here:
`SINDy` with control inputs (the inflow is not measured, so it is subtracted pieces instead),
ensembling and weak form (not tried: the data is already one step per unit, and the failure is
selection, not noise in derivatives). **Worth carrying into the main line on their own**: the joint
conservation fit (test c: the precise row sets a move, where matrix trusts a noisy receiver), and
product terms read as effects and losses in another unit as co-flows, but offered only as candidate
rows, not as a free library. **Ideas noticed (not pursued)**: a product term admitted only when the
row without it, with its inflow pieces refitted, still leaves residuals that follow the product
(test it against pieces, not beside them); a judge that also runs each candidate on a constant
inflow equal to its pieces' mean, to catch models that only work fed their own inflows; noise-weighted
rows (Poisson counts: variance grows with the flows) in both the selection and the joint fit;
saturating effects (tables) read off binned residuals of a product row, for sawmill and
learning-curve whose effects are tables.

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
