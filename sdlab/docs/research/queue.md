# Work queue

The hourly research cycle starts these, top first, when fewer than 6-8 agents are running. It
moves each started item to "Started" with the date, and each finished item to "Done" with its commits.
Each agent works in the main checkout on branch `sdlab`, follows `sdlab/CLAUDE.md`, and gets the
item's text below as its brief, with the context it needs (the docs to read, what it owns, and the
other agents editing shared files).

Approved by the user on 2026-10-18 ("make it more difficult": a 97.8% pass+equivalent rate
for `combined` on the test cases).

## Queued

2d. **Engine features for the remaining blockers** (HOLD until the watcher's backlog is under ~10k items: a `simulate.py` change re-runs every strategy) (approved by the user on 2026-10-18 if
   additive, with existing numbers bit-identical):
   - two-way flows and negative stocks, opt-in per stock or flow;
   - DELAY FIXED;
   - MIN/MAX and ratios of stocks in rates;
   - sqrt and power.

   Prove additivity as item 0 did, with `tests/engine_outputs.sha256`.

3. **Strict pass tier.** Add a second, stricter verdict beside pass/equivalent/fail. Do not
   replace pass, so history stays comparable. Strict pass requires all of:
   - a pass;
   - found complexity no greater than the truth's (no extra parts);
   - long-run error (`longrun.py`) under a threshold at 10× the truth's slowest time constant;
   - good fresh-run prediction (skill@100 fresh above a threshold).

   Thresholds come from what the true model itself achieves on the same data (the true
   structure refitted), not from arbitrary numbers. Show strict pass rate as a leaderboard
   column and a ranking option. The definition of "pass" itself is unchanged: changing it
   needs the user.
4. **Physics-generated cases (out-of-class data).** Generate data from physical systems that
   are not stock-and-flow models, simulated in continuous time with a proper ODE solver and
   sampled:
   - a draining tank (outflow proportional to √level);
   - two coupled tanks;
   - Newton cooling;
   - a mass-spring-damper (position and velocity as stocks);
   - Lotka–Volterra predator–prey;
   - a chemical reaction chain A→B→C;
   - a thermostat with on/off control.

   Scoring needs its own design:
   - the expected structure from the physics, i.e. which stocks couple and the sign and shape
     of each coupling;
   - held-out prediction (skill on a fresh run, long-run error);
   - a note when the best SD approximation differs from the physics (e.g. √ outflow vs a
     proportional drain).

   Tag `physics`; keep it out of the Tests pass rate (its own leaderboard view, like Realistic).
   Mass-spring and control loops cover the automotive/aerospace idea.
5. **Real data with professional models.** `case-study-sources.md` has landed (a8ccdc8). Start with
   its recommended steps:
   - a PySD converter for SDXorg/test-models (shared with item 2);
   - a BLS labour-force loader, which has measured flows to score against;
   - gauseR and the boarding-school flu as real cases;
   - technology adoption as a family of Bass cases.

   Steps needing an engine change (measured input series, `dt`, stock ceilings) wait for the
   user's answer (journal, "Needs you"). Originally: ingest its top
   3-5 recommended sources as `real` cases. The true equations are only the modeller's, so the
   scoring is held-out prediction plus a structure comparison with the published model. Keep
   it in its own leaderboard view.
6. **Shared fixes to `matrix`**, proposed by `censored` (`docs/research/censored.md`):
   - `flows.read_flows` may write a negative cross term as an inflow `c + k·x` (k < 0) when the
     row has an outside inflow, a goal gap's true form;
   - price the main line's inflow changes at 2 log n (PELT `mult` 2);
   - note in `oracle.py` that its linear fit ignores floors and caps.

   Proposed by `effect_hats` (`docs/research/effect-hats.md`):
   - pooled, re-cut inflows (`pieces.py`) as a matrix option, guarded against seasonal inflows;
     cutting inflows into many pieces biases drains fast under counting noise (case 027);
   - in `effects.translate`, pair a drain and a link into a move whatever stock the curve is
     based on;
   - effect flows should carry `driver`;
   - compute the oracle (`oracle.py`) per row, so linear parts in effect cases get SE allowances.

   Also proposed by earned_pieces (`docs/research/earned_pieces.md`,
   "Proposed shared changes"):
   - the tie test in `matrix.conserve` should use both rows' SEs, without the extra log T, and
     not count a negative reading;
   - keep a constant inflow unless its residuals are not white;
   - floor the rss at the data's rounding;
   - add a flag to skip conservation.

   One agent owns `sdlab/discovery/matrix.py` and `regression.py` for this. It measures every
   strategy before and after (the ladder and both benches) and reports cells that flip either
   way. Since most strategies build on matrix, this re-runs everything: start it when the
   watcher's backlog is small.

## Started

- 2026-10-18 20:50: item 2c, converter coverage.

- 2026-10-18 21:15: item 2b, products of stocks, multi-stock gaps, hidden delay chains.

- 2026-10-18 20:50: item 0b, noise-robust discovery.


## Done

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
