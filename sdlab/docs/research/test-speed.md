# Making ladder tests faster: a lower time limit, and reusing shared first fits

**Status:** measured, nothing changed (2026-10-20). Study script: `tests/study_speed.py` (commands below).
Strategy code measured: a33bc14 (no uncommitted changes under `sdlab/discovery/`); store read at 15:50-16:15 PDT.
The two ideas are leads for whoever owns the watcher, the pool (docs/pool.md) and the strategies. This doc
changes no strategy, harness or library code.

## Short answer

| idea | discovery time saved | passes lost | risk |
|---|---|---|---|
| per-item limit 240 s (today 300 s; cases with their own limit stay as they are) | 2.3 h of 67.6 h (3.4%) | 0 | none measured |
| per-item limit 180 s | 4.3 h (6.3%) | 9 | the 9 are combined2 (5), structures (3), odefit (1) |
| per-item limit 120 s | 8.1 h (12.0%) | 112 | 71 of them odefit |
| **per-set limits: realistic 60 s, physics 180 s, the rest 240 s** | **8.6 h (12.8%)** | **0** | realistic results lose their scores, not their status (see below) |
| cache the main-line fits by (code hash, inputs) | 9.8% of run time on 20 cells; 8.6 h of 72.8 h projected | 0 | a cache keyed by name, not code, would be wrong for master_eq |
| the same, with vendored copies' import lines normalised | 11.5%; 10.6 h projected | 0 | equal outputs in all 40 groups it merges |

"Active" means `select_strategies('all')`: the 39 strategies that are neither parked nor retired. kalman_bayes
and the four parked combined* strategies held 52 more hours of the 120 h total, so they are left out. Counted with
them, every limit saves more and loses more: 120 s loses 210 passes, 92 of them kalman_bayes's.

## 1. A lower per-item limit

**Method.** `uv run python tests/study_speed.py limits --strategies all` reads every latest result that has a
time. That is 54,411 results for the active strategies (93,682 for all of them). A result's discovery time is
counted the way `timing.discovery_seconds` counts it: a timeout counts as its wall seconds. Under a limit L, a
result that took s > L stops at L, which saves s - L. If it passed or was equivalent it is lost, because it now
times out. A case whose own limit is already at or below L is left alone. Today's limits are 300 s for 53,803
results, and 900, 1200 and 1800 s for a few hundred physics and realistic results.

**Active strategies (67.6 discovery hours, 30,625 pass/equivalent):**

| limit | saved h | share | passes lost | lost per hour saved | results over |
|---|---|---|---|---|---|
| 30 | 27.47 | 40.7% | 821 | 29.9 | 1718 |
| 60 | 17.36 | 25.7% | 343 | 19.8 | 843 |
| 90 | 11.95 | 17.7% | 174 | 14.6 | 534 |
| 120 | 8.13 | 12.0% | 112 | 13.8 | 394 |
| 180 | 4.25 | 6.3% | 9 | 2.1 | 158 |
| 240 | 2.28 | 3.4% | 0 | 0 | 81 |
| 300 | 1.53 | 2.3% | 0 | 0 | 12 (physics only: their own 900-1800 s limit) |

Each step down: 300 to 240 s saves 0.75 h more and loses 0 passes. 240 to 180 s saves 1.97 h more and loses
9 (4.6 per hour). 180 to 120 s saves 3.88 h more and loses 103 (26.5 per hour). 120 to 90 s loses 16.2 per hour,
90 to 60 s 31.2 per hour, and 60 to 30 s 47.3 per hour. **The fewest passes lost per hour saved: 240 s loses none,
and 180 s loses 2.1 per hour.** Below 180 s the cost jumps.

**By set (hours saved, passes lost):**

| set | 60 s | 90 s | 120 s | 180 s | 240 s |
|---|---|---|---|---|---|
| tests | 5.22, 297 | 2.78, 146 | 1.21, 103 | 0.23, 9 | 0.06, 0 |
| noisy | 0.41, 24 | 0.18, 10 | 0.06, 5 | 0.01, 0 | 0, 0 |
| canonical | 0.85, 7 | 0.49, 7 | 0.24, 2 | 0.03, 0 | 0, 0 |
| physics | 4.61, 15 | 3.79, 11 | 3.17, 2 | 2.31, 0 | 1.79, 0 |
| realistic | 6.27, 0 | 4.71, 0 | 3.46, 0 | 1.68, 0 | 0.43, 0 |
| real | 0.01, 0 | 0, 0 | 0, 0 | 0, 0 | 0, 0 |

The realistic set holds 12.3 discovery hours and only 9 passes out of 903 results, and none of the 9 took longer
than 60 s. Physics holds 8.7 h. The slow tail is mostly these two sets and a few strategies.

**By strategy at 120 s (hours saved, passes lost):** sindy 1.55, 0; combined2 1.14, 17; structures 0.94, 15;
engine_forms 0.67, 4; kalman_lna 0.63, 3; common_cause 0.48, 0; odefit 0.45, 71; archetypes 0.44, 1. odefit
loses many passes for little time saved, because its passes take 120-180 s (the lost cells include 304/305
k8s, 030, 042, 043 and 152). At 180 s the lost passes are 030-two-chains-of-three, 043#1, 042#8, 131, 152, 195 and
305-k8s-retries.

**Caveats.**
- The store's times were taken under the shared machine's load (load average 34-37 on 28 cores while this was
  measured). In a quiet process combined2 took 32-36 s on 030 none-long, against 141 s in the store, and
  structures took 110 s against 197 s. A result near a limit can pass or time out depending on the load, so a
  tight limit turns load into failures.
- Composites that read the time left (combined2, realistic_flows/hats and loop_transit through
  `deadline.outer_left()`, blockwise's budget) shrink their own work under a lower limit instead of timing out.
  For them the "lost" count is an upper bound, but their results would change.
- A realistic result's value is its scores (skill, behaviour), not its rarely passing status. A 60 s limit
  there loses no passes but turns about 216 results into timeouts with no scores. Decide this per set, with the
  user.

**Recommendation.** Use 240 s for the watcher's default (0 passes lost, 2.3 h). For realistic and physics, set
per-set limits (60 s and 180 s, 0 passes lost, a further 6.3 h) if their scores may be given up on the slowest
cells. Together that is 8.6 h, 12.8% of discovery time, with no pass lost. A flat 120 s would save a similar
8.1 h but lose 112 passes.

## 2. Reusing a first fit that strategies share

**Method.** `tests/study_speed.py shared` runs each of the 42 roster:kubernetes survivors in one process per
cell, on 20 cells from `pick`: 8 tests, 4 noisy, 3 canonical, 2 realistic, 2 physics and 1 real, with short
and long variants, spread over cheap and dear cells (1.27 stored hours). There were 3 worker processes, under the
watcher's 300 s limit through `runner._alarm`. Before each strategy runs, every reference to these functions
in the loaded sdlab modules is wrapped (module attributes, and module-level lists, tuples and dicts of them). The
wrapping is a monkeypatch in that process only, undone afterwards, and nothing on disk changes:

- `identify.identify` (the pinned main line) and `matrix.identify_one` (its row fit), both from the shared library;
- every `main_line` a strategy package defines (the `earned.py` copies);
- copies of `identify`/`identify_one` in modules named `identify` or `matrix` (shared_noise, matrix_v2,
  common_cause's vendored matrix);
- the lna search `discover` in every `lna*.run` module, the vendored copies included.

Each call records three hashes of its code, its input hash (stocks, run, opts, canonical JSON, arrays by their
bytes), its output hash and its seconds. The code hashes cover the sources of the function's module and of every
sdlab module it reaches through its globals:
- **bytes**: the sources exactly as they are;
- **stripped**: comments and docstrings removed;
- **normalised**: stripped, with `from x.y.leaf import` read as `from leaf import`. This only merges vendored
  copies whose sole change is their rewritten imports.

The normalised hash is computed afterwards from the code on disk. Only the outermost wrapped call counts toward
the saving, so nested time is not counted twice. `report` then counts the saving of a cache keyed by (code hash,
inputs) over each cell: every call after the first with the same key is free.

**Results** (`uv run python tests/study_speed.py report shared.json`): 840 runs, 1.04 h of run time, 1 error.
That error is held_out timing out at 300 s on sd-university counts-short, as it does on the ladder.

- **20.0% of all run time is inside a main-line fit.** By function: earned `main_line` 0.069 h, `identify_one`
  0.051 h, `identify.identify` 0.025 h, the lna `discover` copies about 0.06 h together.
- **Byte-identical code:** 4,208 of 7,598 outermost calls repeat a (code, inputs) key already seen on the same
  cell. Caching them saves **9.8% of run time**. All of it is across strategies: no strategy repeats its own
  outermost call. Projected on the store (each strategy's saved share times its latest discovery hours), that is
  **8.6 h of 72.8 h**.
- Stripped hash: 10.5% (9.5 h projected). **Normalised hash: 11.5% (10.6 h).** The extra saving comes from the 12
  vendored lna copies, which differ only in their import lines and provenance comments.
- Caching only the frozen `matrix.identify_one` at every depth saves 6.8%.
- **Who gains:** the cheap strategies whose whole run is the main line, such as matrix (91.6% of its time),
  mass_balance 85.8%, drifting_drain 65.5%, censored 62.0%, latent_eras 55.9%, the lna family 42-48% and
  effect_hats 43.4%. The expensive ones gain little: combined2 7.7%, kalman_lna 6.8%, engine_forms 6.2%,
  structures 5.8%, inflow_effects 5.0%, odefit 4.1% and archetypes 0.4%. held_out, sindy, master_eq, matrix_v2,
  common_cause, blockwise, earned_pieces, recession and shared_noise gain nothing: their first fit is their own,
  with its own options.
- **Families of byte-identical code:** the earned main line is shared by 14 strategies (blockwise, censored,
  drifting_drain, hidden_transit, latent_eras, mass_balance, matrix, numopt_bo/cma/nm/powell, odefit, own_tables,
  periodic_inflows), and by 17 with loop_transit, realistic_flows and realistic_hats once normalised.
  `identify.identify` is shared by 16 strategies, and the shared `identify_one` by 19.

**Risk.**
- *Copies that differ.* In 60 groups on a cell, the same function name got the same inputs through different
  byte code. The outputs differed in 4 groups, all of them master_eq's `earned.main_line`: its `earned_rows.py`
  and `earned_joint.py` differ from the 14-strategy family, though its `earned.py` is byte-identical. A cache
  keyed by function name or by `earned.py` alone would hand master_eq the wrong first fit, so the key must hash
  everything the function reaches. coflow_hats, master_eq, loop_transit, realistic_flows and realistic_hats each
  have their own byte hash.
- *Normalised copies.* The normalised hash merged 40 groups whose bytes differ, and the outputs were identical in
  all 40. On this sample it is safe, but that is not a proof. An import rewrite could point to a module that
  really differs, and the closure would hash that module's own content, which keeps this case safe. A
  normalisation that missed a real change would not be.
- *Determinism.* There were 0 of 3,390 keys where the same code and inputs gave a different output.
- *Mutation.* The returned dicts are mutable. `main_line` itself sets `chosen` and `tried` on its result, and a
  caller may edit it. matrix's `_eiv_` refit deep-copies first, but not every caller was checked. A cache must hand
  out deep copies.
- *Invariant 11.* A shared cache couples strategies at run time. It is only safe if the key is the full code
  closure, so that a change to one copy can never reach another. Where such a cache would live (harness or pool)
  is for the user to decide. The shared library is frozen, so it cannot go in there.
- *Where the saving appears.* Items run in separate worker processes, so the cache would have to be on disk (or
  in the pool), keyed per cell. The saving appears only when the strategies run on the same cell with the same
  code: a full re-run of a cell, not a single strategy's re-run after its own change.

**Recommendation.** It is worth about 9-11% of discovery time (8.6-10.6 h), but mostly in strategies that are
already cheap. Do it only with a key over the full code closure (bytes, or normalised imports) and with deep
copies. The per-set limit above saves as much with less machinery.

## 3. Hot spots in the four most expensive strategies (leads only)

`tests/study_speed.py profile STRATEGY 030-two-chains-of-three none-long` (cProfile, a quiet single process; times
are under the profiler):

- **combined2** (35.7 s):
  1. `changes.pelt` 17.0 s own (4,509 calls)
  2. vendored common_cause `places.joint_pelt` 2.6 s
  3. vendored drifting_drain `segment.partition` 1.5 s
  4. numpy `lstsq` 1.2 s (4,081 calls)
  5. vendored common_cause `exact.pelt` 1.0 s

  Cumulatively, `matrix.identify_one` takes 13.8 s over 108 calls.
- **structures** (109.7 s):
  1. scipy `nnls` 60.9 s own (13,809 calls from `structures/fit.py:_solve`, inside `fit.search`, 74.5 s cum)
  2. `changes.pelt` 10.5 s
  3. `structures/terms.py:init_response` 5.6 s
  4. `lstsq` 2.9 s
  5. `fit.fit` 2.9 s own
- **odefit** (150.1 s):
  1. scipy batched `svd` 37.1 s (862 calls)
  2. `odefit/fit.py:_linear_parts` 34.7 s (22,332 calls)
  3. `einsum` 19.8 s
  4. `fit._batch_steps` 16.8 s
  5. `changes.pelt` 11.3 s

  Of the run, 135 s is `least_squares` (trf) in `run.output_error` and `prune`. The finite-difference
  Jacobian (`approx_derivative`) costs 55.7 s of that.
- **inflow_effects** (69.7 s):
  1. `changes.pelt` 14.9 s
  2. MINPACK `lmder` 11.0 s (from `gate.polish`)
  3. `lstsq` 9.9 s (49,330 calls)
  4. `gate._viterbi_w` 8.4 s
  5. `gate._alternate` 2.6 s own

  `gate.search` takes 60.0 s cum, through `_best_knots` and `_knots_fit`.

**`changes.pelt` is in all four, and is mostly called again on inputs it has already seen**
(`tests/study_speed.py repeats sdlab.discovery.changes pelt STRATEGY 030-two-chains-of-three none-long`):

| strategy | calls | distinct inputs | seconds in pelt | seconds on repeats | share of the run |
|---|---|---|---|---|---|
| combined2 | 4,509 | 1,136 | 17.1 | 12.5 | 38.9% |
| inflow_effects | 3,925 | 953 | 16.2 | 12.1 | 16.8% |
| odefit | 3,984 | 476 | 12.4 | 10.8 | 7.0% |
| structures | 2,782 | 1,136 | 10.8 | 6.2 | 5.6% |

A memo on (series bytes, min_len, mult) inside a strategy would remove those repeats without changing any
result, since pelt is deterministic. `changes.py` is the frozen shared library, so the memo would go in a
strategy's own copy, or in the library with the user's approval. That is one cell only; other leads:
- structures: fewer or warm-started `nnls` solves in `fit.search`;
- odefit: an analytic Jacobian instead of finite differences, and fewer SVDs in `_linear_parts`.

## Commands

```sh
uv run python tests/study_speed.py limits --strategies all            # section 1 (active strategies)
uv run python tests/study_speed.py limits                             # section 1, every stored strategy
uv run python tests/study_speed.py pick > cells.json                  # the 20 cells
uv run python tests/study_speed.py shared --cells cells.json --out shared.json --jobs 3
uv run python tests/study_speed.py report shared.json                 # section 2
uv run python tests/study_speed.py profile combined2 030-two-chains-of-three none-long --top 12
uv run python tests/study_speed.py repeats sdlab.discovery.changes pelt combined2 030-two-chains-of-three none-long
```

The shared run took about 21 minutes of wall time on 3 processes, under the machine's load. It is in-process
instrumentation, so it cannot go through the pool (CLAUDE.md 15b; the pool's workers were not running yet).
