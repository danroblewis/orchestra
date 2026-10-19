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
