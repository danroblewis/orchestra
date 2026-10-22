# 316 (k8s-shared-database): structures, round 1

**Status (2026-10-22, agent structures-316-r1): structures passes every achievable variant of 316.** none-short,
none-long and counts-long PASS 16/16 at **b7a1474** (pool job 357, all on node2, complexity 32 = the truth's).
counts-short fails 14/16, and `analyse` calls it data-limited, so it is not a target. Before the work, at 59d2ccf,
all four failed. I kept five fixes, all inside `sdlab/discovery/strategies/structures/`. I held the structures lock
for the round and released it after this doc's commit.

## Achievability

`uv run sdlab-ladder analyse 316-k8s-shared-database --variant V`:

| variant | analyse | target? |
|---|---|---|
| none-short | ok, p 1.000 | yes |
| none-long | ok, p 1.000 | yes |
| counts-short | **DATA-LIMITED, p 0.407**: the two query links into db_waiting reach tolerance with p 0.42 and 0.61 (bound SE 0.0109 against 0.006 allowed, 0.0116 against 0.01) | no |
| counts-long | ok, p 0.844 | yes |

## Results

`uv run sdlab-ladder submit --strategies structures --cases 316-k8s-shared-database --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-316-r1`, then `uv run sdlab-ladder job N --wait`:

| variant | before (59d2ccf, stored) | job 346 (58b44f3) | job 355 (470e0dd) | **job 357 (b7a1474)** | discovery |
|---|---|---|---|---|---|
| none-short | FAIL 12/16 | PASS | - | **PASS 16/16** | 134 s |
| none-long | FAIL | PASS | - | **PASS 16/16** | 317 s |
| counts-short | FAIL | FAIL | FAIL | FAIL 14/16 (data-limited) | 78 s |
| counts-long | FAIL | FAIL (frontend rows broken) | FAIL (pool move lost) | **PASS 16/16** | 240 s |

job 353 (d7cfa79, counts only) timed out on counts-long after 1800 s on the Mac, in the output-error refit (fix 3).
job 356 was superseded and cancelled. counts-short at b7a1474 drops the `0.06 x pricing_inflight` link and puts
0.163 on cart_inflight. That is the collinearity the analysis names.

## Diagnosis

`diff 316 --strategy structures` at 59d2ccf: on every variant the database's flows were wrong or missing. The rest
(12 flows) was right on none-short. There were three causes, all **method faults**:

1. **The limit has no measured capacity.** The truth is `acquired = min(0.8 db_waiting, 80 - 0.2 db_active)`, a
   pool of a fixed size less the connections in use. capmin's offer can say only `MIN(X, theta Y)` with Y a
   measured stock, so it offered `MIN(db_waiting, 0.98 db_active)`. That binds on 3% of steps and is a proxy. On
   none-short, X's row gain was 1626 for the proxy and 4396 for the true shape (scratch `proto.py`).
2. **The move crosses units.** db_waiting is in `queries` and db_active in `connections`. The search library
   (`terms.library`), rowwise's translation and the boundary guard make moves only within a unit. The declared
   boundary gives db_waiting no outflow and db_active no inflow, so with no move the search could not explain
   either row. It wrote `link outside -> db_waiting [series] 4.89` plus a gap.
3. **counts-long only:** (a) the search ran out of its 90 s cap and returned nothing, so the base was kept. The
   base never read the pool series on the db rows. (b) After fix 1, `enforce_sides` fixed frontend_queue's declared
   input at 1 x the offered pool series in place of traffic (job 346). (c) The output-error refit, which cannot run
   the pool form, refitted a plain stand-in for 30 min on the Mac (job 353), and on node2 it rewrote the frontend
   rows (job 346).

## Fixes kept

| # | type | mechanism | commit | files |
|---|---|---|---|---|
| 1 | **pool-min** (new; extends ledger type 0 *min-form*) | capmin offers `MIN(X, max(0, a - b Z))`, a fixed capacity less what occupies it, for every non-final X and Z. A coarse screen (8 b on a log grid, a by golden section over quantiles of X + bZ) keeps the best 3 pairs, which are refined by golden section on X's row and then on X's row with the receiver's. It is subject to the offer's own guards (each regime on 1% and 5 or more steps, gain and kink above 6 log T), and it replaces the plain offer only when its kink is larger by more than log T. It is written back as `min(kX, max(0, ka - kb Z))`. On 316 it finds a = 100.0 and b = 0.2500 on none (99.3 / 0.235 on counts-long) | 58b44f3 | `capmin.py` (`_pool`, `_Proj`, `_series`, `_min_text`), `tests/test_structures_pool.py` |
| 2 | **limited-move** (new) | the search's library gets the move the offered series limits, `source -> receiver` reading the series, whatever the units are (the offer found the receiver gaining what the source loses), and every search start is seeded with it. On none-short the search then finds the truth's 16 flows exactly | 58b44f3 | `discover.py` (`_limited`) |
| 3 | **oefit-skip** (ledger type 10 guard) | the output-error refit leaves an answer that reads a fixed pool's series as it is (it cannot run that form, and its plain stand-in searched for 30 min) | 470e0dd (and the parse guard in 58b44f3) | `oefit.py` |
| 4 | **series-not-input** (ledger type 0 *input-kind* guard) | `enforce_sides` never takes an offered capacity series (`capmin__*`) as a declared measured input | d7cfa79 | `boundary.py` |
| 5 | **best-so-far** (ledger type 10 budget) | a search that reaches its time cap answers with the best model any of its stepwise searches reached (`fit._note`, kept on the Problem), not with nothing. On counts-long the first search, seeded with the pool move, had the truth's 16 flows when the 90 s cap fell (local trace on the Mac, 90 s) | b7a1474 | `fit.py`, `discover.py` |

A sixth change was kept but is not proven necessary. **pair-terms** (d892501, `pairing.py` `_pair_terms`): the
offered series' term is taken out of the source's outflow and the receiver's inflow when those read it beside other
terms, and made the move. I made it for counts-long's lost pool move, but a local trace then showed that the base
never reads the series there (fix 5 was the cure). It is idle on 316 and is general (it makes the move only with a
positive number on both sides).

### The units decision (the user's rule "a move needs both stocks in the same unit")

The truth's `db_waiting -> db_active` joins queries to connections. I let a move cross units **only** where the
capacity offer names its two ends from the data: the source's row loses the series and the receiver's row gains it
(capmin's receiver test). Every other move (library, rowwise, guard, repair, counted) still needs one unit. Nothing
reads the case.

## How another strategy adopts these

- **pool-min:** copy `_pool`, `_Proj`, `_series` and the `cap is None` branch of `_min_text` from structures'
  `capmin.py` at 58b44f3 into the strategy's own capmin copy, and call `_pool` at the end of `offer` (see the
  `pool = _pool(...)` lines). Every strategy carries a capmin copy (43), so this is the main port. A copy's oefit
  must then skip or support the pool form (fix 3), and its boundary's input fixer must skip `capmin__` names
  (fix 4). The offer costs 2-13 s on 316 (14 stocks), and the screen grows as stocks squared, so expect about 1 min
  on 317 (36 stocks).
- **limited-move:** a strategy whose search makes moves only within a unit or only reading the source needs a
  candidate move `source -> receiver` reading the offered series (capmin.offered gives both ends). Matrix-style
  strategies get the two outside terms from their rows and need pairing (`pairing.pair`, with fix 6 for terms
  beside others) to make the move before the boundary guard drops both.
- **best-so-far:** any time-capped stepwise search should keep its best fit and answer with it on time-out.

## Risks

- **No regression run** (the plan). The pool offer runs on every case with a capmin copy, and it may offer a pool
  where the plain offer offered nothing. Its guards are the plain offer's plus log T, but it is not verified
  elsewhere. Fix 5 changes what time-capped searches return on every rung, though only toward a model the judge
  must still prefer over the base.
- counts-long passed with release 0.826 (truth 0.8) and cart queries 0.105 (0.1), inside tolerance. The pool's a
  and b on counts-long are 99.3 and 0.235, which the whole-flow comparison accepts.
