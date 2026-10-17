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

### 2026-10-17: floors and caps (`floors` strategy, branch exp/floors) - NEEDS A COMBINATION (not adopted)
**Hypothesis.** The engine floors every rate at 0 and caps a stock's outflows at what it holds
(sdtruth: "outflows share what it holds"). Where either binds, a row's change is a kinked function
of the levels, and the single-step straight line bends: wrong slope, the flow's constant lost into
the outside inflow, and a found model that runs the flow where the true one is shut. Measured on the
truth (diagnosis only, `max(0, ...)` argument < 0, or wanted outflow > level), at the default length:
floors bind on sd-moderation (escalate 59%, hire 49%), sd-ev-fleet (dispatch 36%, plug 8%),
sd-fishery (launch 24%); **caps bind more widely**: sd-supply warehouse 43% / shop 34%,
sd-manufacturing finished 53%, sd-restaurant waiting 43%, sd-ev-fleet queue 41% / parcels 19%,
sd-orders stock 16%, sd-university applicants 14%. The sd-recycling floor (sell = max(0, -40 +
0.2 bales)) never binds (bales > 200 throughout), so it is just a line there.

**Mechanisms** (`sdlab/discovery/caps.py`, `sdlab/discovery/hinges.py`, `strategies/floors.py`;
opt-in hooks in `matrix.identify_one`: `dy_adjust` and `extra_columns`, both off for `matrix`, zero
deltas on sd-saas, sd-eras, sd-pipeline):
- *Caps, EM for censored data*: from a found model, the steps where a stock's wanted outflow exceeded
  its level (and the data agrees: it ended the step holding no more than arrived), the shortfall is
  added back to the source's change and to the receivers', and the rows are fitted again; each round
  is a candidate for the judge. Stocks emptied on more than half the steps are left alone (their
  outflow is not identifiable, and their estimated outside outflow takes whatever is added back).
- *Floors, hinge columns*: per stock at most one column `max(0, +-(x - theta))`, the threshold a
  quantile of its level chosen from the data (gain in the rows beside all levels and each row's
  pieces, greedy, rows of the same unit), offered to every row's stepwise search; read as a flow
  `linear {c: -k theta, terms: [{x, k}]}` (via a pseudo-stock in `read_flows`), which the model floors
  exactly as the truth does. The side is the one whose hinge best replaces the stock's own level.

**Mechanism test** (`tests/test_strategy_floors.py`, synthetic, 2000 steps):
- Floor: a -> b = max(0, -30 + 0.2 a), shut 50% of the time. `matrix`: a -> b = 0.140 a, b's row
  73 outside inflow pieces (b has no outside inflow), skill@20 -5.4%, @100 80.5%. `floors` with hinges
  chosen by BIC: threshold 149 (truth 150), a -> b = max(0, 0.190 a - 28.4) (truth 0.2, -30), no
  pieces in b, skill@20 93.9%, @100 98.6%. **With the judge alone the plain fit wins** (data error
  0.074 vs 0.094): its pieces replay the kink's history, which an in-sample judge cannot penalise.
- Cap: s sells 15 a step and is emptied on 36% of steps. `matrix`: sale = 0.0165 s + 9.5 (pieces),
  skill@20 70.1%. Cap EM (the default): 0.0098 s + 11.6, skill@20 88.8%. A hinge on s writes the cap
  itself, min(0.71 s, ~15), skill@20 98.0%. On seeds 2 and 3 the EM alone is not reliably better
  (90.9% vs 89.5%, 83.8% vs 91.1%); the hinge is (98%, 98.4%).

**Bench** (against "python": 18 of 42, mean skill@20 70.8%, skill@100 68.9%):

| attempt | skill@20 | skill@100 | goal |
|---|---|---|---|
| cap EM, 3 rounds, last round kept | 45.9% | 41.5% | 15 |
| cap EM, confirmed by the data, <= half the steps, every round judged (**the default**) | **72.2% (+1.4)** | **69.3% (+0.3)** | 18 |
| + judge stepping models with the cap | 62.9% | 57.5% | 16 |
| + hinges (best per stock, side by tie, all rows), judged | 73.3% (+2.4) | 68.2% (-0.7) | 20 |
| hinges greedy, same unit; hinged-or-plain by rows' BIC | 66.1% | 61.2% | 21 |
| + thresholds only above 2x a step's outflow; BIC and judge <= 1.5x | 68.0% | 64.6% | 19 |
| same, judged | 69.8% | 67.5% | 18 |
| hinges per stock, no unit rule, side fixed at "above" | 61.9% | 59.3% | 20 |
| greedy, same unit, side by replacing the level, judged | 69.6% | 67.7% | 20 |
| same, by BIC | 64.5% | 62.0% | 17 |

The default (caps only), every example that moved more than 2 points: **sd-orders long 7.0% ->
83.9% @20, 53.3% -> 95.2% @100** (sale read as 15.7 a day instead of 21.8 plus "stock grows with
itself"); sd-ev-fleet long 78.7% -> 67.9% @20, 59.6% -> 41.2% @100; sd-kanban default 76.8% -> 69.3%
@20, 66.5% -> 56.7% @100 (the judge prefers an EM round the grader likes less). Runs meeting the goal
unchanged (18). Time: about 1.5x matrix (every round of every variant is fitted and judged).
With hinges the movers are large both ways and change with small choices: sd-moderation long
49% -> 83% @20 and -32% -> 75% @100 (flagged > 307, truth 300; escalation read as max(0, 0.104
flagged - 31.9), truth max(0, 0.1 flagged - 30)), sd-university default 86% -> 95-98%, sd-restaurant
+4 to +9, sd-support-tiers long +17 to +33, sd-recycling long +8; but sd-manufacturing long 84% ->
-38% .. -184%, sd-fishery long 30% -> -12% .. -50% (hinges imitate its unannounced seasons),
sd-ev-fleet -9 to -23 @100, sd-supply default -6.5, and on long runs BIC takes hinges everywhere
(sd-services long 99% -> 31%, sd-hidden-chain long 98% -> 78%). Flipping only a hinge's side (the
two sides fit the rows identically but read as different flows, each floored on its own) moves
sd-manufacturing default from 72.8% to -354%.

**A grader finding (not changed).** `grade.same_behaviour` runs the truth with `simulate.Model`,
which does not share a stock's level among its outflows as the engine does (it floors levels after
the step, so a move out of an empty stock still fills its receiver). The truth stepped with the
engine's cap, graded against the grader's truth: sd-supply 54.8% @20 / 79.1% @100 (long 54.4% /
77.5%), sd-manufacturing 88.9% / 90.8% (long 90.7% / 93.4%), sd-ev-fleet 89.3% / 89.5% (long 89.1%
/ 89.5%), sd-orders long 91.8% / 96.7%, sd-restaurant 93.7% / 97.1%, sd-university 98.7% / 99.6%;
the examples without caps 100%. So **sd-supply cannot meet the goal with a model of its data**, and
sd-manufacturing and sd-ev-fleet are at the line; a model that reproduces the data's caps (a hinge
does) is penalised for it. The judge has the same blind spot in the other direction (stepping the
judge with the cap, attempt 3, hid runaway models that the uncapped grader then punished).

**Verdict: not adopted; needs a combination.** The cap EM is a small net gain (+1.4 / +0.3, no change
in runs meeting the goal) carried by one example, with two regressions, and is unreliable on the
synthetic seeds. Hinges recover a floor exactly in isolation, but on the bench whether they help is
decided by model selection, and neither selector is fit for it: the judge rewards outside inflow
pieces that replay history (a kink's history included), while BIC on long runs pays for any kink
(seasons, caps) and picks models that run away under grading. Worth revisiting after (1) the grader
(and judge) step the truth as the engine does, and (2) a selector that charges for pieces (judging
on steps the pieces were not fitted on, or the inflow forecast rather than replayed).

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
