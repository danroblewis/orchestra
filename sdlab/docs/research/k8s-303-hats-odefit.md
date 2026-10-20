# Kubernetes rung 4 (case 303): effect_hats and odefit, and what each can represent

**Status:** done (2026-10-20). effect_hats: fixed (631e5b8), 303 6 of 6. odefit: not fixed; its one fail
(303 meas-long) is the output-error model class, and the two fixes tried are reverted (240f9d2).
Earlier 303 rounds: [k8s-303-c2.md](k8s-303-c2.md), [k8s-303-c1.md](k8s-303-c1.md).

## effect_hats: 303 counts-short

**Diagnosis (rule 4b).** `sdlab-ladder analyse` rates counts-short achievable (p 1.00), so it was the
method's fault. effect_hats' base is the shared main line (`identify.identify`), and that alone already
failed: it read the move `inflight -> responses_total` as 0.5402 from inflight's row, and five pieces
of a spurious `responses_total -> outside` (mean 30.3 a step) took up the difference. The effect step
found no candidate (`effects_tried` empty) and eiv.py's white test saw no measurement error, so the base,
re-cut, was returned as it was. This is the same failure inflow_effects had (fcc0c9a).

**Fix tried first (711d936), reverted in 631e5b8.** The base became matrix's earned main line (a copy of
`matrix/earned*.py` at 49e4ca7). That cleared 303 counts-short, but on the paired sample below it lost
4 passes and 2 equivalents (084 meas-short and outliers-short, 087 meas-long and outliers-short, 083
counts-long and meas-long) for 2 passes and 2 equivalents gained: the earned refit puts constant inflows
into stocks that have none (`outside -> B1 10.6`, `outside -> B 4.7` in 15 pieces). matrix and
earned_pieces fail those cells for the same reason (ladder rows at b25604c).

**Fix (631e5b8).** effect_hats' own price prunes the re-cut base's small flows, as it already pruned each
effect candidate (`prune_base`, inflow_effects' rule at fcc0c9a; effect_hats' `price.py` and `pieces.py`
are byte-identical to inflow_effects'). With the pieces gone, the joint refit reads the move from both
rows: 0.6004 / 0.5018 / 1.002 (truth 0.6 / 0.5 / 1), complexity 7 against the truth's 7.

**Numbers.** `uv run sdlab-ladder run --strategies effect_hats,odefit --cases 303,300,301,302 --jobs 4
--timeout 600` (single-threaded, 240f9d2, which holds 631e5b8). effect_hats: **20 of 20 pass**. 303
counts-short went fail -> pass and the other 19 stayed pass. The rows before were the latest rows
(b9fe1d6, 5417dd4, b965158).

Paired sample of 40 cells: 080-084 and 087 at counts, meas and outliers, short and long, plus 141 and
142 meas-short and meas-long. The same code was run in process with `prune_base` off (exactly the code
before 711d936) and on, scored by the ladder's `run_item` (scratchpad `pair.py`, `pair_eh2.json`).

| before -> after | cells |
|---|---|
| unchanged | 38 (13 pass, 9 equivalent, 16 fail) |
| fail -> pass | 1 (087 outliers-long) |
| fail -> equivalent | 1 (083 counts-short) |
| worse | 0 |

The found model changed in 19 of the 40 cells. Summed discovery time went from 69.6 s to 70.0 s.

## odefit: 303 meas-long

**Diagnosis (rule 4b).** `analyse` rates meas-long achievable (p 1.00), and odefit's own main line
(earned refit + eiv.py) passes it. odefit returns its output-error model instead, because that model
predicts the held-out 30% better: 1,973.5 against 1,994.0 (1%). The main line's judge rates it 0.2324
against 0.2126, inside the 3x slack. The output-error model is wrong in structure. The queue reads
inflight and traffic (`queue -> outside 0.253 x inflight`, `outside -> queue 0.506 x traffic`), and
inflight reads the queue as a link (0.6785) rather than a move.

The cause is the model class. odefit's output-error model is a free linear map: each stock's change
reads every level, input and constant, with no conservation (a move's loss and gain are separate
numbers) and no signs. On 303 the queue settles in about 1.7 steps against a 288-step daily cycle, so
along the run the queue, inflight and traffic are nearly proportional. Without conservation, a queue
row that reads inflight and traffic follows the data as well as the true row
(scratchpad `od4.py`, `od5.py`, `od7.py`, the cell's data):

| model in odefit's output-error fit (per-stock weights) | numbers | BIC |
|---|---|---|
| backward elimination stopped by its time limit (0.4 x 150 s), as in ladder runs under load | 11 | 86.73 |
| the true structure's mask | 5 | 84.97 |
| backward elimination run to the end (budget 1,500 s) | 5 | **58.59** (the ladder's wrong model) |

So the output-error likelihood prefers the wrong structure by 26 BIC. Within its class this cell is
not identified; the main line identifies it because a move ties the queue's loss to inflight's gain.

**Fixes tried (none kept):**
- *Pick the output-error model only if its held-out edge is above 2 paired SE* (711d936, reverted in
  240f9d2). It passed 303 meas-long (edge 20.6 against SE 21.0). But on 40 paired cells (7 physics
  meas-short; 141, 142 and 143 at four variants; 080-084 and 087 meas-short, meas-long and
  outliers-short; 139 meas; 087 outliers-long) it lost 6 cells and gained none:
  - pass -> fail: 141 and 142 meas-short, 139 meas-short and meas-long, 080 outliers-short;
  - equivalent -> fail: 087 outliers-long.

  The per-segment errors are heavy-tailed (141 meas-short: 13,385 against 129, yet only 2.0 SE). A
  relative margin would have to sit between 1% (303) and 2-3% (139, 143 and the reaction chain, where
  the output-error model is needed), which would be tuning to the case.
- *Each level weighted by a level-proportional error* (variance a + b x level^2 fitted from the output
  errors; not committed). The true mask then leads the time-limited model (63.67 against 84.18), but
  elimination run to the end stops at 63.82 with 7 numbers (the queue and inflight rows each reading
  queue, inflight and traffic), and the cell still fails.

Without the 711d936 gate, odefit's 300-303 run (above, 240f9d2) gives 19 pass and 303 meas-long fail,
the same as before.

## Capability remarks

**effect_hats.** It extends the matrix main line with multiplicative effects: a flow's rate times a
piecewise-linear (tent) curve of one stock's level, found by a residual screen and kept on one-step
BIC. It also handles measured inputs as columns, pooled and re-cut outside-inflow pieces, and the eiv.py
refit under measurement error. It cannot represent hidden stocks, delays, MIN/MAX floors other than the
engine's at 0, or two effects on one flow in one round. Its noise model is one weight per row.

Ladder (latest rows, mixed versions because of the watcher backlog): 584 of 1,437 cells pass (inflow_effects
588, matrix 496, combined2 906). It passes no cell that two or fewer other active strategies miss.
Effect-table cases: 4 of 44 (engine_forms 14, combined2 13, own_tables 12, inflow_effects 9).
inflow_effects is effect_hats plus gates and differs in 8 cells (2 effect_hats only, 6 inflow_effects
only).

Its 303 limitation was fixable and is fixed: **not hard, not retired.** It is nearly redundant with
inflow_effects, but that is a roster question, not a structural limit.

**odefit.** It fits a per-step model linear in its numbers (levels, measured inputs, a constant, and,
when BIC and a held-out check earn them, products, squares and square roots) by output error with each
segment's start estimated. That makes it unbiased under measurement error, where one-step fits shrink
couplings. Hinges are coded but off.

It cannot represent conservation (moves come out as a link plus an outflow), signed or floored flows,
pieces or unannounced inflow changes, eras, delays or hidden stocks. Its noise model is homoscedastic
per stock. On counted levels, uneven times or announced eras it hands over to the main line. Its
backward elimination stops at a wall-clock limit (0.4 x 150 s), so long runs depend on machine load: a
fixable reproducibility issue, not fixed here. The choice between its own model and the main line is a
selection between two finished models, by design.

Ladder (latest rows, mixed versions): 512 of 1,435 pass. It passes 14 cells that two or fewer other
active strategies pass. Six of them no other strategy passes: 139 meas-long, 141 meas-short and
meas-long, 142 meas-short, phys-mass-spring-damper meas-short and phys-thermostat none-short.

Its 303 meas-long failure is **hard** for its model class: in output error the wrong structure has the
better likelihood, and no held-out rule tells a 1% edge from the 2-3% edges it needs elsewhere. Every
other active strategy passes 303 meas-long, and odefit's own main line does too. But its strength,
measurement error on smooth linear dynamics, is not covered by another strategy, so it is **not
retired**.

## Open

- odefit: conservation in the output-error model (a move as one number shared by two rows) is the
  structural fix. It is not a small change.
- odefit: a deterministic elimination budget (step counts, not wall-clock seconds).
- effect_hats: the 16 fails of the paired sample are unchanged (082 and 083 loops, 084 meas-long,
  141 and 142 meas).
