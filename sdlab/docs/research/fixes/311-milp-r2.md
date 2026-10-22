# 311 (k8s-node-pool): milp, round 2

Status (2026-10-22, milp code ec2164b, unchanged this round): **milp passes every achievable variant of 311.**
none-short and none-long pass 26/26 (pool job 297). The results are current at the `sdlab` HEAD:
`uv run sdlab-ladder status --strategies milp` shows `311-k8s-node-pool PPFF` with no stale mark.
counts-short and counts-long fail and are **data-limited** (re-measured below), so they are not targets.
No code was changed this round.

| variant      | achievable?                                                          | result (job 297, ec2164b) |
|--------------|----------------------------------------------------------------------|---------------------------|
| none-short   | yes                                                                  | **PASS 26/26** (223 s) |
| none-long    | yes                                                                  | **PASS 26/26** (679 s) |
| counts-short | no: P(kill flow within 10%) = 0.25 at the bound, knots given         | FAIL 14/23 (204 s) |
| counts-long  | no: P = 0.36 at the bound, knots and the 5000 height given           | FAIL 17/23 (935 s) |

Commands: `uv run sdlab-ladder show 311-k8s-node-pool --strategy milp --variant V`, `uv run sdlab-ladder job 297`.

## The data limit, re-measured (rule 4b)

`analyse 311-k8s-node-pool --variant counts-short|counts-long` gives "not analysed: a truth this analysis does
not cover" (effect table plus a hidden stock). So the bound was recomputed by hand, with the analyse definitions and
the script from 310-milp-r2.md pointed at 311. The truth's table `oom_killed` was checked from the case: knots 0,
480, 512, 560, 5000 with heights 0, 0, 0.3, 0.8, 1. Kills are Poisson about `ready x table(mem)`. The truth's knots
are given and only the heights listed are free. Fisher normal, then a Monte Carlo of the scorer's whole-flow
relative error (20,000 draws, seed 0):

| variant      | kill steps | states with mem > 512 | heights free | median error | P(error <= 10%) |
|--------------|------------|-----------------------|--------------|--------------|-----------------|
| counts-short | 6          | 0                     | 512          | 0.206        | **0.25** |
| counts-short | 6          | 0                     | 512, 560     | 0.205        | 0.26 |
| counts-long  | 84         | 5                     | 512          | 0.065        | 0.69 |
| counts-long  | 84         | 5                     | 512, 560     | 0.125        | **0.36** |

The 560 height has to be read from 5 states, and the knots have to be found too. So both counts variants stay below
0.5 even with that help, which agrees with round 1 (311-milp.md) and the other four strategies' 311 docs.

## Fixes kept

None this round. Round 1's fixes (room-min, counted-move-after-room, gap-side-unblock; 311-milp.md, ec2164b) stand.

## Open (not targets)

- counts-long: the room move is not found in the pool run (`pending -> ready = 0.0404 pending`), even though
  `room.refine` fires on the older stored answer. This was not diagnosed in either round. It matters for the
  later noise round (a Poisson-weighted room comparison, and polish that drops a same-pair plain move by BIC).
- Run time: counts-long took 935 s of the case's 1,800 s.
