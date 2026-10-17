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

### 2026-10-17: choose among candidates on data they were not fitted on (exp/held-out-judge) - REJECTED
**Hypothesis**: identify() keeps the candidate with the lowest multi-step error on the data it was
fitted on, each fed its own estimated outside inflows; in sample, inflow pieces can absorb almost
anything (sd-support-tiers default: chosen candidate, judge 0.297, graded -652%; "backward, constant
inflows, trust receivers, numbers per era", judge 0.555, graded +35%). Judging out of sample, or
pricing pieces as parameters, should pick the candidates the bench rewards.
**What was built**: `identify_one` takes `steps` (fit on those steps only; default: all, `matrix`
unchanged - zero deltas on sd-saas, sd-eras, sd-pipeline default); `discovery/holdout.py` (blocked
cross-validation: cut the run into contiguous blocks, fit on all but one, run forward from moments in
the held-out block, its outside inflow there = the piece in force before it, or the pieces' mean;
never the block's data); strategies `held_out` (lowest mean held-out error over 5 blocks, horizons
5/20/100, each block capped at 1000; the chosen candidate refitted on all the data) and
`held_out_blend` (log in-sample error + 0.1 x log held-out error, 10 blocks, horizons 20/100).
**Mechanism test** (`tests/test_strategy_held_out.py`): children/adults, births = 0.022 x adults,
600 steps. With a candidate that trusts receivers whatever it costs (the rule before "trusting
receivers must pass a test"), in sample that candidate wins (error 0.013 vs 0.034/0.876): births read
as a move adults -> children paid back by adults' inflow pieces averaging 234 a step (truth 80 then
160); `matrix`'s judge picks it, graded 65.6% skill@20. Held out, it is the worst candidate (1.20 vs
0.74/0.15); the held-out judge picks constant inflows, births a link 0.0238 x adults, graded 73.7%.
The second test shows the failure that sinks it: customers/tickets with signups that really change
(730 steps): `matrix` picks changing inflows (68.5%), held out the stale last piece loses to a constant
inflow and `held_out` picks constant inflows (-298%).
**Offline first** (every candidate of every run fitted and graded once, scratch; the bench numbers
below reproduce these exactly). Oracle (best-graded candidate per run): mean skill@20 78.3%, @100
76.2%; the in-sample judge picks it (within 2 points of skill@20 + skill@100) in 31 of 42 runs.
- Fit on the first 50/60/70/80% (and averages of these), judge forward on the rest, inflows extrapolated
  as the last piece, the mean, or the last quarter's mean, horizons 5/20/100, 20/100 or 20: mean
  skill@20 between -12.6% and +7.2%, 3-9 runs meet the goal, best-graded picked in 4-12 of 42.
- Blocked CV, 5 or 10 blocks, last piece or mean, any horizons, mean/log-mean/median over blocks:
  skill@20 -8.6% to +3.3%. It picks a constant-inflow candidate in 41 of 42 runs.
- BIC-like criterion on the in-sample multi-step error, T log(error) + lam x (pieces [+ coefficients])
  x log T: lam 0.25 70.2% (18 runs), 0.5 66.2% (19), 1 64.5% (18), 2 41.9%, 4 17.3%.
- Held-out error as a veto (in-sample judge among candidates within m x the best held-out error):
  m 1.1-5 18.6%-58.9%, m 10 70.3%. Held-out only within the inflow form the in-sample judge chose:
  63.6-70.9%, 16-19 runs. Blend log in-sample + a x log held-out: a 0.1 70.2-70.9%, 19-20 runs;
  a >= 0.5 54-64%.
**Bench** (`--baseline python`, full suite, both lengths):
- `held_out` (5 blocks, last piece): **mean skill@20 70.8% -> -4.8%, skill@100 68.9% -> -6.3%,
  runs meeting the goal 18 -> 3**, parts 59.9% -> 55.1%. Chosen candidate changed in 40 of 42 runs;
  best-graded candidate picked in 31 -> 9. Better by > 2 points at skill@20: sd-support-tiers default
  -652% -> 35%, sd-ev-fleet long 79% -> 94.5%, default 87% -> 94%, sd-recycling default 32% -> 55%,
  sd-kanban long 74% -> 80%. Worse: sd-services -61295% / -55552% (from 97/99%), sd-saas -12648% /
  -16119% (from 100%), sd-housing -989% / -1193%, sd-hidden-chain -896% / -857%, sd-manufacturing
  -564% / -512%, sd-eras -200% / -312%, sd-moderation long -297%, sd-support-tiers long -54% -> -302%,
  sd-reservoirs -95% / -165%, sd-supply -1.5% / 6%, sd-pipeline 40% / 44.5% (long from 99%), sd-ci
  60.5% / 54%, sd-orders default 21%, sd-population default 29%, sd-fishery default 32%,
  sd-restaurant 70% / 70%, sd-university 75% / 76%, sd-hospital default 84%, sd-recycling long 77%.
  Run time ~3-5x.
- `held_out_blend`: **70.8% -> 70.5%, 68.9% -> 68.1%, meeting the goal 18 -> 20**; changed in 13
  runs; best-graded picked 31 -> 30. Moved > 2 points at skill@20: sd-ev-fleet long 79% -> 94.5%
  (@100 60% -> 99.5%), sd-kanban default 77% -> 91% (@100 66.5% -> 84%); sd-pipeline default 58% ->
  40% (@100 -122% -> -178%), sd-restaurant long 86% -> 70% (@100 85% -> -2%), sd-university default
  86% -> 75%. Run time ~6x (sd-hospital long 243 s).
**Why it fails**: the bench feeds every model the truth's outside inflows, so it asks only whether
the model's own dynamics are right. A held-out judge must also forecast the outside inflow, which
in these examples changes unannounced (demand, sprints, intake every 30 days, bug spikes); the
forecast error of a stale last piece dwarfs the dynamics, so candidates that need a changing
inflow (most of the right ones: hidden stocks seen as outside inflows, real demand changes) lose
to constant inflows whose wrong dynamics happen to drift less over a block. The in-sample judge,
feeding each candidate its own inflow estimate, is closer to what the bench asks. Pricing pieces as
parameters fails the same way: the pieces are needed. Neither can tell pieces into a stock the truth
feeds from outside (harmless: the bench replaces them) from pieces that stand in for an internal
flow (the sd-support-tiers failure: tickets that follow customers read as pieces). Even the right
candidate on sd-support-tiers default does not beat the wrong one held out (0.84 vs 0.64 at 60%).
**Verdict: reject** `held_out`. `held_out_blend` is noise-level (+2 runs meeting the goal, means
slightly down, 6x the time, best-graded picks 31 -> 30); not adopted. The held-out mechanism is real
but narrow (it does reject compensating pieces that do not carry over to unseen data); what the
bench needs is a judge of dynamics given inflows, not of forecasts.

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
