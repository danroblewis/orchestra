# Unannounced eras: recurring regimes found in the data, then fitted as eras

**Status:** idea (not started)

## Why
In 14 of the 31 truths, an internal flow's equation changes without being announced. Examples:
- sd-moderation: posting per creator switches between 0.1 and 0.03 every 10-14 steps (day and night);
- sd-fishery: the launch gap's goal switches between 36 and 0 with the season;
- sd-bakery and sd-print-shop: the restock time switches 10 -> 60 -> 10 -> 40 and 5 -> 30;
- also sd-farm-soil (restore), sd-saas (churn), sd-university, sd-manufacturing, sd-orders, sd-supply,
  sd-ci and sd-brewery.

The main line can absorb such a change only in an outside inflow's pieces. Pieces take the constant
part of the change, never the coefficient part (a gap's -1/time, a link's k).

On sd-moderation every candidate predicts the data *worse than assuming nothing changes* (judge error
3.2 on the default run, 6.6 on the long run). On sd-fishery default it is 1.4. The machinery for
announced eras works once it has labels: on v1 it took sd-eras long from -1748% to 50% and sd-fishery
default from 27% to 97%. [regime-models](regime-models.md) proposes switching models for the
*outside inflow*. This idea finds regimes in the *coefficients* and hands them to the existing
per-configuration columns.

## How it could be tried
- Strategy `latent_eras`, module `discovery/regimes.py`. Per row, estimate the coefficients locally on
  the main line's chosen columns: windowed regressions, or Kalman-smoothed time-varying coefficients with
  a random-walk prior.
- Cluster the coefficient paths into K = 2-3 recurring regimes (Markov-switching regression), with K and
  the number of switches chosen by BIC. Share the regimes across rows whose switch times coincide.
- Append the inferred regimes to `opts["eras"]` as synthetic labelled eras, merged with announced ones.
  Run `identify` with `split_eras`, so per-configuration columns stay only where they pay.
- A regime must recur (at least 3 switches each way) and must change a coefficient, not just the
  constant. A change in the constant alone stays an inflow piece.
- Mechanism test: creators (inflow 20, drain 0.008) -> screening by a link at k = 0.1 for 12 steps and
  0.03 for 12 steps, repeating unannounced; screening -> published 0.5. Baseline: skill@20 below 0.5.
  Strategy: two regimes, switch times within 1 step, k within 0.01, skill@20 above 0.9. Controls: an
  outside-inflow change alone (pipeline-like) gets no regime; a model with no changes gets K = 1.
- Combine with [periodic-inflows](periodic-inflows.md): a day/night regime is periodic, so the phase can
  label it.

## Sources
Hamilton (1989) Econometrica 57(2):357-384; Kim (1994) J. Econometrics 60(1-2):1-22; Dureau,
Kalogeropoulos and Baguelin (2013) Biostatistics 14(3):541-555 (rates that change unannounced as a
random walk); Deyle et al. (2016) Proc. R. Soc. B 283:20152258 (S-map local coefficients); Mangan et al.
(2019) Proc. R. Soc. A 475:20180534 (hybrid-SINDy); Ohlsson, Ljung and Boyd (2010) Automatica
46(6):1107-1111; our eras result in DISCOVERY-EXPERIMENTS.md.
