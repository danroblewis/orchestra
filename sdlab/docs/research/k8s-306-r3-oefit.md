# Kubernetes 306, round 3: combined2, hidden_transit, lna_pulses, numopt_bo, realistic_hats

**Status:** done (2026-10-21). On `306-k8s-ready-replicas-cap` these five went from 20 of 30 cells
passing to **29 of 30** (job 216 at 9e9fb0c). Before the change, every none and counts cell passed and
every meas cell failed (job 195 at f640c89; the same at c7cade0 in process). combined2, hidden_transit,
numopt_bo and realistic_hats now pass all six variants. lna_pulses passes five and fails meas-long.

Commits:
- 0921062: `oefit.py`, one identical copy per package, and `tests/test_oefit.py`.
- 9e9fb0c: the search stops at a budget of simulated steps, not a wall clock.

Job 215, at 0921062, passed 26 of 30. Its answers depended on the machine: the wall-clock budget cut
the search at a different point on node2 than on the Mac. 9e9fb0c fixed that.

Earlier rungs were not re-run. The user asked for one regression check at the end, in the report step.

## Why meas failed (rule 4b: the method's fault, not the data's)

Since the scorer oracle (3747e29), the meas cells carry Kalman standard errors. Under them, an
output-error fit of the true structure passes both meas cells on the case's seed. The data can deliver
every part.

The five strategies all fit one step at a time on the noisy levels, so they hit errors in variables.
At c7cade0, with the traffic input fixed at 1 by the boundary, this showed in three ways:

- **On meas-short, capmin offers no MIN.** The kink is lost in the noise.
  - hidden_transit, numopt_bo and realistic_hats wrote dispatch as 0.12 x queue.
  - They wrote inflight's drain as `queue -> responses_total` reading inflight.
  - They wrote `inflight -> queue` reading retries, and left errors_total unfed.
- **On meas-long, the MIN is offered but its coefficient is attenuated.** It read 0.375 for a true
  0.6. A spurious `queue -> responses_total` and a slow inflight drain (0.36) made up the difference.
- **eiv.py cannot correct this.** Its instruments were "weak" on every meas cell. It treats capmin's
  series as a measured input, which is its own instrument. But that series is computed from the noisy
  levels, so as an instrument it is invalid.

lna_pulses and combined2 have a further problem: their lna likelihood models counting noise only.
- Under measurement error the changes spread far beyond counting noise, so lna gives up (MAX_MISFIT).
- lna then falls back to the pinned matrix method's model.
- On meas-short that model has empty rows: only the declared traffic inflow and the retries drain are
  left.

## Change: `oefit.py`

The module docstring has the details. In short:

- **Placement.** It runs between each strategy's own fit and capmin's restore.
- **Gate.** It runs only where the found model's one-step residuals show white measurement error
  (`eiv.white_z`). A stock is tested only when its residuals are above 1e-3 (rms) of its changes. On 306
  the gate fires on meas only (`tests/test_oefit.py`).
- **Fit.** The model is run through the whole record from fitted starting levels (numba). It follows
  the engine's rules:
  - injections are added before their step;
  - rates are floored at 0;
  - a stock's outflows share what it holds.

  The numbers are fitted on the weighted output error. Each stock's noise is a + b x level^2, fitted
  to its own residuals.
- **Search.** A beam search, priced by Bayes (log n per number). A MIN's extra number costs
  6 log n, and each of its regimes must hold on at least 5% of the steps. The moves:
  - drop a part;
  - write a term on the flow's own source as a x MIN(X, theta Y);
  - write a MIN as a plain rate;
  - take a flow from the stock its rate reads, or make it read its source;
  - make a drain into a stock a drain of another stock;
  - add a move into a counter, or between two stocks that move beyond their injections and noise;
  - put back a dropped part of the found structure.

  It never adds or removes an outside flow.
- **Two seeds.** The found structure, and the found structure with every such move added and then
  thinned by the Wald statistic of its fit. The answer with the lower Gaussian -2 log-likelihood plus
  price wins. The noise is re-read after each search, up to 3 cycles.
- **Write-back.**
  - A stock whose own-level outflows sum past 1 a step is written with shares of 1. The engine runs
    it the same way.
  - A flow that carries nothing on any step is removed.
- **Budget.** 1e9 simulated steps, with each run counted as its steps plus 700. That is about 60-80 s
  on the Mac and about 110 s on node2. A 120 s wall-clock cap remains as a safety net.

## Results (job 216 at 9e9fb0c; `uv run sdlab-ladder job 216`)

| strategy | none-s | none-l | counts-s | counts-l | meas-s | meas-l |
|---|---|---|---|---|---|---|
| combined2 | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| hidden_transit | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| lna_pulses | pass | pass | pass | pass | pass (was fail) | **fail** |
| numopt_bo | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| realistic_hats | pass | pass | pass | pass | pass (was fail) | pass (was fail) |

On meas, every pass finds the true structure. Examples:
- hidden_transit meas-long: MIN(0.5997 queue, 39.91 ready), retries split 0.604 / 0.396, inflight drains
  0.500 / 0.0299.
- realistic_hats meas-short: MIN(0.592 queue, 39.6 ready).

**What still fails: lna_pulses meas-long.** The answer has `queue -> retries` at 0.033 (true 0.08) and no
`retries -> queue`.
- Its seed is a pinned-matrix model that eiv's Moves stage rearranged into flows out of counters
  (`responses_total -> inflight` reading retries, `inflight -> errors_total` reading ready).
- The search does not get from that seed to the truth within the budget.
- With a 120 s or 300 s budget it passes (local, scratchpad `r4/e_*.txt`), but that is too slow for
  the pool.
- This is a method fault (the seed and the budget), not a data limit.

**Time.**
- meas cells take 60-125 s each (oefit's budget), where before they took 1-17 s.
- combined2 meas-long took 227 s on the Mac, inside the pool's 300 s timeout. On node2 it would be
  closer to the limit. **This is a timeout risk.**

**Regression risk (not run).**
- The gate fires wherever a found model's one-step residuals show measurement error. That includes
  the 300-305 meas cells and other meas or noisy cells, and the new model replaces the found one when
  its output error is lower.
- Two pinned-library failures were here before this change:
  - `tests/test_ladder_hidden_transit.py::015-hidden-stock-none-short` fails at c7cade0 without
    oefit as well (oefit is not reached there);
  - the stored pass of that cell is from 2026-10-19 (2b6a827).

## Capability remarks (for the elimination question)

None of the five has a hard limit on 306. All represent the MIN, given as capmin's series or as
oefit's expression. All pass none and counts, and four pass meas. **No elimination is proposed.**

- **combined2:** a selection composite. Each specialist is a vendored copy: kalman, archetypes,
  the matrix family and lna, plus a BIC judge. On 306 there are 6 stocks, so its Kalman stage (4 stocks
  at most) does not run. It cannot model measurement error itself. Its lna specialists give up and it
  returns the pinned matrix's model, which is empty on meas-short. With oefit it passes all six.
  Limit: fixable. Cost: the slowest of the five (227 s on meas-long).
- **hidden_transit:** the main line, plus hidden transit stocks fitted by a Kalman likelihood, plus
  hidden stages.
  - It represents linear and proportional rates, inputs, the offered MIN, hidden delays (DELAY1/3)
    and counting noise in its pair fits.
  - Its one-step main line has no measurement-error model; eiv corrects numbers only where its
    instruments are strong. oefit fixes this.
  - It passes all six. Fixable.
- **lna_pulses:** pulses, then lna (an LNA counting-noise likelihood: moves against links, co-flows,
  births and deaths).
  - It represents MIN as capmin's move atom, plus signed links and drains on inputs.
  - Its likelihood has no measurement error, so on meas it gives up and returns the pinned matrix's
    model.
  - It passes five of six. On meas-long the oefit search does not finish from its poor seed within
    the budget (it passes with 2-5x the budget).
  - Fixable, not hard. Two ways: a measurement-error term in lna's likelihood (the Kalman filter is
    the LNA with observation noise; kalman_lna has one), or a better-seeded or faster search.
- **numopt_bo:** numeric optimisation of the matrix model's numbers on multi-step error, with forward
  selection of optional terms and Bayesian optimisation.
  - Multi-step error resists errors in variables, but it starts from the one-step structure and
    restarts each window from the noisy levels.
  - It passes all six with oefit. Fixable.
- **realistic_hats:** effect_hats (effects, tables) plus hidden_transit's pair search, under a time
  cap. It has the same one-step core and the same EIV fault, and passes all six with oefit. Fixable.

## milp

It is unchanged here. Job 212, at 26522ec, gave none and counts pass and meas fail (k8s-306-r3-six.md).
That report and k8s-306-s1.md recommend that it enter the roster. Its meas cells now face the same
errors-in-variables cause, and this oefit stage or the oe.py one would apply to it.
