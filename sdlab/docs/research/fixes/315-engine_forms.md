# 315 (k8s-fan-out): engine_forms, round 1

**Status (2026-10-22, agent ef315-r1, engine_forms lock held and released): engine_forms passes every plan variant of
315 (none-short, none-long, counts-short, counts-long) with no code change.** Pool job 337 at 20ed81c
(`uv run sdlab-ladder job 337`): 4 pass, 0 errors; engine_forms' package is unchanged since 104ee76 (312 round 2).

| variant | achievable? (`analyse`) | before (store, 20ed81cad) | after (20ed81c, job 337) |
|---|---|---|---|
| none-short | yes, p 1.000 | pass (12 unchanged) | **PASS** (110 s, node2) |
| none-long | yes, p 1.000 | pass (12 unchanged) | **PASS** (205 s, node2) |
| counts-short | yes, p 1.000 | pass (13 unchanged) | **PASS** (Mac/node2) |
| counts-long | yes, p 1.000 | pass (13 unchanged) | **PASS** (190 s, node2) |

## Diagnosis (rule 4b)

`uv run sdlab-ladder diff 315-k8s-fan-out --strategy engine_forms --variant V`: no hunk on any of the four variants.
The fan-out is read as two links from frontend_inflight on the callees' declared estimated inflows
(`outside -> catalog_queue = 0.3 x frontend_inflight`, `outside -> cart_queue = 0.15 x frontend_inflight`), plus
`outside -> pricing_queue = 0.4 x catalog_inflight`, and no link between catalog and cart.

The rung's common misses across the other strategies (`diff 315-k8s-fan-out --summary`: 179 results, 69 fail,
3 error, 2 timeout) are the 313/314 miss at every call: invented moves `catalog_inflight -> pricing_queue`
(44 results, 29 strategies), `frontend_inflight -> cart_queue` (42, 28) and `frontend_inflight -> catalog_queue`
(38, 26) in place of the links, the queue rates pushed off to compensate, and on counts-short invented links reading
the near-collinear counters (`outside -> pricing_queue = c + k x frontend_responses_total`). engine_forms avoids them
for the reason 313-engine_forms.md gives: its exact row reader reads each caller's inflight row with no call outflow,
so the declared outside side takes the link. With two callees on one caller, a move would have to drain
frontend_inflight by 0.45 x itself, which frontend_inflight's and frontend_responses_total's rows rule out.

## Fixes kept

None needed. No fix type was added or used on this rung.

## For the other strategies (port notes)

Same as 313 and 314: before preferring a move from the caller's inflight into a callee's queue over a declared outside
(estimate) inflow reading the same column, check that the move's source row is reproduced with the move's outflow.
On 315 this check is needed for each callee of the fan-out (the drains add up on the caller's row).
