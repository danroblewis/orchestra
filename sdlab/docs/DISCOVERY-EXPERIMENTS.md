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

### 2026-10-17: experiment hidden_delays - hidden stocks as delayed copies of a level - NEEDS A COMBINATION
Branch `exp/hidden-delays`, strategy `hidden_delays` (`sdlab/discovery/hidden.py`,
`sdlab/discovery/strategies/hidden_delays.py`), test `tests/test_strategy_hidden_delays.py`.
**Hypothesis.** In 9 of the 12 examples short of the goal the truth has an unmeasured stock between
two measured ones (kanban testing -> undetected -> bugs, supply warehouse -> trucks -> shop, ...).
No row has a column for its arrivals, so they are read as the receiver's outside inflow in pieces or
as wrong links. A stock H fed at k x A and drained at d x H is, in B's row, k x z(t-1) with z the
copy of A's level delayed by d (z(t) = (1-d) z(t-1) + d A(t-1)); offer such copies, and turn a chosen
one into A -> H -> B with H's level estimated as (k/d) x z.
**Method (final).** The main line's 8-16 candidates are built and judged as usual; on the best one:
(1) proposals: copies of every stock at d in {0.5, 0.3, 0.17, 0.1, 0.06, 0.03}, offered to the rows of
same-unit stocks (matrix option `extra`), the ones the stepwise search picks with a positive number,
plus the best per (A, B) by a row-level screen without pieces (top 6, must pay log T); (2) greedy:
each proposal is tried alone in B's row in place of A's level (option `replaces`), as it is and as a
"steady" receiver (no inflow pieces in B, B's row starting from the copy and its own level: options
`steady`, `start_with`); accepted if H is fed mostly by a move out of A (not a link), the model
explains the receivers better with their pieces held at their means (pieces fitted to the run explain
any arrivals, so the plain judge always prefers them) by 2%, on a judge scaled per stock by how far
it moved (the main judge's spread scale all but ignores a stock that only accumulates), without being
more than 15% worse with its pieces (0% for steady, whose row must also beat the replaced row by BIC
with each piece priced as two numbers); (3) the accepted delay is tuned by x1.4 steps. All new
matrix/flows/simulate options default off: `--strategy matrix` on sd-saas, sd-eras, sd-pipeline
gives zero deltas.
**Mechanism test** (a -> h -> b, h unmeasured, a's inflow changing 3 times, 2000 steps, counting
noise): hidden_delays finds a -> H 0.208 (truth 0.2), H -> b at d = 0.1 (0.1), b -> out 0.26 (0.25),
no outside inflow into b; skill@20 94%, @100 98%. The matrix: b gets 12 inflow pieces, a drains to
outside at 0.25; skill@20 -25%, @100 72%. Noise-free, both reach 100% (the matrix's pieces into b,
fitted to the same run the grader replays, reproduce it exactly).
**Bench vs "python"** (42 runs): **mean skill@20 70.8% -> 70.9%, skill@100 68.9% -> 68.6%, parts
59.9% -> 62.0%, runs meeting the goal 18 -> 20** (sd-recycling long, sd-university default). Moved
more than 2 points (skill@20 / @100): sd-ci default 93.9/91.8 -> 96.1/96.2 (todo -> builds, steady),
sd-ci long 93.5/86.9 -> 95.9/96.6 (commits -> 0.17 -> builds: the true review stage, 0.2),
sd-fishery long 29.5/30.8 -> 39.5/38.4 (landed -> 0.3 -> processed: the true cold store, 0.33),
sd-moderation default @20 36.5 -> 38.8 (flagged -> 0.03 -> removed: the true vendor, 0.028),
sd-moderation long 49.4/-32.4 -> 60.3/-12.8, sd-orders long @20 7.0 -> 27.6, sd-recycling long
86.4/89.9 -> 91.5/94.3 (bales -> shelves: the true rail), sd-restaurant default 86.8/88.8 ->
88.3/92.7 (cooking -> 0.7 -> pass: the true plating, 0.5), sd-university default 85.7/96.1 ->
95.2/98.8, sd-hidden-chain long @5 +1.9; worse: **sd-population default 68.2/87.3 -> 6.7/20.3**
(adults -> 0.7 -> elderly, steady: no hidden stock in the truth; better on the data, runs away fed
the true inputs), sd-ev-fleet long @100 59.6 -> 57.4. Not found: kanban testing -> bugs (a row-level
gain of ~7 against log T = 8: the arrivals are too small beside the sprint spikes), supply (the
truck stage is fed by a gap on the shop, not by the warehouse's level), support-tiers, manufacturing,
saas lapsed. Run time 220 s -> 805 s (summed over the bench).
**Grader extension (tests/bench/grade.py), recorded as required**: a found result may carry its own
unmeasured stocks, `result["inferred_levels"] = {id: series aligned with t}`; every stock a found
model names that is not measured is renamed apart from the truth's stocks and started from that
estimate (empty without one), never from the truth's level; `found()` reads A -> H -> B through such a
stock as a hidden relation A > B. **Bug fixed with it**: before, a found flow naming a stock with the
same id as the truth's hidden stock was run from the truth's hidden level (the exact structure with
the stock called "h" graded 100% without any estimate; now it starts empty). Flows into other
unknown stocks used to vanish; now they go into an empty found stock. Results that name only
measured stocks (every main-line result) grade exactly as before: a frozen value test, and
`--strategy matrix` zero deltas. `behaviour_error` (judge) takes the same `inferred` levels.
Attempts on the way (all against "python", 42 runs; @20 / @100 / goal):
- **v0, all copies as columns in every row, as extra candidates for every variant**: rows took 2-6
  copies, both directions, mixed delays; runaways (restaurant: judge 136 vs 0.31). Never chosen.
- **v2, greedy one pair at a time from the stepwise picks, judged on the data, 2% margin**: 69.0 /
  64.5 / 19; sd-population long -104 (children -> adults fed by a link), sd-fishery long -18/-91.
- **v3, + H must be fed mostly by a move**: 71.0 / 67.3 / 19 (population and supply fixed; fishery
  long boat loop at_sea <-> in_port still accepted: better on the data, worse on processed, which the
  spread-scaled judge cannot see).
- **v4/v5, every horizon must improve / delay refinement**: 70.1 / 67.0 and 70.6 / 67.2 (refining
  drifted population default to a worse delay).
- **v6, receivers judged with their pieces held at their means ("structural")**: 71.1 / 67.0 / 19,
  parts +2.4 (more true pairs: ci, ev-fleet road -> queue, fishery, moderation, restaurant).
- **v7/v8, + per-stock "moved" scale, + screened proposals**: **72.1 / 69.6 / 20**, no run worse by
  2 at @20 - the best bench, but it fails the mechanism test (synthetic skill@20 -310%: b keeps 38
  pieces beside the copy, which bias its drain 0.39 and the delay to 0.06).
- **v9, 10-delay grid**: 71.3 / 68.5 (more false picks). **v10, 5% margin, 5% slack**: 72.0 / 69.5.
- **v11, receivers always steady**: 68.2 / 65.4 (moderation long -88, population default -61, eras
  default -20: receivers with real changing inflows lose them). **v12, steady or not**: 69.6 / 67.4.
  **v13, rows start from copy + own level, never steady**: 71.2 / 68.0 (start alone hurts).
- **v14, steady only within 0% slack**: 70.4 / 69.0 / 19 (eras default still -20). **v15 = final,
  + steady row must beat the replaced row by BIC**: eras fixed; population default remains.
**Verdict: needs a combination.** The mechanism works in isolation and recovers true hidden stocks
on real data (ci review, fishery cold store, moderation vendor, recycling rail, restaurant plating,
ev-fleet partly), with clear gains on 9 runs and 2 more meeting the goal; but acceptance relies on a
judge that is fooled by in-sample fits (population default, fishery boats), so the net mean is flat.
Combine with a judge that is not (out-of-sample, or the stability check of the "runaway" idea), or
adopt the v8 settings (no steady receivers: +1.2 / +0.7, 20 runs) if the mechanism test is relaxed
to noise-free data. Other ideas noticed: the change scan's single noise variance over-segments
heteroscedastic (counting) noise (synthetic a: 24-33 pieces for 4 true); the main judge's per-stock
spread scale ignores accumulating stocks; inflow pieces into a stock the truth does not feed are
fitted to the very run the grader replays (noise-free, a wrong model grades 100%).

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
