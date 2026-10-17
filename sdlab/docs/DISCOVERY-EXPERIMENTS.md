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

### 2026-10-17: experiment numerical-opt - whole-model numbers and optional terms fitted by multi-step error with numerical optimisers - NEEDS A COMBINATION
**Hypothesis.** The simulator (`simulate.Model`) is exact but not differentiable (floors, tables,
capacity sharing). Fitting a candidate structure's numbers - rates, effect curves, co-flow ratios,
hidden stocks' delays - directly on multi-step simulation error with that simulator, by finite
differences, derivative-free optimisers or Bayesian optimisation, should recover the effects, hidden
stocks and co-flows that one-step regression misses (benchmark v2's worst examples). The numerical
counterpart of exp/gradient (same framing: the matrix result plus optional terms, multi-step error on
the data, the judge as the final gate).
**Method** (`sdlab/discovery/numopt.py`; building blocks `outerror.py` (multi-step residuals at 5, 20
and 100 steps from 80 moments other than the judge's; a hidden stock starts from the level its inflow
implies, a first-order filter of the data), `terms.py` (the model as a vector of named numbers in
boxes) and `optimisers.py` (fd = scipy least_squares TRF with finite-difference Jacobian, lbfgs =
L-BFGS-B with finite-difference gradient, powell, nm = Nelder-Mead, cma = CMA-ES from the `cma`
package, bo = Gaussian process (Matern 5/2, length scale by marginal likelihood) with expected
improvement, written here; every method counts every evaluation, including finite differences,
against one budget and returns the best point it saw)). From identify()'s model: forward selection, up
to 3 rounds. Candidate terms: a table effect (5 points at the stock's observed quantiles, the middle
fixed at 1) of every other stock on every flow out of a measured stock, alone or replacing the links
that stock drives into the flow's ends (the curve then starts as what flow + links carried); a co-flow
of every flow on every other stock, alone or replacing the link "that stock drains faster when the
flow's source is high" (per starts at link k / flow k); a hidden stock on every move (off on the bench,
see below). Every candidate is screened by one Gauss-Newton step on 5/20-step error (same screen for
every optimiser); the best 5 are fitted with the optimiser (term + the rates of every flow at the
stocks it touches, 60 evaluations), and the best joins if the error falls by more than 2% per net
number (its numbers less those of the flows it replaces) and, for a term that replaces nothing, the
fit with the term switched off is clearly worse (otherwise the fall came from refitted rates). Then
every number is fitted together (300 evaluations; BO skips fits of more than 8 numbers). The result is
kept only if identify()'s judge prefers it. Three treatments of the outside inflows: **fixed** (as
found; the default), **profile** (the found pieces of every stock a chosen term touches re-measured at
every evaluation as what its one-step change leaves over, except a co-flow's stock, which the co-flow
takes from like the link it replaces), **coarse** (every inflow averaged into max(8, n/100) blocks, a
free factor per block, priced by roughness between blocks and the mean log factor).
Strategies: `numopt_fd`, `numopt_lbfgs`, `numopt_powell`, `numopt_nm`, `numopt_cma`, `numopt_bo`
(inflows fixed), `numopt_fd_profile`, `numopt_fd_coarse`. Dependency: `cma` 4.5.0 (pure Python,
2.6 MB, numpy only). `matrix` unchanged (sd-saas/sd-eras/sd-pipeline default: zero deltas).
**Mechanism tests** (`tests/test_strategy_numopt.py`, two seeds each; FD, 60 evaluations, profile):
- (a) **table effect** of c on a -> b (0.3 x a x curve(c), c 40-170 on its own). matrix reads a plain
  move, two links driven by c and 31 inflow pieces into a: skill@20 -8.4 / -8.8 (seed 1 / 2). The
  effect in place of the links recovers the curve's shape within 2.9% / 2.1% RMS over the observed
  range; with its scale (k x table vs 0.3 x curve) 9.3% on seed 1 (skill 0.85 / 0.95), 36% on seed 2
  (the rate trades with a's re-measured inflow; skill -0.47 / 0.77). The whole strategy (numopt_fd_profile)
  finds it on seed 1 (skill 0.84 / 0.95) but not on seed 2: there the data's multi-step error is
  *higher* with the right structure (0.719 vs 0.693), because matrix's fine inflow pieces replay the
  data. With inflows fixed it cannot be found at all (a's inflow was measured beside the links:
  the fit with them dropped is 3.9 vs 1.0).
- (b) **hidden stock** a -> h -> b (delay 10, a loses 0.2): matrix splits a's drain into a -> b 0.064
  and a -> outside 0.17 (skill 0.92 / 0.91). The hidden stock on a -> b recovers delay 10.3 / 9.6 and
  flow 0.191 / 0.179, and cuts the multi-step error 15% / 16%. But the bench grader runs the found model
  on the measured stocks only (plus the truth's hidden ones, by their own ids), so a found hidden stock
  cannot be started; given back as a direct move (with `via`) it behaves worse (0.85 / 0.84 on seed 1)
  and the judge rejects it. Hidden stocks are therefore off on the bench.
- (c) **co-flow ratio** (a -> b uses 0.5 of c per unit): matrix's link-to-move ratio 0.645 / 0.507 (seed
  1 runs off: skill -0.26 / -2.43). The co-flow in place of the link gives per 0.502 / 0.560: right on
  seed 1 (skill 0.76 / 0.97), worse on seed 2 (0.99 -> 0.80). The data cannot tell them apart (error
  within 0.7%), so the judge keeps matrix's model on seed 1 too.
**Optimisers per parameter type** (same terms, final multi-step error / recovered value, seeds 1 and 2):
at 30-60 evaluations FD is best on every type (effect shape 0.029 / 0.021, delay 10.3 / 9.6, per 0.502
/ 0.560); L-BFGS-B, Powell and Nelder-Mead reach the same at 150 (Powell never moves the delay); CMA-ES
lags at every budget (shape 0.05, delay 4.6 / 6.9 at 150); BO is good on the single delay (10.3 / 9.6
at 150) and poor on the 7-number effect (cost above start on seed 2). On the co-flow, CMA-ES and BO
stay at the start: per's box is wide (twice the used stock's maximum per unit moved) and the error is
flat across it.
**Bench** vs v2 (17 of 62, 31.6% / 32.1%, parts 55.4%, matrix total 326 s); equal budgets for every
optimiser (60 per candidate fit, 300 for the final fit, the same screen). Run times are summed over
the runs with 3 jobs on a heavily loaded shared machine (load 16 to 200 on 28 cores), so they are
noisy; evaluations are the fair measure.

| strategy | skill@20 | skill@100 | parts | goal | kept | optimiser evals (mean/run) | screen evals | run time (total / mean / max) |
|---|---|---|---|---|---|---|---|---|
| matrix (v2) | 31.6% | 32.1% | 55.4% | 17 | - | - | - | 326 s / 5 s / 36 s |
| numopt_fd (fixed) | 32.6% | 34.2% | 55.8% | **20** | 50 | 39647 (639) | 131719 | 2599 s / 42 s / 265 s |
| numopt_lbfgs | 32.1% | 33.3% | 55.5% | 18 | 46 | 42831 (691) | 106510 | 2399 s / 39 s / 290 s |
| numopt_powell | **32.7%** | **35.3%** | 55.5% | 19 | 48 | 40554 (654) | 94684 | 2274 s / 37 s / 281 s |
| numopt_nm | **32.7%** | 33.8% | 55.5% | 18 | 48 | 40839 (659) | 103618 | 2193 s / 35 s / 263 s |
| numopt_cma | 31.6% | 33.6% | 55.5% | 15 | 35 | 43620 (704) | 110020 | 2254 s / 36 s / 265 s |
| numopt_bo | 32.3% | 32.4% | 55.5% | 17 | 17 | 15420 (249) | 91900 | 1878 s / 30 s / 243 s |
| numopt_fd_profile | 31.0% | 31.9% | 56.2% | 18 | 49 | 42485 (685) | 126645 | 2087 s / 34 s / 249 s |
| numopt_fd_coarse | 29.2% | 31.8% | 55.5% | 17 | 7 | 54281 (876) | 592972 | 9940 s / 160 s / 1676 s |

("kept": runs where the judge kept the searched model. BO's final fits of more than 8 numbers are
skipped, hence its fewer evaluations and fewer kept models.)
Moved more than 2 points (skill@20 / skill@100) with numopt_fd (fixed): **better** sd-brewery default
79.5%/92.4% -> 94.3%/98.4% and long 88.0%/95.8% -> 95.0%/98.5% (both now meet the goal), sd-ci long
87.9%/91.0% -> 92.3%/94.8% (meets it), sd-population long 50.4%/92.5% -> 84.8%/95.0%, sd-fishery long
35.4%/25.2% -> 41.9%/68.9%, sd-learning-curve long 44.8%/48.9% -> 61.4%/72.6%, sd-orders default
66.8%/87.2% -> 78.2%/91.5%, sd-restaurant default 63.9%/59.1% -> 73.0%/71.5%, sd-kanban default
37.6%/26.1% -> 48.1%/39.1%, sd-manufacturing long 81.6%/88.0% -> 86.9%/91.2%, sd-support-tiers long
42.5%/-12.9% -> 61.6%/27.7%, sd-webshop-stock long -25.6%/-83.0% -> 24.8%/6.5%, sd-cloud-credits long
-16.2%/54.5% -> 7.7%/75.8%, sd-emergency long -50.7%/59.3% -> -17.3%/68.6%, sd-farm-soil @100 49.0% ->
61.8% / 76.7% -> 83.2%, sd-housing long @100 -99.9% -> -82.7%, and the runaway runs less runaway
(sd-bakery both, sd-clinic-doses both, sd-cloud-credits default, sd-print-shop both, sd-support-tiers
default, sd-webshop-stock default, sd-moderation default); **worse** sd-hospital long 92.8%/90.7% ->
10.5%/-4.3% (no term: the final refit of the rates alone), sd-hospital default 96.2%/98.0% ->
90.6%/89.9%, sd-restaurant long 67.8%/-39.5% -> 37.5%/-295.3%, sd-ev-fleet 58.6%/63.9% -> 47.9%/60.6% and
76.0%/79.4% -> 46.4%/66.8%, sd-moderation long -58.6% -> -135.0% @20, sd-pipeline default 57.6%/-122.1%
-> 43.7%/-164.4%, sd-reservoirs default 93.5%/93.7% -> 90.6%/90.7%, sd-kanban long @100 56.7% -> 45.0%.
Profile against fixed: the effect examples gain where an effect replaces links (sd-webshop-stock default
-155% -> 92% @20, sd-print-shop default -547% -> -105%), but it is the output-error failure again
elsewhere: rates trade with re-measured inflows the grader replaces with the truth's (sd-population long
50% -> -134%, sd-support-tiers long 42% -> -156%), net -1.6 points against fixed. Coarse learnable
inflows: the judge (which feeds the model its own inflows) keeps only 7 searched models, since coarse
pieces no longer replay the data; of those, sd-fishery long 35%/25% -> 51%/73% and sd-cloud-credits
long -16%/55% -> 19%/72%, but sd-population long 50% -> -106% (rates handing their job to the freed
inflows, the output-error lesson again) and sd-moderation long -59% -> -212%; -2.4 points, and the
inflow factors make every fit larger (screen evaluations 4.5x, run time ~4x on the loaded machine).
**What was chosen.** Many accepted terms are not the truth's: co-flows and effects that stand in for
something else (sd-population long with profiled inflows: a co-flow using up the elderly,
-185 points @20; sd-bakery an effect of flour on
baking where the truth has baking use flour - a fair stand-in, graded as an effect, not a use), and on
the long runs the data's error differs by under 1% between them. Where they help behaviour the gain is
real (the grader runs them against the truth); where they hurt, the judge on the data could not see it.
**Verdict: needs a combination.** +1.0 / +2.1 points and 3 more runs meeting the goal (fixed inflows,
FD), at 8x the run time. Split by what was kept (numopt_fd, fixed): the 34 runs where terms joined
gain +2.4 / +4.4 points of the suite mean, the 16 where only the rates were refitted lose -1.4 / -2.3
(sd-hospital long alone -1.3 @20: the output-error refinement's risk, rates refitted around a wrong
structure), 12 were rejected by the judge. So terms do carry the gain, but the judge passes rate-only
refits it should not. The optimiser is not what limits it: at equal budget FD,
Powell and Nelder-Mead land within 0.6 points of each other, CMA-ES is worse (fewer models kept, 15 meet
the goal) and BO cannot fit whole models. What limits it is the criterion: multi-step error on the data
with the model's own estimated outside inflows cannot tell a right structure from a wrong one when fine
inflow pieces replay the data (effect seed 2: the truth's structure fits the data worse than matrix's),
and gives no grip at all on a co-flow ratio or an inflow level. The mechanism works when the structure
is offered and the inflow re-measured (curve shape within 3%, delay within 5%, per within 1-12%), so it is
worth combining with a criterion that does not let inflow pieces replay the data (inflows estimated
jointly with the structure under a strong price, or judged on held-out stretches), and, for hidden
stocks, with a grader that can start a found hidden stock from the level its own flows imply.

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
