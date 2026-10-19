# Work queue

The hourly research cycle starts these, top first, when fewer than 6-8 agents are running. It
moves each started item to "Started" with the date, and each finished item to "Done" with its commits.
Each agent works in the main checkout on branch `sdlab`, follows `sdlab/CLAUDE.md`, and gets the
item's text below as its brief, with the context it needs (the docs to read, what it owns, and the
other agents editing shared files).

Approved by the user on 2026-10-18 ("make it more difficult": a 97.8% pass+equivalent rate
for `combined` on the test cases).

## Queued

2g. **Runner fix and lna fixes** (from the hook port). lna may be fixed in place (strategies are not frozen); its derivatives must carry copies first (item 0c), so this waits for 0c:
   - when the runner's timeout alarm fires inside numba code, the result is recorded as an error (`SystemError` in `inv_logdet`); record it as a timeout;
   - lna: stop the fit on parameter change, not on likelihood (FTOL), so extra zero-impact rows don't shift the stopping point;
   - lna: `identify(..., base=...)` and a public flow writer `run.written`, so the variants stop recomputing and copying.

2k. **Engine and scoring gaps found distilling 113-117** (2026-10-19; docs/LADDER.md, "Distilled from the new canonical cases"). Harness items, except the third, which touches the pinned discovery library and needs the user:
   - `sim.amounts` (sdlab/ladder/sim.py) crashes on a truth flow whose rate is *linear* and reads a switch (`8 * heater`): `_compile.<locals>.<lambda>() takes 1 positional argument but 2 were given`, so the case's truth cannot be scored. 225 writes its heater as the expression `8 * max(0, heater)` to get round it; fix it so the plain form scores too;
   - a rate that reads a smoothing or a `delayed` stage is not scored (LADDER.md "Not done"): 115's graduation (`smooth3(enrolment, 4)`) has no part, so every drain a strategy finds for it is spurious and 115 cannot pass (noise-free skill@20 100% for every leader, all fail). A smaller case of that mechanism would hit the same gap, so it is not distilled until the scorer reads such a rate (e.g. as a hidden path fed by the input);
   - found models cannot be signed: the scorer honours `two_way: true` on a found flow (the truth given as found passes 113, 220 and 221), but skill@H runs a found model through `sdlab/discovery/simulate.py`, which floors every rate and level at 0. A strategy that writes 220's or 113's truth exactly still gets the behaviour of a floored model. Needs a signed/two-way option in the found-model simulator (pinned library: user approval) or a scorer-side simulator for found two-way flows.

## Started

- 2026-10-19 06:30: 2d (harness engine features), 6 (matrix_v2), and distilled fixes for 156-160 and 216-218.

- 2026-10-19: 2f, combined round 2 as a new strategy `combined2` (copies of the new specialists, a behaviour judge that doesn't replay pieces).

- 2026-10-19 03:30: 0c (derivative strategies self-contained), 1a (control-theory cases), 1b (time measurements).

- 2026-10-18 23:20: short series and published-model twins (from the real-data results).

- 2026-10-18 23:00: fix measured-input handling in censored, effect_hats and earned_pieces (found by the physics cases).

- 2026-10-18 22:35: rotation c, research to implementation (ideas-2026-10-18.md).




- 2026-10-18 21:15: item 2b, products of stocks, multi-stock gaps, hidden delay chains.



## Done

- 2026-10-19: 2h, common_cause without runtime patching (3f5f064): private copies of matrix.identify_one/finish/conserve and regression.stepwise take the floored fit; the swap is gone. Found flows byte-identical on 028-038 (44 cells) and 20 other cells.

- 2026-10-19: 1a, control-theory cases 200-215 and distilled 216-218 (cd9e8b1, 34e948c, a319289, docs). Leaders pass 14 of 448 cells; structures passes 3 of 34 achievable cells.

- 2026-10-19: 2b, structures (up to 7e0a2bf, doc 0acdab1). Canonical 30/44 against combined's 3; distilled products 17/24; 99 cells better than combined, 6 worse.
- 2026-10-19: realistic round 1 (realistic_hats 52cd6d1, 06b0062; triage doc; distilled 152-161). Goals met 14 → 15 of 66; timeouts 12 → 1.
- 2026-10-19: scorer fixes (cb1c69d, f01908d). 179 flips: 178 fail → equivalent, 1 equivalent → fail, none into or out of pass.
- 2026-10-19: 1b, time measurements (c2a3c25 …); `sdlab-ladder cost`, runs panel.

- 2026-10-19: short series and twins (archetypes; 445aabf … 3c3e009). Real held-out 0.9% → 4.9%, twins −1.3% → 10.0%, 12 twins pass + 20 equivalent.
- 2026-10-19: fast leaderboard (210afce): incremental summary, server-side rows, cached responses.

- 2026-10-19: item 0b, kalman_lna (28b23cf … 6a93270, doc 00c0038). Noisy achievable cells: 85/97 against combined's 35. It matches combined on the tests; bench skill@20 +7.9 against v2.1. Self-contained (vendored copies).

- 2026-10-19: item 2e, the lna_* variants run as hooks on lna (dc73851, 9bd1e2a, 7b82abc). No timeouts or errors; lna_stack's realistic cells all finish. One cell lost (lna_stack 101 counts-short, a fit stopping-rule effect). lna should stop on parameter change, not on likelihood.

- 2026-10-18: item 5, real-data cases (67b8007, e91a320, 2658c57, 9fe0afd, e6dcb8a): 52 cases (BLS, 29 Gause, flu, 21 Bass adoption). No strategy agrees with a published structure. 29 cases are too short (< 21 samples). Every strategy fails all 52 twins.

- 2026-10-18: item 4, physics cases (2cde024, 382ea4d, 0b7eb5b): 7 ODE systems with their own scoring and view. matrix/lna 13/28, combined 12/28. No leader finds Lotka–Volterra's products or the thermostat's switch; √ outflows have no SD form.

- 2026-10-18: item 2c, converter coverage (e83aa25, 2deb86d, 089fbf3): arrays, macros, external data, DELAY N/SMOOTH N; SDXorg exact conversions 37 → 90 of 165. New case 111 (arrayed switching). The remaining engine blockers go to 2d: two-way flows (30), negative stocks (9), DELAY FIXED (3), MIN/MAX (2), variable delay time/order (3), pipeline stocks (3), TREND/FORECAST (3).
- 2026-10-19: item 2d, engine features (harness only; simulate.py untouched): expressions (ratios, MIN/MAX/CEIL, sqrt/power, lookups, IF THEN ELSE), auxiliaries, switches with memory, signed stocks, two-way flows, flow(id), net ceilings, DELAY FIXED (pipe and delayed()), variable delay time, TREND/FORECAST; every existing case, example and bench model bit-identical. SDXorg exact conversions 90 -> 139 of 165 (samples 3 -> 9). New canonical cases 113-117. Left: delays whose time or order changes in PySD's per-stage way, vector functions, ALLOCATE, SAMPLE IF TRUE, random; scoring of rates that read a smoothing; the editor (sim.js) and checks.py's short-run crash.

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
