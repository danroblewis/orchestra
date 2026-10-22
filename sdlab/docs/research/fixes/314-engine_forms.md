# 314 (k8s-chain-of-three): engine_forms, round 1

**Status (2026-10-22, agent ef314-r1, engine_forms lock held and released): engine_forms passes every plan variant of
314 (none-short, none-long, counts-short, counts-long) with no code change.** Pool job 334 at 4f92f82
(`uv run sdlab-ladder job 334`); engine_forms' package is unchanged since 104ee76 (312 round 2).

| variant | achievable? (`analyse`) | before (store, b43a0f49c) | after (4f92f82, job 334) |
|---|---|---|---|
| none-short | yes, p 1.000 | pass | **PASS** 9/9 (14 s, Mac) |
| none-long | yes, p 1.000 | pass | **PASS** 9/9 (159 s, node2) |
| counts-short | yes, p 1.000 | pass | **PASS** 9/9 (9.5 s, Mac) |
| counts-long | yes, p 1.000 | pass | **PASS** 9/9 (111 s, node2) |

## Diagnosis (rule 4b)

`uv run sdlab-ladder diff 314-k8s-chain-of-three --strategy engine_forms --variant V`: no hunk on any of the four
variants ("9 unchanged"; counts-long "10 unchanged"). Both calls are read as links on the callee's declared estimated
inflow (`outside -> catalog_queue = 0.3 x frontend_inflight`, `outside -> pricing_queue = 0.4 x catalog_inflight`),
and there is no two-hop link from frontend straight to pricing.

The rung's common misses across the other strategies (`diff 314-k8s-chain-of-three --summary`: 180 results, 92 fail)
are the 313 miss twice over: the invented moves `frontend_inflight -> catalog_queue` (64 results, 26 strategies) and
`catalog_inflight -> pricing_queue` (46 results, 25 strategies) in place of the links, plus the queue rates pushed off
to compensate. engine_forms avoids them for the reason 313-engine_forms.md gives: its exact row reader reads each
caller's inflight row with no call outflow, so the declared outside side takes the link.

## Fixes kept

None needed. No fix type was added or used on this rung.

## For the other strategies (port notes)

Same as 313: before preferring a move from the caller's inflight into the callee's queue over a declared outside
(estimate) inflow reading the same column, check that the move's source row is reproduced with the move's outflow
(a move would drain the caller's inflight by the call amount, which its own row and its counter's row rule out).
On 314 this check is needed at each hop of the chain.
