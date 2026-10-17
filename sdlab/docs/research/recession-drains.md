# Drains measured where nothing flows in (recession analysis)

**Status:** idea (not started)

## Why
In the one-step fit a drain and an unannounced outside inflow are confounded, and pieces bias the
drain. Within-piece demeaning biases it by about (1 + a)/(m - 1)
([change-price](change-price.md)). On sd-pipeline default, under constant inflows, the inbox drains
0.11 against a true 0.3, and skill@100 is -178%.

Many truths have stretches with no inflow at all:
- sd-restaurant: doors close, and arrivals are 0.3 a minute in the mornings;
- sd-farm-soil: no growth for 23 of every 52 weeks;
- sd-clinic-doses: six days in seven without a delivery;
- also sd-emergency at night, sd-kanban sprint days 2-14, and sd-fishery's closed season.

On those stretches a stock's level decays freely, and its drain can be read off the recession curve
with no inflow model at all. Hydrology does this backwards (Kirchner 2009): identify the
storage-discharge law from recessions, then invert it to recover the unmeasured input. Here that
means fixing the drain first, then estimating the inflow with the drain fixed, which cannot bias the
drain.

## How it could be tried
- Strategy `recession`. From the first pass, mark candidate quiet steps per row: steps whose local
  inflow estimate (piece value) sits at the bottom of its distribution and is not distinguishable from
  0, or runs of at least m consecutive falls.
- Fit the row's level coefficients on quiet steps only, with no inflow term. If there are enough quiet
  steps (at least 5 x the number of coefficients) and the quiet fit differs from the full fit by more
  than 2 SE, keep the quiet coefficients.
- Then estimate the pieces on all steps with those coefficients fixed. Never refit the levels on the
  reported pieces: the change-price spiral needs that refit.
- Enter the result as a candidate.
- Mechanism test: an inbox whose intake alternates on and off (9 per step for 20 steps, then 0 for
  20, with unannounced variation) drains 0.3 to working, and working drains 0.2; 600 steps. Baseline:
  inbox drain off by more than 0.05. Strategy: within 0.02, skill@100 at least 0.9. Control: an intake
  that never stops (always above 3) gives no quiet steps and the matrix result.
- Targets: sd-pipeline default @100, sd-restaurant @100, sd-farm-soil @100, sd-clinic-doses, sd-kanban,
  sd-fishery, sd-emergency.

## Sources
Kirchner (2009) WRR 45(2):W02429; Brutsaert and Nieber (1977) WRR 13(3):637-643 (recession analysis);
literature report [compartmental analogues](literature/compartmental-analogues.md), summary item 8;
[change-price](change-price.md) open ideas (estimate the levels beside cheap pieces and never refit them).
