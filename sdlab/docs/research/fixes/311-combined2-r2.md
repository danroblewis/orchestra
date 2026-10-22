# 311 (k8s-node-pool), combined2, round 2 check (2026-10-22, agent combined2-311-r2)

**Status: combined2 passes every achievable variant of 311. No code change this round; no fix added.**
none-short and none-long PASS 26/26 at afb19cf (pool job 301, results #386965 / #386967). counts-short and
counts-long fail and stay **data-limited on the OOM move** (re-measured at HEAD c7352bb, below), so they are not targets.

| variant | achievable? | result (afb19cf, job 301) |
|---|---|---|
| none-short | yes | **PASS 26/26** (#386965) |
| none-long | yes | **PASS 26/26** (#386967) |
| counts-short | no: OOM move 15.4% off at the free-knot Poisson ML optimum (tol. 10%) | FAIL: 2 removed, 4 added, 5 values wrong (#386964) |
| counts-long | no: OOM move 17.2% off at the free-knot Poisson ML optimum | FAIL: 4 values wrong (#386966) |

The results are current: `runner.plan(['311-k8s-node-pool'], runner.select_strategies('combined2')[0], [the four
variants], every_variant=True)` returns no items at HEAD c7352bb (the scoring changes 198baf2, hidden-stock credit and
"fits", and bab9156, proven equivalence, are ancestors of afb19cf, so the stored statuses already use them). No pool job
was submitted: nothing was stale and no code changed. Commands: `uv run sdlab-ladder diff 311-k8s-node-pool --strategy
combined2 --variant V` (read 2026-10-22).

## The data limit, re-measured (rule 4b)

`analyse` gives "not analysed" on every 311 variant (a hidden stock and a table), so the bound is by hand: round 1's
scratch `c2_311/freeknot.py` re-run at HEAD (the truth's model kept exact except the kill table, fitted to the measured
`diff(oom_kills_total)` by Poisson maximum likelihood, scored with `score.equations`). Same numbers as round 1:

| variant | kill steps / kills | free knots | capped free knots | true knots given |
|---|---|---|---|---|
| counts-short | 4 / 9 | 15.4% (-log L 3.77) | 15.4% | 16.4% (-log L 3.92) |
| counts-long | 46 / 88 | 17.2% (-log L 52.99) | 17.2% | 6.5% (-log L 53.79) |

The free-knot tables are more likely than the true-knot ones on both, and only the truth's own knots (which no method
has) pass on counts-long. The OOM move cannot be placed within 10% from these data, so neither counts variant is a
target (the proxy's 310 rule: data-limited by a measured bound).

## Left for the regression / noise rounds

Unchanged from `311-combined2.md`, "What is left": counts-short got worse at afb19cf (weak headroom limits offered first);
a price on the headroom limit's extra number is the next step there. The regression risks (a)-(e) listed there are for the
306-310 regression run.
