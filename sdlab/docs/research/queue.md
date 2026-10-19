# Work queue

The hourly research cycle starts these, top first, when fewer than 6-8 agents are running. It
moves each started item to "Started" with the date, and each finished item to "Done" with its commits.
Each agent works in the main checkout on branch `sdlab`, follows `sdlab/CLAUDE.md`, and gets the
item's text below as its brief, with the context it needs (the docs to read, what it owns, and the
other agents editing shared files).

Approved by the user on 2026-10-18 ("make it more difficult": a 97.8% pass+equivalent rate
for `combined` on the test cases).

## Queued

1b. **Time measurements in the ladder and its UI** (requested by the user on 2026-10-19). Today
   each result stores discovery seconds only, and the leaderboard has one "time (s)" column.
   Add:
   - **Per result:** scoring seconds beside discovery seconds (scoring can dominate: one
     realistic case took 417 s to score), and the worker's queue wait if cheap.
   - **Per strategy:** time per cell by set (tests / noisy / canonical / realistic / physics /
     real), median and p95, and its trend across versions. Show it as a column group on the
     leaderboard and a small chart on the strategy page.
   - **Per run and batch:** record each `sdlab-ladder run` / watch batch (start, end, items,
     done, errors, timeouts, worker count) in the store.
   - **A Runs page,** or a panel on the Now page: the watcher's current batch, items done and
     left, throughput (results per hour), and an ETA for the backlog.
   - **Cost estimates:** `sdlab-ladder cost --strategies X` / `--cases Y` estimates wall time to
     re-test from stored per-cell times and the current throughput, so an agent (or the user)
     can see "this fix costs ~4 min; this shared change costs ~5 h" before making it. Use it in
     the hourly journal.

   Keep the summary fast: aggregates are cached, out of the request path.

1a. **Control-theory cases** (requested by the user on 2026-10-19: "it might be interesting to
   make some test examples based on control theory, or some classic control theory book
   examples"). The user is less familiar with control theory, so each case's doc should explain
   the control idea in a sentence or two.

   Sources: textbook examples, preferring freely available ones, with citations:
   - Åström & Murray, *Feedback Systems* (free online): cruise control, the bicycle, the
     insulin–glucose loop, the predator-prey loop, AFM, the web server queue (a queueing control
     example that fits the user's SRE interest);
   - Franklin, Powell & Emami-Naeini;
   - Ogata;
   - Nise.

   Write them as ladder cases in SD Lab's format (integrators as stocks, a PI controller's
   integral as a stock; setpoints and disturbances as measured inputs; signed quantities through
   offsets or two one-way flows, as the physics cases did). Mainly linear, so the truth is exact.
   Candidates:
   - a first-order lag under P control (steady-state error) and PI control (no error);
   - a second-order plant under PI or PID (overshoot, settling);
   - cruise control with a hill disturbance;
   - tank level control;
   - temperature control with dead time (a DELAY chain) and the instability it causes at high
     gain;
   - cascade control;
   - feedforward plus feedback;
   - integrator windup at an actuator limit (a ceiling);
   - bang-bang versus proportional;
   - a web-server admission-control queue.

   A family of closed-loop identification probes:
   - the same loop with no setpoint changes (weak excitation);
   - with steps;
   - with a PRBS-like setpoint.

   The analysis (`analysis.py`) should label the weak-excitation cells data-limited or
   unidentifiable. That is the classic closed-loop identification problem, where the
   controller's input correlates with the noise.

   Scoring: the standard ladder scoring. Also report the control metrics of found against true
   models: step-response overshoot, settling time, steady-state error, gain/phase margin of the
   linear part, from `jump.py`'s linear maps. A new tag `control`, in the Tests set unless a
   case is out-of-format.

   Run the leaders and distil failures (invariant 4).

2g. **Runner fix, and lna2** (from the hook port). lna and its variants are frozen (invariant 11), so the lna changes go into a NEW strategy `lna2` (a copy), never into lna:
   - when the runner's timeout alarm fires inside numba code, the result is recorded as an error (`SystemError` in `inv_logdet`); record it as a timeout;
   - lna: stop the fit on parameter change, not on likelihood (FTOL), so extra zero-impact rows don't shift the stopping point;
   - lna: `identify(..., base=...)` and a public flow writer `run.written`, so the variants stop recomputing and copying.

2f. **combined, round 2** (from `docs/research/combined.md`, code ded5e80). Start it once the
   noise-robust (`kalman_lna`) and structures agents have committed.
   - **A behaviour judge** that does not replay each model's own inflow pieces, e.g. a held-out
     era or rolling-origin forecasts. In-data error can't tell the lna family's runaway models
     from effect_hats' sound ones (sd-webshop-stock: 0.239 vs 0.181 in-data, skill −7.6 vs 0.74).
     Realistic skill@20 is 41.1% for combined against 49.9% for effect_hats. Close that gap
     without losing test cells.
   - **New candidates:** add `kalman_lna` (60 cells combined misses, mainly the noisy cases
     080-087) and `structures` (25 cells, canonical 100-110), with a likelihood that knows about
     measurement noise.
   - **Small counts:** a discrete likelihood for small counts (056).
   - **Speed:** skip common_cause when no two stocks move alike. combined averages 11 s per test
     cell, against lna's 1.1 s.

   Report tests, strict, realistic and noisy results.

2d. **Engine features for the remaining blockers** (in the HARNESS only: `sdtruth.py`, plus a harness copy of the simulator under `sdlab/ladder/` if scoring needs it. The frozen `sdlab/discovery/simulate.py` is never changed, so no strategy re-runs; no HOLD) (approved by the user on 2026-10-18 if
   additive, with existing numbers bit-identical):
   - two-way flows (30 SDXorg models) and negative stocks (9), opt-in per stock or flow;
   - delays whose time or order changes, pipeline stocks, TREND/FORECAST (3 each);
   - DELAY FIXED;
   - MIN/MAX and ratios of stocks in rates;
   - sqrt and power;
   - from the Kubernetes model (`docs/research/k8s-model.md`, 2026-10-19): auxiliaries (algebraic
     variables without a stock; today each is a hidden stock re-read every step, a one-step lag),
     an effect of a ratio of two stocks (today a `1/x` table on the denominator), CEIL/MIN/MAX in
     rates (the HPA), a flow reading another flow's amount (a restart counter equal to the OOM
     kills), a ceiling that holds at `max` at dt 1 (today `max / (1 + k)`), and measured inputs in
     the editor's Discover request (the ladder passes them; the page does not).

   Prove additivity as item 0 did, with `tests/engine_outputs.sha256`.

6. **matrix_v2: the proposed matrix fixes as a NEW strategy** (rewritten on 2026-10-19: the
   shared discovery library and `matrix` are frozen, CLAUDE.md invariant 11). Copy what is needed
   from `sdlab/discovery/` (matrix, flows, regression, changes) into `strategies/matrix_v2/` and
   apply the fixes proposed by censored, effect_hats and earned_pieces there (see their docs):
   - read a negative cross term as a falling inflow;
   - price inflow changes at 2 log n;
   - pool and re-cut inflows;
   - a conservation tie test with both rows' SEs;
   - keep a constant inflow unless the residuals aren't white;
   - floor the rss at the data's rounding;
   - pair drains and links whatever stock an effect is based on.

   No other strategy changes, so nothing else re-runs. No HOLD needed.

## Started

- 2026-10-18 23:20: short series and published-model twins (from the real-data results).

- 2026-10-18 23:00: fix measured-input handling in censored, effect_hats and earned_pieces (found by the physics cases).

- 2026-10-18 22:35: rotation c, research to implementation (ideas-2026-10-18.md).




- 2026-10-18 21:15: item 2b, products of stocks, multi-stock gaps, hidden delay chains.

- 2026-10-18 20:50: item 0b, noise-robust discovery.


## Done

- 2026-10-19: item 2e, the lna_* variants run as hooks on lna (dc73851, 9bd1e2a, 7b82abc). No timeouts or errors; lna_stack's realistic cells all finish. One cell lost (lna_stack 101 counts-short, a fit stopping-rule effect). lna should stop on parameter change, not on likelihood.

- 2026-10-18: item 5, real-data cases (67b8007, e91a320, 2658c57, 9fe0afd, e6dcb8a): 52 cases (BLS, 29 Gause, flu, 21 Bass adoption). No strategy agrees with a published structure. 29 cases are too short (< 21 samples). Every strategy fails all 52 twins.

- 2026-10-18: item 4, physics cases (2cde024, 382ea4d, 0b7eb5b): 7 ODE systems with their own scoring and view. matrix/lna 13/28, combined 12/28. No leader finds Lotka–Volterra's products or the thermostat's switch; √ outflows have no SD form.

- 2026-10-18: item 2c, converter coverage (e83aa25, 2deb86d, 089fbf3): arrays, macros, external data, DELAY N/SMOOTH N; SDXorg exact conversions 37 → 90 of 165. New case 111 (arrayed switching). The remaining engine blockers go to 2d: two-way flows (30), negative stocks (9), DELAY FIXED (3), MIN/MAX (2), variable delay time/order (3), pipeline stocks (3), TREND/FORECAST (3).

- 2026-10-18: item 3, strict pass tier (f75a064). Strict = pass, with no extra parts, long-run error and fresh skill within what refits of the truth achieve. combined leads by strict (67.6%); matrix drops 41.4% → 22.9%. Kept current by the hourly cycle (`sdlab-ladder strict`).

- 2026-10-18: item 2, canonical models: cases 100-110 and the PySD converter (3660a5d, 0b3fbb8,
  08ef0d7, 1b14f42). Coverage of SDXorg/test-models: 37 exact, 15 differ, 111 blocked
  (`docs/research/canonical-coverage.md`). Leaders: combined 3 passes of 44 cells, the others 0-2.

- 2026-10-18: realistic examples run (7 leaders on the 31 sd-* cases; results in the journal's 19:45 entry).

- 2026-10-19: item 1, noise variants: meas, gaps, weekly, lag, outliers, bias (noise.py, opt-in),
  Kalman-scaled tolerances and labels, cases 080-088, the leaders run (docs/LADDER.md, "Real-world
  noise"). Every leader breaks on meas from 2% (long runs), on outliers, gaps, weekly and bias;
  lag costs little except where injections are announced.

- 2026-10-18: item 0, engine features (1baf38e, 9646bf2, cb97c26). Additive: 2,201 output hashes identical. New cases 062 (measured pump) and 063 (DELAY3). Still missing: sqrt/power/exp, MIN/MAX/IF, two-way flows, arrays, observation models, sparse sampling, a real-data scorer, and the editor forwarding inputs.

- 2026-10-18: survey of case studies with data (`docs/research/case-study-sources.md`, a8ccdc8).
