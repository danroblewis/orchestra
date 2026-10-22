# 313 (k8s-two-services), combined2, round 1 (2026-10-22, agent c2-313)

**Status: combined2 passes all four plan variants of 313 at d0a995c with no change to its code.** No fix was made or
needed. The rung passes: every top-5 strategy passes every plan variant.

| variant | achievable? (`analyse`) | combined2 at d0a995c (store) |
|---|---|---|
| none-short | yes (p 1.00) | **PASS** 6/6, complexity 13 = truth, 11.4 s (#387057) |
| none-long | yes (p 1.00) | **PASS** 6/6, 37.5 s (#387063) |
| counts-short | yes (p 1.00) | **PASS** 6/6, 9.6 s (#387056) |
| counts-long | yes (p 1.00) | **PASS** 6/6, 36.5 s (#387062) |

Commands (2026-10-22): `uv run sdlab-ladder analyse 313-k8s-two-services --variant V`, `uv run sdlab-ladder show
313-k8s-two-services --strategy combined2`, `uv run sdlab-ladder diff 313-k8s-two-services --strategy combined2
--variant V` (each: "none", 6 unchanged), and `uv run sdlab-ladder diff 313-k8s-two-services --summary --strategies
combined2,milp,structures,kalman_lna,engine_forms --variants none-short,none-long,counts-short,counts-long`: "20 results
(20 pass)". The results were run at d0a995c, which is the HEAD and the last commit to touch combined2, so they are
current. No pool job was submitted, because there was nothing to re-run.

Found model (every variant): the truth's six flows, including the cross-service link
`outside -> catalog_queue = 0.3 x frontend_inflight` (a link, not a move) and the input side
`outside -> frontend_queue = 1 x traffic`.

## Fixes kept

None. The fixes from 307-312 (fix-ledger types 0-10) did not disturb this rung: the switch, hinge, counted and
blocks passes find nothing to change on a linear two-chain model.

## Not targets

meas-short and meas-long are data-limited (`analyse` p 0.13 and 0.27) and deferred per the plan. combined2's meas-long
result (4/6, code 4d317d5, 2026-10-21) is stale and was not re-run.
