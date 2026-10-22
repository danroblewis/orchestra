# 314 (k8s-chain-of-three), combined2, round 1 (2026-10-22, agent c2-314)

**Status: combined2 passes all four plan variants of 314 with no change to its code.** No fix was made or needed.
The results in the store were run at b43a0f4; the last commit to touch combined2 is 388d15d (an ancestor of b43a0f4),
so they are current for combined2's code. No pool job was submitted, because there was nothing to re-run.

| variant | achievable? (`analyse`) | combined2 at b43a0f4 (store) |
|---|---|---|
| none-short | yes (p 1.00) | **PASS** 9/9, complexity 21 vs truth 19, 72.5 s (#387095) |
| none-long | yes (p 1.00) | **PASS** 9/9, complexity 19 = truth, 183.0 s |
| counts-short | yes (p 1.00) | **PASS** 9/9, complexity 19 = truth, 35.8 s |
| counts-long | yes (p 1.00) | **PASS** 9/9, complexity 19 = truth, 225.9 s |

Commands (2026-10-22): `uv run sdlab-ladder analyse 314-k8s-chain-of-three --variant V` (every variant achievable,
p 1.000 on every number), `uv run sdlab-ladder show 314-k8s-chain-of-three --strategy combined2`, and
`uv run sdlab-ladder diff 314-k8s-chain-of-three --summary --strategies combined2 --variants
none-short,none-long,counts-short,counts-long`: "4 results (4 pass)".

Found model (every variant): the truth's nine flows: three queue -> inflight -> responses_total chains, the input
`outside -> frontend_queue = 1 x traffic`, and the two links `outside -> catalog_queue = 0.3 x frontend_inflight` and
`outside -> pricing_queue = 0.4 x catalog_inflight`. There is no spurious frontend -> pricing link (the two-hop
correlation the rung tests).

## Fixes kept

None. The fixes from 307-313 (fix-ledger types 0-10) did not disturb this rung.

## Noted, not fixed

On none-short the two links carry float-floor constants (`-2e-06 + 0.3 x frontend_inflight`,
`4e-06 + 0.4 x catalog_inflight`), which cost +2 terms of complexity (21 vs 19) but not the pass. Fix-ledger
type 1 (zero-term prune, engine_forms `tidy.py`: drop a term whose largest contribution is below 1e-4 of the flow's
largest amount) would remove them. It was not ported here because the rung passes and the plan defers anything
that is not needed for the current rung; it is a candidate for the post-climb port.
