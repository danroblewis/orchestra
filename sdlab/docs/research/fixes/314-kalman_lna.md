# 314 (k8s-chain-of-three), kalman_lna, round 1 (2026-10-22, agent kalman-314-r1)

**Status: kalman_lna passes all four plan variants of 314 with no change to its code.** No fix was made or needed.

| variant | achievable? (`analyse`) | before: store | after: pool job 333 at 4f92f82 |
|---|---|---|---|
| none-short | yes (p 1.00) | PASS 9/9 (#387084, b43a0f4) | **PASS** 9/9, complexity 19 = truth, 26.7 s (node2) |
| none-long | yes (p 1.00) | PASS 9/9 (#386655, bab9156, stale) | **PASS** 9/9, 135.3 s (node2) |
| counts-short | yes (p 1.00) | PASS 9/9 (#387083, b43a0f4) | **PASS** 9/9, 15.2 s (node2) |
| counts-long | yes (p 1.00) | PASS 9/9 (#387092, b43a0f4) | **PASS** 9/9, 91.4 s (node2) |

Commands (2026-10-22): `uv run sdlab-ladder analyse 314-k8s-chain-of-three --variant V` (all four achievable, every
scored part p 1.000); `uv run sdlab-ladder diff 314-k8s-chain-of-three --strategy kalman_lna --variant V` ("none",
every variant); `uv run sdlab-ladder submit --strategies kalman_lna --cases 314-k8s-chain-of-three --variants
none-short,none-long,counts-short,counts-long --priority 400 --by kalman-314-r1` (job 333), then
`uv run sdlab-ladder job 333 --wait` ("4 pass") and `uv run sdlab-ladder show 314-k8s-chain-of-three --strategy kalman_lna`.

none-long's stored result was at bab9156, before the 310-312 fixes (6fd4778 and earlier); job 333 re-ran all four cells
at the current HEAD to confirm that those fixes did not break it. They did not.

Found model (none variants): the truth's nine flows exactly, both links (`outside -> catalog_queue = 0.3 x
frontend_inflight`, `outside -> pricing_queue = 0.4 x catalog_inflight`) as outside flows on the declared `estimate`
sides, and no two-hop link from frontend to pricing. The declared-boundary handling (fix-ledger type 0) is what keeps
each link a link, as on 313.

## Fixes kept

None.

## Residue (passes, but not the simplest model)

counts-long (the store's #387092 at b43a0f4, same strategy code as HEAD) found 22 complexity against the truth's 19: an
extra move `catalog_inflight -> pricing_queue = 0.0095 x catalog_inflight` (2.5% of the link it sits beside, the link
then 0.379 instead of 0.4) and a second term on frontend completion reading `catalog_inflight` (0.033). These are fits to
counting noise. Every scored part is within tolerance, so it is a pass, but the extra pieces cost complexity (rule 7). A
general fix would be a pruning test that drops a term when the error it removes is no larger than the noise's expected
share (an F-test or held-out check on the one-step rows). It was not attempted this round: the rung passes, and the
noise round is deferred.
