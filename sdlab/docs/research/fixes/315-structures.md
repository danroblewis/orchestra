# 315 (k8s-fan-out): structures, round 1

**Status (2026-10-22, agent structures-315-r1):** structures passes all four plan variants of 315 at **ee94317**
(pool job 340: 4 done, 4 pass, 0 errors). Before the fix, at 20ed81c, it passed 3 of 4 and failed none-short. One
fix was kept, in `rowwise.py`. I held the structures lock for this round and released it after this doc's commit.

## Achievability

`uv run sdlab-ladder analyse 315-k8s-fan-out --variant V`: **ok, p = 1.000** on none-short, none-long, counts-short
and counts-long, so all four are targets. On the none variants the analysis reports frontend_queue's row at rank
11 of 14 (condition 1e16). The callees' queues and the counters are nearly collinear, but identification is not
blocked.

## Results

| variant | before (20ed81c, stored) | after (ee94317, job 340) | parts | complexity (truth 25) | discovery |
|---|---|---|---|---|---|
| none-short | FAIL, 9/12, skill@20 78.5% | **PASS** | 12/12, 0.0% | 25 | 28.5 s (was 42.3 s) |
| none-long | PASS | **PASS** | 12/12, 0.0% | 25 | 207.6 s |
| counts-short | PASS | **PASS** | 12/12, at most 0.9% | 25 | 27.5 s |
| counts-long | PASS | **PASS** | 12/12, at most 0.6% | 25 | 117.9 s |

The commands were `uv run sdlab-ladder submit --strategies structures --cases 315-k8s-fan-out --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-315-r1 --every-variant` and
`uv run sdlab-ladder job 340 --wait`. Running `sdlab-ladder diff 315-k8s-fan-out --summary --strategies structures`
gives 4 results (4 pass) and 0 diff lines. Both calls are found as links from frontend_inflight (0.3 into
catalog_queue, 0.15 into cart_queue), and there is no link between the callees.

## Diagnosis (none-short)

`diff 315 --strategy structures --variant none-short` at 20ed81c showed all three catalog equations missing. In
their place was a hidden 2-stage chain into catalog_queue (`outside -> outside~catalog_queue~h1s1 = 0`, delay
4.5), fed by nothing and holding only its starting contents. This is a **method fault**, not a data limit. The
truth's 12 terms score BIC -36189 on the search's own likelihood. The search's plain model scored -24120, and its
chain model scored -24599.

I traced it stage by stage with scratch scripts (`s315/chain.py`, `truthbic.py`):

1. `rowwise.regress` is each stock's own forward-stepwise regression, and it seeds the joint search. It read
   frontend_inflight's row as **24 columns**: catalog_queue, cart_queue, their squares and products, and others.
   The exact 2-column answer (`0.6 frontend_queue - 0.5 frontend_inflight`) was never among them. The cause is the
   fan-out. Each callee queue's change is `k x frontend_inflight - d x queue`, so the callees' queues nearly span
   frontend_inflight. The first greedy step picks one of these proxies, and from there the greedy path never
   reaches frontend_queue.
2. With that seed, the joint stepwise search fits frontend's rows with a goal term `traffic - catalog_queue`. It
   cannot reach the truth from there, because the link and the move are each worthless alone: adding the move
   gives theta 0.003. This is a two-term valley that single adds, swaps and merges cannot cross.
3. The chain stage then found a lower BIC by fitting frontend exactly and giving up catalog's three rows to an
   empty chain. That cost less because catalog's rows have smaller variance. The post-passes kept the result
   (`moves: bad catalog_inflight, catalog_responses_total, kept false`).

On rung 314 there was one callee per caller, so the near-span did not exist.

## Fix kept

**Type: best-subset row regression** (ledger type 3's row re-read, as in engine_forms' `reread.py` and
structures' own `rebuild.py` from 311, implemented as in type 10's *batched-subsets*, kalman_lna `subsets.py`
6fd4778). Commit **ee94317**, `sdlab/discovery/strategies/structures/rowwise.py`:

- `select_row` (each stock's own regression) now compares its greedy result with `best_subset`. That function
  tries every single column and every pair of the allowed columns (products included; up to 400 columns), and
  every triple of the plain columns (constant, levels, inputs; up to 40). It ranks each size at once by the scaled
  normal equations (a batched Gram stack) and refits the best 4 of each size by least squares, so that
  exactness is judged precisely. It uses the same BIC as the greedy path, and the subset replaces the greedy
  answer only when its BIC is lower.
- A chain's feed columns, which carry start contents, are left out of the subset check. These are kept as before.
- The rule is the same on every row and every run. Nothing reads the case.

**Effect:** on 315 none-short every row's seed is the truth's, the joint search starts at BIC -36189, and the
chain stage cannot beat it. On counts-short the search also starts better: plain BIC 12104, where it used to start
from a first BIC of 14279. Discovery got faster (42 s to 28 s), because the search begins nearer its optimum.

**How another strategy adopts it:** any strategy that seeds or reads rows by forward stepwise regression should
check the result against an exhaustive best subset of size 1-3, with a batched Gram ranking and an exact refit of
the top few. The function is self-contained and numpy-only: copy `best_subset` (takes M, y, w, crit) from
structures' `rowwise.py` at ee94317. combined2 carries a vendored copy of structures
(`_vendored/structures`), which was not changed and is the natural first adopter.

## Risks

- **No regression run**, following the plan. The change affects the seed of every structures search, so any
  rung could move. The likely direction is better, since the seed's BIC can only fall. Not verified elsewhere.
- Cost grows with the column count. With products on, a 36-stock case (317) has about 600 columns, which is over
  SUBSET_PAIRS = 400, so pairs are skipped there and singles and plain triples remain. 317 may need the cap
  reconsidered.
