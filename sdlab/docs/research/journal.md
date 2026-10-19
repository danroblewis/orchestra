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

  Parking keeps the code and history but stops the watcher spending time on them. I have not done it.
