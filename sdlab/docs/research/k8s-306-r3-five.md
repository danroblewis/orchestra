# Kubernetes 306, round 3: earned_pieces, latent_eras, mass_balance, numopt_powell, shared_noise

**Status:** done (2026-10-21). On `306-k8s-ready-replicas-cap` these five went from 20 of 30 cells passing
(job 198 at c7cade0: every none and counts cell passes, every meas cell fails) to **29 of 30** (job 214 at
fcb6c2c). earned_pieces, latent_eras, mass_balance and numopt_powell pass all six variants. shared_noise
passes five and fails meas-long. Commits: 2716adf (oe.py), fcb6c2c (the gate's rounding floor). Earlier
rungs were not re-run (the user: one regression check at the end, in the report step). See the
regression risk below.

## Why meas failed (rule 4b: the method's fault)

- After the scorer oracle (3747e29) the meas cells carry Kalman SEs. With them, a fit of 306's TRUE
  structure passes both meas variants on the case's seed. It is fitted on output error from free
  starting levels, with ready run as its own stock (initial level plus the announced injections)
  (scratchpad `r4/best2.py`): meas-short 7/7, and meas-long 7/7 from the true start.
- With the noisy measured ready used as the cap's input instead, meas-long misses only retries -> queue.
- So the data can deliver every part. What the strategies do instead:
  - They fit one step at a time on noisy levels: errors in variables.
  - The numbers are biased. Under the old scorer, traffic read 0.45 on meas-short and retries -> queue
    read 2.0 (33 after c7cade0).
  - The capacity screen (capmin) does not fire on meas-short: the kink is lost in the noise.
  - The structure is chosen on that biased fit: inflight's drain is written as `queue -> responses_total`
    reading inflight, errors_total is left unfed, and `inflight -> queue` reads retries.
- earned_pieces, latent_eras and mass_balance return the identical model on both meas cells.
- numopt_powell fits on multi-step error, but restarts every run from the noisy measured levels. It
  sees the MIN only as capmin's series, computed from those noisy levels. On meas-long it got the
  retries split, but misrouted inflight's drain.
- The meas data are a counting run with measurement error laid on it (`noise.py`). The residuals of
  queue, inflight and retries carry real counting noise: lag-1 correlation 0.3-0.5, and for retries the
  counting variance is about 10x the measurement variance (scratchpad `r4/truthprice.py`).
- So plain output error misprices structure. The likelihood that fits these data is a state-space one.

## Change: `oe.py` (one identical copy in each of the five packages; `tests/test_oe_copies.py`)

The module docstring has the details. In short:

- **Gate.** The stage runs only where the found model's one-step residuals show white measurement error
  (a lag-1 test, p < 1e-3 over the stocks).
  - A stock is left out of the test when its residuals are below 1e-8 of its squared changes.
  - That is the recorded levels' 4-decimal rounding. Job 213 refined none-long's exact answers without
    this floor and broke all five; fcb6c2c added it.
  - Every other answer is returned unchanged.
  - The gate was checked on the 30 stored c7cade0 answers: it fires on the 10 meas cells only.
- **Likelihood.** An extended Kalman filter (numba):
  - counting noise in every flow, with variance equal to its amount;
  - measurement error of variance a + b x level^2 in every measured level;
  - the engine's rules: injections at the start of a step, rates floored at 0, outflows sharing what
    the stock holds, the input read at the step's own time.
- **Search.** Greedy moves priced by Bayes (log n per number), searched on the first 600 steps:
  - drop a flow;
  - add a move;
  - a constant becomes a share of the flow's source;
  - take a flow from the stock its rate reads;
  - move its source;
  - send it elsewhere;
  - pass it through a stock;
  - limit a term on the flow's own source as MIN(k X, b Y), where Y is a stock or an input and each side
    binds on at least 5% of the steps.

  Then the measurement noise is fitted on the model the search reached, and the search runs again. The
  numbers are then fitted on the whole run.
- **Noise first from the data.** The first noise comes from the one-step residuals' lag-1 covariance,
  not from a fit. Fitted on a wrong model, a counter's measurement variance swallowed its missing inflow,
  and the search never fed it.
- **Two starts of the same search** (a multi-start of one fit, not a choice between finished models):
  1. the found structure;
  2. the found structure with each one-term flow taken from the stock it reads.

  The lower final price is kept. The true path from the found meas-short model goes uphill first
  (6.10M -> 6.11M -> 21.8k -> 14.9k, scratchpad `r4/path.py`), so one start was not enough.
- **Boundary.** The declared boundary is kept. The input inflow stays at exactly 1 x traffic, declared
  outside flows are never dropped or moved, and outside outflows are added only where the boundary
  declares them.
- **Wiring.** The stage is wrapped outermost in each `__init__.py`, after capmin.
- **Time.** The stage takes 45-62 s per meas cell on the pool (job 214), against the 120 s item timeout.

## Results (job 214, fcb6c2c; `uv run sdlab-ladder job 214`)

| strategy | none-short | none-long | counts-short | counts-long | meas-short | meas-long |
|---|---|---|---|---|---|---|
| earned_pieces | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| latent_eras | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| mass_balance | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| numopt_powell | pass | pass | pass | pass | pass (was fail) | pass (was fail) |
| shared_noise | pass | pass | pass | pass | pass (was fail) | **fail** |

"Was" is job 198 at c7cade0. There are 0 pass -> fail flips on 306.

**shared_noise meas-long (still fails, 2/7).** Its own answer is far from the truth:
- capmin offered the right limit (queue, capped by ready, into inflight).
- shared_noise's main fit wrote the MIN on `queue -> responses_total`.
- Its EIV pass moved retries' drain into errors_total, and its declared retries outflow is a constant.

From there every single move of the refinement is uphill. The stage is a local search and cannot
untangle it. This is a method fault in shared_noise's own one-step structure search, and fixable: its
search would have to keep capmin's receiver, or the refinement would need a wider start. No small change
in its package fixes it. Not done.

## Regression risk (for the report step's one check)

- The gate fires on meas variants of any case. There the stage can change answers that pass today:
  - the stage adds and drops flows on its own Kalman price;
  - a larger model (more stocks) means more candidates and an n^3 filter, so it can run into the
    120 s timeout.
- It does nothing on none and counts (the gate), nor on forms it cannot run: pieces, eras, effects,
  co-flows, two-way flows, hidden stocks.
- **Check:** the meas cells of 300-305 for these five strategies, and their time.

## Elimination

None proposed. All five now represent the MIN, through capmin's offer and, on meas, the stage's own
fitted limit. Four pass every 306 variant. shared_noise's one failure is fixable, not a hard limit.
