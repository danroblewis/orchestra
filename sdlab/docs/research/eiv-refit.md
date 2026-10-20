# Errors in variables: refitting the numbers when levels are measured with error

**Status:** done, round 1 (code e8edf28, and 5a31020 for the margin below). A stage added to 40 strategies, each with its own copy
(`eiv.py` in a package, or the same code inline with names prefixed `_eiv_` in a single-file
strategy; sdlab/CLAUDE.md invariant 11).

## The failure

On Kubernetes rung 1 (case 300, requests in flight: `1 x traffic` in, `0.5 x inflight` out) almost
every strategy failed both measurement-error variants (5% error on the levels) while passing none and
counts. They found `1.220949 x traffic` / `0.6124 x inflight` on meas-long and `1.2748` / `0.6373` on
meas-short: 22-27% off with the ratio right.

**Diagnosis (invariant 4b).** The numbers are the one-step least-squares fit on the measured levels:
regressing `y[i] - y[i-1]` on `traffic[i]` and `y[i-1]` reproduces them to every digit. That fit is
not consistent under measurement error: the error at `i-1` is in the regressor and, with the other
sign, in the change, so the drain comes out too fast, and the input coefficient follows to keep the
steady state. The bias does not shrink with run length (long 22%, short 27%). The data can do better:
a Kalman likelihood of the true structure gives 1.0045 / 0.5049 (long) and 1.019 / 0.511 (short),
and odefit's output-error fit passes both. So this is the method's fault, not the data's limit.

## The change

`refit(flows, stocks, run, opts)` keeps the structure and refits its numbers (a proportional rate's
k, a linear rate's constant and term k's, a constant rate, a found inflow's piece values, per era):

1. **The one-step fit** of those numbers (Gauss-Newton on `Model.change`, rows weighted by each
   stock's residual spread).
2. **A test for measurement error.** Measurement error leaves the one-step residuals negatively
   correlated from one step to the next; counting noise leaves them white, a structure that misses
   something leaves them smooth. Each stock's lag-1 correlation as a z-score; the refit goes on only
   when one is below the one-sided `p < 1e-3` point (Bonferroni over the stocks).
3. **The instrumental-variables fit.** Each row's regressors (the derivative of the step's change
   with respect to each number, at the levels `y[i-1]`) are instrumented by the same derivative at
   `y[i-2]`, at the row's own time and inputs. White measurement error makes `y[i-2]` independent of
   the errors in row `i`; counting noise is independent of every earlier level; measured inputs are
   their own instruments. So the fit is consistent under both noises.
4. **A guard.** The refitted numbers are kept only if the model then runs at least as close to the
   data over 5, 20 and 100 steps (the main line's judge, a multi-step error, which measurement error
   does not bias). This keeps the found numbers where the structure is wrong and the instruments do
   not suit it (on the trial below: `082-noisy-link-loop` meas-short for unified, equivalent -> fail
   without the guard, kept with it).

No step looks at the case, the variant or what kind of input there is. Flows that read a stock
nobody measures, uneven times and missing points are left alone.

**kalman_lna, engine_forms (its `_kalman` copy) and combined2.** Six of the cells failed differently:
these three send data with a measurement error to their Kalman filter, whose atoms read no measured
input, and found `2.087 x inflight` out with a spurious `2.064 x inflight` link in (long) or 0.536
out, a 0.339 link and 13 inflow pieces (short). Where the filter answers for a measurement error,
its model is now weighed against the base's answer with refitted numbers on the same multi-step
judge, and the base's is kept only when the filter's multi-step error is over 1.25 times its own (a filter's model with an unmeasured stock is always kept: the
judge sees only measured levels).

## Ladder results (2026-10-20, Mac, `sdlab-ladder run --jobs 4 --timeout 600`, single-threaded)

Before: each strategy's latest stored status, snapshotted just before the runs. After: the runs on
commits e8edf28 (37 strategies) and 5a31020 (kalman_lna, engine_forms, combined2). The scorer's hash
changed between the two (an uncommitted noise-oracle change elsewhere in the checkout); a flip whose
found flows are identical before and after is marked as the scorer's.

| cells | re-run | fail -> pass | fail -> equivalent | pass -> anything else | equivalent -> fail |
|---|---|---|---|---|---|
| 300, 301 (all variants) | 400 | 79 (every one of the 79 target cells) | 0 | 0 | 0 |
| 080, 081, 082, 086, 139 (meas and counts, short and long) | 800 | 10 | 15 | 0 | 1 (structures 139 meas-long: same flows, the scorer's) |
| 003, 010, 014, 021, 023, 027, 142, 143, 303, 304 (all variants) | 1,480 | 4 | 0 | 0 | 0 |

So 57 other cells per strategy, 2,280 in all, with no regression from the code. The other gains:
086-noisy-stepping-inflow meas-long (archetypes, combined, combined_lean, combined_misfit, combined_r2,
periodic_inflows, structures), 082-noisy-link-loop meas-long (combined_lean, combined_r2, schedules),
142-oscillator-pushed-by-measured-input meas-long (earned_pieces, held_out, matrix_v2,
starved_coflows), and 081-noisy-link meas-long fail -> equivalent for 15 strategies.

On case 300 the refit gives 1.0838 / 0.5410 (short) and 0.9783 / 0.4901 (long) for every strategy.
That is within the bare 10% tolerance the scorer used before its noise oracle covered measured inputs,
and within 3 SE under the current one (SE 0.056 / 0.028 short, 0.023 / 0.012 long). Short is 8.4% off,
an instrumental-variables fit is less efficient than the Kalman likelihood (1.9% there): a Kalman
refit is the next step if a tighter short-run estimate is wanted.

**Not fixed here:** periodic_inflows meas-long still crashes (`'traffic' is not in list` in
remeasure: the measured-input KeyError group, not this cause), so it passes meas-short only.

The first version of the filter comparison (e8edf28, base kept whenever closer) turned 080 and 081
meas-long pass -> fail/equivalent for kalman_lna, engine_forms and combined2, and 086 meas-short
pass -> fail for combined2; the 1.25 margin (5a31020) removed all of them.

## Round 2: seven more strategies (commit 4006a72)

common_cause, sindy, shared_noise, numopt_bo, numopt_cma, numopt_nm and numopt_powell had no refit:
on 300 meas they stored the one-step fit (sindy, shared_noise: 1.275 / 0.637 short, 1.221 / 0.612
long; common_cause 1.204 / 0.602, 1.198 / 0.601), and numopt_*'s in-sample judge rejected the
output-error search on meas-short (e0 0.07804 < e1 0.0844), leaving the biased base. Each now carries
the same eiv.py (byte-identical copy; sindy inline with `_eiv_` names, from held_out.py) wrapped
around its identify; for numopt_* the refit runs on the final answer, after the search and its judge.
Applying the refit to their answers gives 1.0838 / 0.5410 (short) and 0.9783 / 0.4901 (long), as for
the 40.

Paired check, same code and scorer, base (`_identify`) vs refitted, in one process
(`scratchpad .../eiv7/pair.py`), on 204 cells per strategy (300, 301 and 080-088, 112, 139, 141-143,
303, 306, 002, 007, 011, 016, 023, all variants): 1,428 cells, refit used in 148; 31 fail -> pass,
2 pass -> equivalent, no other change.

- fail -> pass: all 10 target cells (300 meas-short and meas-long for common_cause, sindy,
  shared_noise; 300 meas-short for the four numopt), 023-injection none-short/long (sindy and the four
  numopt; the refit lands on 0.5 / 0.2 / 10 exactly), 141 none (sindy x2, numopt_bo x2,
  numopt_powell long), 142 meas-long (common_cause, sindy), 143 none-short (four numopt).
- pass -> equivalent: 087-noisy-injection outliers-long for shared_noise and numopt_cma. The outliers
  make the white test fire (z -12.9), and the IV fit enlarges a spurious A -> B link already in the
  structure from 0.011 to 0.050 (judge 0.1032 -> 0.1023), and moves the true numbers away (0.505 ->
  0.486, 10.11 -> 9.72). The module does the same for matrix (one of the 40; its stored 087
  outliers-long result predates e8edf28, so the board does not show it yet). A fix belongs in eiv.py
  for every copy (e.g. a robust or margin-gated acceptance), not in these seven alone.
