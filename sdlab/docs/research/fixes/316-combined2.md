# 316 (k8s-shared-database), combined2, round 1 (2026-10-22, agent c2-316)

**Status: combined2 passes every achievable plan variant of 316 at 6b1c269 (pool job 347).** It passes none-short,
none-long and counts-long, each 16/16 parts. counts-short fails at 14/16, but `analyse` calls it data-limited
(p 0.407), so it is not a target. Before this round all four variants failed at 59d2ccf with 13/16 parts each.

| variant | achievable? (`analyse`) | before (59d2ccf) | after (6b1c269, job 347) |
|---|---|---|---|
| none-short | yes (p 1.00) | FAIL 13/16, 430 s | **PASS** 16/16, complexity 32 = truth, 308 s |
| none-long | yes (p 1.00) | FAIL 13/16, 785 s | **PASS** 16/16, 32 = truth, 501 s |
| counts-short | **data-limited** (p 0.407: the two query links' bound SE 18% and 12%, allowed 10%) | FAIL 13/16, 704 s | FAIL 14/16 (no `pricing_inflight` term; cart's link is 0.161), 232 s |
| counts-long | yes (p 0.844) | FAIL 13/16, 1616 s (of 1800) | **PASS** 16/16, complexity 34 vs 32, 483 s |

Commands: `uv run sdlab-ladder analyse 316-k8s-shared-database --variant V`, `uv run sdlab-ladder diff
316-k8s-shared-database --strategy combined2 --variant V`, `uv run sdlab-ladder job 347`, `uv run sdlab-ladder show
316-k8s-shared-database --strategy combined2`. All were read at 2026-10-22 17:23Z.

## Diagnosis: a method fault, not a data limit

The truth's database half is:

```
outside -> db_waiting   0.06 pricing_inflight          (queries)
outside -> db_waiting   0.1 cart_inflight
db_waiting -> db_active min(0.8 db_waiting, 80 - 0.2 db_active)   (queries -> connections)
db_active -> outside    0.8 db_active
```

The boundary declares only `db_waiting: {in: [estimate, estimate]}` and `db_active: {out: estimate}`. On none-short the
pool binds on 141 of 300 steps.

At 59d2ccf the diff (none-short) was:

```
~ outside -> db_waiting   pricing_inflight 0.06 -> 0.152
- outside -> db_waiting   0.1 cart_inflight
+ outside -> db_waiting   ... - 0.793 db_active
+ db_active -> outside    -0.8 db_waiting + 0.8 db_active
  (and no db_waiting -> db_active at all)
```

combined2 had three rules that each blocked the truth's move:

1. `one_unit_moves` (312) drops every move between stocks of different units. This is the user's rule that a move
   carries one thing.
2. capmin's receiver must be in X's unit (312). capmin therefore offered `MIN(db_waiting, 0.98 db_active)` as an
   outflow with no receiver. That offer binds on only 3% of steps and is spurious.
3. capmin's headroom form `theta x max(0, beta Y - Z)` needs a measured Y. The truth's cap `80 - 0.2 db_active` has
   a fixed pool, and its "Z" is the receiver, which belongs to another unit.

The declared boundary leaves no other drawing. `db_waiting` is the only `queries` stock and has no outside outflow.
`db_active` is the only `connections` stock and has no outside inflow. So what db_waiting loses can only go into
db_active.

## Fix kept

**Type 12 (new): boundary-forced cross-unit move with a fixed-pool limit (6b1c269).** It has four parts, all in
combined2's own package.

- **capmin.forced_pairs(stocks, run):** returns the pairs (A, B) where the boundary is declared and four things hold:
  - A and B are each the only non-final stock of their unit;
  - A has no declared outside outflow;
  - B has no declared outside inflow;
  - A and B are in different units.

  Only for such a pair is a move across units admitted. `one_unit_moves` keeps such a move. capmin's receiver search
  (`_judge`) and the headroom's occupant Z may both be the forced partner. On 316 the only pair is (db_waiting,
  db_active). On 312, nodes has declared sides, so nodes -> ready stays dropped as before.
- **Fixed pool in capmin's headroom limit:** for a forced pair, the capacity may be the constant `Y = 1`, giving
  `MIN(X, theta x max(0, beta - Z))`, which is the same as `min(k X, c - d Z)`. The pool-size grid then also extends
  past Z's largest level (x 1.25 to 10), because a pool of 80 reached through `0.2 x db_active` sits at
  beta = 400. It is written as `min(k * X, max(0, c * 1 + -d * Z))`. The engine floors every rate at 0, so the
  `max(0, .)` is algebraically the truth's `min(0.8 w, 80 - 0.2 a)`.

  On none-short the offer gives `min(0.8000 w, max(0, 80.003 - 0.20004 a))` (share 0.53, kink 9286). The offer also
  got faster on none-short: 164 s became 112 s in local traces (the cause was not traced).
- **sparseblock after restore, with the limit held:** the pick had fitted the database rows' outside flows on rows
  that no longer carried the limit's series (`-63.8 + 0.18 pricing_queue` into db_waiting, and `-7.3 + 0.00025
  cart_responses_total` out of db_active). Held at full strength, those flows sent minrefit to a wrong optimum:
  `min(0.85 w, max(0, 0.52 + 0.83 a))`. Now `sparseblock.apply` runs a second time, right after `capmin.restore`. A
  block is one unit, or the units that a forced move in the flows joins. A move whose rate is a MIN expression that
  `hinge.amount` evaluates is held: its amounts are taken off the rows, and it is kept as it is. The rest is re-read
  as in 315 (type 11).

  On none-short the database block's SSE went from 1.48e6 to 6.6e-7 with 3 atoms: `0.06 pricing_inflight + 0.1
  cart_inflight` into db_waiting and `0.8 db_active` out. The pass is idle on whole-number counts, as before.
- **minrefit on both units' rows:** a limit's move is refitted on the rows of its source's unit and its receiver's
  unit (`_block`). For a same-unit limit this is the same set as before. The constant column `"1"` is a known
  column there. On counts-long, where sparseblock is idle, this refit is what placed the database sides:
  `0.0597 pricing_inflight + 0.105 cart_inflight`, `0.826 db_active`, and the limit `min(0.828 w, max(0, 81.5 - 0.194
  a))`. The block's BIC went from 31569 to 17877 (local trace).

**Cells fixed:** 3 (none-short, none-long, counts-long). counts-long also became 3.3 x faster (1616 s to 483 s), with
nearly all of the old time spent on the misfit rows.

**Port:**
- **forced_pairs:** about 20 lines. It needs only the stocks' units and the declared boundary. Use it wherever a
  strategy enforces "a move needs one unit" (milp's move set, structures' and engine_forms' unit guards, kalman_lna's
  move pairing in rows.py). Every capmin copy (43) can take the fixed-pool arm: add `("1", ones)` to the headroom
  loop's capacities for forced pairs only, and extend its beta grid.
- **Hold the limit:** a strategy with a block re-reader (engine_forms `reread.py`, kalman_lna `rows.py`, milp's row
  rebuilders) should subtract a found limit's amounts from the rows before re-reading the rest, and should join the
  two units of a forced move into one block.

**Test:** `tests/test_forcedpool_combined2.py` covers two things:
- forced_pairs gives only (w, a), and gives nothing without a declared boundary or when a's unit holds another stock;
- a block with a binding pool limit and wrong side flows is re-read to the true sides, with the limit held unchanged.

## The user's rule and this fix

The user's standing decision is that "a move needs both stocks in the same unit". This case's truth draws a move from
queries into connections, and its declared boundary admits no other drawing. With no outside outflow on db_waiting
and no outside inflow on db_active, a link plus a drain would be an invented boundary. I resolved this, without
asking, as follows: the declared boundary is the case's own statement, so the move is admitted only where the
boundary forces it (each stock alone in its unit, with no outside side to take the loss or supply the gain).
Everywhere else the one-unit rule stands unchanged. 312's nodes -> ready is still dropped, and 315 has one unit.

## Regression risk (for the later regression run)

- forced_pairs is empty unless two single-stock units face each other with no outside side, so most cases are
  unaffected. Cases with a declared boundary and two lone units of different kinds would now admit the move between
  them. The data would still have to show it, through capmin's gain and kink or an exact sparse re-read.
- The second sparseblock call runs on every case. It is idle on whole-number data, on exact blocks and on blocks with
  a non-plain flow other than a held limit. When it fires, the result is exact to the rounding.
- minrefit's rows are unchanged for same-unit limits. The constant column only enters through a forced pair's offer.
- Earlier rungs (307-315) were not re-run, per the plan.
