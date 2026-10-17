# Outside inflows as a repeating profile

**Status:** done (wave 4, benchmark v2)  
**Verdict:** needs a combination (adopt candidate: +11.7 / +17.4 points in-sample and on fresh runs, 3 more runs meet the goal; echoes of a driver and the judge are the weak parts)

## Why
Every example's schedule repeats with a fixed period. The truths' `every` runs from 14 to 1800 steps,
with daily cycles of 24 inside sd-ev-fleet, sd-emergency, sd-moderation and sd-hospital, and weekly
deliveries in sd-clinic-doses. The main line pays one free value per piece over the whole run:
sd-print-shop long has 1362 pieces, sd-ev-fleet default 294, sd-support-tiers default 103. Pieces can
therefore follow anything, including internal dynamics (playbook convergence 6), and say nothing about
the next block, which is why the held-out judge failed: its forecast was a stale last piece.

A periodic profile has a fixed, small number of parameters: one value per phase segment, shared by
every period, plus a slow level. It cannot follow dynamics that do not repeat, and it forecasts
held-out blocks. Daily, weekly and yearly seasonality is the commonest structure in real operational
data, so this is a generic prior, not a bench trick. The generator must still contain aperiodic inputs
to check that.

## How it could be tried
- Strategy `periodic_inflows`, module `discovery/periodic.py`. After the first pass, detect a period
  on each row's residual and pooled across rows: periodogram or autocorrelation peaks between 2 and
  T/3, refined by how much variance the phase-folded mean explains.
- Fit the profile by PELT on the phase-folded residual (changes found once per phase), plus a slow
  component at a high price for drift between periods.
- Profile segments are columns in the row, so levels and profile are fitted jointly. There is no
  demeaning bias from short pieces.
- Accept a period only if it beats pieces by BIC, counting the profile's values and cut positions.
- The inflow is written as ordinary `inflow` segments, so the simulator and the page are unchanged.
- Mechanism test: chain a -> b -> c, with a's intake on a 24-step day profile (4 / 12 / 9) varying
  ±20% from day to day, 2000 steps. Baseline: a gets more than 100 pieces and b gets chance pieces.
  Strategy: period 24 found, a's drain within 0.02, no inflow into b or c, skill@20 at least the
  baseline's. Control: an intake that changes at random times gets no period and the matrix result.
- Targets: sd-ev-fleet, sd-emergency, sd-hospital, sd-moderation, sd-clinic-doses, sd-kanban,
  sd-restaurant, sd-print-shop, sd-support-tiers, sd-services.

## What was done
Branch `exp/periodic-inflows` (worktree `.claude/worktrees/agent-a53e4dfe314e10fbe`; commit: the branch
head). Module `discovery/periodic.py`, strategy `periodic_inflows`, one `matrix` option
(`varying_inflow`, default off: rows a strategy knows have a varying inflow count as changing in
conservation).
1. Each stock's main-line row (levels and pieces) gives a residual. Candidate periods per row: the
   fold score (sum of squares of the phase-folded means over the noise variance, against chi-squared
   with P - 1 degrees of freedom, every P at once from the autocovariance); the sharpest peaks and
   their divisors that are peaks too; the two best by a profile-only BIC are fitted fully.
2. Full fit: levels (stepwise) with the profile segments and slow pieces projected out (from counts,
   no columns formed); the profile's segments by optimal partitioning of the circular fold (each
   segment costs 2 log T sigma^2: value and position); slow pieces by PELT, at least one period long,
   at twice the price. Alternated up to four times.
3. Kept if its BIC (levels + 2 x segments + 2 x slow changes + 1) beats both pieces and a constant by
   log T, and (v2) if its gain over a constant is at least 0.25 of the strongest profile at its period.
4. Kept profiles become known changes; the 16 main-line variants run on the rest; each candidate's
   profiles are re-measured beside its final numbers, written as ordinary `inflow` segments (profile
   plus any pieces found beside it), and judged; the main line's own best competes in the same judge.

## Mechanism test
`tests/test_strategy_periodic_inflows.py`: chain a -> b -> c (0.2, 0.1, 0.05), a fed on a 24-step day
(4 / 12 / 9) scaled by a factor in 0.8..1.2 per day; 2000 steps.

| | matrix | periodic_inflows |
|---|---|---|
| a's inflow | 56 pieces (about 250 changes) | period 24, 4 segments, 1 slow piece |
| a -> b | 0.172, plus "a drains faster when b is high" 0.107 and a link a -> b | 0.197 |
| inflow into b or c | none | none |
| skill@20 / @100 | -462% / -631% | 99.8% / 99.7% |

The brief expected more than 100 pieces; the change scan's price allows only 56, which is why the
main line reads the rest as dynamics. Control: an intake changing at random times gets no period and
exactly the main line's flows. Without counting the profiled row as changing in conservation, a's drain
stays at 0.143 (the day-to-day factor the profile cannot follow biases it) and the judge picks a
"trust rows" candidate at -70%.

## Results (baseline v2.1: 29.6% / 29.3%, 12 of 62; fresh runs 28.9% / 29.7%, 12)
| version | skill@20 | skill@100 | goal | fresh @20 / @100 | fresh goal | time (summed) |
|---|---|---|---|---|---|---|
| v1: every profile that pays | 38.0% | 44.4% | 15 | 37.4% / 44.7% | 15 | 1775 s |
| **v2: echoes dropped (ratio 0.25)** | **41.3%** | **46.8%** | **15** | **40.7% / 47.0%** | **15** | 2172 s (3.7x; machine loaded) |

Moving by more than 2 points at skill@20 (v2, in-sample; fresh within a few points): bakery default
-1170 -> 50, clinic-doses default -602 -> -8 and long -347 -> 59, pipeline default 40 -> 99.7,
support-tiers long 43 -> 95, housing long -120 -> -2, emergency 5 -> 25 / -48 -> 18, kanban 61 -> 79 /
57 -> 76, ev-fleet long 18 -> 38, hospital long 92 -> 99, orders long 86 -> 99.5, fishery default 3 ->
21, ci long 88 -> 90, print-shop default -529 -> -107; worse: webshop-stock long 64 -> 37 (@100 49 ->
-49), bakery long 19 -> -21, sawmill long -207 -> -219, hospital default 97 -> 94. New goal runs: orders
long, pipeline default, support-tiers long; none lost. v1 also lost manufacturing long 87 -> -66 (a
yearly demand: material, inspection and finished were profiled too).

## Lessons
- A profile is a much better outside inflow than pieces where it holds, and the gain is in the drains:
  the grader feeds the truth's inflow, so the inflow itself never mattered there, only what the pieces
  did to the rows.
- It does follow dynamics that repeat: in a system driven by a periodic input every stock's misfit
  repeats (manufacturing; the webshop shelf, fed by a hidden stock), and a rate that switches by time
  of day times a level (moderation `post`) looks like a profile. The echo ratio is a crude prior; the
  behaviour-consistency gate or the piece-proof judge should replace it.
- Judge risk (flexibility the current judge can be fooled by): a profile replays the run's repeating
  input, so a model with a spurious profile into an internal stock judges well on the data and grades
  badly (truth inflows). Fresh runs do not catch it (same schedule). The mechanism stays usable as an
  option for that combination: `periodic.find` returns the profiles; the strategy takes
  `source_ratio`, `period_screen`, `period_candidates` and `against_main_line`.
- Day-to-day variation in a profile's level biases the drain (0.143 for 0.2 in the test) unless the row
  trusts its receivers; a per-period scale is the obvious refinement.

## Open ideas
- Per-period scale (profile x level per period) for ev-fleet-like days, and a profile of a link's
  coefficient (k by phase x level) offered as a column for moderation's `post`.
- Restrict profiles to stocks the found structure says are fed from outside, instead of the echo ratio.
- With the inflow-conditioned held-out judge: a profile forecasts held-out blocks, pieces do not.
- Speed: run only the chosen variant with the profiles instead of all 16 plus the main line.

## Sources
Cleveland et al. (1990) J. Official Statistics 6(1):3-73 (STL); Bandara, Hyndman and Bergmeir (2021)
MSTL, arXiv:2107.13462; Hyndman and Athanasopoulos (2021) Forecasting: Principles and Practice, 3rd
ed. (seasonal dummies, dynamic regression); Killick, Fearnhead and Eckley (2012) JASA
107(500):1590-1598; [held-out-judge](held-out-judge.md) (why stale pieces sank it);
[change-price](change-price.md).
