# 314 (k8s-chain-of-three): milp, round 1

Status (2026-10-22, code 4f92f82, the `sdlab` HEAD; milp's package unchanged since 67c8919; pool job 332, all four
items on node2): **all four variants pass 9/9. No fix was needed.**

| variant      | achievable? (`analyse`) | round 1 (4f92f82, job 332) |
|--------------|-------------------------|----------------------------|
| none-short   | yes (p 1.000 per part)  | **PASS 9/9** (12.1 s)      |
| none-long    | yes (p 1.000)           | **PASS 9/9** (32.8 s)      |
| counts-short | yes (p 1.000)           | **PASS 9/9** (69.8 s)      |
| counts-long  | yes (p 1.000)           | **PASS 9/9** (224.4 s)     |

Commands: `uv run sdlab-ladder job 332`, `uv run sdlab-ladder diff 314-k8s-chain-of-three --strategy milp --variant V`
(each variant: "none", 9 unchanged), `uv run sdlab-ladder show 314-k8s-chain-of-three --strategy milp --variant counts-long`.

## What milp finds

On every variant the truth's nine flows and nothing more (complexity 19 vs 19, 1.00x): three queue -> inflight ->
responses_total chains as moves, `outside -> frontend_queue = 1 x traffic` (the declared input, fixed), and the two
calls as **links** on the declared estimated inflows, `outside -> catalog_queue = 0.2998 x frontend_inflight` and
`outside -> pricing_queue = 0.4005 x catalog_inflight` (counts-long), with no two-hop link from frontend straight to
pricing. counts-long numbers: 0.5991, 0.501, 0.5985, 0.5006, 0.6987, 0.5981 (all within 0.3%).

The rung's common failure across the other strategies (`diff 314-k8s-chain-of-three --summary`: 64 of 92 failing
cells) is the call written as a move `frontend_inflight -> catalog_queue` (invented) instead of the declared outside
link. milp does not make it: the boundary admits only an outside inflow on catalog_queue and pricing_queue, and milp's
program offers outside flows only where declared (the 309-311 boundary work), so a move between those stocks has to
pay for itself against the link and does not.

## Fixes kept

None. The 313 behaviour (calls as links on declared estimated inflows) carries to a third service unchanged.

## For the regression run

Nothing new to check from this rung: milp's code is the same as at 313 (job 325, 4/4 pass).
