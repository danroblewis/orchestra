# 311 (k8s-node-pool): structures, round 2

**Status (2026-10-22, agent structures-311-r2): structures passes every achievable variant of 311, with no code
change in round 2.** At the sdlab HEAD 3c6165b (structures' package unchanged since 542bc3d), pool job 303 ran all
four variants on **node2**: none-short PASS (199 s) and none-long PASS (467 s). counts-short and counts-long FAIL,
and both are data-limited, so they are not targets. I kept no fixes this round. I held the structures lock and
released it after this doc's commit.

Round 1 of this rung is in `311-structures.md`.

## Where the numbers come from

`uv run sdlab-ladder submit --strategies structures --cases 311-k8s-node-pool --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-311-r2 --every-variant`, then
`uv run sdlab-ladder job 303 --wait` and `uv run sdlab-ladder job 303 --json` (status, seconds, machine):

| variant | achievable? | job 299 (542bc3d, round 1, Mac) | job 303 (3c6165b, round 2, node2) |
|---|---|---|---|
| none-short | yes | PASS 26/26, 130 s | **PASS**, 199 s |
| none-long | yes | PASS 26/26, 340 s | **PASS**, 467 s |
| counts-short | no: data-limited | FAIL 5/23 | FAIL, 353 s |
| counts-long | no: data-limited | FAIL 14/23 | FAIL, 746 s |

The stored none answers at 542bc3d have the same strategy hash. `sdlab-ladder diff 311-k8s-node-pool --strategy
structures --variant none-short` gives "none (28 unchanged)". `show ... --variant none-long` lists 26/26 parts right,
with every flow at 0.0% error.

**Achievability.** `analyse 311-k8s-node-pool` still says "not analysed" on every variant. On none-short its z3
report fails to import (`cannot import name 'z3core'`), which is a harness issue, reported here and not fixed. I kept
round 1's verdict, and the other strategies' agents reached the same verdict independently:

- the kill-rate bound: 9 kills on counts-short (relative SE about 33%) and 88 on counts-long (about 10.7%), against
  the 10% tolerance (311-structures.md);
- combined2's free-knot Poisson ML on the kill table is 15.4% / 17.2% off (311-combined2.md);
- engine_forms measured a relative error of 0.31 / 0.20 against 0.10 (311-engine_forms.md).

## What round 2 checked

- **Machine dependence (round 1's open risk).** Round 1's passes had run only on the Mac, and on 310 node2's
  time-capped search had once lost a flow. Job 303 ran both none variants on node2, and both pass. The 311 fixes
  (row-rebuild, injection-aware post-stages, room-limited move, judge-runs-expressions) therefore carry to node2.
- **The user's standing decisions as of this round.**
  - *Credit a hidden stock.* none-long's `h_mem` (filled at 1 a step, drained by `h_mem x table(mem)`) is scored
    as the truth's `leak`, and the parts `outside -> leak` and `leak -> outside` are both ok.
  - *A fitted time schedule standing in for hidden state is not robust.* No none answer carries a time schedule or
    era pieces. The OOM effect is a state table on `mem` and the hidden stock is an integrator, so nothing here is
    "fits" by that rule.
  - *Conserving move.* `ready -> pending = ready x table(mem)` is a move between two same-unit stocks, the truth's
    form.
- **Off-run differences.** The HPA's clamps `min(16, ...)` and `max(3, ...)` are not written on none-long, as in
  round 1. Neither binds on either run, so the data cannot identify them. The scorer passes the whole-flow
  comparison. These clamps are not a method fault on this data. A rung that drives the HPA into its clamps would
  test them.

## Fixes kept

None in round 2. Round 1's four (542bc3d) are recorded in `311-structures.md` and in the fix ledger.

## Risks and what is not done

- **No regression run**, per the plan. Round 1's expression-aware judge is still the largest regression risk on
  306-310 (see 311-structures.md).
- counts-long's lost `outside -> pending` and mem drain (`mem -> outside` written as `0.11 mem + min(...)`) are not
  diagnosed, because the variant is data-limited and so not a target. Its long run is RUNAWAY. A later robustness
  round should look at it, because a runaway is worse than a missed coefficient.
- The z3 import failure in `analyse` / `show` for none-short is a harness issue for the harness owner.
