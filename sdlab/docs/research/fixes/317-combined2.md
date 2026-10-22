# 317 (k8s-mesh-of-three), combined2, round 1 (2026-10-22, agent c2-317-r1)

**Status: combined2 does not pass 317; no variant passes.** Two fixes were kept (b3728e6, 9d8bfc0). Before them every
variant timed out at 1800 s. After them every variant finishes and is scored (job 375: "4 done in 1776.9 s: 4 fail";
none-short 49/76 and none-long 64/85 parts, from timeouts):

| variant | achievable? | before: job 362 at 64b5f36 | job 372 at b3728e6 (fix A) | job 375 at 9d8bfc0 (fixes A + B) |
|---|---|---|---|---|
| none-short | **no (unidentifiable parts, below)** | TIMEOUT (1800 s) | FAIL 49/85 parts, 1206 s | FAIL **49/76**, 404 s |
| none-long | **no (unidentifiable parts, below)** | TIMEOUT | FAIL 40/76, 1754 s (stopped by the pass deadline) | FAIL **64/85**, 1672 s |
| counts-short | no: data-limited (OOM kills: 2-5 kill steps a service) | TIMEOUT | FAIL 27/82, 427 s | FAIL 27/82, 422 s |
| counts-long | no: data-limited (OOM kills: 31-39 kill steps a service) | TIMEOUT | FAIL 25/76, 1754 s (pass deadline) | FAIL 36/76, 1754 s (pass deadline) |

Commands (2026-10-22): `uv run sdlab-ladder job 362|372|375` (`--json` for the parts), `uv run sdlab-ladder diff
317-k8s-mesh-of-three --strategy combined2 --variant V`, `uv run sdlab-ladder analyse 317-k8s-mesh-of-three --variant
V` ("not analysed": tables, switches and hidden stocks are outside the analysis; none-long's run crashed on a broken
z3 import in the shared venv). Local traces ran single-threaded at nice 5 from scratchpad scripts (`c2-317/trace.py`,
`rest.py`, `score.py`: the pass sequence on a cached pick, scored with `score.score`); they are not committed.
"Parts" counts differ between runs (76, 82, 85) because the scorer adds parts for hidden stocks it matches.

## Is any variant achievable? (rule 4b)

`analyse` does not cover 317, so I checked the binding counts on the truth's own levels (scratch `binds.py`,
`kills.py`):

| | none-short | none-long | counts-short | counts-long |
|---|---|---|---|---|
| frontend / catalog / cart dispatch MIN binds on | 1 / 0 / 0 steps | 9 / 7 / 2 | - | 107 / 91 / 100 |
| the db pool MIN (`min(0.8 w, 80 - 0.2 a)`) binds on | **0 steps** | **0 steps** | - | 115 |
| OOM kill steps (frontend / catalog / cart) | 18 / 30 / 33 | 397 / 398 / 448 | 3 / 2 / 5 | 39 / 35 / 31 |

- **none-short and none-long:** the db pool never binds, so `db_waiting -> db_active` written as the truth's MIN cannot
  be told from `0.8 db_waiting` on these records. Since 2026-10-21 that is "fits", never a pass. On none-short two of the
  three dispatch MINs never bind either. By the user's rule (unidentifiable variants do not count), neither none
  variant is a target. They are still the right place to measure progress, because everything else in them is
  noise-free and identifiable.
- **counts-short and counts-long:** the OOM move has 2-5 kill steps a service on counts-short and 31-39 on counts-long.
  310 counts-long, with 44 kill steps on one service, was shown data-limited on the OOM move (free-knot Poisson ML
  11.6-33.5% off against a 10% tolerance; 310-combined2-r2.md). So both are data-limited by that measurement.

**So 317 has no achievable plan variant for combined2 to pass.** This is my reading, not an `analyse` verdict. It
should be confirmed by extending `analyse` (the harness) to never-binding limits and table effects, then reported to
the user.

## Diagnosis: why every variant timed out (method fault: budgets that grow with the number of columns)

317 has 36 measured stocks and one input, so every search over "the columns" became 3-10 x larger than on 316 (14
stocks). Local trace of none-short at 64b5f36:

1. **capmin.offer: 585 s for one round of four.** The kink test regresses each candidate on every product of two
   columns: 703 products, more than the 300 steps, so the surface fits anything. The headroom search runs X x Z x Y x 12
   betas x a golden section, which is about 7.8 million projections a round. The one limit it found was junk:
   `catalog_ready` limited by `catalog_mem` with room `frontend_desired`, received by a counter.
2. **hinge.fit_side: 280 s a call, 3 calls.** It scores every set of up to 3 of 41 columns, 11,500 sets, each an
   active-set fit from 3 starts.
3. **counted 228 s, rowrepair 150 s, lagrow 99 s.** These are the same fits inside the row repairs.

## Fixes kept

### A. Wide-record searches within the time (b3728e6), type 10 (guards and budgets), new rows

Every one of these applies only above 24 measured columns (levels and inputs), so rungs up to 316 (at most 17 columns)
take the old paths unchanged.

- **capmin, screened limit search:** each round first scores every plain (X, Y) and headroom (X, Y, Z) candidate on a
  coarse grid (8 thetas x 6 betas) by one matrix projection on X's row. Only the 8 best of each kind, by gain on X's
  row, are searched in full as before. The kink's smooth surface is B plus the limit's own arguments (X, Y, Z) times
  every column, instead of every product. On none-short the offer takes 14 s instead of about 40 minutes.
- **hinge.fit_side, beam:** every single column, then the 6 best sets of each size, each extended by every column. An
  extension by only the 12 best singles missed a gap `max(0, a - b)` whose columns are weak alone; the test now pins
  this. Each active set is solved by the normal equations, and a set already solved, by this start or another, is not
  walked again. Fits that cycled had used all 40 iterations from each of 3 starts. counted on none-short: 336 s -> 84 s
  (profiled).
- **lagrow._lagfit:** the same rule for active sets already walked, with regimes in the key. 153 s -> 60 s (profiled).
- **Passes within the caller's timer** (`__init__._passes`): each pass after the pick runs under the runner's remaining
  time less 45 s. A pass that would overrun answers with its input, and the passes after it are skipped
  (`passes_skipped`). A cap that fell inside a pass had lost the whole answer.

Cells fixed: none passes, but 4 timeouts became scored results (job 372).
How another strategy adopts it: copy capmin's `_screened`/`_screen`/`_kinkq` (all 43 capmin copies share the
same `_search`); hinge's beam and `_normal`/`seen` in `hfit` (every hinge.py and floor.py copy); any pipeline of
post passes can wrap each pass in its own `deadline(outer_left() - reserve)` (the combined family's `deadline.py`).
kalman_lna's 9d3ca8e (staged row budget) is the same kind of fix for its rows pass.

### B. A block linear on all but a few steps (9d8bfc0), type 11 extended (sparse block re-read)

315's sparseblock re-reads a unit's block only when every row has an exact linear subset. On 317 none-short the
requests block has 15 rows: three services' queues, inflights, retries and counters. Two rows are linear except at
one step, t 130, where the node failure makes frontend's dispatch MIN bind. So the block was refused, and the pick's
crossed moves stayed: `frontend_inflight -> catalog_queue 0.218`, `cart_queue -> frontend_inflight 0.67`, retries
drains at 1e-6.

- `sparseblock._rare`: for each row with no exact subset, the best subset is refitted without its worst steps, at most
  1% of the steps (`RARE`). The rows' unexplained steps are joined into a mask. The block is re-read on the kept steps
  and compared with the pick's flows on the same steps, with the same EXACT and FAR rules.
- The block's held limits are tried first held, then left out. The pick's offered room limit on `frontend_queue` was
  junk, and holding it made the block inexact.
- A constant flow counts as plain.

Result on 317 none-short (local, from a cached pick): the requests block is the truth's 21 flows, with 1 step set
aside and SSE 6.3e-6 against the pick's 2.1e7. Parts went from 31/76 to 49/76. none-long (local, all passes complete):
57/85. On none-long the pass deadline can skip `counted` on a loaded pool.

The 9d8bfc0 commit message says "local trace from job 372's pick". That is wrong: it was a local pick from the same
code, cached in the scratchpad.

How another strategy adopts it: any exact-row re-reader (engine_forms `reread.py`, kalman_lna `rows.py`, milp's row
rebuilders) can trim a row's worst 1% of steps and refit, then read the whole block on the remaining steps. Announced
injection steps are where rare limits bind. Dropping held limits a block does not need is the same rule as
minrefit._earn.

Tests: `tests/test_wide_combined2.py`, 6 tests:
- the narrow design is unchanged, and the wide one uses the local surface;
- fast hfit matches lstsq;
- the wide beam finds a two-column gap;
- the passes stop inside the caller's timer;
- a block that is linear except at one kink step is re-read to its true numbers with 1 step set aside.

The existing combined2 tests pass: hinge, lagrow, counted, forcedpool, sparseblock, switch, isolation, capmin and
ladder_combined2.

## What still fails (none-short, local, 27 parts missing)

- **The pods blocks (each service):** the gaps `desired - pending - ready` and `ready - desired` are not all found,
  and the starts are not found. The truth's start is a new form, a shared room split by demand:
  `min(0.5 p_i, max(0, 4 nodes - Σ ready) x p_i / max(1, Σ pending))`. Neither capmin's headroom form (one occupant Z)
  nor any other pass can write it. This is the largest missing mechanism: a pool shared by several sources in
  proportion to their demand.
- **mem (each service):** the leak is hidden, and `0.5 x (150 + leak + 2 inflight / max(1, ready))` is not recovered.
  hiddenrow finds a hidden stock on some services but not all, so mem's drain is 0.066 against 0.5.
- **nodes:** the hidden provisioning DELAY1 is not found here (lagrow ran out of candidates), and the removal rule
  reads the six pod stocks.
- **db:** the two query links are missing, and the pool MIN is unidentifiable on none (above).
- cart's OOM move and effect table are missing (counted placed catalog's and frontend's).

## Not done / next

- counted on none-long takes 600 s locally (its row repairs on 2000 steps), so on the pool the deadline can cut it.
  Next: restrict counted's placement trials to the peers whose rows the counted rate changes.
- A shared-room limit form (above) in capmin, offered where several stocks of one unit lose to one other unit's pool.
- `analyse` coverage for never-binding limits (harness, needs its owner) so that "unidentifiable" here is a measured
  verdict.

## Regression risk (for the later regression run)

- Fix A is gated on more than 24 columns, so earlier rungs are unchanged by construction (no copy of it runs there).
- Fix B is not gated. A block that had been refused because a row missed on at most 1% of its steps may now be
  re-read. That happens only when the re-read is exact on the other steps and the pick is 1000 x worse there.
  Constant flows no longer exclude a block. Earlier rungs were not re-run, per the plan.
