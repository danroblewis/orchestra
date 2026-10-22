# 313 (k8s-two-services), kalman_lna, round 1 (2026-10-22, agent kalman_lna-313-r1)

**Status: kalman_lna passes all four plan variants of 313 with no change to its code.** No fix was made or needed.

| variant | achievable? (`analyse`) | before: store at d0a995c | after: pool job 329 at ef79317 (scorer 5dca817) |
|---|---|---|---|
| none-short | yes (p 1.00) | PASS 6/6 (#387051) | **PASS** 6/6, complexity 13 = truth, 12.9 s |
| none-long | yes (p 1.00) | PASS 6/6 (#387065) | **PASS** 6/6, 113.4 s (node2) |
| counts-short | yes (p 1.00) | PASS 6/6 (#387050) | **PASS** 6/6, 5.2 s |
| counts-long | yes (p 1.00) | PASS 6/6 (#387059) | **PASS** 6/6, 41.8 s (node2) |

Commands (2026-10-22): `uv run sdlab-ladder analyse 313-k8s-two-services --variant V` (all four achievable, every
scored part p 1.000); `uv run sdlab-ladder diff 313-k8s-two-services --strategy kalman_lna --variant V` ("none", 6
unchanged, each variant); `uv run sdlab-ladder submit --strategies kalman_lna --cases 313-k8s-two-services --variants
none-short,none-long,counts-short,counts-long --priority 400 --by kalman_lna-313-r1` (job 329), then
`uv run sdlab-ladder job 329 --wait` ("4 pass") and `uv run sdlab-ladder show 313-k8s-two-services --strategy kalman_lna`.

The store's results were stale only because of the scoring change 5dca817 (levels read with announced injections). 313
announces no injections, so the change could not move it; job 329 re-ran the four cells at the current HEAD to confirm.

Found model (every variant): the truth's six flows, including the cross-service link
`outside -> catalog_queue = 0.3 x frontend_inflight` (a link, not a move: the caller's requests are not used up) and
the input side `outside -> frontend_queue = 1 x traffic`. The common failure on this rung among other strategies (`diff
--summary`: `+ frontend_inflight -> catalog_queue` invented, with `frontend_queue -> frontend_inflight` high to
compensate) does not occur: kalman_lna's declared-boundary handling (fix-ledger type 0, boundary-fill / one-per-side)
keeps the declared `estimate` inflow of catalog_queue as an outside flow, so the link is found directly.

## Fixes kept

None. The fixes from 307-312 (fix-ledger types 0-10, including tracker.py, rows.py's derived columns and the batched
subset fits of 6fd4778) find nothing to change on a linear two-chain model.

## Not targets

meas-short and meas-long are data-limited (`analyse`: p 0.13 and 0.27) and deferred with the noise round; kalman_lna
passes both anyway (store, code bab9156, stale).
