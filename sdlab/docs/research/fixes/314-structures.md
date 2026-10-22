# 314 (k8s-chain-of-three): structures, round 1

**Status (2026-10-22, agent structures-314-r1):** structures passes all four plan variants of 314 with **no code
change**. The structures package is unchanged since round 2 of 312 (`git log -- sdlab/strategies/structures`). I
held the structures lock for this round and released it after this doc's commit.

## Achievability

`uv run sdlab-ladder analyse 314 --variant V`: **ok, p = 1.000** on none-short, none-long, counts-short and
counts-long, so all four are targets. The analysis lists the move-vs-(link plus drain) equivalences, where parsimony
picks the move, and the collinear counters and queues. Neither blocks identification.

## Results

`uv run sdlab-ladder submit --strategies structures --cases 314-k8s-chain-of-three --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-314-r1 --every-variant`, then
`uv run sdlab-ladder job 335 --wait` (2026-10-22, at 4f92f82, on the Mac and node2): **4 done, 4 pass, 0 errors**
(counts-long 124 s, none-long 205 s).

The main line's stored results at b43a0f4 (`sdlab-ladder show 314 --strategy structures --variant V`) agree. No
strategy code changed between b43a0f4 and 4f92f82.

| variant | stored (b43a0f4) | parts | complexity (truth 19) | discovery |
|---|---|---|---|---|
| none-short | **PASS** | 9/9, all 0.0% | 19 | 17.8 s |
| none-long | **PASS** | 9/9, all 0.0% | 19 | 213.6 s |
| counts-short | **PASS** | 9/9, at most 0.6% | 19 | 14.0 s |
| counts-long | **PASS** | 9/9, at most 0.3% | 19 | 223.0 s |

Every variant recovers the truth's 9 equations. Both calls are written as links (`outside -> catalog_queue = 0.3 x
frontend_inflight`, `outside -> pricing_queue = 0.4 x catalog_inflight`). There is no spurious two-hop link from
frontend to pricing.

## Diagnosis

`uv run sdlab-ladder diff 314 --summary --strategies structures --variants none-short,none-long,counts-short,counts-long`:
4 results (4 pass), 0 diff lines. There was nothing to fix.

## Fixes kept

None. As on 313, the declared boundary (`catalog_queue` and `pricing_queue`: `{in: estimate}`) allows only an
outside inflow on each callee's queue. So each call is fitted as that side's single link, and the BIC search does not
add the two-hop reader. The fixes from 307-312 stay inactive on this linear case.

## Risks

- No regression run, following the plan.
- none-long and counts-long take 124-223 s against the 1800 s timeout. That is 3-4x rung 313's time for 3 more
  stocks, so the post-passes grow quickly with the number of stocks. Watch this on 317 (40 stocks).
