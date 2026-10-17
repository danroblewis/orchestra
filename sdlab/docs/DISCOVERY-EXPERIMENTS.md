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

### 2026-10-17: experiment change_price - pricing changes in the outside inflow honestly - REJECTED (gate: needs a combination)
Branch `exp/change-price`, strategy `change_price`, building blocks in `sdlab/discovery/pricing.py`
(`noise_variance`: differences or long-run; `scan`: PELT at mult x log n x that variance; `prune`).
`matrix.py` gained options whose defaults keep `matrix` identical (checked: zero deltas on sd-saas,
sd-eras, sd-pipeline default): `scan` (the change scan per phase: fine, pass, level, conserve),
`gate`, `level_change_params` / `form_change_params` (BIC parameters per change).
**Hypothesis**: changes are priced too cheaply (1 x log n, 0.5 in the fine pass; the textbook BIC
price is 2 x log n, and the variance from successive differences, sigma^2 (1 - rho), shrinks when a
missing level leaves autocorrelated residuals), so chance pieces stand in for internal dynamics.
**Mechanism test** (`tests/test_strategy_change_price.py`, synthetic chain inbox -> b -> c -> out with
the intake changing every 30 steps, 2000 steps): `matrix` gives the internal stock c 9 chance
pieces and numbers b -> c 0.229, drain 0.212; `change_price` gives c none (0.203 / 0.201) and keeps the
inbox's 62 pieces (drain 0.31). Also: the long-run variance of AR(0.6) noise is ~6 where differences
say < 1; at 2 x log n no chance change in 3000 steps of noise; pruning PELT's optimum at its own price
changes nothing.
**Bench (vs "python": 18/42, skill@20 70.8%, skill@100 68.9%)**, every attempt:
- **Textbook price in every pass** (2 x log n, differences' variance): skill@20 52.4% (-18.5),
  @100 43.8% (-25.1), 17/42. With the long-run variance and every change paying alone: 57.8% / 50.1%,
  17/42. sd-pipeline long 99% -> 45%, sd-hidden-chain long 97% -> -857%, sd-housing long 97% ->
  -793%, sd-eras long 49% -> -227%, sd-population long 50% -> -148%, sd-restaurant long 86% -> 70%;
  up: sd-support-tiers 652% better at default (still -298%), long -54% -> 62%, sd-recycling default
  32% -> 92%.
- **Why it hurts sd-pipeline (the price, through the refit)**: on the inbox's residual at the true
  drain 0.30 the intake's 200 changes are found as 147 at 1 x log n and 76 at 2 x log n (the real
  changes are individually weak: ~30 steps, steps of 3-6 against a noise variance of ~12). Missing
  ones bias the drain, which hides more changes: drain 0.25 -> 23 pieces, 0.20 -> 1, and the refit
  ends at drain 0.135 with one piece (the "spiral"). Both ends are self-consistent, and honest BIC
  prefers the wrong one: constant 15776 vs 166 pieces 16974 (6000 steps). 2 x log n is derived for a
  fixed number of changes as n grows; an intake that changes at a fixed rate is outside that regime,
  and there no price for detecting changes is right: under-cutting a real changing inflow biases the
  levels, over-cutting costs only variance. So the earlier attempt hurt through the price, but only
  because the levels are refitted on the pieces it finds.
- **Long-run variance at the usual price** (mult 1, rho from the differences' lag-1
  autocorrelation): 68.0% (-2.9) / 62.7% (-6.3), 13/42; sd-pipeline long -54, sd-moderation long -110,
  sd-university long -25; sd-support-tiers default +629 (to -24%), sd-ev-fleet long +16. (A first
  version estimating rho around fine pieces barely moved the variance, since the pieces eat the
  autocorrelation: 64.6% / 63.5%.)
- **Every change must pay alone** (prune at the scan's own price): identical to baseline; PELT's
  optimum already satisfies it.
- **A level in place of pieces judged with 2 parameters per change**: 64.2% (-6.7) / 58.7% (-10.2),
  16/42 (sd-pipeline long -55, sd-housing default -1206, sd-hospital default -25; sd-support-tiers
  default +687 to 35%, sd-recycling default +65, sd-population default +31).
- **The gate (the strategy as committed)**: passes at the matrix's price; at the first pass, beside
  the levels alone (no pieces yet to bias them), a stock gets pieces only if a constant inflow beats
  none or a change survives 2 x log n x the long-run variance. **71.0% (+0.2) / 69.5% (+0.6), 18/42,
  parts 57.8% (-2.1).** Up: sd-recycling default +17.5 / +5.9, sd-pipeline default +8.7 / +64.7,
  sd-moderation long +4.9 / +8.4, sd-eras default +2.6, sd-recycling long +2.1. Down: sd-university
  default -10.6 / -5.3, sd-manufacturing default -5.4 / -6.7 and long -4.1 / -4.7, sd-eras long
  -4.3 / -2.1, sd-kanban long -2.3 / -7.1 and default -1.8 / -9.0 @100, sd-support-tiers default
  -16.8 (-669%). With the differences' variance in the gate: the same to 0.1. Constant-beats-none
  alone (no change test): 70.7% / 67.5%. The losers are internal stocks whose pieces stand for
  internal rates that change unannounced (sd-university's enrolment pulse, sd-manufacturing's
  second line in a non-era candidate): there the pieces are real.
- **Minimum piece length** (an aside the brief allowed): 10 steps everywhere 73.2% (+2.4) / 71.2%
  (+2.3), 18/42: sd-pipeline default 58% -> 99% / -122% -> 99.8% (the inbox loses its spurious
  done link), sd-eras long +26.7, sd-moderation long +23.7, sd-university default +12.4; but
  sd-support-tiers default -308, sd-hospital default -14.7 / -33.4 (day/night), sd-restaurant long
  -15.4 / -86.7, sd-housing long -12.6. Only in the fine pass: 72.7% / 71.9% but 16/42
  (sd-reservoirs default -31). With the gate: 72.2% / 68.2%. 20 steps: 57.1%, sd-saas long blows
  up. A fixed length is a knob, not a principle.
**Verdict: REJECTED** as a price change: the honest price of a change is wrong for the stocks that
matter most (inflows that change at a fixed rate), and every honest variant in the passes loses
3-19 points. The gate is neutral overall (+0.2 / +0.6, the same 18 runs) and does what it claims on
the mechanism; it **needs a combination** with something that models internal rates that change
(per-configuration numbers for unannounced changes) before internal pieces can be banned.
The pipeline xfail is **not fixed**: the inbox still takes +0.026 x working (pieces in the inbox
are too few or too short there, not too many; the gate does not touch a stock with an inflow).
Noticed, not pursued: (1) short pieces bias a row's own coefficient (the Nickell bias of fixed
effects, ~(1 + a) / (m - 1) for pieces of m steps), which is why a 10-step minimum helps sd-pipeline
default and sd-eras long; a minimum tied to the row's own time constant, or a bias correction, may
get the gain without the losses at day/night and sprint spikes. (2) Estimate the levels with the
cheap pieces and never refit them on the reported pieces: the spiral needs the refit. (3) Choose the
inflow form per stock by behaviour (the judge), not one global "changing / constant" candidate.
(4) sd-support-tiers default: new tickets' pieces take the customers link; neither price nor gate
fixes it.

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
