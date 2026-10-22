# 313 (k8s-two-services): engine_forms, round 1

**Status (2026-10-22, agent engine_forms-313-r1, engine_forms lock held and released): engine_forms passes every
plan variant of 313 (none-short, none-long, counts-short, counts-long) with no code change.** Pool job 328 at
ef79317 (`uv run sdlab-ladder job 328`); engine_forms' package is unchanged since 104ee76 (312 round 2).

| variant | achievable? (`analyse`) | before (store, stale strategy hash a6539fefe) | after (ef79317, job 328) |
|---|---|---|---|
| none-short | yes, p 1.000 | pass | **PASS** (5.5 s, Mac) |
| none-long | yes, p 1.000 | pass | **PASS** (62 s, Mac) |
| counts-short | yes, p 1.000 | pass | **PASS** (3.5 s, Mac) |
| counts-long | yes, p 1.000 | pass | **PASS** (23 s, Mac) |

meas-short and meas-long are DATA-LIMITED (`analyse` p 0.133 / 0.267) and deferred by the plan.

## Diagnosis (rule 4b)

`uv run sdlab-ladder diff 313-k8s-two-services --strategy engine_forms --variant V`: "(6 unchanged)" on all four
variants. The call is read as the link `outside -> catalog_queue = 0.3001 x frontend_inflight` (counts-long), not
as the move `frontend_inflight -> catalog_queue`. The rung's most common miss across the other strategies
(`diff --summary`: 59 results draw that invented move, 70 miss the link) does not occur here: engine_forms' exact
row reader reads frontend_inflight's row as `0.6 queue - 0.5 inflight` with no 0.3 outflow, and the declared estimated
inflow of catalog_queue may read any measured stock, so the boundary side takes the link.

## Fixes kept

None needed. No fix type was added or used on this rung.

## For the other strategies (port notes)

The common 313 failure (an invented conserving move from the caller's inflight into the callee's queue where the truth
is a link on the callee's declared estimated inflow) is a row-fit issue, not a missing mechanism: frontend_inflight's
own row and frontend_responses_total's row rule the move out (a move would drain the caller and leave 0.2, not 0.5,
for its completions). A strategy that draws the move should check that each move's source row is reproduced with
the move's outflow before preferring the move over a declared outside side reading the same column.
