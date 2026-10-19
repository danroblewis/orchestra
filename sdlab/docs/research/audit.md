# Audit of claims made to the user (2026-10-18, ~17:30-17:55 PDT / 00:30-00:55 UTC)

An independent, read-only check of what the orchestrator told the user about the discovery
research and about the orchestration itself. Every number below comes from a command run during
the audit; the store (`~/.cache/sdlab/ladder/results.sqlite`) was changing under it (several
`sdlab-ladder sync/run` processes and strategy agents were active), so "now" means the time of the
query. Where a number has moved since the claim, the claim is judged against the store's history
for the strategy version that was current when it was made, and the drift is reported separately.

Scripts used are short Python reads of `sdlab.ladder.store` / `cases` / `catalog` / `runner.plan`,
`curl` on `/api/ladder/*`, `git log/show/status/diff`, `sdlab-ladder check`, `pytest tests/test_ladder*.py`
and `tests/bench/compare.py`. Nothing was run into the store.

## Verdicts

| # | claim | verdict | evidence |
|---|---|---|---|
| A1 | hidden_transit passes 015 in 3/4 (fails counts-short), 026 in 4/4; nothing else ever passed 015; no other case changes vs matrix; 56 P / 14 E / 62 F of 132 | **VERIFIED (when made); drifted** | store: HT 015 none-short/none-long/counts-long pass, 026 all 4 pass; `results` table: only `hidden_transit` has ever stored a 015 pass; HT vs matrix latest statuses differ only on 015 (3) and 026 (4); HT on 001-033 = 56 pass / 14 equiv / 62 fail of 132 (matrix 49/14/69). **Drift:** scorer commit c9b6072 (hidden-stock oracle, score hash 3ef6c33b) turned HT 015 counts-short into a pass (now 4/4) and also mass_balance / mass_balance_all 015 counts-short and mass_balance 026 counts-short into passes, so "only hidden_transit passes 015" is no longer true under the current scorer. |
| A2 | examples bench skill@20 29.6% -> 31.2%, 10 better / 1 worse | **VERIFIED** (saved output, not rerun) | `tests/bench/compare.py v2.1 2026-10-19T00-04-18-400Z-hidden-transit-final.json`: skill@20 10 better, 1 worse, 51 same, +1.5 points, sign p=0.0117; clipped means 29.6 -> 31.2 (@100 29.3 -> 33.5). Caveat: that run's `commit` field is `86d0394+changes`, i.e. uncommitted code. |
| A3 | 034-038 exist and pass `check`; lna 14/20, common_cause / earned_pieces / held_out 12/20, matrix 5/20; noise-free 034/035/038 fail for all, 036/037 noise-free pass for (nearly) all | **VERIFIED (when made); drifted** | `sdlab-ladder check --cases 034..038`: all `ok` (commits 6b905a1, 9f5c944). Per-version history on 034-038: lna 14/20 (all 8 versions), common_cause 12/20 (hashes 06861447, e669ddab), earned_pieces 12/20, held_out 24/40 = 12/20, matrix 15/60 = 5/20. 036/037 noise-free: 32/32 strategies pass. **Drift:** common_cause from hash 71edd39b (00:21 UTC) onward passes noise-free 034 and 035, from 820d9eb5 (00:23) also 038; now 19/20. effect_hats (not in the claim) is 14/20. |
| A4 | 035 noise-free: [A, B, C, 1] span 2 dimensions; same for 034, 038 | **VERIFIED, with a precision caveat** | SVD of column-normalised [levels, 1] on recorded data: 034 none-short sv/sv0 = 1, 3.3e-2, 3.8e-16, 1.3e-20 (rank 2); 038 none-short 1, 4.6e-2, 8.3e-3, 4e-16, 3e-17 (rank 3 of 5 = 2 per identical chain pair); 035 none-short 1, 7.0e-2, **6.9e-8, 3.1e-8**: rank 2 only up to the recording's rounding (levels are stored to 4 decimals; B = 0.5000001 A + 49.99999, C = -1.5000001 A + 250.00001, max residual 1e-4). Also all three stocks sit within 1e-6 of 100 from step 66, so most of each run carries no information. Analytically exact (each gap to 100 shrinks by 0.8 per step). With counting noise the matrix is full rank (sv ~0.03-0.08). |
| A5 | matrix on 034 none-long: `B -> outside = 0.2*A`, `C -> outside = 0.2*A` | **VERIFIED** (none-long); none-short differs | latest matrix 034 none-long (hash b0884353): A->out 0.2A, B->out 0.2A, C->out 0.2A, three inflows 20. none-short is a different mess: 0.1A and 0.1B split across all three drains. |
| A6 | noise-free link == move + smaller drain; ~74 lna cells equivalent, mostly noise-free link/loop | **VERIFIED** | Algebra: link (B += kA, A -= dA) and move kA plus drain (d-k)A give the same dA, dB exactly. Store: lna equivalent = 74 of 472; 60 noise-free (30 none-short, 30 none-long), 14 noisy; by case 046 26, 045 17, 047 (goal gap) 16, 010 3, 016 3, 007/008/009/011 2 each, 044 1. "Mostly link/loop" = 50 of 74; 18 are goal-gap cases. |
| A7 | lna 60.5% hand-written, 70.3% all; any-strategy 88.8% / 81.8%; later 72.0% | **VERIFIED and reconciled** | lna timeline (`/api/ladder/strategies/lna/timeline`): versions 7f1be14c/eadfd61c = 332 pass of 472 = 70.3%; at that time 92/152 hand = 60.5%. Now (hash 79e9c3b6/37a7a2d3) 340/472 = **72.0%**, hand 94/152 = 61.8%. Any strategy passes: now 136/152 = 89.5% hand, 396/472 = 83.9% all (was 135 and 386). The two lna numbers are two lna versions 6 minutes apart, not a discrepancy. Caveat: the "latest" lna row set mixes versions (59 of 472 rows are on an older hash, i.e. stale and not re-run). |
| A8 | complexity.py as documented; Occam common_cause ~90, earned_pieces ~87, lna ~86; matrix ~1.7x; commits bf219c5, 3847fc2; ladder tests pass | **VERIFIED except tests: PARTLY** | complexity.py docstring and `occam()` (lines 189-199): fit x min(1, true/found), fit 1 for pass/equivalent else right/of, 0 for error/timeout. From `/api/ladder/summary` (472 cells): common_cause 90.7%, earned_pieces 86.8%, lna 86.0%; x truth geometric mean: matrix 1.71, common_cause 1.01. Both commits exist and touch only complexity/api/cli/store/static/docs/tests. Tests: `pytest tests/test_ladder*.py` -> 743 passed, 14 failed, all from the in-progress sweep case 052, none from complexity (see Tests). |
| A9 | 8cc69d9 throttles the summary; public summary well under 1 s warm; leaderboard loads; one process on :8020 | **PARTLY** | 8cc69d9 adds a 10 s FRESH_FOR + non-blocking lock (api.py:178-207). Warm: local 0.05-0.19 s; public 0.36-0.70 s (7.4 MB raw, 0.54 MB gzipped; gzip middleware is an uncommitted edit to server.py). `/ladder` and `/ladder/leaderboard` 200 in ~0.1 s. One listener on 127.0.0.1:8020 (PID 55641, then 61881 after a restart at 17:40). **But:** 30 samples 3 s apart: 28 under 0.2 s, one 0.79 s, one **6.6 s** (the request that recomputes after a store change waits for the whole recompute); right after the 17:40 restart requests took **3.8 s, 25 s and 81 s** (no cached copy, every request blocks on the lock, load average 93). "About a second" holds only warm. |
| B10 | "re-runs a strategy automatically whenever its code or a case changes" | **FALSE as stated** | What is automatic: staleness. Results are keyed by case hash, strategy hash (own package + imported sibling strategies + all of `sdlab/discovery` outside `strategies/`) and score hash (`store.staleness`, `catalog.strategy_hash`), and the matrix marks stale cells. Nothing re-runs them by itself: no `sdlab-ladder watch` process, no cron/launchd job. The running ladder processes are one-shot commands started by agents (`sync --strategies everything` since 17:32, `run --cases tag:parametric ...` since 17:33, `sync --strategies combined`, `sync ... --cases tag:sweep`). `runner.plan` right now: **15,076 stale items** for the default strategies (13,796 never run, 1,230 strategy changed, 48 case changed (035), 2 scoring changed). The test suite does not run strategies at all. |
| B11 | every version stored; History shows lna improving | **PARTLY** | Rows are never deleted; lna has **25 strategy hashes** since 23:30 UTC, each listed by the timeline API (0.7 s) and drawn by the History view (`ladder.js:564-567`). But (a) only the hash is kept, not the code: lna has 5 commits (b351d67 .. 2dcc85f) and uncommitted edits now, so most of the 25 versions were uncommitted working states that cannot be re-run (invariant 8); (b) each point's totals are "of 472" but early versions ran only 100-152 cells, so the curve (31 -> 340 passes) mostly shows more cases being run, not lna improving; on like-for-like cells it went 80 -> 94 on the 152 hand-written cells. |
| B12 | parked.yaml lists 10 with reasons; default skips; `everything` includes | **VERIFIED** | `sdlab/ladder/parked.yaml`: 10 entries, each with time and pass rate; `runner.select_strategies` (runner.py:56-74): "all"/empty drops `parked()`, "everything" keeps all. A `sync --strategies everything` is running now. Note: the leaderboard still lists parked strategies, with their not-run cells counted as non-passes (see B16). |
| B13 | invariant 1: discovery never sees the truth | **VERIFIED** (no violation found) | `runner.discover` (runner.py:105-111) passes `page_stocks(model)` (measured stocks' id, name, unit, final, group), `{"t", "levels"}` where `levels` = `Truth.measured()` (measured stocks only, sdtruth.py:153), announced eras (only when >1) and announced injections. The truth model, `all_levels`, seed and case id stay in `run_item`. Grep of `sdlab/discovery/strategies/**` for `sdtruth`, `all_levels`, `ladder`, `cases/`, `.yaml`, `seed`, `truth`, `counters`, `SDLAB_LADDER`, file reads, frame introspection, hard-coded case ids or stock names: only docstring/comment hits (censored/__init__.py:4,6,8,22; common_cause/exact.py:10,20,89; floors.py:15; combined/params.py:3) and env-var option parsing. Observation: the `final` flag is structural information that comes from the case (used by matrix.py:102); it is part of what a page gets, so allowed, but only 001 uses it. |
| B14 | invariant 12: agents own their files | **PARTLY: no clear violation in commits; large uncommitted shared edits** | Commits e350038..HEAD touching shared modules: a3a5e01 (cases.py), 8cc69d9 (api.py), 6b905a1/9f5c944 (new cases 034-038), bf219c5/3847fc2 (complexity agent: complexity, api, cli, store, static), c9b6072 (oracle agent: hidden_oracle.py, score.py). Every strategy commit touches only its own package/tests (19de233 common_cause, 51a7422/559c670/86d0394 earned_pieces, dedca50 censored, 4298f8d effect_hats, 2dcc85f/1f3356c/3a379e6 lna). No change to `sdtruth.py`, `sdlab/discovery/*.py` or `skill.py`. Uncommitted now: +502/-47 lines in ladder api/caseformat/cases/cli/routes/runner, server.py, basics.py, static (draws, long-run, sweeps), plus untracked analysis.py, fisher.py, draws.py, jump.py, longrun*.py, cases 039-056. All in the roles' lanes as far as can be told, but every commit is by "Orchestra Dev", so authorship cannot be proved from git. Case meanings 001-038: case hashes unchanged in the store's history except **035**, whose hash changed when 9f5c944 reworded its `tests:` sentence (the model is unchanged; the hash covers the compiled case including `tests`). |
| B15 | invariant 13: every strategy documented, with a README row | **FALSE** | No doc: **lna** (the top pass-rate strategy), **earned_pieces**, **combined** (its docstring names `docs/research/combined.md`, which does not exist), **lna_loops** (names `revisit.md`, missing), lna_pulses, gap_prior (names `identifiability.md`, which never mentions it). Docs exist but are untracked and have no row in `docs/research/README.md`: common_cause.md, effect-hats.md, censored.md. `tries.md` mentions none of lna, common_cause, earned_pieces. `strategies/README.md` has no row for censored, combined, common_cause, earned_pieces, effect_hats, gap_prior, hidden_transit, lna, lna_loops, lna_pulses. (Older strategies are covered by topic docs: held_out -> held-out-judge.md, numopt_* -> numerical-optimisation.md, etc.) |
| B16 | invariant 6: not-run cells | **VIOLATION confirmed** | `leaderboard.html:136-140`: `n = cs.length` over every cell of every case, so `pass = k("pass")/n` counts not-run as a non-pass, and `occam: mean(cs.map(c => c.occam || 0))` (line 169) counts not-run as 0. The note says "(not run, error, timeout = 0)", and not-run is lumped into the grey "error / timeout / not run" bar, but the rates are not labelled. Misranking, from the summary at ~00:50 UTC: combined 33.5% pass shown (87.3% of the 181 cells it ran), Occam 38.0% (99.2% on its runs); gap_prior 23.7% (73.2% of 153); lna_loops 21.8% (69.1% of 149); hidden_transit showed 29.2% before the parametric run filled its cells (53% of the 258 it had run). So combined ranks below matrix on the board although on its own cells it is the best strategy. Comparisons are also not paired (different cell sets). |
| B17 | work claimed in progress | **mostly VERIFIED in progress; two docs missing** | combined: `strategies/combined/` (untracked, 7 files, edited 17:36), stored on 181 cells, a `sync --strategies combined` running; doc missing. Revisit: no `docs/research/revisit.md`; `strategies/lna_loops/` (named as part of the revisit) untracked, 149 cells run, so started, nothing written up. Mathematical probes: `ladder/analysis.py` (24 KB) and `fisher.py` (17 KB), untracked, edited 17:42-17:44; sweep cases 049-056 (`grid(...)`) untracked, a `sync --cases tag:sweep` running. Long run: `ladder/longrun.py`, `longrun_cache.py`, `longrun_series.py`, `jump.py`, `static/ladder-run.html`, route `/api/ladder/longrun/{id}` and `/ladder/run` page (uncommitted). Hidden-stock oracle: **done**, committed c9b6072. Parametric draws: `draws.py` + cases 039-048 (10 cases, 8 draws each, 320 cells), all untracked, results stored. common_cause for independent systems: committed 19de233 (doc untracked); on the `independent` tag 135 pass / 2 equiv / 3 fail of 140 (lna 124, matrix 69). |

## Tests

`pytest tests/test_ladder*.py` (single-threaded): with `-x`, 566 passed and
`test_ladder.py::test_the_cli_runs_a_subset_end_to_end` failed with
`ValueError: invalid literal for int() with base 10: 'grid(100'` at `sdlab/ladder/cases.py:168`:
the untracked sweep cases (049-056, `grid(...)` numbers) are not yet understood by the committed
case loader in every path. A full run a few minutes later (the sweep agent had changed the loader
meanwhile): **743 passed, 14 failed**: `test_there_is_a_ladder` (052-sweep-run-length), 12 x
`test_the_true_model_passes_its_own_equation_scoring[...052-sweep-run-length#1..6]` (none-short and
counts-long) and `test_the_page_s_endpoints`. All failures involve the in-progress, untracked sweep
case 052; the complexity, draws, hidden-oracle, long-run and strategy test files pass. So "ladder
tests pass" was true for the committed tree at the time, and is false for the working tree now.

## Invariant violations found (most serious first)

1. **Nothing re-runs automatically (claim B10 is false).** Staleness is computed correctly, but no
   watcher runs; 15,076 items are stale. Results the user sees are whatever the last ad hoc command
   left, a mix of strategy versions (e.g. 59 of 472 lna rows, 18 of 20 earned_pieces rows on 034-038
   were stale when queried).
2. **Not-run cells counted as fails on the leaderboard (invariant 6).** Strategies that have not run
   the parametric cases are ranked by a diluted rate; combined (best on its own cells) shows 33.5%.
3. **Results from uncommitted code, versions not reproducible (invariant 8).** lna has 25 stored
   versions in ~80 minutes and 5 commits; the hidden_transit bench run was on `86d0394+changes`;
   the server runs uncommitted ladder/server code (restarted 17:40). A number quoted from such a
   version cannot be rerun.
4. **Undocumented strategies (invariant 13).** lna, earned_pieces, combined, lna_loops, lna_pulses,
   gap_prior have no doc; common_cause, effect_hats, censored docs are untracked and unindexed;
   tries.md is silent on the current leaders.
5. **The hidden-stock oracle copies hidden_transit's own filter (c9b6072).** It was reported with
   before/after statuses (good, invariant 5), but the tolerance on 015/026 is now set by the very
   model family hidden_transit fits; the commit says the SEs were checked against 30 fresh seeds,
   which is the right test, but it should be reviewed independently since it turned the strategy's
   one failing cell into a pass.
6. **The summary can block for seconds to minutes** (6.6 s warm spike, 25-81 s after a restart under
   load), against invariant 15's "about a second".
7. **035's hash changed for a wording edit** (9f5c944, a minute after the case was added). The model
   is unchanged, so no meaning changed, but 48 results are now stale for it; the hash covering
   `tests:` contradicts LADDER.md's "rewriting how it is written does not" make results stale.
8. Minor: runner workers import the strategy code when they first run an item but record the hash
   computed at plan time, so a long run (e.g. the 17:32 `everything` sync) can store results of
   newer code under an older hash. They then show as stale, so the harm is wasted re-runs and
   mislabelled history points, not wrong current results.

## Recommendations

- **Make "re-runs automatically" true:** run one `uv run sdlab-ladder watch --jobs N` as a single
  owned background service (launchd or a supervised `nohup`, one instance, logged), restricted to
  the default (non-parked) strategies, and have agents stop launching overlapping `sync` runs; or
  stop making the claim and say "stale results are marked; `sdlab-ladder sync` re-runs them".
  Show the stale count on the leaderboard header.
- **Leaderboard:** compute pass rate and Occam over the cells a strategy ran, show "ran n of N"
  next to it, and rank only strategies with the same cell set (or restrict the ranking to cells
  every compared strategy has run, which is the paired comparison invariant 6 asks for).
- **Record the code:** store the git commit plus a diff hash (or the strategy's source tarball) with
  each result, and require a commit before a number is quoted to the user. Compute the strategy
  hash in the worker from the files it actually imported.
- **Docs:** each strategy agent writes `docs/research/<name>.md`, its row in `README.md`,
  `strategies/README.md` and a line in `tries.md` before its numbers are reported.
- **Summary latency:** compute the summary in a background thread and always serve the last copy
  (also on cold start, after a first compute at server start); never block a request on it.
- **Case hash:** exclude `title`/`tests` text from the hash, as LADDER.md already promises.
- Have someone other than the oracle's author review `hidden_oracle.py` against the identifiability
  analysis (`analysis.py`/`fisher.py`) for 015/026 before counting the new passes.
