# Outside inflows as a repeating profile

**Status:** idea (not started)

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

## Sources
Cleveland et al. (1990) J. Official Statistics 6(1):3-73 (STL); Bandara, Hyndman and Bergmeir (2021)
MSTL, arXiv:2107.13462; Hyndman and Athanasopoulos (2021) Forecasting: Principles and Practice, 3rd
ed. (seasonal dummies, dynamic regression); Killick, Fearnhead and Eckley (2012) JASA
107(500):1590-1598; [held-out-judge](held-out-judge.md) (why stale pieces sank it);
[change-price](change-price.md).
