# 313 (k8s-two-services): milp, round 1

Status (2026-10-22, code 5dca817, the `sdlab` HEAD; milp's package last changed in 67c8919; pool job 325, all four
items on the Mac): **all four variants pass. No fix was needed.**

| variant      | achievable? (`analyse`) | before (store, 6f5766f / ab73e30, 2026-10-21) | round 1 (5dca817, job 325) |
|--------------|-------------------------|-----------------------------------------------|----------------------------|
| none-short   | yes (p 1.00 per part)   | PASS                                          | **PASS 6/6** (1.3 s)       |
| none-long    | yes                     | PASS                                          | **PASS 6/6** (3.5 s)       |
| counts-short | yes                     | PASS                                          | **PASS 6/6** (20.9 s)      |
| counts-long  | yes                     | PASS                                          | **PASS 6/6** (26.5 s)      |

Commands: `uv run sdlab-ladder job 325`, `uv run sdlab-ladder diff 313-k8s-two-services --strategy milp --variant V`
(each variant: "none", 6 unchanged), `uv run sdlab-ladder show 313-k8s-two-services --strategy milp --variant counts-long`.

## What milp finds

On every variant it finds the truth's six flows and nothing more (complexity 13 vs 13, 1.00x): the two queue ->
inflight -> responses_total chains as moves, `outside -> frontend_queue = 1 x traffic` (the declared input, fixed), and
the call as a **link** `outside -> catalog_queue = 0.3003 x frontend_inflight` on catalog_queue's declared estimated
inflow (counts-long), not a move out of frontend_inflight. counts-long numbers: 0.5992, 0.4997, 0.6, 0.5006, 0.3003
(all within 0.2%). `analyse` notes the two counters are nearly collinear on this run; milp still gives each its own
service's inflight.

## Fixes kept

None. The rung needs none of the 308-312 mechanisms (no controller, gap, table or capacity form), and none of
milp's post passes (quantized, hinge.refine, effects, polish) fires a spurious flow here.

## For the regression run

The earlier store passes (2026-10-21) were from milp before the 310-312 changes; job 325 confirms the 312 round 2
code (step budget, joint polish of tables) did not break this rung.
