# Pulses: one-step arrivals and short bursts as their own kind of input

**Status:** done (wave 4, benchmark v2)  
**Verdict:** adopt candidate, best combined with the behaviour gate and the piece-proof judge
(+7.4 points of mean skill@20 and +7.7 at @100, also on fresh runs; pulses are a new kind of
flexibility the judge rewards when replayed)

## Why
Several truths deliver in pulses:
- sd-clinic-doses: 450 doses on one day a week (20 short pulses per period);
- sd-kanban: 25 cards and a capacity reset on day 1 of every 14-day sprint;
- sd-support-tiers: bug releases of 45-90 tickets a day for 3-6 days;
- also sd-university and sd-moderation.

The change scan has a 5-step minimum piece, so it cannot represent a 1-step pulse. Either it smears the
pulse into a 5-step piece, or the constant-inflow candidate wins and the row's drain absorbs the
deliveries. On sd-clinic-doses default the doses row drains 0.41 to outside and gets an
"expired -> doses" link of 2.26 (truth: expire 0.02 to expired), and skill@20 is -602% (-347% long).
The time-series outlier taxonomy tells a pulse (additive or innovational outlier), a temporary change
and a level shift apart by detecting them jointly with the model's coefficients. The signals review
ranked this sixth, and it is not yet in any topic.

## What was done
Branch `exp/impulse-inputs`, commit `0869f84` (worktree `.claude/worktrees/agent-af30dd0135be12792`); see the
experiment log. Modules: `sdlab/discovery/pulses.py` (building blocks), strategy
`sdlab/discovery/strategies/impulses.py`. Nothing shared was changed: the strategy hands the pulses to
the main line through the existing `opts["known"]` (known changes are taken out of the rows before
they are fitted and fed to every candidate when it is judged), so `matrix` is untouched (zero deltas).

- `pulses.detect`: Chen-Liu style. Robust scale from the MAD of successive differences; the window
  of 1 to 6 steps with the largest |sum| / (sigma sqrt m) is taken while it passes sqrt(2 log(6T));
  a window that grows when lengthened (up to 24 steps, by one SD) is a level shift, blocked and left
  to the change scan.
- `pulses.scan`: pulses in what a row's levels leave (u). Pieces of u first (PELT, minimum length 7,
  so a burst cannot be a piece), measured by their median (a pulse smeared into a piece does not move
  it), found again with the pulses taken out; a pulse within 6 steps of a cut that the neighbouring
  piece's level explains is a late cut, not a pulse.
- `pulses.joint`: find the pulses, refit the row's numbers without the pulse steps (an indicator per
  pulse step), until the pulses stay the same. Amounts: u less the piece's mean over non-pulse steps.
- Strategy: joint detection per stock, first with only its own level as a column (a fit through the
  pulses lets the drain absorb them, which turns them into a smooth wave), then twice with the
  columns `identify_one` chose with the pulses known. Stocks in whole numbers get a counting-noise
  floor on the scale (sqrt of what flows through them a step): otherwise a stock that changes by 0
  most steps has MAD 0 and every +-1 is a "pulse". A sudden loss is kept only where another stock
  gains in the same step (a batch move, or a co-flow used up as in university's enrolment using
  rooms); deliveries are kept alone. Pulses are returned as outside flows (constant form, inflow
  segments that hold each pulse on its step and 0 between), so the grader replaces them where the
  truth feeds the stock.

## Mechanism test
`tests/test_strategy_impulses.py`, on `synth.generate`: doses get 450 every 7th step, expire at 0.02,
are used by vaccination at 0.2 x waiting (bookings 30/60, unannounced, so waiting moves), 1000 steps.

| | doses drain | skill@20 | skill@100 | pulses |
|---|---|---|---|---|
| matrix | 0.33 (+ links done 1.06, waiting -0.96) | -1985% | -58600% | - |
| impulses | 0.0200 (waiting term 0.200) | 99.3% | 98.4% | 142 of 142, 0 false |

Controls: counting noise around constant intakes (one of 1 a step) gives no pulses in 2000 steps; an
unannounced level shift 20 -> 60 gives no pulses, a piece, and exactly the main line's model.

## Results (baseline v2.1: mean skill@20 29.6%, @100 29.3%; fresh 28.9% / 29.7%; 12 of 62 meet the goal; 586 s)

| version | @20 | @100 | fresh @20 / @100 | goal (fresh) | time |
|---|---|---|---|---|---|
| probe: running-median start (targets only) | clinic default -602 -> 73-76, moderation default -67 -> -373 | | | | |
| v1: own-level start, joint masked rows, both signs | 33.2% | 34.0% | 32.4% / 34.4% | 14 (14) | 2113 s |
| v2: gains only | 29.8% | 27.6% | 28.8% / 27.7% | 11 (12) | 1678 s |
| v3: losses only paired with a gain in a same-unit stock | 35.5% | 36.4% | 34.4% / 36.5% | 11 (12) | 1932 s |
| **v4: losses paired with a gain in any stock (final)** | **37.0%** | **37.0%** | **36.2% / 37.1%** | **14 (15)** | 1465 s |

v4, every run moving more than 2 points (skill@20 / @100, baseline -> now):
- better: clinic-doses long -347/-208 -> 91/90 (meets the goal), clinic-doses default -602/-864 ->
  -435/-856; university default 75/88 -> 97/96 and long 76/94 -> 99/100 (both meet the goal); kanban
  61/63 -> 76/96 and 57/60 -> 76/99; emergency default 5/69 -> 68/88; support-tiers long 42/-13 ->
  65/29; moderation long -99/-91 -> 25/-17; ev-fleet 32/48 -> 43/58 and 18/40 -> 26/49; print-shop
  -529/-2305 -> -341/-1529 and -158/-196 -> -145/-146; housing default 96/97 -> 98/99; manufacturing
  long 87/95 -> 90/97; farm-soil default @100 50 -> 60; restaurant default @100 -14 -> -10.
- worse: moderation default -67/-172 -> -358/-52 (worse @20, better @100); hospital long 92/86 ->
  86/69; learning-curve default -72 -> -81; support-tiers default @100 -1574 -> -1625.
- fresh runs track in-sample within a point on average, so the gain is not pulses replaying their own
  run's draws (the fresh run has the same schedule, though: see the risks).
- v1's fishery default 3/-102 -> 93/86 came from losses in fuel and in_port/at_sea that v3/v4 pairing
  keeps or drops differently; its gain is lost in v4. v1's clinic-doses long (-1007%) shows why lone
  losses are dropped: when the fridge runs dry, vaccinations stop, and pulses that replay that
  (waiting up, vaccinated down) leave the rows to explain the rest wrongly.

## Verdict
Adopt candidate. The mechanism works exactly where it should (deliveries, sprint loads, release
bursts, enrolment bursts), the bench gain holds on fresh runs, and nothing shared changed. Before
adopting, combine it with the behaviour-consistency gate and the piece-proof judge:
- **Judge flexibility.** Pulses are exogenous inputs the judge replays in-sample, like pieces. A
  pulse can stand in for an internal dynamic (university's enrolment burst is an unannounced change
  of an internal rate, found as a loss in admitted and rooms and a gain in year1) and the judge
  rewards it. On the bench's fresh run (same schedule) that replay is right; on a run with a
  different schedule it would not be. The piece-proof judge should price pulses as it prices pieces
  (hold them at their mean, or judge with them removed).
- **Variant fragility.** Several moves (pipeline default in v1, university long -110514% in v3,
  clinic-doses default between versions) come from the judge choosing a different variant on small
  changes of the data, not from the pulses themselves; the behaviour gate should catch the runaways.
- Cost: 2.5x run time (two extra `identify_one` fits per run, and known pulses judged as one segment
  per step).

## Open ideas
- Pool pulses at the same phase of a period ([periodic-inflows](periodic-inflows.md)): a weekly
  delivery as one periodic input would also generalise to runs with other draws of the schedule.
- With [starved-coflows](starved-coflows.md): clinic-doses default is still limited by the fridge
  running dry (lone losses dropped, but the rows still see the stopped vaccinations).
- Represent paired pulses as batch moves (from A to B), not as two outside flows.
- Count the pulses in the complexity budget; cap them per stock by what they save in BIC.
- Hand the judge the pulses compactly (segments only where nonzero) to cut the run time.
