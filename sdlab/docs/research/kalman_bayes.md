# kalman_bayes: a posterior in place of one best fit

**Status:** done (ladder: kalman_lna's failing and borderline cells, the noisy set, Kubernetes 300/301; 484 cells, run 376 of the store, 2026-10-20).
**Strategy:** `sdlab/discovery/strategies/kalman_bayes/`, a copy of `kalman_lna` as at commit `e8edf28`
(every module but `bag.py`, `ekf.py`, `mcmc.py`, `posterior.py`; `_point` in `__init__.py` is
kalman_lna's `identify`). Commits: `783f90f` (first version), `4004dfa` (time caps, faster filter),
`3bcbc1f` (the version measured below; studies `282d534`). Tests `tests/test_ladder_kalman_bayes.py` (4); study script
`tests/study_kalman_bayes.py`, `tests/study_kalman_bayes_point.py`. Idea from [bayesian-structure.md](bayesian-structure.md) (playbook M10).
No new dependency: the sampler is a hand-written adaptive Metropolis (numpy, scipy, numba already in use).
**Verdict:** reject as an answer, keep as a reading of uncertainty. Returning the posterior median
in place of the point fit loses 25 passes and gains 12 against the same point answer on the same
cells (164 vs 177 of 484). It helps only under reporting noise (+9 / -4: the measurement-error sweep
088, 085, 081 weekly) and hurts on noise-free (0 / -11) and counting-noise cells (+3 / -10). The
95% intervals cover the truth 80% of the time where the structure is right (nominal 95%). The
borderline failures are bias, not width: the truth is inside the interval for 5 of 17. **The scorer's
tolerance is about 2.9 times the posterior's 95% half-width** (about 5.6 posterior sds), so it is
loose, not tight, for noisy data. It is tighter than the posterior only for 6% of the numbers, mostly
noise-free cells on a ridge (056). The flows' inclusion probabilities do tell true flows from others
(mean 0.89 vs 0.63), but the blocks alone cannot be trusted to set the structure.

## The question

kalman_lna returns one best fit. Does a posterior help: (a) a structure made of the flows that
resamples of the data keep finding (Ensemble-SINDy / stability selection), and (b) every number's
posterior under kalman_lna's own likelihood, returned at its median? And when a point estimate
misses the scorer's tolerance by a little, is the truth inside the posterior's 95% interval, i.e. are
the scorer's tolerances in line with what the data pin down?

## What it does

1. **The point answer**: kalman_lna's (its own copy), unchanged.
2. **The block ensemble** (`bag.py`): the whole discovery is run again on 8 contiguous blocks of the
   run, each 70% of the reports, starts spread evenly (eras kept, injections and measured inputs cut
   to the block). A flow is keyed by its ends, the stocks its rate reads, its co-flows and effects
   (numbers and inflow pieces aside). Its **inclusion probability** is the share of blocks whose
   model has it. The **blocks' structure** is the point answer's flows found in more than half the
   blocks, plus flows more than half the blocks have that it lacks (plain rates only). Blocks get at
   most 2x the point run's time each and 6x in all; fewer than 4 finished blocks: no ensemble.
3. **The likelihood** (`ekf.py`): kalman_lna's state-space model written on found flows of any form
   the simulator runs (so it serves the base's answers as well as the filter's): the stocks (and any
   stock the flows name that nobody measures) are hidden states on the grid of every step,
   `x_k = x_(k-1) + inj_k + f(x_(k-1) + inj_k) + w_k`, `f` linearised at a fixed reference path (the
   reports interpolated; a hidden stock's inferred levels), process noise
   `phi * sum_f a_f v_f v_f' + diag(tau)` (lna's counting noise with a free multiplier, plus extra
   variance), reports as levels or window means times a scale, with `1/12 + alpha + rho2 level^2`
   error, the found reporting delay applied to the injections and times; reports beyond 5
   standardised innovations left out (kalman_lna's rule). The filter takes the reports one at a time.
4. **Which structure** (`__init__.py`): the joint mode (Powell) of the found structure's numbers and
   noise numbers, and of the blocks' structure on the same reports; the blocks' structure replaces the
   found one only when its BIC (noise numbers counted) is lower. The blocks propose; the whole run's
   evidence decides (see "What went wrong first").
5. **The posterior** (`posterior.py`, `mcmc.py`): a uniform prior on each number within 10x its found
   size of the found value, with a proportional rate's k, a constant and an inflow's pieces not below
   0 (the engine floors a rate at 0, so below 0 the likelihood is flat and a flat prior is improper);
   uniform priors on the log noise numbers. The flows' numbers are sampled by adaptive Metropolis
   (Haario et al. 2001; first proposal from a finite-difference Hessian at the mode, 2000 burn-in, up
   to 10000 draws, at most 90 s for mode and chain) **with the noise numbers held at the joint mode**
   (empirical Bayes: sampled jointly, noise numbers sitting at their bounds left chains with an
   effective sample size near 10). The returned model is the posterior median of every number; each
   number carries `"<key>_post": {median, sd, lo, hi}` (95% interval) and each flow its
   `"inclusion"`, so the stored results keep them; the result's `posterior` key holds the rest
   (inclusion of every flow seen, BIC of both structures, effective sample sizes, acceptance, noise
   numbers, seconds per stage).

One algorithm on every cell: no branch on case, variant or input type.

## Ladder (`uv run sdlab-ladder run --strategies kalman_bayes --cases <99 cases> --jobs 4 --timeout 600`, commit `3bcbc1f`, run 376, 2026-10-20)

**Which cells.** kalman_lna's failing cells (247 local test cells) and its passes whose worst number
uses over 70% of the scorer's allowed error (20), the noisy set (`tag:noisy`, 080-088, 139, 141-143),
and Kubernetes 300 and 301. The run covers every variant of those 99 cases: 484 cells. The `--cases` list, as id prefixes
(draws as `NNN#k`): `011,017,018,022,024,033,045#2,046#4,047#5,054#1,054#3,056#3,056#4,056#5,056#6,056#7,063,080,081,082,083,084,085,086,087,088#1,088#2,088#3,088#4,088#5,088#6,088#7,112,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,141,142,143,152,153,154,155,156,157,158,159,160,161,171,172,196,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,220,221,222,224,225,226,300,301,303,306,307`. The machine's load was 200-320 on 28 cores during
the run. Nothing timed out or raised an error. 473 cells carry a posterior. In 11 the point answer was
returned (no numbers to sample, or a likelihood that was not finite).

**Paired with its own point answer** (`tests/study_kalman_bayes_point.py`: the same code's `_point`,
which is kalman_lna as at `e8edf28`, run and scored on the same cells and machine; the stored
kalman_lna rows mix six code versions, most from before the errors-in-variables refit):

| | cells | point passes | kalman_bayes passes | gained | lost |
|---|---|---|---|---|---|
| noise-free (`none`) | 166 | 39 | 28 | 0 | 11 |
| counting noise (`counts`) | 192 | 60 | 53 | 3 | 10 |
| reporting noise (meas, outliers, gaps, weekly, bias, lag) | 126 | 78 | 83 | 9 | 4 |
| **all** | **484** | **177** | **164** | **12** | **25** |

(equivalent: 51 point, 49 kalman_bayes.) On the noisy set alone (156 cells) it is 114 passes vs 111.
On Kubernetes 300 and 301 every cell passes both ways (10 of 10).

Against the stored kalman_lna rows (`tests/study_kalman_bayes.py --run 376`), the result is 8 passes
gained and 29 lost, with 6 cells kalman_lna has not run (306, 307).

- **Gained** (12): 088 meas-long #3, #4, #5 and meas-short #5, #6. The likelihood reads the
  measurement error jointly with the numbers, and the posterior median removes the bias the point
  fit kept. Also 085 bias-short and gaps-long, 081 weekly-short, 083 outliers-short, 024 counts-long,
  131 counts-long and 056#5 counts-short.
- **Lost** (25):
  - Ten noise-free cells of 056 (the zero-floor sweep, none-short and none-long of #3-#7). The point
    fit is exact. The posterior is honest here (the truth is inside the interval), but its median
    lands 2-4% off on a ridge that `sdlab-ladder analyse` calls unidentifiable, against the 2%
    noise-free tolerance.
  - 056 counts-short #4, #6, #7: a stock at its zero floor. The linear-Gaussian approximation is
    confident and wrong there.
  - 017 and 018 counts (4 cells): an effect's numbers are not sampled, so the rates move under a fixed
    curve. Also, the counting noise's variance grows with the flows, which pulls a stock's gross
    flows up.
  - 022 counts-long, 086 gaps-short, meas-short and meas-long (a stepping inflow's drain drifts), 083
    weekly-short, 156 counts-short (hidden stage), 082 counts-short (now equivalent).
  - Lost equivalences on noise-free data: 045#2 and 054#3 (both lengths), 046#4.

**Time per cell.** Median 21.0 s against its point answer's 2.9 s (7.4x per cell). 90th percentile
182 s against 26 s, longest 430 s. In all, 29,110 s against 5,409 s. The blocks cost about 5-6 point
runs. The posterior is capped at 90 s; the likelihood takes about 1.3 ms per evaluation on a 2,000-step,
3-stock run, so 12,000 Metropolis steps take about 15-60 s under this load.

## Does the posterior explain the borderline failures?

`tests/study_kalman_bayes.py --run 376 --point <point.json>`. Every true number part with a
posterior: 1,158 parts in 415 cells. The interval is each number's 2.5-97.5% posterior quantiles,
scored as flows. "allowed" is the scorer's own error bound, max(rel x |true|, floor / level,
3 x oracle SE).

| parts | n (cells) | truth in 95% interval | median abs(z) (0.67 if calibrated) | abs(z) > 1.96 | allowed / 95% half-width (median, quartiles) | allowed < half-width |
|---|---|---|---|---|---|---|
| all | 1,158 (415) | 0.635 | 1.20 | 0.351 | 2.88 (1.79-5.54) | 0.125 |
| structure right (recall 1, nothing spurious) | 608 (200) | 0.803 | 0.88 | 0.188 | 2.85 (2.10-4.13) | 0.064 |
| - noise-free | 108 (39) | 0.870 | 0.17 | 0.102 | 8.72 (2.35-33.6) | 0.194 |
| - counting noise | 201 (69) | 0.771 | 1.00 | 0.209 | 2.84 (2.08-4.06) | 0.065 |
| - reporting noise | 299 (92) | 0.799 | 1.07 | 0.204 | 2.69 (2.07-3.38) | 0.017 |

- **Calibration.** The intervals are too narrow. Where the structure is right they cover 80% instead
  of 95%, and the median |z| is 0.88-1.07 under noise (0.67 if calibrated): the sds are about 1.4-1.6
  times too small, or the medians biased. Where the structure is wrong, coverage falls to about 46%;
  the numbers then stand in for missing or spurious flows. Three simplifications are the likely
  causes:
  - the reference path is held fixed (no relinearisation);
  - the noise numbers are held at their mode;
  - the counting-noise variance is tied to the flows' sizes.
- **Borderline misses** (structure right, error 1-2x the allowed): 17. The truth is inside the 95%
  interval for 5 of them: four from 056#3 noise-free and 142 meas-long. The other 12 are confidently
  off:
  - 056 counts at the floor (7);
  - 080 meas-long, 086 gaps-short and meas-long (a drain, with sd 0.006-0.018 against an error of
    0.025-0.065);
  - 083 weekly-short;
  - 154 counts-long;
  - 017 counts-long.
  So the borderline failures are mostly bias (the floor, the approximation, the structure around
  the number), not the data's spread. A wider tolerance would pass them for the wrong reason.
- **The scorer's tolerances against the posterior.** Under noise, the allowed error is a median 2.7-2.9
  times the posterior's 95% half-width: about 5.5 posterior sds. It is tighter than the half-width for
  only 2% (reporting noise) to 7% (counts) of the numbers. **The tolerances are loose against what the
  data pin down, not tight.** A number outside them is far outside the posterior too, as the 12
  confident borderline misses show. The exception is noise-free data: the 2% exact tolerance is tighter
  than the posterior's half-width for 19% of those numbers. Those are cells like 056 none, where the
  levels sit at an equilibrium and only their rounding informs the ratio of inflow to drain. Tolerances
  are not changed here (invariant 5); the comparison is for the scorer's owner.

## The block ensemble

468 cells had at least 4 blocks. Over the flows returned:
- flows between a pair of ends that the truth has: mean inclusion 0.89, 10.5% at or below 0.5 (1,563 flows);
- flows between other ends: mean inclusion 0.63, 38.7% at or below 0.5 (346 flows).

The inclusion probability carries real information about which flows are true. But in 124 cells
the BIC kept the point structure over the blocks' structure, so low-inclusion flows were returned
(the study's inclusion section; which structure each cell chose is not stored, only the returned flows'
inclusion).

## What went wrong first (commits `783f90f`, `4004dfa`; runs 371-372, stopped)

- **The blocks voted true flows out.** On a long noise-free run the information sits in the first
  transient. Blocks that start later see a settled system and find nothing: 040#2 none-long gave
  three true flows in the first block and none in the last two. With the blocks' structure taken as
  it was, 040#2, 050#5-#7 and 088#5 lost their passes. Now the blocks only propose, and the whole
  run's BIC decides.
- **A flat region below zero.** The engine floors a rate at 0, so below 0 the likelihood is flat. A
  flat prior then let a drain wander to -1.6e5. The prior is now proper: k, constants and pieces
  not below 0, each within 10x its found size.
- **Joint sampling of the noise numbers.** It left an effective sample size near 10. The noise
  numbers are now held at the joint mode.
- **Time.** At first a cell used up to 510 s, because the chain ran until the deadline. Now the
  posterior is capped at 90 s and the blocks at 6 point runs. The filter takes the reports one at a
  time, which is 4-5x faster.

The watcher's batch that started at 07:23 (run 370) held the first version in memory. It re-ran 92
of these cells after run 376 with that code, so the store's latest rows for them are run 370's
(hash `6acc054`). Run 376's rows stay in the history and are what the study reads; the watcher will
re-run the 92 as stale.

## Open

- Return the posterior **mode**, the MAP under this likelihood, rather than the median where the
  posterior sits on a ridge. Or keep the point answer and attach the posterior as uncertainty only.
  That would keep the reporting-noise gains only if they come from the likelihood, not from the median.
- Sample an effect's numbers too. Relinearise the reference path at the posterior mode. Hold phi at 1
  as kalman_lna does, with tau freed only where it pays: this tests whether the counting-noise
  variance link causes the 017/018 and 086 drifts.
- Rebuild the blocks: a residual block bootstrap from the filter's smoother (process and measurement
  residuals kept apart, as in Dogan 2007), so every resample keeps the transient.
- Show inclusion and intervals on the ladder pages: the uncertainty the idea asked for.
