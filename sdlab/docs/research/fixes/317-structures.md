# 317 (k8s-mesh-of-three): structures, round 1

**Status (2026-10-22, agent structures-317-r1): structures passes 317 none-short (85/85, pool job 374 at
dd9d8d1, 1043 s on node2; also job 373 at 7959beb, 548 s on the Mac). none-long (41/76), counts-short (23/76) and
counts-long (30/76) fail, and none of them times out any more.** At the start (64b5f36, pool job 360) none-short,
none-long and counts-long timed out and counts-short failed. I made four attempts (c6fa9ea, 942bf2d, 7959beb,
dd9d8d1), all inside `sdlab/discovery/strategies/structures/` plus one test. I held the structures lock for the round
and released it after this doc's commit.

## Achievability

`uv run sdlab-ladder analyse 317-k8s-mesh-of-three --variant V` says **"not analysed: a truth this analysis does
not cover"** on all four variants, so all four count as targets. It also lists near-collinear sets on every
variant: on none-short, 9 to 11 of the request levels are collinear to a relative size of 1e-6, and the counters
are exactly collinear.

Three facts from the data bear on the diagnosis (scratch `analyse` of the levels):
- the dispatch MINs (`min(0.6 queue, 40 ready)`) bind on 1 of 299 steps on none-short (the frontend's, after the
  node failure at t 130), and on 9, 7 and 2 of 1999 steps on none-long;
- the database pool never binds on either run;
- the shared node room binds on 86 of 299 steps and 549 of 1999.

## Results

`uv run sdlab-ladder submit --strategies structures --cases 317-k8s-mesh-of-three --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-317-r1`. Parts are right of all. Job 374's rows
are the main line's latest. The earlier jobs' rows are job-only (their commit is not the `sdlab` HEAD), read with a
scratch reader of `pool_results.row`.

| variant | 64b5f36 (job 360) | c6fa9ea (job 367) | 942bf2d (job 369) | 7959beb (job 373) | dd9d8d1 (job 374) |
|---|---|---|---|---|---|
| none-short | timeout (node2, 1800 s) | FAIL 56/85, 622 s | FAIL 84/85, 555 s | **PASS 85/85, 548 s** | **PASS 85/85, 1043 s (node2)** |
| none-long | timeout | cancelled | FAIL 37/76, 1710 s | cancelled | FAIL 41/76, 1710 s |
| counts-short | FAIL | cancelled | FAIL 12/76, 1544 s | cancelled | FAIL 23/76, 1089 s |
| counts-long | timeout | cancelled | FAIL 37/76, 1710 s | cancelled | FAIL 30/76, 1709 s |

Local traces (`scratchpad st317/trace.py`, single-threaded, the Mac): none-short at 64b5f36 took 1002 s for 44/85.
At dd9d8d1 with an 1800 s timer, counts-short gives 23/76 in 756 s. none-long gives 37/76 and is stopped by the
timer in the counted stage.

## Diagnosis (none-short, `diff` and local traces)

At 64b5f36 these are all **method faults**: the truth's rows are exact and sparse on this record.

1. **Time.** The base (combined) takes 210 s and the 90 s search finds nothing. Then the counted stage takes 421 s:
   3 counters × 8 same-unit receivers, each tried with a full floor search and a repair on 36 stocks. The total is
   1002 s locally and over 1800 s on node2.
2. **A spurious limit.** capmin offered `MIN(frontend_queue, 103 x catalog_ready)` (kink 458). Its evidence is the
   one step where the true dispatch binds. The frontend's queue and inflight rows were then written around it.
3. **Exact but crossed rows.** The base's rows are exact, but they are not written as the truth's flows. Each retries
   loop is outside terms (`retries -> outside = retries - 0.08 queue`, `outside -> queue = ... + 0.6 retries`). One
   service's dispatch lands in another's inflight (`catalog_queue -> frontend_inflight`). The counters read proxies
   (`frontend_inflight -> catalog_responses_total = 2.4 db_waiting`). moves.py (312) re-reads only rows that are far
   from exact, so it did nothing. Even run on every row, it fell apart for four reasons:
   - the frontend rows miss the single binding step, so best subset picked pending columns that spike there;
   - a held time schedule (an `inflow` profile) sat on catalog_queue's row;
   - the pairing gave the link `cart_inflight -> catalog_queue` the share that belongs to the errors' move;
   - the database's move `db_waiting -> db_active` crosses units.
4. **A shared room.** The pods of all three services start into one room:
   `min(0.5 P_i, max(0, 4 nodes - sum ready) x P_i / max(1, sum pending))`. room.py (311) writes one move with one
   occupant, so it took `catalog_pending -> cart_pending`.
5. **A declared side dropped.** The floor refit dropped `nodes -> outside` (the scale-down). It never acts on the
   short run (its true amount is 0 on every step), and the scorer counts a missing declared side as a miss.

## Fixes kept

| # | type | mechanism | commit | files |
|---|---|---|---|---|
| 1 | **every-row rebuild** (new; extends 312's moves.py) | moves.apply(every=True) runs after the 312 pass and makes every measured row a candidate, not only the far-from-exact ones. Each row is read by best subset (memoised per held set). The selection is robust: it is refitted without the TRIM = 2 steps its first fit misses most, and pruning, numbers and the exactness test (`rms_t`) use the kept steps. The base's scheduled outside flows (`inflow` profiles) are replaceable, with their amounts read as the engine reads them. Pairing serves the receivers with no outside inflow first, because their term can only be a move. The move the declared boundary forces across units (two stocks each alone in its unit, the source with no outflow side and the receiver with no inflow side, 316's rule) is joined. The set is fitted and judged on the steps every row kept, and accepted when exact there and when BIC falls by 6 log n. On 317 none-short the 20 request and database rows become the truth's flows: BIC -26991 -> -107176 | c6fa9ea, 942bf2d | `moves.py`, `__init__.py` |
| 2 | **limit guards** (ledger type 5 unit guard + new trimmed gain) | capmin offers up to 4 limits, one per source. Each must be a same-unit move (a receiver in the source's unit) or a fixed pool. A limit is not offered when its gain on the source's row, with the 2 steps the linear row misses most left out, is below the price, because its evidence is one shock. On 317 none-short nothing is offered (the dispatch binds once; the pool never binds) | c6fa9ea | `capmin.py`, `oefit.py` (every offer parsed) |
| 3 | **shared room** (new; extends 311's room.py) | `room._family` builds moves `A_i -> B_i` that start into one room, each by its share: `min(k_i A_i, k_i theta max(0, c Y - sum B) A_i / max(1, sum A))`. With one move this is 311's room. The family is grown greedily from each of the 3 best single pairs, for the capacities they read. A pair joins while the coarse joint gain (least squares on one k per move after the rows' free flows are projected off) rises by 5%. c and theta are then refined by golden section on the rows' BIC with the plain flows refitted, and the family is kept by 6 log n. `room._polish_family` refits k_i, theta and c last, with every other flow held. On 317 none-short it finds the three services' starts, with c 4.0016 and theta 2.07 after the polish | 942bf2d | `room.py`, `tests/test_structures_room_family.py` |
| 4 | **declared last** (ledger type 0 *boundary-fill*, re-applied) | after every stage, a declared side the stages dropped is filled again (`boundary.fill_declared`). Where the data leave it nothing (its number at or under the fill's 1e-6 floor), it is written at its fitted 0. On 317 none-short, `nodes -> outside` with true amount 0 on every step went from 84/85 to pass 85/85 | 7959beb | `__init__.py` |
| 5 | **stage budget** (ledger type 10) | each optional stage (moves, rebuild, floor, oefit, room, repair, counted, hidden, polish, delay) runs under the caller's timer less RESERVE (90 s). Past that, the answer stands as it came and the stage is noted in `skipped`. The output-error refit takes at most a quarter of what is left. The counted move tries only the 2 receivers whose rows its amount repairs most (projection of the two rows' one-step residuals), with the floor search on the move's neighbourhood (`floor.apply(only=...)`). Timeouts became answers: job 369's long variants ended at 1710 s. none-short went 1002 -> 548 s and counted 421 -> 89 s | c6fa9ea, 942bf2d, dd9d8d1 | `__init__.py`, `counted.py`, `floor.py` |

### Decisions

- **Fix 4 (zero side)** is the data's estimate, not a tuning. The side is declared, so it must exist. The run shows
  nothing leaving, and the least-squares number is 0. Before this fix, fill_declared's 1e-6 floor wrote a drain the
  data do not support.
- **Fix 2 (one shock)** follows the user's rule against a fitted stand-in for state the data do not show. A limit
  whose whole evidence is one or two steps is a fit to a shock, not a found capacity.
- **Units:** fix 1 lets a move cross units only where the declared boundary forces it (316's rule, see
  316-structures.md). Every other move stays in one unit.

## What still fails (next round)

- **none-long (41/76 in job 374; 37/76 in the local trace):** the stage budget runs out. floor.apply takes **661 s** on 2000 steps (65 s on 300), because
  every stock's sides are searched and judged on the whole model. So counted is stopped and the hidden, polish,
  delay and last repair stages are skipped. The every-row rebuild is not kept there: its set is 9 rows and the BIC is
  slightly worse, -333566 against -333791. The room takes a single move (`cart_pending -> cart_ready`, occupant
  frontend_ready) and not the family. The search returns nothing on long records (36 x 1999 x 2273 terms exceeds
  CELLS, 3e7). Next: search floor only on rows that are not exact (most of them are after fix 1). Then check why
  the family loses to the single room on none-long.
- **counts (23/76 short, 30/76 long in job 374):** not diagnosed this round. Fix 1 is idle on whole-number counts (the
  tolerance is 100 quanta). 316's counts-short was data-limited, and `analyse` cannot say here.

## How another strategy adopts these

- **every-row rebuild:** copy structures' `moves.py` at 942bf2d. It needs `rebuild._best_subset`, `repair._fit`
  (with `keep`), `hidden._amount` and `steps`. Call `apply(r, stocks, run, opts, every=True)` after the strategy's
  own row fit, before the passes that refit sides. The two parts that carry over even without the module are the
  robust subset (refit without the 2 worst steps) and the receiver ordering in the pairing. A matrix-style strategy
  (the earned family) gets crossed but exact rows on any wide record, and is the first candidate.
- **limit guards:** about 20 lines in any capmin copy: the per-source `per` dict, `_trimmed`, and the unit filter
  on `chosen`. Every capmin copy (43) makes the same single-shock offer on 317 none-short.
- **shared room:** `room._family`, `_set_basis` and `_polish_family` (room.py at 942bf2d) need room.py's single
  room as the source of pairs. A strategy without room.py needs 311's room first.
- **declared last / stage budget:** `_declared_last` and `_timed` in structures' `__init__.py` are self-contained
  (combined's `deadline` module). Any strategy with post-passes after its fit can wrap them.

## Risks

- **No regression run** (the plan). Three of the changes run on every case:
  - fix 1's every-row pass (kept only on an exact set and a 6 log n gain);
  - fix 2's guards, which can remove an offer an earlier rung used: any to-outside limit and any single-shock
    limit. Rungs 306-312 should be re-run first;
  - fix 5's narrower counted search: 2 receivers, and a floor on the neighbourhood only.
- The stage budget makes results depend on machine speed near the cap: node2 is slower than the Mac.
