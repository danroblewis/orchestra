# odefit: per-step models fitted by output error, for smooth measured data

**Status:** done for the physics cases (ladder, commit `8d8e8c6`); standard tests: see "Standard tests" below.
**Strategy:** `sdlab/discovery/strategies/odefit/` (`fit.py` the output-error fit, `extend.py`
products and the runaway check, `compare.py` comparing two models by output error, `run.py` the
choice, `write.py` the flows). Tests `tests/test_odefit.py` (4). No other strategy is imported; the
main line comes from the shared library (`sdlab.discovery.identify`).
**Verdict:** adopt for physics and other smooth measured data. Physics cases **25 of 28** (the best
before: 15, earned_pieces and symbolic; matrix and lna 13; combined 12), structure agreeing in 25,
mean fresh skill@20 96.5% against the reference's 97.1% (gap -0.6 points; matrix -10.5), long-run
error 8.3% (the reference's 17.0%). Distilled cases 141-143 (from the physics failures): 12 of 12.

## The question

The physics view (LADDER.md, "Physics cases") found the leaders at 12-15 of 28. Its misses were:
measurement noise losing couplings (the spring's V <- P and V <- force, the chain's C <- B, the
tanks' H2), Lotka-Volterra written as a linearised oscillator, the tanks' short runs inventing
H2 <- pump, and the thermostat. Coupled linear ODEs sampled once a step are exactly linear in the
levels (the per-step map `x(t+1) = e^{A} x(t) + ...` is linear), so a careful linear method
should reach the reference on cooling, the chain and the spring whatever the noise.

## Diagnosis (invariant 4b)

The noise cases are the method's fault, not the data's: fitting the true linear structure by
output error on the measured levels reaches the reference on every meas cell of the spring, the
chain and cooling (gap 0.0 to +0.1 points). The one-step regressions every leader uses suffer
from errors in variables. On the spring, V's measurement error (0.02) is half V's spread (0.045)
and seven times its change in a step, so a one-step fit shrinks V <- P and V <- force towards 0.
On the chain, C's 2% error at levels of 285-1,568 is 6-31 against a change of about 1 a step.

## What it does

1. **The model.** Each stock's change in a step is a number times each level, each measured input
   and a constant (`fit.columns`), stepped as the engine steps (an injection added at the start of
   its step, the input of the step read at its end).
2. **Output error with estimated starts.** The run is cut into 100-step segments. Within each, the
   model runs free from a start state that is estimated too, and the numbers minimise the weighted
   squared gap to the measured levels. For a linear model the start states enter linearly, so they
   are solved exactly for every trial of the numbers (variable projection). Each stock is weighted
   by 1/sd of its own output error (a second pass), so a noisier stock counts less.
3. **Terms pruned by BIC** (backward elimination). Each stock's RSS is floored at the record's
   rounding (levels with 4 decimals: n x (1e-4)^2 / 12), so a term cannot earn its place by fitting
   rounding error. Without the floor, noise-free SD runs (050, 051, 056 none-long) kept terms of
   1e-6 that ran away on fresh starts.
4. **Products** (all products of two levels; then squares only; then cross products only) are
   fitted with the linear terms. The start states are then fitted beside the numbers, with a
   forward-difference Jacobian in one batched simulation. Products are pruned the same way and
   kept only if all of these hold:
   - they save 10 BIC;
   - refitted on the first 70% of the run, they predict the last 30% at most 0.8 of the linear
     model's error;
   - they **do not run away**: run free for 2,000 steps from the run's first and last states, with
     the inputs repeated or held half their range beyond the values seen, the model stays within
     20 ranges of the levels seen. On the tanks' meas-short run a positive square on a tank's own
     level (a concave drain, right in range) turned into growth above the levels seen, and the
     fresh run ran away.
5. **Hinges** (a rate linear in the levels and inputs, floored at 0: a switch) are implemented
   (`opts["hinges"]`) but **off**. On the thermostat they saved BIC but lost fresh skill (59%
   against the linear 76% on meas-long), and the distilled-fix agent owns the switch shapes
   (own_tables, cases 122/123).
6. **The choice.** The main line (`identify`) runs too. Then:
   - **counted levels** (whole numbers), uneven times and announced eras go to the main line; for
     counted levels its result is exactly matrix's;
   - an output-error model that **runs away** is never chosen;
   - **noise in the dynamics**, i.e. counting noise or shocks (`noise_kind`): for some stock the
     output error's variance is over 1.3 times the one-step error's (R), and the one-step error's
     lag-1 autocorrelation rho is between -0.3 and 0.6. The main line's behaviour judge then
     decides. The diagnostic's signatures:

     | data | R | rho |
     |---|---|---|
     | measurement error alone | about 1/2 | about -1/2 |
     | a noise-free misfit | 15-44 | above 0.89 |
     | counting noise under measurement error (080, 082, 083, 087, 088) | 1.5-2.9 | -0.24 to 0.21 |

     Output error is the wrong estimator under counting noise: it fits a smooth path to a random
     walk. Without this test it took 088#2 meas from matrix (a pass) to a fail.
   - otherwise both models are refitted on the first 70% and compared on the **last 30% by output
     error**, each 20-step segment from its own fitted start (`compare.py`). The main line's judge
     runs each model from measured levels; under measurement error a model that shrinks every run
     towards the mean then looks better than the true one, and the judge chose matrix's model on
     spring meas-short. On the whole run the main line's changing-inflow pieces follow the data,
     but not past it; the held-out comparison is what put the thermostat's short runs to the
     linear model.
7. **The flows** (`write.py`): a negative own number is a drain. What other stocks of the same unit
   gain in proportion to a level moves out of that drain (a move), and the rest is a link. Other
   positive terms form one linear inflow and negative ones one linear outflow. A product
   k X_a X_b is `k normal x X_a x effect(X_b, linear, normal)`, unclamped. Numbers are written to 6
   significant figures (the main line's 4 decimals cost the spring's w^2 = 0.01).

## Results

### Physics cases

Command: `sdlab-ladder run --strategies odefit --cases phys-,141,142,143 --jobs 2 --timeout 300`,
single-threaded, at `8d8e8c6`, 19 October 2026. Read from `api.summary()["physics"]` and the store.
The other strategies' numbers are their latest stored results (combined, lna and matrix as in
LADDER.md; earned_pieces after its input fix 89adae4).

| strategy | phys pass | structure | couplings right | shape right | fresh@20 | vs ref @20 | long-run err | diverges |
|---|---|---|---|---|---|---|---|---|
| **odefit** | **25/28** | 25/28 | 97.6% | 71.7% | 96.5% | -0.6 | 8.3% | 0 |
| earned_pieces | 15/28 | 20/28 | 91.1% | 54.8% | 83.9% | -13.2 | 20.2% | 0 |
| symbolic | 15/28 | 16/28 | 84.5% | 58.0% | 86.8% | -10.3 | 26.4% | 0 |
| matrix, lna | 13/28 | 14/28 | 81.8% | 51.8% | 86.6% | -10.5 | 27.0% | 0 |
| combined | 12/28 | 14/28 | 78.9% | 49.7% | 71.9% | -25.2 | 28.1% | 0 |
| kalman_lna | 12/28 | 13/28 | 76.2% | 48.8% | 67.5% | -29.7 | 31.0% | 0 |
| structures | 8/28 | 10/28 | 73.5% | 43.8% | 53.0% | -44.2 | 26.9% | 0 |

Per case (variants none-short, none-long, meas-short, meas-long). Before: the best of the 59
strategies on the ladder in each cell. After: odefit, with the gap to the reference's fresh
skill@20 in points.

| case | before (best strategy, any) | odefit | gap @20 (odefit) | what changed |
|---|---|---|---|---|
| coupled tanks | 1, 0, 1, 0 (none-long by 33; meas-short earned_pieces only) | 1, 1, 0, 1 | +0.4, 0.0, -1.4, 0.0 | squares of the levels (a concave drain) remove the spurious H2 <- pump; meas-short: every product family runs away, and the linear model keeps H2 <- pump |
| draining tank | 1, 1, 1, 1 | 1, 1, 1, 1 | -1.8, +0.1, -1.7, -0.4 | as before |
| Lotka-Volterra | 0, 1, 1, 1 (numopt_fd_profile; symbolic) | 1, 1, 1, 1 | +0.8, +1.0, +0.8, +1.0 | products X x Y and the self-couplings that change sign; better than the reference |
| mass-spring-damper | 1, 1, 0, 0 | 1, 1, 1, 1 | +0.1 to 0.0 | output error keeps V <- P and V <- force under noise |
| Newton cooling | 1, 1, 1, 1 | 1, 1, 1, 1 | 0.0 | as before |
| reaction chain | 1, 1, 1, 0 | 1, 1, 1, 1 | 0.0 | output error keeps C <- B on meas-long |
| thermostat | 0, 0, 0, 0 | 1, 0, 1, 0 | -4.3, -3.3, -4.3, -3.2 | a linear controller (no floor) within 5 points; on long runs T <- outside comes out missing or of the wrong sign (closed loop: see the journal, Needs you) |
| **total** | 21 cells passed by some strategy, 15 by the best one | **25** | | |

What it still misses:
- **coupled tanks meas-short**: the data's limit for this method. Every product family runs away
  outside the 300 noisy steps seen. The linear model has H2 <- pump above the 10% presence line;
  earned_pieces passes this cell at the 5-point boundary (gap -5.0).
- **thermostat long, none and meas**: skill is within 3.3 points of the reference. The structure
  fails because the best linear predictor of a closed loop reads the outside temperature weakly or
  with the wrong sign; the reference itself fails the structure there.

### Distilled cases 141-143

odefit from the run above; the leaders from `sdlab-ladder run --strategies
matrix,lna,earned_pieces,symbolic,kalman_lna --cases 141,142,143 --jobs 1 --timeout 300`
(single-threaded, 19 October 2026, the strategies as committed at 8d8e8c6). Passes of none-short,
none-long, meas-short, meas-long:

| case | matrix | lna | earned_pieces | symbolic | kalman_lna | odefit |
|---|---|---|---|---|---|---|
| 141 noisy offset oscillator | P P F F | P P F F | P P F F | P P F F | E P F F | **P P P P** |
| 142 oscillator pushed by a measured force | P P F F | P P F F | P P F F | P F F F | P P F F | **P P P P** |
| 143 chain into an ever-growing stock | P P P F | P P P F | P P P F | P P P F | P P P F | **P P P P** |

(E: equivalent.) Every leader makes the physics' mistake on the small cases: right without noise,
wrong with measurement error, and on 143 only at the long run's large levels.

### Standard tests

See the section below (filled from the store after the run).

## Lessons

- The physics' noise failures were errors in variables. Output error with estimated segment starts
  removes them without a noise model: the numbers never see the measurement error on the right-hand
  side.
- How two models are compared matters as much as how they are fitted. Running each model from the
  measured levels favours shrunk models under measurement error. Judging on the run that was fitted
  favours changing-inflow pieces. Output error fits the wrong model under counting noise. The
  diagnostic R / rho tells the last case apart from the other two.
- A nonlinear term must be tested where it was not fitted. Squares that are right inside the range
  seen can turn a drain into growth just past it.

## Open ideas

- Use the R / rho diagnostic to hand counting-noise cells to an estimator with process noise (a
  Kalman filter on the same linear model: kalman_lna's territory) instead of the main line.
- A floored proportional controller fitted by output error for switch-like data (the reference's
  form). The hinge code is there; it needs a held-out check that also prices fresh skill.
- Product terms with the reference's form (a rate times a linear effect) for crowding cases (103, 139)
  on the standard ladder.
