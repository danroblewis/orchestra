# Work queue

The hourly research cycle starts these, top first, when fewer than 6-8 agents are running. It
moves each started item to "Started" with the date, and each finished item to "Done" with its commits.
Each agent works in the main checkout on branch `sdlab`, follows `sdlab/CLAUDE.md`, and gets the
item's text below as its brief, with the context it needs (the docs to read, what it owns, and the
other agents editing shared files).

Approved by the user on 2026-10-18 ("make it more difficult": a 97.8% pass+equivalent rate
for `combined` on the test cases).

## Queued

0. **Engine features the sources need** (approved by the user on 2026-10-18; started first, since
   items 2 and 5 depend on it). Additive changes to `sdlab/sdtruth.py`, the case format and the
   simulator `sdlab/discovery/simulate.py`, plus the page's run input:
   - measured input series (an outside driver given as data, which discovery sees as known input);
   - a step `dt` smaller than one recorded step;
   - stock ceilings;
   - DELAY1/DELAY3/SMOOTH and PULSE/STEP/RAMP functions. Prefer exact rewrites into existing parts
     where possible, e.g. DELAY3 as three hidden stocks.

   Every existing case, example and fingerprint must give exactly the same numbers (a test
   proves it). Discovery may read inputs only as page inputs. Document in MODEL.md / LADDER.md.

1. **Noise variants (harder data).** Today a case has only noise `none` and `counts` (the
   randomness of whole units moving). Add variants for the noise real data carries, each a
   separate variant name, so every case can be run under it:
   - measurement error (relative and absolute Gaussian on the reported levels);
   - missing points and uneven sampling;
   - aggregated reporting (weekly totals or averages instead of every step);
   - a reporting delay;
   - occasional outliers;
   - a multiplicative bias on one stock's count.

   Rules:
   - The engine is fixed: noise is applied to the recorded levels after simulation, in the
     ladder's data layer.
   - A variant must be deterministic from the case seed.
   - Existing variants and their results must stay unchanged, so the defaults stay `none` and
     `counts`.
   - New variants run where a case or a new top-level setting asks for them. Start with a
     `noisy` tag on a set of representative cases, plus a sweep of measurement-error size.
   - The analysis (`analysis.py`, `fisher.py`) must say what is achievable under each new noise,
     so tolerances stay honest.
   - The scorer's tolerances follow the oracle, not a fixed relaxation.

   Report which strategies break first and how.
2. **Canonical system dynamics models.** Import classic SD models as new ladder cases (new ids,
   tag `canonical`), for example:
   - Bass diffusion and SIR/SEIR epidemics;
   - inventory with a supply line and the beer game;
   - workforce/hiring, a project model with rework, a commodity cycle;
   - World3 subsystems, the market-growth model and limits-to-growth archetypes.

   How:
   - Prefer machine-readable sources (PySD's test-models, Vensim/XMILE samples), converted
     through PySD where possible. See `docs/research/case-study-sources.md` when it exists.
   - Each case states its source and licence.
   - Where a model uses a function SD Lab's format lacks (DELAY3, SMOOTH, PULSE TRAIN, ...),
     write the equivalent structure explicitly (e.g. a third-order delay as three hidden stocks)
     if it is exact. Otherwise list it under "Needs you": changing the engine needs the user's
     approval.

   Run the leaders on them and report.
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

- 2026-10-18 20:00: item 1, noise variants.

- 2026-10-18 19:45: item 0, engine features (inputs, dt, ceilings, delays/smooth/test inputs).

- 2026-10-18: realistic examples run (7 leaders × 31 examples × 2 lengths, `~/.sdlab/realistic-run.log`).


## Done

- 2026-10-18: survey of case studies with data (`docs/research/case-study-sources.md`, a8ccdc8).
