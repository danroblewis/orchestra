# 312 (k8s-cluster-autoscaler): structures, round 2

**Status (2026-10-22, agent structures-r2-312):** structures already passes every variant of 312 it can pass,
and I made no code change this round. none-short **PASS 28/28**. none-long fails at **27/28**. Its one miss is
the scorer's handling of announced injections (a harness issue), so no model that writes the counter as a rate
can pass it. counts-short and counts-long fail and are data-limited, so they are not targets. Pool job 317 ran the
structures code from round 1 (b6f2b6e; the job ran at e81d1d2, and nothing in structures, `sdlab/ladder/`,
`sdtruth.py` or the case has changed since b6f2b6e) and reproduced round 1's results on the **Mac** (job 309 ran
on node2). I held the structures lock for this round and released it after this doc's commit.

## Where the numbers come from

`uv run sdlab-ladder submit --strategies structures --cases 312-k8s-cluster-autoscaler --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-r2-312 --every-variant`, then
`uv run sdlab-ladder job 317 --wait` and `job 317 --json` (2026-10-22 13:24-13:31Z):

| variant | achievable? | job 309 (b6f2b6e, round 1, node2) | job 317 (e81d1d2, round 2, Mac) |
|---|---|---|---|
| none-short | yes | **PASS 28/28** | **PASS 28/28**, 141 s |
| none-long | yes, except the counter part (harness) | FAIL 27/28, 569 s | FAIL 27/28, 423 s: only `outside -> oom_kills_total [as a whole]`, 2.018% against 2% |
| counts-short | no: data-limited | FAIL | FAIL 7/25, 100 s |
| counts-long | no: data-limited | FAIL 14/25 | FAIL 14/25, 238 s |

**Achievability.** `uv run sdlab-ladder analyse 312-k8s-cluster-autoscaler --variant V` gives "not analysed" on
every variant: a truth this analysis does not cover on the counts variants, and "hidden stock without noise: exact
if identifiable" on the none variants. So I used the event counts from round 1, which match the precedent for 310
and 311:
- **counts-short:** 3 node joins, 1 removal and 19 kills. With 3 joins, the provisioning delay's relative SE is
  about 58%, against a 10% tolerance.
- **counts-long:** 14 joins and 12 removals, giving relative SEs of about 27% and 29%. The kill table is in the
  310/311 regime (an SE of about 10% at the tolerance; 311-structures.md). Job 317 misses the table by 19.1%.

**The none-long miss is the harness's.** The scorer reads the truth's `flow(oom_killed)` from the engine's recorded
counters, and those are computed after the announced node-failure injections (t 706 and 1282: ready - 3). It
evaluates a found flow on `score._levels_at`, which does not add those injections. A found model cannot read
`flow(id)` (`sim._ExprRate` reads it as 0), so it must write the counter as a rate, `ready x table(mem)`. The
truth's own equations, with the counter written that way, fail the same part at 2.02% (milp, engine_forms,
kalman_lna and structures all showed this in round 1). The fix belongs to the harness owner: `_levels_at`, or the
whole-flow comparison, should add the announced injections to the step-start states, as `rows._data` and the
engine do. Under rule 5 the before/after statuses must be reported, because that change turns a fail into a pass
for every top-5 strategy on 312 none-long. Once it lands, structures' none-long answer passes as it stands: every
other part has 0.0% error, and the nodes and delay flows are algebraically the truth's:
- the removal `max(0, min(0.05 nodes - 0.025 ready - 0.025 pending, 0.05 nodes - 0.1))` is
  `0.05 max(0, nodes - max(2, (ready + pending) / 2))`;
- the order `max(0, 0.075 pending - 0.075 max(0, 4 nodes - ready))` is the truth's provisioning inflow;
- the hidden stock `delay_nodes` is credited as the truth's provisioning stage (`ok outside -> (hidden) -> nodes,
  delay 2`), and `h_mem` is matched to the truth's leak (R^2 1.0000).

## Diagnosis this round

`diff 312-k8s-cluster-autoscaler --strategy structures --variant V` for each variant, plus `diff --summary`,
`show` and `analyse`:
- none-short: `diff` gives no difference.
- none-long: `diff` gives no difference. The only wrong part is the counter, which is a scoring artifact (above).
  The run took 423 s on the Mac against a case timeout of 1800 s.
- counts-short and counts-long: not targets. I recorded what I saw for the later all-variants pass, without
  changing anything:
  - counts-long keeps a junk co-flow, `pending -> ready = 0.2536 pending; uses 6.81 inflight per unit`.
    `moves.coflows` (round 1's coflow-earn) keeps a draw when the BIC on the drawn stock's row pays for it. On
    Poisson data, inflight's row apparently does pay for this draw. The draw then blocks every pod-row stage, the
    same failure that round-1 fix 3 removed on the none variants. That leaves `outside -> pending` wrong (114%
    off), `pending -> ready` 56% off, and no hidden delay stage written. A likely fix for that pass: weigh a draw
    on its own stock's row and on the drawing flow's row together, with each row weighted by its noise, or try
    the row search with the draw dropped and keep whichever wins on both rows.
  - The mem drain is too low on both counts variants (0.10 and 0.26 against 0.5). This is the errors-in-variables
    attenuation that the coordinator's 310 note names (kubernetes-ladder.md, "310 after round 1").

## Fixes kept

None this round. Round 1's nine fixes (312-structures.md: min-form rare regime, row-rebuild moves, coflow-earn,
room stand-in replacement, counted stand-in and free knots, hidden-delay stage, subterm columns, goal-floor gap,
guards) are the whole 312 catalogue for structures. Job 317 confirms that they reproduce on the Mac.

## Risks and what is not done

- No regression run, following the plan. Round 1's risks still stand: room.py's untrimmed objective and plain-move
  replacement against 310 and 311, capmin's smaller share, and moves.py on cases with two or more far-off rows.
- The counts-long co-flow and the mem drain are recorded above for the all-variants phase but not fixed.
- Harness (reported, not changed): the scorer ignores announced injections in the whole-flow comparison.
