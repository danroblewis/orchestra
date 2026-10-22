# 310 (k8s-memory-oom), combined2: noise-free and counts variants

Agent combined2-310, 2026-10-21. The plan: climb kubernetes 307-311 on none-short, none-long, counts-short and
counts-long only (the user, 2026-10-21). No regression runs on earlier rungs.

## Status: 0 of 4 pass. No variant can pass under the current scorer (the hidden leak, below)

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
