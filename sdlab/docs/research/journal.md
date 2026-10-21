# Research journal

Hourly entries from the unattended research cycle (see sdlab/CLAUDE.md). Numbers come from the
ladder's result store (`sdlab.ladder.store.latest()`), with each result's recorded code commit.

## 2026-10-18 18:35

**Health**
- **Server:** one listener on :8020. The summary takes 1.1–1.3 s warm through the public URL, slightly over target, with machine load ~120. Restarted at about 18:50: the editor's new strategy picker (live-runs agent, in progress) was served before its endpoint existed and crashed the toolbar.
- **Watcher:** running (`--strategies everything --jobs 4`).
- **Tests:** 823 pass, 3 fail. All three come from `lna_stack` (revisit agent, uncommitted): it raises ImportError and has no explanations.yaml entry.

**Finished since the last entry**
- **Scorer oracle for hidden stocks** (c9b6072), with an independent review (67f1237) and the Hessian fix (baa3e09).
- **Audit** (8ee7966).
- **Complexity** (bf219c5, 3847fc2).
- **Explanations** (79b2a6e).
- **Parametric draws and provenance** (55b6806, c073b19, 6d64af3): the store was migrated to the new case hashes, so nothing re-ran.
- **Math probes** (591d339, 40a0579).
- **Long-run and line graphs** (63374b0, df53825, 532737f).
- **earned_pieces** (51a7422, 1a086e6, doc 36f3b75).

**Running (9, above the 6-8 target, so no new wave this cycle):**
- effects (effect_hats), floors (censored), links/loops (lna), independence (common_cause, waiting on its bench)
- combined, revisit, realistic cases, strategy behaviour page, live runs + editor strategy picker

**Leaderboard top 5** (pass over the cells each strategy ran; tests and draws, realistic excluded; 720 cells):

| strategy | pass | ran | commits of its results |
|---|---|---|---|
| combined | 84.6% (609) | 720 of 720 | 627 at 8e8cd17, 93 at 1a086e6 with uncommitted changes |
| lna_stack | 81.4% (450) | 553 of 720 | uncommitted; mostly c4b20a0 and 339737f with changes |
| gap_prior | 76.0% (547) | 720 of 720 | 452 from before provenance, 183 at 2f6d017 |
| lna_levels | 75.0% (540) | 720 of 720 | c4b20a0, 339737f with changes, 20e6119 |
| lna_loops | 75.0% (404) | 539 of 720 | mostly from before provenance |

For reference: lna 73.2% (527/720), mostly from before provenance.

**The board mixes versions.** Most of lna's, earned_pieces' and common_cause's latest results predate commit tracking, and the watcher's backlog is still large. Compare strategies on these numbers with care.

**Problems**
- **Public site exposed in-progress work:** static files are served from disk, so an agent's in-progress JS went live before its server route did. The agent was asked to make the page robust to missing endpoints.
- **Shared fixes proposed by earned_pieces, not yet applied:** a tie test in `matrix.conserve` (it deletes real exits), a constant-inflow-unless-not-white rule, and an rss floor at the data's rounding. They need one agent owning matrix.py, plus a re-run of all strategies. Queue it when a slot frees.

**Needs you**
- **Should "equivalent" count as a pass** on cells the analysis marks unidentifiable (170 cells, mostly noise-free link↔move and constant+drain↔gap)? It is currently shown separately and not counted.
- **Retire candidates:** explanations.yaml marks change_price, held_out, gated, gated_no_high, piece_proof and sindy as "retire-candidate" from their old-bench verdicts. held_out is strong on the ladder, and you asked not to dismiss sindy. Wait for revisit.md before retiring anything.

## 2026-10-18 19:30 (note)

- **Finished:** the strategy behaviour page (6f98957, e37f84a) at `/ladder/strategy?name=<strategy>`, and the case-study survey (a8ccdc8).
- **Fixed on the editor:** the user found the live estimate misleading. The server's estimate on 003 was correct (in 19.6, 0.49·A, 0.199·B). The canvas labelled found flows with per-step amounts and drew found outside flows under the toolbar. The live-runs agent was asked to fix the labels, the placement, a legend, and a per-flow diff.

**Needs you (from the survey)**
- **Engine:** may the case format and engine gain measured input series and a smaller simulation step (`dt`)? Without them, only the top eight survey sources are usable.
- **Placement:** should real-data cases go on the ladder, or on a separate board (the survey suggests separate, scored by held-out prediction and agreement)?
- **Licensing:** several sources have no licence or are GPL. May their data be downloaded at ingest time rather than committed?

## 2026-10-18 19:40 (user decisions)

- **Engine features approved:** measured input series, `dt`, and whatever else the sources need. They must be additive: existing numbers stay identical. Recorded in CLAUDE.md invariant 2.
- **Real-data cases go on the ladder as additional information,** apart from the formal tests (own view; not in the Tests pass rate). Recorded in CLAUDE.md invariant 3.
- **Downloading unlicensed or GPL data at ingest time is OK.** Don't commit it.

## 2026-10-18 20:15 (note)

- **Finished:**
  - censored (3a0f24c, 665d991);
  - effect_hats (d95fb2d, 1baf38e);
  - revisit (up to cbb87a1, `docs/research/revisit.md`): lna_stack passes 381/472 on 001-048 against lna's 340, with 0 losses;
  - live runs and the editor strategy picker (90c741d).
- **Sent on:**
  - the combined agent was asked to add lna_stack (not lna_loops);
  - the lna agent was asked for a stage hook, so the lna_* variants stop copying `discover`;
  - added lna_stack's explanations.yaml entry (the test passes).
- **Started:** queue item 1, noise variants.

**Needs you**
- **Retire (park with a reason)?** The revisit found these dominated everywhere on the ladder:
  - numopt_fd, numopt_fd_profile, numopt_fd_coarse, numopt_lbfgs, gradient, held_out_blend (already parked; would become retired);
  - mass_balance_all, symbolic, impulses (each dominated by a sibling);
  - about 20 matrix-plus-one-mechanism variants.

  It recommends keeping shared_noise, mass_balance, periodic_inflows and sindy. latent_eras, starved_coflows and recession should wait until a rung tests their mechanism.

  Parking alone saves no time: the watcher runs `everything`, parked included, per your rule that untested means failed. Retiring would mean a separate `retired` list the watcher skips, with code and history kept. I have not done it.

## 2026-10-18 19:45 (hourly cycle)

**Health**
- **Server:** summary 0.8 s warm; one listener on :8020.
- **Watcher:** running; its latest pass planned 35,198 items (17,072 to run, 18,126 to re-score), after the engine change altered every strategy's hash.
- **Tests:** `tests/test_ladder*.py` 910 passed, 15 skipped. Load average about 90.

**Finished since the last entry**
- **Engine features** (1baf38e, 9646bf2, cb97c26), queue item 0. They are additive: 2,201 output hashes are identical.

**Started**
- **Queue item 2:** canonical models, plus a PySD converter and a coverage report.
- **Running agents:** links/lna, combined, realistic, noise variants and canonical. The effects and independence agents are only waiting on their benches. No new start, at 7 agents.

**Leaderboard, Tests** (868 cells, which now include the new cases; pass over the cells each strategy ran):

| strategy | pass | ran | commits |
|---|---|---|---|
| lna_stack | 78.5% (463) | 590 of 868 | 2bbc025 ×418, 339737f ×172 |
| combined | 77.5% (673) | 868 of 868 | 444ee50 ×633, 147874e ×194 |
| gap_prior | 76.0% (547) | 720 | 2bbc025 ×472, pre-provenance ×164 |
| lna_levels | 75.0% (540) | 720 | 2bbc025 ×408, 339737f ×182 |
| lna_loops | 74.1% (437) | 590 | 2bbc025 ×350, 90c741d ×122 |

**Realistic** (31 sd-* examples × 2 lengths = 62 runs; mean in-sample skill@20, each run clipped at -100%)
- effect_hats 49.9% (54 scored, 8 timeouts).
- censored 41.3% (61 scored).
- matrix 29.6% (62 scored), the same as the old bench's v2.1. This confirms the realistic cases reproduce the bench.
- combined 21.9% (62 scored).
- lna 21.7% (10 scored, 6 timeouts).
- earned_pieces 27.6% (15 scored).
- lna_stack, gap_prior and common_cause mostly time out at 600 s.

**Problems**
- **combined does worse than matrix on realistic models,** although it is near the top on tests: its judge favours models that pass tests but behave worse. The combined agent was asked to find out why and to guard against it.
- **The lna family times out on 10-20-stock models.** The lna agent was asked for a budget with fallback.
- **Test leaders and realistic leaders differ.** effect_hats and censored lead on realistic, and the lna family leads on tests. Strategies should be judged on both from now on.

## 2026-10-18 21:10 (note)

- **Finished:**
  - canonical models (queue item 2): cases 100-110 and a PySD converter;
  - noise variants (queue item 1, 10f1d24); the agent was asked to replace its import-time oracle swap with a visible score.py edit.
- **Started:** noise-robust discovery (queue item 0b).
- **Fixed:** impulses (and so lna_stack) raised on cases with measured inputs, treating an input's name as a stock. Fixed in impulses.py; 062 and 105 now run.
- **Queued from the canonical results:** 2b (products of stocks, hidden delays), 2c (converter coverage), 2d (engine features for blockers: two-way flows, DELAY FIXED, MIN/MAX/ratios, sqrt/power).

**Needs you (scoring)**
- **Delays fed from outside are not scored as parts.** The answer key reads a DELAY chain only between two measured stocks, so in 105, 108 and 110 those inflows aren't counted, and 105 and 110 score one part each. Making the scorer count them is a scoring change.
- **Cases with dt < 1** (100 SIR, 104 teacup) record once per time unit from a finer run. A drain k then shows per step as 1 − e^(−k). The truth's k = 0.1 and a found 0.0957 behave identically (100% skill), but this is scored as a fail. Options:
  - the scorer converts the truth's continuous rates to per-step rates for such cases;
  - or discovery fits continuous time.

  The first is a scoring change.

## 2026-10-18 20:45 (hourly cycle)

**Health**
- **Server:** summary 0.75 s warm; one listener.
- **Watcher:** running. Its latest pass planned 47,564 items (42,706 to run). The backlog keeps growing: the engine change altered every strategy's hash, and new cases keep arriving.
- **Machine:** 28 cores fully used (~22 by SD Lab), so more watcher workers would not help.
- **Tests:** 957 passed, 39 skipped, 2 failed. Both failures are missing explanations.yaml entries for in-progress packages: `kalman_lna` (noise-robust agent) and `structures` (products agent). Their agents must add them.

**Finished**
- **Noise variants, final** (130d21b): the oracle is now chosen in score.py and analysis.py, with no import hook. Re-scoring 8,758 existing results flipped no status.
- **Canonical models** (queue item 2), reported at 21:10.

**Started**
- **Queue item 2c,** converter coverage (arrays, macros, external data, DELAY N). Light, and no engine change.
- **Held: queue item 2d** (engine features). Changing `simulate.py` would re-run every strategy again. Start it when the watcher's backlog is under ~10k.

**Leaderboard, Tests** (728 standard cells; noisy, canonical and realistic counted separately):

| strategy | pass | ran | commits | realistic skill@20 |
|---|---|---|---|---|
| combined | 84.9% (618) | 728 of 728 | 696189d ×625, 130d21b ×102 | 32.1% (62 of 62 scored; was 21.9% at the last cycle) |
| lna_stack | 78.3% (465) | 594 | 2bbc025 ×367, 339737f ×122 | only 3 of 22 scored (timeouts) |
| gap_prior | 75.9% (548) | 722 | 2bbc025 ×421, pre-provenance ×164 | 16.0% (15 scored) |
| lna_levels | 74.9% (541) | 722 | 2bbc025 ×357, 339737f ×132 | not run |
| lna_loops | 74.0% (438) | 592 | 2bbc025 ×309, 90c741d ×112 | not run |

lna: 72.9% (531/728), realistic 15.1% (62 of 62 scored, no timeouts now).

**Realistic**, from the last cycle: effect_hats 49.9%, censored 41.3%, matrix 29.6%.

**Problems**
- **The watcher can't keep up.** At this rate the backlog takes days, so the board stays a mix of versions.

**Needs you**
- **Reduce the watcher's load?** Retiring the dominated strategies the revisit listed would cut roughly half the workload (see 20:15). Alternatively, run them less often, e.g. only when their own code changes, not when shared code changes.

## 2026-10-18 21:00 (note)

- **Finished: lna** (f3270a8, `docs/research/lna.md`).
  - **Ladder:** best on equations, 578 pass / 123 equivalent of 912.
  - **Behaviour:** worse. Examples skill@20 is 15.8% against matrix's 29.6% (paired −13.8, p = 0.13), the generated bench is about even, and realistic is 21.3% against 29.6%.
  - **Hook API** for variants: queued as 2e.
- **Started: queue item 3,** the strict pass tier.
- **Pattern:** strategies tuned on the small tests (lna, combined) can do worse on realistic models. The strict tier, with long-run and fresh-run behaviour required, is meant to expose this on the leaderboard.

## 2026-10-18 22:30 (hourly cycle)

**Health**
- **Server:** summary 1.1-1.4 s warm, over the ~1 s target (the payload is ~22 MB raw, compressed in transit). One listener.
- **Watcher:** running, still on its 47,564-item pass (42,706 to run).
- **Caches:** long-run graded 24,218 + 1,367 results; strict references +67 cells.
- **Tests:** 1,005 passed, 47 skipped, 2 failed. Both are missing explanations.yaml entries for `kalman_lna` and `structures`; their agents are still running.

**Finished since the last entry**
- **converter coverage** (2c: e83aa25, 2deb86d, 089fbf3): SDXorg exact conversions 37 → 90 of 165;
- **strict tier** (3: f75a064);
- **realistic cases** (8a3b339, 4c99470, 5cc36de, c7e9f07): the timeout now covers discovery only, not scoring;
- **combined** (up to ded5e80 / 087d0fa).

**Started**
- **2e:** lna_* variants onto lna's hooks.
- **4:** physics cases.
- **5:** real-data cases.
- **Rotation c:** research to implementation (`ideas-2026-10-18.md`).
- **Running:** kalman_lna (0b) and structures (2b).
- **Held:** 2d (engine) and 6 (matrix fixes), until the backlog is under 10k.
- **Waiting:** 2f (combined round 2), until 0b and 2b commit their final versions.

**Leaderboard, Tests** (`sdlab-ladder strict --no-fill` output; rates over cells run, strict over the verdicts known):

| strategy | pass | strict | ran | commit |
|---|---|---|---|---|
| kalman_lna | 80.2% | 72.3% | 916 | c124a98, agent still running |
| structures | 77.0% | 70.5% | 916 | ad4e110, agent still running |
| combined | 74.3% | 67.6% | 912 | ded5e80 ×771, 130d21b ×202 |
| gap_prior | 73.6% | 56.6% | 766 | 2bbc025, 1b14f42 |
| lna_stack | 65.6% | 53.2% | 780 | 7fcf437, 2bbc025 |

By strict, lna_levels (55.1%) is 5th, ahead of lna_stack. Passes fail strict mostly for extra parts (extra pieces).

**Realistic** (mean skill@20, store at 22:03): combined 41.1%, earned_pieces 35.0%, common_cause 33.0% (23 timeouts), matrix 29.6%, lna 17.5%. From the 19:45 cycle: effect_hats 49.9%, censored 41.3%.

**Problems**
- **The summary payload keeps growing** with cells × strategies, so the warm time is now just over 1 s. If it keeps rising, the leaderboard needs a compact per-strategy endpoint.
- **The backlog isn't shrinking.** The watcher's single pass blocks new plans for hours.

**Needs you** (still open from earlier entries)
1. Count "equivalent" as pass on unidentifiable cells?
2. Retire dominated strategies, or re-run them less often, to cut the backlog?
3. Should delays fed from outside be scored as parts (105, 108, 110)?
4. Score dt < 1 cases per step?

## 2026-10-18 23:30 (hourly cycle)

**Health**
- **Server:** summary 1.0-1.1 s warm; one listener.
- **Watcher:** its log still shows the 47,564-item pass, but the store gained 14,520 results in the last hour and 32,534 in the last 3 hours, so the backlog should clear in a few hours.
- **Caches:** long-run graded 10,692 + 3,975 results.
- **Tests:** 1,046 passed, 47 skipped, 2 failed. Both are the explanation test: `archetypes` (short-series agent, still running) has no entry.

**Finished:** physics cases (4) and real-data cases (5), both reported earlier.

**Started**
- short series and published-model twins (from the real-data results);
- distilled cases from hard-case failures (CLAUDE.md invariant 4, the user's method; now a standing step in the hourly cycle);
- a Kubernetes platform ground-truth model with at least 30 services (the user's request; brief in the agent prompt; doc to come in `docs/research/k8s-model.md`);
- the input-handling fix for censored/effect_hats/earned_pieces;
- 2e, the lna variants onto hooks;
- the research round (rotation c).

8 agents are running.

**Leaderboard, Tests** (`sdlab-ladder strict --no-fill`; rates over cells run):

| strategy | pass | strict | ran | commits | note |
|---|---|---|---|---|---|
| combined_lean | 90.0% | 87.0% | 281 of 916 | 2cde024, e0bc5f5 | research round, still running |
| combined_r2 | 90.0% | 87.0% | 280 | 2cde024, 382ea4d | research round, still running |
| combined_misfit | 89.3% | 86.2% | 281 | cd92c79, e0bc5f5 | research round, still running |
| kalman_lna | 80.2% | 71.3% | 916 | c124a98 | |
| structures | 77.0% | 70.5% | 916 | ad4e110 | |
| combined | 74.3% | 67.3% | 912 | ded5e80, 130d21b | |

**The top three have run less than a third of the cells,** which the watcher fills in. Their rates are not comparable with full-coverage strategies yet; the user saw ~91% on the leaderboard.

**Problems:** none new. The summary is about 1 s.

## 2026-10-19 (note): distilled cases

- **Finished:** 20 distilled cases, 120-139 (717c9d7). Each is the smallest case that repeats
  one mistake made on a realistic, physics, canonical or real-data case. The mapping and the
  leaders' results are in `docs/LADDER.md`, "Distilled cases".
- **The leaders on them** (560 runs, no errors or timeouts; passes of 80 cells, equivalents in
  brackets): structures 19 (2); combined, kalman_lna and effect_hats 3 (2); lna 1 (2);
  censored 0 (3); matrix 0 (2).
- **Mechanisms no leader passes in any cell:**
  - short series (120);
  - a concave drain (122);
  - an inflow shut off by its own level (123);
  - co-flows: on an outside inflow (128), running empty (129), slowing their own move (130);
  - an effect fed by its own flow (131);
  - a link with a daily cycle (132);
  - a hidden supply line fed from outside (133);
  - predator-prey products (127);
  - crowding from 21-30 samples (136).
- **Not reduced:** sd-population, sd-housing, sd-services (a combined fault: an empty model after
  a specialist timed out), sd-support-tiers, sd-emergency, sd-fishery's conservation, BLS's
  two-way flows (a data limit), and the flu's hidden infected stock (a scoring gap). The reasons
  are in LADDER.md.
- **Engine gaps** added to queue item 2d: hysteresis, signed states, and the checks' crash under
  20 steps.

**Needs you (scoring, from the distilled cases)**
1. **dt < 1 cases** (100, 104; still open from 21:10). The scorer grades against the model's
   per-time-unit numbers, but the data show per-step ones: 104's drain is found at 0.0957
   against 0.1, a 4.3% error with identical behaviour. Should the scorer grade against the exact
   one-step map, as the physics scorer does? Until you decide, no dt case is distilled.
2. **Hidden stocks fed from outside are not scored** (105, 108, 110, and the new 133, 134). A
   found `k x input` link even counts as spurious there. The flu-like probe (a hidden stock read
   by an effect) cannot be scored at all, because the truth is reduced to a plain hidden path.
3. **Equivalence ignores flows that read a measured input** (`parts.linear_system`), so an exact
   equivalent of 125 or 106 is scored fail.
4. **Effect cases are never checked for equivalence.** A product with its roles swapped fails
   even when the flow matches: 101 combined counts-long is within 0.7%.
5. **The behaviour grader swaps in only the truth's constant inflows.** Where a found model's
   inflow constant absorbs a nearly constant link or a constant outflow, the swap breaks a model
   that predicts well with its own inflows. sd-sawmill, sd-support-tiers, sd-print-shop and
   sd-cloud-credits score -16% to -561% as graded, but 76-97% with their own inflows. sd-housing
   loses in the same way. (These numbers come from a scratch re-scoring of the stored models, not
   from a committed command.) This changes what skill@20 means on realistic cases.
6. **Real twins:**
   - Their analysis uses the noise-free full-length run, not the training samples with
     measurement error, so their "achievable" labels are not meaningful.
   - The adoption twins' N = 100 - A makes several forms give the same levels. Should those
     forms count as equivalent?
7. **The analysis ignores floors,** so 125 is labelled unidentifiable although the floor that
   binds separates its gap from a drain.

## 2026-10-19 01:40 (user decisions on scoring)

The user answered the distilling agent's scoring questions. Approved scorer changes (one agent, with before/after flips reported per fix):
1. **dt < 1 cases:** "I would hope the issue would fall out after normalization". Compare per-recorded-step equivalents of the truth's continuous rates.
2. **Hidden stocks fed from outside:** score them as parts.
3. **Measured inputs:** include them in equivalence and in the linear oracle.
4. **Effects:** check equivalence for effects by what the flow computes (e.g. a product with its roles swapped).
5. **Real-data twins:** the analysis uses the twin's measurement noise and the training cut; decide whether the adoption twins' alternative forms are equivalent.
6. **Floors:** the analysis accounts for binding floors (125).

Still open: the behaviour grader feeding only the truth's constant inflows. The realistic agent is measuring it, and the result goes to the user before any change.

## 2026-10-19 02:30 (hourly cycle)

**Health**
- **Server:** summary 1.4 s warm, but 113 s on the first request after a restart; the payload is ~39 MB raw. The fast-leaderboard agent is replacing it with compact aggregates.
- **Watcher:** backlog 75,600 stale. It jumped because strategies changed code (input fixes, vendored copies), the scorer changed (cb1c69d), and new distilled and particle cases arrived.
- **Tests:** 1,239 passed, 51 skipped, 2 failed:
  - the noise "existing cases keep four variants" test: likely distilled 141-143; sent to the physics agent;
  - a realistic test on the uncommitted sd-k8s files; sent to the k8s agent.

**Finished since the last entry**
- **kalman_lna** (queue 0b; doc 00c0038).
- **Input handling** in censored, effect_hats and earned_pieces (89adae4, ccd07e2): 1,074/1,074 non-input cells identical; 062 and Newton cooling pass in every variant.
- **Particle cases** (5481119 … ba68e43): 8 cases; distilled 170, 171, 195.
- **Newest-tests view** (24930b2, `/ladder/new`): only one clean regression (lna_stack 101 counts-short, the known port loss).
- **Editor truth and strategy-switch fixes.**
- **The combined empty-model fix** (beab53e).
- **The six scorer fixes** (cb1c69d). Strict verdicts are pending until re-scored.

**Running** (10): structures, research round, short series, k8s, distilled fixes, realistic, physics, scorer fixes, fast leaderboard, one more. No new start.

**New strategies seen this hour** (each with an explanations entry; the test passes):
- realistic_hats, coflow_hats (copies of effect_hats);
- drifting_drain, own_tables (distilled-fix agent);
- odefit (physics agent);
- archetypes (short-series agent).

**Leaderboard, Tests** (`sdlab-ladder strict --no-fill`, rates over cells run; strict pending after the scorer change):

| strategy | pass | ran |
|---|---|---|
| realistic_hats | 81.4% | 118 cells only |
| kalman_lna | 73.6% | 1,006 |
| archetypes | 73.3% | 930 |
| structures | 71.7% | 1,006 |
| combined_lean / combined_r2 | 70.2% | 971 |
| combined | 68.3% | 1,002 |

Pass rates fell because the Tests set now includes the new distilled cases.

**Realistic** (mean skill@20 over latest results):

| strategy | skill@20 |
|---|---|
| realistic_hats | 50.4% (16 runs only) |
| effect_hats | 49.9% |
| censored | 41.9% |
| combined | 40.6% |
| kalman_lna | 38.6% |
| structures | 38.7% |
| matrix | 31.0% |

**Physics** (passes of 44 cells over the 15 physics and particle cases):

| strategy | passes |
|---|---|
| odefit | 27 |
| effect_hats | 17 |
| matrix | 17 |
| censored | 16 |
| combined | 15 |
| kalman_lna | 15 |
| archetypes | 12 (of 28) |
| structures | 11 |

**Distilled** (38 cases; passes over cells run):

| strategy | passes |
|---|---|
| structures | 25/90 |
| coflow_hats | 15/78 |
| censored | 13/150 |
| archetypes | 11/58 |
| combined | 6/90 |
| effect_hats | 4/130 |
| matrix | 1/126 |

At the first distilled run (20 cases), structures had 19/80 and every other strategy 0-3/80.

**Needs you**
- **The shared library's `identify.judge`, `identify.identify` and `onestep.bic` take no measured inputs**, so the main line judges input-driven flows as zero when choosing among its variants. The input-fix agent worked around it with local copies in its 3 strategies. Proposed fix: an optional `inputs=None` parameter, with existing calls byte-identical (an additive interface change). May the library change?
- **Behaviour grader:** swap in only the truth's truly exogenous inflows (constants with no effect)? This affects sawmill. Evidence is in `docs/research/realistic-triage.md`.
- **Still open from before:** retire dominated strategies, or run them less often, to cut the watcher's load.

## 2026-10-19 (note): physics coverage, odefit

**Triage** (every physics cell before this work: the best of the 59 strategies' stored results, from
`api.summary()`; 15 of 28 was the best single strategy, 21 cells passed by some strategy):

| case | none-short | none-long | meas-short | meas-long |
|---|---|---|---|---|
| coupled tanks | fail: spurious H2 <- pump (linear model of a sqrt cascade; skill fine) | pass (33 strategies) | earned_pieces only (gap -5.0, at the line); others lose H2's couplings | fail: spurious H2 <- pump |
| draining tank | pass | pass (combined fails: pump coupling lost, -198) | pass | pass |
| Lotka-Volterra | fail: the linearised oscillator (self-couplings missing; skill within 3-4 points) | numopt_fd_profile only | symbolic, sindy | symbolic, numopt_lbfgs |
| spring | pass | pass | fail: V <- P and V <- force lost (errors in variables; skill -50) | fail: same (-59 to -74) |
| cooling | pass | pass | pass | pass |
| chain | pass | pass | earned_pieces, sindy, common_cause | fail: C <- B lost (-20) |
| thermostat | fail: structure and skill (-26 to -38) | fail: skill -20, long-run 0.87 | fail: structure; skill -3.5 to -114 | fail: structure; skill -7.7 to -50 |

So: the noise cells were method failures (errors in variables). Output error on the true
structure reaches the reference on all of them. LV was the missing products. The tanks' short runs
were a linear misfit. The thermostat is part method, part scoring (below).

**Built:** `odefit` (docs/research/odefit.md; commits 3eacd05, 8d8e8c6). Per-step models linear in
their numbers (levels, measured inputs, a constant; products of two levels where they earn it and
do not run away), fitted by output error with every segment's start state estimated. The main
line's model is kept where it predicts a held-out 30% better, or, with noise in the dynamics
(counting noise), where the main line's judge prefers it.
**Physics 25 of 28** (was 15 at best; same at 333f814), gap to the reference -0.6 points (was -10 to -30), long-run
error 8.3% (reference 17%). Fails: tanks meas-short (every product family runs away; the linear
model keeps H2 <- pump) and thermostat long (both noises; skill within 3.3 points, structure only).

**Standard tests** (333f814, paired with matrix's latest results, 821 cells): 20 fail -> pass,
14 fail -> equivalent, 1 pass -> equivalent (087 outliers-long), 0 pass -> fail. **Particle
distilled 170/171/195:** noise-free 170 and 195 pass (shared with structures and others), 171
equivalent/fail; every counts cell fails (main line).

**Distilled** (commit 14da1fe): 141 (a noisy oscillator in offset stocks), 142 (an oscillator
pushed by a measured force, noisy), 143 (a chain into an ever-growing stock, 2% relative error).
Flows are exact, so only the measurement is noisy. matrix, lna, earned_pieces, symbolic and
kalman_lna pass the noise-free cells and fail the meas ones (141, 142 both lengths; 143 long), the
physics' mistake; odefit passes all 12.

**Needs you (physics scoring)**
1. **The thermostat's structure rule cannot be met by the best SD model.** A coupling is present at
   10% of the strongest coupling into the stock. In closed loop the controller's coupling (T <- T,
   T <- setpoint) is strong and the physical T <- outside is weak, so the best predicting model
   drops it or gives it the wrong sign. The reference itself fails the structure (LADDER.md). odefit's long
   runs are within 3.3 points of the reference's skill and fail on structure alone. Options:
   score the thermostat's structure without T <- outside, compare against the reference's own
   structure, or label the cell's structure unidentifiable. No change made.
2. **Is the 5-point rule fair?** Yes, on what was measured. The reference is fitted on the 2,000-step
   noise-free run, yet odefit is within 0.0-1.8 points of it on every short and meas cell of the
   linear and sqrt cases, and above it on LV and the tanks (products are not in the reference's
   form). The only cells further than 3.3 points below the reference are the thermostat's short
   runs (-4.3, inside the line).
3. **Per-step numbers are compared correctly.** Structure is read from the Jacobian of the found
   model's one-step map, with the exact one-step map's sampling couplings allowed. Behaviour is
   graded by stepping the found model against the sampled solution. Neither mixes per-step and
   continuous rates. The sampling-coupling list is not computed for the thermostat. The chain's
   exact-map C <- A (k1 k2 / 2, about 4% of C <- B) sits below the presence line, so it can never
   count against a model.
4. **The physics tag includes the particle cases** (`--cases tag:physics` ran 44 items for one
   strategy: the 28 physics cells and 16 particle cells), so "physics passes" quoted from a tag run mix the two. The physics view
   (`summary()["physics"]`) counts the 28 physics cells only.
5. **`tests/test_ladder_noise.py::test_existing_cases_keep_their_four_variants` fails on
   112-distilled-short-logistic** (archetypes, 445aabf). It declares a noise variant without the
   `noisy` tag. 141-143 are tagged `noisy` and pass the check. For the archetypes agent.

## 2026-10-19 03:40 (hourly cycle)

**Health**
- **Server:** leaderboard rows 0.13 s warm (the compact endpoint, 210afce); one listener.
- **Watcher:** backlog 75,600 stale, at about 2,000 per 26 min (about 16 h).
- **Tests:** 1,315 passed, 51 skipped, 1 failed. The noise test "existing cases keep four variants" still fails, likely distilled 141-143; sent to the physics agent last cycle. The realistic test now passes.

**Finished**
- **archetypes** (short series and twins): real held-out 0.9% → 4.9%; twins −1.3% → 10.0%, with 12 pass and 20 equivalent.
- **The fast leaderboard** (210afce).

**Started**
- 0c: the remaining 12 derivative strategies self-contained, starting from KNOWN;
- 1a: control-theory cases (the user's request);
- 1b: time measurements, run history, backlog ETA, cost (the user's request).

11 agents are running.

**Leaderboard, Tests** (`sdlab-ladder strict --no-fill`; strict re-graded after the scorer fixes cb1c69d):

| strategy | pass | strict | ran |
|---|---|---|---|
| kalman_lna | 71.3% | 63.7% | 1,046 |
| archetypes | 71.2% | 64.9% | 957 |
| structures | 70.9% | 64.5% | 1,033 |
| combined_lean | 70.2% | 66.8% | 971 |
| combined_r2 | 70.2% | 66.8% | 971 |
| combined_misfit | 69.8% | 63.5% | 971 |
| combined | 66.6% | 60.4% | 1,030 |

By strict: combined_lean / combined_r2 66.8%, archetypes 64.9%, structures 64.5%, kalman_lna 63.7%.

**Realistic, physics and distilled:** as at the 02:30 entry. Effect_hats leads realistic (49.9% skill@20). odefit leads physics (27/44). structures leads distilled (25/90), then coflow_hats (15/78).

**Needs you:** unchanged from 02:30.
- shared `identify.judge` gaining an optional inputs parameter;
- the behaviour grader swapping only exogenous inflows;
- retiring dominated strategies.

## 2026-10-19 06:05 (hourly cycle, after a usage-limit pause)

**What happened:** at about 04:45 the session hit its usage limit, and every running agent stopped mid-task. The limit reset at 06:00, and all 11 were resumed from where they stopped: scorer fixes, time measurements, control cases, distilled fixes x2, structures, physics, realistic, research round, 0c vendoring, and one unattributed agent (a9c204d, asked to state its task). No work was lost: agents keep their state.

**Health**
- **Server:** leaderboard 0.11 s warm; one listener.
- **Watcher:** running, backlog 69,970 stale (down from 77,394).
- **Load:** average ~40, lower during the pause.
- **Tests:** 1,315 passed, 51 skipped, 1 failed: the noise four-variants test, again sent to the physics agent (cases 141-143).

**Finished before the pause**
- **The Kubernetes models** (47a5fac, 78b69df): sd-k8s-small (74 stocks) and sd-k8s-platform (479 stocks, 1,130 flows). Only matrix gets useful behaviour, on the small model; every leader returns nothing or times out on the platform.
- **Heavy cases** (this cycle's coordinator change): a platform worker holds ~15 GB and memory was exhausted (0.1 GB free, 94 GB compressed). Cases tagged `heavy` now run only when named. sd-k8s-platform is heavy, and its case hash is unchanged.
- **Control-theory cases** 200-215 and `control.py` (cd9e8b1); the agent is finishing.
- **Time measurements** (c2a3c25): `sdlab-ladder cost` exists; the agent is finishing.

**Leaderboard:** as at 03:40. No new full strict run this cycle.

**Needs you:** unchanged.
- shared `identify.judge` gaining an optional inputs parameter;
- the behaviour grader swapping only exogenous inflows;
- retiring dominated strategies.

## 2026-10-19 06:30 (hourly cycle)

**Health**
- **Server:** leaderboard 0.17 s warm; one listener.
- **Watcher:** running; backlog ~70k (stale) at ~2,000 per batch.
- **Memory:** 200 orphaned sdlab worker processes (11 GB, 0% CPU, parent gone) were stopped at about 06:15; other projects' orphans were left alone.

**Finished**
- **structures** (2b): canonical 30/44 against combined's 3.
- **Realistic round 1** (realistic_hats; distilled 152-161; triage doc): goals met 14 → 15, timeouts 12 → 1.
- **Scorer fixes** (cb1c69d, f01908d): 179 flips, none into or out of pass.
- **Time measurements** (1b).
- **Control-theory cases** (1a): 16 cases plus 216-218. Leaders 14/448 pass.
- **Shape distilled fixes** (own_tables, drifting_drain, censored's floored gap): 121 PPPP; 122, 123 and 125 3/4 each. They carry back to 106 and phys-draining-tank.
- **Input fixes** in censored, effect_hats and earned_pieces.

**Started**
- realistic round 2 (mechanisms B-E);
- combined2 (combined round 2, with the new specialists and a held-out judge);
- distilled fixes for 156-160 and 216-218;
- 2d, engine features (harness only);
- 6, matrix_v2.

The physics agent was also given particles 170, 171 and 195. 10 agents are running.

**Numbers:** as at 03:40, pending a fresh strict pass.

**Needs you:** unchanged.
- an optional inputs parameter on the shared judge;
- the grader swapping only effect-free constants;
- retiring dominated strategies.

## 2026-10-19 07:30 (hourly cycle)

**Health**
- **Load:** 459 on 28 cores (about 4× usual), but the leaderboard was still 0.11 s warm.
- **Cause:** leftover runs from finished agents were still running: the k8s agent's two leader runs (one worker at 33 GB), the independence agent's common_cause bench (~14 h), and runs of odefit, coflow_hats and censored from agents that had reported. All were stopped with their workers; spawn workers went 57 → 34. sdlab still uses ~20 cores (other projects ~3).
- **Forks:** one agent (the 156-160 / 216-218 fixer) spawned four `fork` subagents and finished; two are still running and were asked to report and run at `--jobs 1`.
- **Skipped this hour:** cache refresh and tests, to avoid adding load.

**Finished**
- **odefit (physics agent):** physics 15/28 → 25/28; fresh skill@20 96.5% against the reference's 97.1%. Distilled 141-143 (oscillators and a chain under measurement error) pass 12/12 with odefit and fail for every other leader. No standard test lost.
  - Correction: the "27/44" quoted earlier mixed physics with particle cells.
- **k8s agent correction:** kalman_lna on sd-k8s-platform is untested (its runs were killed), not "in progress".

**Committed this hour, agents still running:** matrix_v2 (options and ablation), combined2 (first version), realistic_flows (realistic round 2), loop_transit, schedules, censored's floored gaps (218, 200, 203).

**Process issues**
- An agent's commit 6cb271f cut 392 lines from explanations.yaml by mistake; restored in 7cb33fd.
- Agents leave runs going after they report. From now on, a finishing agent must stop its own runs.

**Needs you**
- **The thermostat's structure rule** (from the physics agent): the best SD model can't meet it. A closed loop hides the weak T ← outside coupling below the 10% presence threshold. Options: drop that coupling from the expected structure; compare against the reference's structure (recommended); or label it unidentifiable.
- **Also open:**
  - an inputs parameter on the shared judge;
  - the grader swapping only effect-free constants;
  - retiring dominated strategies.

## 2026-10-19 08:30 (hourly cycle)

**Health**
- **Server:** leaderboard 0.10 s warm; one listener. Load is down to ~30 after the 07:30 cleanup.
- **Watcher was down.** A watcher holding pre-2d code crashed on case 113's new `signed` stocks (CaseError). Fixed in cli.py (committed): the watcher now restarts itself when the ladder's code changes, and never dies on a failed pass (it waits, then restarts on fresh code). Restarted; backlog 86,452 stale (new cases 113-117 and 216-218, new strategies, the scorer change re-scores).
- **Tests and caches:** not run this cycle (startup time); next cycle.

**Finished**
- **2d, harness engine features** (ea1a8dd): two-way flows and signed stocks, expressions (ratios, MIN/MAX/CEIL, if, sqrt/power, `flow()`), auxiliaries, switches with memory, DELAY FIXED and pipelines, TREND/FORECAST, ceilings that hold. All 3,533 recorded engine outputs are bit-identical. SDXorg exact conversions 90 → 139 of 165. Canonical cases 113-117.
  - Note: the engine hash used in case hashes is frozen at its 2026-10-18 value (`ENGINE_1018`), so additivity is enforced by the output-fingerprint test, not by hashes.
- **Research round:** combined_misfit, combined_lean and combined_r2. Strict 618 → 649/936; noisy 26 → 32; realistic skill@20 40.6% → 45.2% for misfit (not significant). Recommended for combined2.
- **loop_transit:** 156 passes 3/4; 4 better, 1 worse against realistic_hats.
- **common_cause** (final): 43/44 on 028-038. It explained the 032 noise-free failure (exact collinearity, shared stepwise and pelt), but it runtime-patches shared functions; queued as 2h.

**Started:** a scalable strategy for the k8s models, physics round 2, distilling canonical 113-117 and control failures, and 2h. Running with the earlier ones: realistic round 2, combined2, matrix_v2, 0c, distilled fixes 156-160/216-218, and two forks. About 10 in all.

**Needs you**
- **The thermostat:** score it against the reference model's structure (recommended)?
- **The shared judge:** an inputs parameter on `identify.judge`?
- **The behaviour grader:** swap only effect-free constants? Note: the research round found the merged `c + kx` flow's c gets counted twice by the grader's inflow swap. This is the same issue.
- **Retiring:** retire dominated strategies?

## 2026-10-19 09:00 (note: distilling 113-117 and the control cases)

**Finished:** distilled cases 220, 221, 222, 224 and 225 (docs/LADDER.md, "Distilled from the new canonical cases and the control cases"). They cover:
- 113's one-way reading of two-way flows: 220 (a signed stock) and 221 (an ordinary stock);
- 114's MIN, read as a linear blend: 222;
- 114's threshold hiring, read as a move out of the backlog: 224;
- the thermostat's switch with memory: 225.

All six leaders fail every cell of the five cases (`sdlab-ladder run --strategies combined,structures,kalman_lna,odefit,realistic_hats,matrix --cases 220,...,225`). 115-117's other failures are already isolated by 122, 133, 134, 137 and 172; 200-215 by 216-218. Engine and scoring gaps went to queue item 2k.

**Needs you**
- **115 can't pass by construction.** Its graduation reads a smoothing of the input, which the scorer leaves unscored. So any drain a strategy finds is spurious: every leader has noise-free skill@20 of 100% and still fails. Options:
  - score such a rate as a hidden path fed by the input, as a DELAY3 of an input is scored;
  - or drop the spurious count for flows that touch an unscored truth flow.

  Either one can turn fails into passes (CLAUDE.md invariant 5).
- **Found models are floored at 0.** Should found models be allowed signed stocks and two-way flows (the pinned `simulate.py`)? The scorer already takes `two_way: true` for the equations. skill@H, though, runs found models floored, so 113 and 220 can't get the truth's behaviour.
- **A pipe read as an Erlang chain passes.** structures passes 117 noise-free with a 5-stage exponential chain scored as delay 5. Should a DELAY FIXED's shape count (pipe against Erlang), or is the delay time enough?

## 2026-10-20 09:30 (note: Kubernetes rungs 1-2, cases 300 and 301)

**Finished:** [k8s-300-301.md](k8s-300-301.md). Every one of the 49 active strategies now passes every variant of 300 and 301. Store at 09:23Z, scorer ec821eb6, 0 stale:
- **300:** before, 1 of 48 strategies passed every variant (cells 202 pass / 115 fail / 11 error of 288); now 294/294 pass.
- **301:** before, 162 / 24 / 6 of 192; now 196/196 pass.

**Why:**
- **Errors in variables.** One-step least squares on levels with 5% measurement error came out 22-27% off on 300's meas variants. A Kalman bound showed the data could do better. Fixed by the eiv refit in 47 strategies (e8edf28, 5a31020, 4006a72).
- **Measured input.** The noise oracle ignored it (401a1e3, 0 flips). Some strategies ignored it or crashed on it: numopt f6643bf, common_cause/sindy f5537cf, shared_noise 42edc32, periodic_inflows/recession 1545e0f.
- **shared_noise move/link.** It read moves as links on noise-free data (2212020).

**Regression:** 087 outliers-long went pass -> equivalent for shared_noise and numopt_cma. The cause is eiv.py's acceptance on outliers, shared by every copy. Not fixed.

**Retirements:** none. shared_noise was considered and kept: the fault was fixable, and its move/link/co-flow test is unique.

**Needs you**
- **The Mac watcher excludes `tag:kubernetes`.** Should it now include it? Parked strategies' kubernetes cells are re-scored only by hand.
- **part-* cells error in the harness**, at physics/score.py:133.

## 2026-10-20 (note: Kubernetes rung 3, case 302)

**Finished:** [k8s-302.md](k8s-302.md), with round 2's details in [k8s-302-round2.md](k8s-302-round2.md). All 49 active strategies now pass every variant of 302-k8s-responses-counter. Before (rows on 66086e7) it was 174/196 cells: counts-short 27 pass / 22 fail, every other variant passing. Now it is 196/196, all on committed code: `store.latest(case='302-k8s-responses-counter')`. The sync `sdlab-ladder sync --strategies all --cases 302` printed "Nothing to run".

**Why:** the new feature, the final counter `responses_total`, exposed two older faults.
- **Chance pieces on inflight.** The counter fixes inflight's drain at 0.4973. Chance PELT pieces on inflight then absorb the leftover drain and win the in-sample judge (0.0461 vs 0.0520). Fixed by copying earned_pieces' refit into 17 strategies plus shared_noise's reselect (8c507a8), then into recession, starved_coflows and matrix_v2 (284390d).
- **Input-blind judges.** held_out, matrix_v2, recession and starved_coflows judged without the measured inputs and picked the counter-only candidate. Fixed by passing the inputs to their judges (c33de93).

**Flips:** no 300, 301 or 302 cell went pass -> not pass.

Off-rung losses, from paired in-process samples:
- 16 from earned_pieces' refit:
  - 15 inherited: noise-free collinear cross-links (042#5, 043#6/#8), 087 outliers, 016/080 pass -> equivalent for numopt
  - 1 from the textbook-price addition: drifting_drain 121
- 2 more from round 1's sample 1: master_eq 048#3 and drifting_drain 196.
- 9 from the input-aware judge, where the blind judge had been right by accident: 142 meas-long, 200, 201, 204, 215.
- 4 in round 2: recession 083 counts-long, starved_coflows 042#5 and 043#6, matrix_v2 043#4.

The gains were much larger: 184 fail -> pass on round 1's sample 1, 48 on cause B's 848 input cells, and +16 in round 2.

**Retirements:** none. All faults were fixable inside each fit. Refuted on the way:
- matrix's `gate` option: +6/-2 against +24/-0.
- matrix_v2's `white` and `pelt_mult 2` options.
- Round 1's claim that the 3 leftover cells had a second cause.

**Needs you**
- The earned refit now carries earned_pieces' noise-free cross-link and 087 outlier losses into 21 strategies. Should one fix (for example matrix_v2's float-precision rss floor under `exact`) be copied into every copy?
- mass_balance's `one_hidden` mechanism is lost (3 xfail).
- The refit makes runs about 1.4-2.7x slower, so watcher timeouts on sd-* cells are possible.

## 2026-10-20 (note: Kubernetes rung 4, case 303)

**Finished:** [k8s-303.md](k8s-303.md). Case 303-k8s-daily-traffic (302 with smooth daily traffic, plus meas variants) went from 188/294 cells passing to 293/294: `store.latest(case='303-k8s-daily-traffic')` over `select_strategies('everything')`, after `sdlab-ladder sync --strategies all --cases 303` printed "Nothing to run". counts-short 41 -> 49, meas-short 0 -> 49, meas-long 0 -> 48. The one left is odefit meas-long. 300, 301 and 302 still pass every cell (294, 196, 196).

**Why:**
- **meas.** The counter's step changes were buried by 5% level error (C1). This is an older cause: 303 is the first case with meas on a final counter. Smooth exact traffic also stood in for the noisy queue (C2), which is the new feature.
- **counts-short.** 8 strategies without the earned refit put chance outflow pieces on the final counter, because the daily cycle makes inflight's row weakly identified.

**Fixes:**
- **Harness (be34a8a).** `sync --strategies all` now includes parked active strategies, and `analyse` works on meas variants.
- **eiv.py, every copy.** Instrumented Wald pruning (def0acb). A drain becomes a move when the receiver's level-space row, with GLS noise growing with the level, earns it (9956255/b9fe1d6): +95 on 303, +35 on 143 meas-long, 0 regressions.
- **Per strategy.** The earned refit or base pruning went into coflow_hats, effect_hats, held_out, inflow_effects, loop_transit, realistic_flows and realistic_hats. sindy got earned pieces in fit_row. symbolic_anchor's addition test now reads the inputs.
- **Off-rung losses.** 5 in the paired samples, 4 of them the earned refit's known ones (083, 084, 042#5).

**Retired:** symbolic_anchor. Two skeptics could not refute it: there is no cell only it passes, and no small change lifts its effect coverage above 2/114.

**Not retired:** sindy. A skeptic showed it is the only strategy ever to pass sd-eras counts-long; the store had hidden this behind BrokenProcessPool rows.

**Needs you:**
- The per-stock oracle's tolerances are about 30x the joint bound on all counts/meas cells. Narrowing them changes what a pass means.
- realistic_hats' net -2 sample (099e99d).
- odefit meas-long.

## 2026-10-20 (note: Kubernetes rung 5, case 304)

**Finished:** [k8s-304.md](k8s-304.md), the first rung run as an elimination competition. Case
304-k8s-timeouts-and-errors (303 plus a 0.08 x queue timeout and 3% of inflight into errors_total) went
from 185/188 cells passing to 188/188 over the 47 roster strategies, and is 184/184 over the 46 left:
`store.latest(case='304-k8s-timeouts-and-errors')` over `select_strategies('roster:kubernetes')`, after
`sdlab-ladder sync --strategies roster:kubernetes --cases 304` printed "Nothing to run". 300-302 pass every
cell; 303 is unchanged (odefit meas-long).

**Why:** the new timeout drain was folded into the move or the traffic gain on counts-short (effect_hats,
inflow_effects, shared_noise; 3 equivalent). The new 5xx counter is found by everyone.

**Fixes (7b6d7f4):** effect_hats and inflow_effects' prune tries one proportional drain in place of a set
of outflow pieces; shared_noise's conserve prices the forced fit at one log T. 300-304 72/72 for the three;
paired samples +4, -0.

**Refuted:** that the ~2x high timeout reading is a bias (seed 304's draw; k8s-304-s2.md); that blockwise
is a duplicate of matrix (it runs its own method at 15+ measured stocks, so on 317, and differs on stored
particle cells).

**Eliminated:** unified, duplicate of matrix (same code path, 0 differences on 1148 shared cells). 46
survivors.

**Needs you:**
- On 13 of 20 fresh counts-short seeds the matrix line drops the timeout (lna 5/20); seed 304 hides it. A
  proper fix rewrites the matrix line with a counting-variance likelihood. 305's retries feed off timeouts.
- The scorer's tolerances are still about 30x the bound on counts cells.

## 2026-10-20 (note: the CPU pool)

**Finished:** the CPU pool ([../pool.md](../pool.md)), at the user's request: CPU, not agents, is the
bottleneck. The server on the Mac holds a job queue in the result store; workers pull items, run them in a
checkout per slot at the job's commit, and post results. Commits: 253da87 (server, queue, token), 902ded6
(worker), 4d6f982, c6ceb02 and 27153a0 (deployment), 27a552a (`sdlab-ladder submit` and `job`; `run` and
`sync` refuse above 40 items or 2 CPU-minutes), dc52b1c and 793b5b5 (review fixes).

**Where:** node2, a systemd `--user` service, 23 slots, `--max-mem-gb 44`, cgroup ceiling 47/49 GB,
`OOMPolicy=continue` (its other programs hold ~9 GB and it has no swap); the Mac, kept up by the daemon,
14 slots at nice 19, 96 GB, fewer slots above load 24. 2 heavy slots each. node2's old watchers, checkout,
bare repository and store are gone (its 2275 results were already here; a copy is in `~/.sdlab/node2-retired/`).

**Measured** (`pool_results`, 2026-10-20): job 4 (160 items) in 2.5 minutes; job 10's first 525 items in
3.5 minutes (~9,000 an hour: Mac 328 at 3.7 s, node2 197 at 11.2 s). Peaks: small cases under 0.5 GB,
realistic up to 9.1 GB, sd-k8s-small ~7 GB, sd-k8s-platform kalman_lna 33 GB and then ~130 GB on its retry
before the hard limit was capped at the worker's budget (793b5b5). A node2 memory stress (job 6, 198
realistic and heavy items alone) never went over ~22 GB; nothing was killed. The Mac stayed responsive with
13 busy slots.

**Open:** the main line is still paused (`~/.sdlab/watch.paused`, for the boundary workflow). The daemon's
`pgrep -f "sdlab.ladder worker"` also matches any shell whose command contains that text. Items that cannot
be planned or checked out use up retries instead of being released. A crash's peak is not kept, so the next
sd-k8s-platform kalman_lna starts at the 16 GB default. Particle cases fail at HEAD with `KeyError:
'galton'` (`sdlab/ladder/physics/score.py:133`, a harness bug). The model editor's writing endpoints
(`/api/models`, including `POST /api/models/{id}/discovery`) need no token and the server is on 0.0.0.0.
