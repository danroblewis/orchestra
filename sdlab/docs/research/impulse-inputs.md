# Pulses: one-step arrivals and short bursts as their own kind of input

**Status:** idea (not started)

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

## How it could be tried
- Strategy `impulses`, a joint detector beside `changes.pelt`. Use a robust scale (MAD of successive
  differences) and iterate in the style of Chen and Liu:
  1. take the largest standardised candidate;
  2. classify it as a 1-step pulse, a 2-6-step burst or a level shift;
  3. add it as an indicator column and refit the row (levels, pieces and pulses).
  Stop when nothing passes a threshold of about sqrt(2 log T) robust SDs. PELT runs on what the pulses
  leave.
- Pulses at the same phase of a period are pooled ([periodic-inflows](periodic-inflows.md)), and the
  number of pulses is capped by [complexity-budget](complexity-budget.md).
- Mechanism test: doses receive 450 every 7th step, expire at 0.02 and are used by vaccination at 0.2 x
  waiting. Baseline: doses drain above 0.2 and skill@20 below 0. Strategy: pulse recall at least 95%,
  at most 2 false pulses, drain within 0.005, skill@20 above 0.9. Controls: counting noise around a
  constant intake gives no pulses in 2000 steps; a real level shift becomes a piece, not pulses.
- Targets: sd-clinic-doses, sd-kanban, sd-support-tiers default, sd-university, sd-moderation.

## Sources
Chen and Liu (1993) JASA 88(421):284-297; Tsay (1988) J. Forecasting 7(1):1-20; Fox (1972) JRSS B
34(3):350-363 (outlier types); literature report [signals and time series](literature/signals-and-time-series.md)
section 4 and summary item 6.
