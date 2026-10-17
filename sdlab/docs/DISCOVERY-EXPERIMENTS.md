# Discovery experiments

Every attempt to improve discovery, newest first: what was tried, why, what it did to the numbers,
and whether it was kept. Numbers come from `node tests/bench/evaluate.mjs` unless noted (headline:
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
