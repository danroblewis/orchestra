# 313 (k8s-two-services): structures, round 1

**Status (2026-10-22, agent structures-313-r1):** structures passes all four plan variants of 313 with **no code
change**. The structures package is unchanged since round 2 of 312 (`git log -- sdlab/strategies/structures`). I
held the structures lock for this round and released it after this doc's commit.

## Achievability

`uv run sdlab-ladder analyse 313 --variant V`: **ok, p = 1.000** on none-short, none-long, counts-short and
counts-long, so all four are targets. The bound SEs are 0.0% on the none variants and at most 0.4% on counts,
against allowances of 1% to 16%. The analysis records the equivalences it accepts (each move against a link plus a
drain, where parsimony picks the move) and the collinearity of the traffic with the queues. Neither stopped the
search.

## Results

`uv run sdlab-ladder submit --strategies structures --cases 313-k8s-two-services --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-313-r1 --every-variant`, then
`uv run sdlab-ladder job 327 --wait` (2026-10-22, at 5dca817, on the Mac):

| variant | job 327 | parts | complexity (truth 13) | discovery |
|---|---|---|---|---|
| none-short | **PASS** | 6/6, all 0.0% | 13 | 5.6 s |
| none-long | **PASS** | 6/6, all 0.0% | 13 | 76.9 s |
| counts-short | **PASS** | 6/6, at most 0.7% | 13 | 4.9 s |
| counts-long | **PASS** | 6/6, at most 0.2% | 13 | 41.5 s |

The main line's stored results at d0a995c (`sdlab-ladder show 313 --strategy structures --variant V`) agree. They
give exactly the truth's equations, and the call is written as the link `outside -> catalog_queue = 0.3 *
frontend_inflight`, not as a move. 5dca817 changed only the scorer's injection handling. 313 has no injections,
so that change cannot affect these results.

## Diagnosis

`uv run sdlab-ladder diff 313 --summary --strategies structures --variants none-short,none-long,counts-short,counts-long`:
4 results (4 pass), 0 diff lines. There was nothing to fix.

## Fixes kept

None. The declared-boundary handling is enough for this rung's new mechanism. On 313, `catalog_queue: {in:
estimate}` allows only an outside inflow, so the cross-service call is fitted as that side's link and the same-unit
move is never offered. The fixes from 307-312 (floor, controller, counted, room, hidden-delay) all stay inactive
here: the model has 6 flows and 13 numbers.

## Risks

- No regression run, following the plan.
- none-long takes 77 s against a 1800 s timeout, so the post-passes cost little on a linear case.
