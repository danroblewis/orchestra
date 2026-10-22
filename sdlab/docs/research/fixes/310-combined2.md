# 310 (k8s-memory-oom), combined2: noise-free and counts variants

Agent combined2-310, 2026-10-21 (round 1), and combined2-310-r1, 2026-10-22 (round 2, below). The plan: climb kubernetes
307-311 on none-short, none-long, counts-short and counts-long only (the user, 2026-10-21). No regression runs on earlier rungs.

## Round 2 (2026-10-22): none-short and none-long pass; both counts variants are data-limited

Pool results (`uv run sdlab-ladder job N --json`, Mac pool, read 2026-10-22; parts right of 23, or of 26 once a found
hidden stock is matched to the truth's leak, which makes its two flows parts):

| variant | analyse | job 274 (c22e751) | job 283 (c437a7d) | job 285 (d363245) |
|---|---|---|---|---|
| none-short | not analysed (target) | FAIL 14/23, 194 s | **PASS 26/26**, 170 s | **PASS 26/26**, 168 s |
| none-long | not analysed (target) | FAIL 21/23, 417 s | **PASS 26/26**, 437 s | **PASS 26/26**, 389 s |
| counts-short | data-limited (below) | FAIL 16/23, 66 s | FAIL 16/23, 40 s | FAIL 16/23, 37 s |
| counts-long | data-limited (below) | FAIL 13/23, 750 s | FAIL 11/23, 856 s | FAIL 13/23, 757 s |

What changed between the rounds: the scorer now credits a found model's own hidden stock (198baf2, the user,
2026-10-21), so the leak can be written as a stock instead of a schedule.

### Diagnosis (rule 4b)

- **none-long: mem's two parts (a method fault, now fixable).** mem's row is `0.5 x (150 + leak + 2 x inflight /
  max(1, ready)) - 0.5 x mem`. The leak gains 1 a step and loses `leak x table(mem)`, the same per-pod fraction as the
  OOM move `ready -> pending = ready x table(mem)` that counted.py already reads off `oom_kills_total`. So the leak's
  level is known up to its start and scale once the kill fraction is known: `H = h0 P + Q` with P, Q stepped from the
  fraction. With H and the per-pod rate `inflight / max(1, ready)` the row is exact (SSE 1.2e-4 on 2000 steps, the
  levels' rounding).
- **none-short: the requests block (a method fault).** Every specialist with the requests right (censored: BIC -5380)
  runs away elsewhere (multi-step error 47-213 against 0.68), so the runaway guard leaves realistic_hats, whose model
  has no flow at all on inflight, responses_total or errors_total. The later passes refit only flows a model has.
  Also, hinge.py refitted queue's declared **input** side (`0.89 x traffic - 0.56 x queue`, "input altered"), which
  the user's rule fixes at exactly 1 x traffic.
- **counts-short and counts-long: data-limited on the OOM move.** An oracle check (scratch `ach.py`): the truth's own
  model, with only the kill table refitted on the counter by non-negative least squares **at the true knots** (480,
  512, 560), scores the move `ready -> pending [ready]` and its effect 28.7% off on counts-short (6 kills on 3 steps)
  and 16.4% off on counts-long (91 kills on 44 steps), against a 10% tolerance with no standard-error allowance
  (`se` None). The rate's relative SE alone is about 1/sqrt(91) = 10.5%. No method can place this part, so neither
  counts variant is a target (the rung passes on its achievable variants).

### Fixes kept (round 2)

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| hidden-integrator-stock | `hiddenrow.py`: for a measured, non-final stock S with an outside inflow (declared `in`, not `input`) left above 1e-6 of its change's energy, S's row is refitted as `in = c + b H + sum w Z`, `out = a S`, where H is a hidden stock fed 1 a step (its scale rides on b) and drained by m x the per-unit fraction `k x table(X)` of a table-effect flow `k x A x table(X)` the model already has (the same event acting per unit on another quantity; m by golden section from 1). H = h0 P + Q makes the row linear; h0 >= 0. Z: measured levels, inputs and per-unit rates `X / max(1, Y)`, by forward selection on BIC; a column must lower the SSE by more than 2 log n on the effective n of the residuals with it (n (1 - rho)/(1 + rho)) and move the row by more than 1e-3 of its spread. Kept when S's BIC falls by > 2 log n against both the model's own sides and the best plain refit. No constant drain is offered: with a constant inflow its H is a fixed curve in time, a schedule ("fits, not robust"). Written as flows `outside -> H = 1`, `H -> outside = k m H x table(X)`, `outside -> S = expr`, `S -> outside = a S`, with `inferred_levels[H]`. | c437a7d | copy `hiddenrow.py` (needs `hinge.columns`, `row_error`, `_side`, `_k`, `allowed_sides`) and call `hiddenrow.apply(r, stocks, run, opts)` last, after a counted-flow pass has written the effect flow (combined2's or structures' `counted.py`) |
| block-repair-nnls | `rowrepair.py`: for each unit, when a stock of that unit has no flow at all while its level moves (row above 1e-4 of its energy), every proportional move A -> B the block lacks (A not a counter) and every declared outflow A has no flow on are fitted together to the block's residual rows by non-negative least squares (each move appears in two rows with opposite signs: mass balance identifies it); the kept trials are added, the block is refitted jointly (`counted._repair_once`), each added flow is dropped again unless it lowers the block's BIC by > 2 log n, and the block is replaced only where its BIC falls by > 2 log n. The SSE floor is the levels' rounding (q^2 / 6 a row-step, q found from the reported decimals). A greedy one-move-at-a-time version picked `queue -> responses_total` first (the quasi-steady state makes inflight ~ queue) and was dropped. | c437a7d, d363245 | copy `rowrepair.py` with `counted.py` and `hinge.py`; call it after counted and before the last floored refit |
| input-side-held | `hinge.allowed_sides` never offers a side declared only `input`, and `counted._refit_moves` holds flows marked `input`: the boundary pass fixed queue's inflow at 1 x traffic, and the later floored refit had undone it | c437a7d | any strategy whose post-boundary passes refit outside sides: skip sides whose declared kinds are all `input` |
| bare-trigger | rowrepair's trigger narrowed to bare stocks: on counts-long the looser trigger (any row above 1e-4) refitted the pods and requests blocks (13 -> 11/23: `desired <-> ready` invented, `inflight -> errors_total` lost) and took 856 s of the 900 s timeout | d363245 | part of `rowrepair.py` |

Tests: `tests/test_hiddenrow_combined2.py` (2: a synthetic cache with a hidden junk stock cleared at the counted
fraction, found with its per-unit rate and drain exactly; no hidden stock where the row needs none),
`tests/test_rowrepair_combined2.py` (2: a queue / busy / retry / done block found together from the input alone, the
input side untouched; an explained block left alone). Before each commit these passed with
`tests/test_counted_combined2.py`, `tests/test_hinge_combined2.py`, `tests/test_switch_combined2.py`,
`tests/test_isolation.py`, `tests/test_frozen.py` (14 passed).

Local diagnostics, not results: the passes applied to stored answers and re-scored (scratch `rs.py`, `post.py`):
none-long 21/23 -> pass 26/26 with hiddenrow alone; the full pipeline run once on none-short (scratch `full.py`,
single-threaded, 170 s): pass 26/26, the same as job 283.

### Risks and what is left (round 2)

- No regression run (the plan). Both passes act on any case: hiddenrow only where a table-effect flow exists and a
  stock's inflow row is left loose; rowrepair only where the pick leaves a stock bare. The later regression run is
  where to look (bare stocks are rare on the earlier rungs).
- The runaway guard is unchanged: it still sets aside every candidate with the right requests block on none-short;
  rowrepair rebuilds the block instead. A per-stock guard remains the more direct fix (it changes the judge
  everywhere).
- counts-long runs 757 s of its 900 s timeout on the Mac pool (job 285; 856 s at c437a7d before the trigger was narrowed).

---

# Round 1 (2026-10-21)

## Status (round 1): 0 of 4 pass. No variant can pass under the scorer of the time (the hidden leak, below)

Pool results (`uv run sdlab-ladder job N --json`, read 2026-10-21; parts right of 23):

| variant | before (a660e75, store) | job 264 (8720834, node2) | job 268 (a379a3a, Mac) | job 270 (7539346, node2) | left (all variants: mem's two parts) |
|---|---|---|---|---|---|
| none-short | FAIL 8 | FAIL 14 | FAIL 14 | FAIL 14 | the requests block (below), mem |
| none-long | FAIL 14 | FAIL 15 | FAIL **21** | FAIL 15 | mem only (21/23) where the counted move is placed |
| counts-short | FAIL 16 | FAIL 16 | FAIL 16 | FAIL 16 | retries split, OOM (3 kill events), mem |
| counts-long | FAIL 10 | FAIL 10 | ERROR (LinAlgError, Mac) | FAIL 10 | HPA switches, pending/ready, OOM, mem |

Job 270's none-long (node2) is 15 because node2's earlier stages gave an answer that had lost `pending -> ready`,
so the OOM move could not be placed. c22e751 fixes that: re-scored locally on job 270's own none-long answer
(counter inflow reset), 15 -> 21/23. **Job 274 (c22e751, all four variants) is queued and has not run**: it waits
behind the coordinator's p450 job 271 (about 131 min left when read). Its numbers are not known yet.

## Diagnosis

`sdlab-ladder analyse 310-k8s-memory-oom` says "not analysed" for every variant (a truth this analysis does not
cover), so I worked out what can be reached by hand:

- **`outside -> mem` [as a whole] and `mem -> outside [mem]`: what the scorer can credit (a harness limit, every
  variant).** `allocated = 0.5 x (150 + leak + 2 x inflight / max(1, ready))` reads the hidden `leak`. The scorer
  compares this whole flow's amounts on the truth's states (`score._levels_at`, every truth stock under its own name),
  so a found model's own hidden stock is never matched to `leak`. Scoring the truth itself with `leak` renamed
  `h_leak` raises `ExprError: flow allocated reads ['h_leak']: not a stock, input or auxiliary`, so the run comes back
  as an error. A linear rate would read the unknown stock as 0. Without the leak, the best least-squares stand-in
  for `allocated` using measured columns only (ratio, traffic, every stock except mem) has a relative rms error of
  0.003 / 0.021 / 0.019 / 0.069 (none-short / none-long / counts-short / counts-long; tolerance 0.02 none, 0.10
  counts). That works by reading the counters as clocks, and the leak still biases mem's own drain: the row
  regression gives -0.52 / -0.05 / -0.53 / -0.26 against the true -0.5 (oracle SE: none). The parts can be hit
  only by luck, and none-long's cannot be hit at all. **Needed (harness, not mine):** the scorer should give a
  found model's hidden stocks their inferred levels, or match them to the truth's hidden stocks, when it compares
  a whole flow that reads one. Until then rungs 310 and 311 (which keeps the leak) cannot pass for any strategy.
- **The OOM move `ready -> pending = ready x table(mem)` and `oom_kills_total` (a method fault on none; data on
  short counts).** `oom_kills_total` is a measured counter of exactly that move, so the move's rate is in the data:
  `y = Δoom = ready x e(mem)`. combined2 fitted the counter as a constant (0.0094) and smeared the move into ready
  and pending's other flows (`outside -> pending` at 31 x desired; none-long `pending -> oom_kills_total` at
  0.33 x pending; pending -> ready lost). Fitting y as A x table(X) recovers it exactly on none (relative rms error
  against the truth's amounts 1e-4 on none-short, 0 on none-long). On counts-short there are 3 kill events, and the
  best fit is 54% off. On counts-long there are 44 events, and a crude fit is 21% off (tolerance 10%), so these
  are likely data-limited.
- **none-short's requests block (queue, inflight, retries; 7 parts): a method fault I did not fix.** Every candidate
  except realistic_hats is set aside by the runaway guard. Their in-data multi-step errors are 47-213 against
  realistic_hats' 0.68, and one stock dominates each (lna: queue 376; censored: queue 22, inflight 20, retries 21).
  realistic_hats' model has no requests block at all (`outside -> queue = 0.0004 x traffic`), so it does not run
  away. The guard sums over stocks, so one runaway stock disqualifies a model whose other rows are right. capmin
  offers nothing here, correctly: the MIN never binds on none-short (share 1.0).
- **counts-long's HPA switches and pending/ready rows:** not diagnosed. With the OOM and mem parts out of reach,
  the variant cannot pass anyway.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| counted-flow | `counted.py`: a measured final stock C fed from outside (a declared `in` side) that nothing leaves is a counter. Its increase y is fitted as `k x A x table(X)` (A: a non-final measured stock of C's unit, or none; X: any measured column; table knots at quantiles of X over the active steps plus the onset, at most one knot per 3 active steps, values by NNLS; BIC on C's row with the SSE floored at 1e-9 of scale, or at rounding n/12 for whole-number counts). It is kept when C's row's BIC falls by > 2 log n against C's current inflows. A move into C that already explains C's row (inflight -> responses_total) is left alone; a smeared one is replaced. The counter's inflow becomes that rate, and the counted flow is placed as a move A -> B (B of the same unit), an outflow A -> outside on a free declared side, or nowhere, whichever gives the lowest BIC of the rows of A and its same-unit peers after repair. It must beat "nowhere" by > 2 log n. | 8720834, a379a3a, c22e751 | copy `counted.py` with `hinge.py` and call `hinge.apply(counted.apply(r, stocks, run, opts), stocks, run, opts)` last |
| joint-active-set-refit | `counted._refit_moves`: the linear flows on a set of rows (the moves between them and their outside rates, floored ones too) are refitted jointly by active-set least squares. Each flow's columns count only where its rate is positive (the engine floors every flow), the fit starts unfloored, and the masks are recomputed until they settle. Alternated 3 times with `hinge.refit_row(force=True)` per row. This is what repairs the rows after a flow is inserted or removed. | a379a3a | copy `counted.py` (`_repair_once`) for any "insert a flow, then repair the rows it touches" step |
| add-missing-move | `counted._repair`: after the repair, a proportional move between two of the rows (same unit) that the model lacks is added, one at a time: screened by the joint refit alone, confirmed by a full repair, kept where the rows' BIC falls by > 2 log n | c22e751 | as above |
| table-amounts | `hinge.amount` evaluates table effects on measured columns (`rate x interp(points)`), so the floored refit and row errors work on rows that carry an effect flow. Before, any such row was skipped. | 8720834 | copy `hinge.py` (strategies with 309's hinge) |
| oefit-guard | `oefit._weights` keeps the previous weights when the model's run blows up or the variance fit's SVD does not converge. Job 268's counts-long errored on the Mac with `LinAlgError` in this function. | 7539346 | strategies with combined2's `oefit.py` (k8s-306 r3 copies): the same two guards in `_weights` |

## Tests

`tests/test_counted_combined2.py` (4): a synthetic up / wait / heat record with a counted fall-back move (the move is
read off the counter exactly and the start rate repaired to 0.5); a counter whose move already explains it is left
alone; a smeared move into a counter is replaced; a move the rows need is added back. Before each commit, these
passed: `tests/test_counted_combined2.py`, `tests/test_hinge_combined2.py`, `tests/test_switch_combined2.py`,
`tests/test_isolation.py`, `tests/test_frozen.py` (and `tests/test_ladder_combined2.py`, 8 passed, at 8720834).

Local diagnostics, which are not results: the full combined2 pipeline traced stage by stage on all four variants
(single-threaded, scratchpad `trace.py`; the counts-long trace hit the same LinAlgError). The new passes were
applied to the stored stage outputs and to job 270's none-long answer and re-scored with `score.equations`.

## Left open

- The scorer limit on the hidden leak (above). This needs a harness change and the user's approval (rule 5).
- none-short's runaway guard: a per-stock guard (set a candidate aside only on stocks where another candidate runs
  well) is the obvious general fix. It changes the judge for every case, so it needs a regression run.
- counts-long: the HPA switches lost and the pending/ready rows (not diagnosed); its OOM parts are probably
  data-limited (44 events).
- Timing: counted adds about 10 s on none-long when the rows are close, and about 70 s when moves must be added back.
  none-long ran 385-490 s of the case's 900 s timeout.
