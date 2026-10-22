# 310 (k8s-memory-oom): milp

Status (2026-10-22, round 1 after the scorer credits a found hidden stock, 198baf2): **none-short and none-long
pass 26/26** (pool job 281, cd7383f; again in job 284, 9bbd66a). counts-short and counts-long still fail, and both are **data-limited**
(below), so they are not targets. All 4 variants are achievable or not as follows:

| variant      | achievable?                                    | before (job 273, 573c5a5) | job 281 (cd7383f)                  | job 284 (9bbd66a) |
|--------------|------------------------------------------------|---------------------------|------------------------------------|-------------------|
| none-short   | yes                                            | FAIL 21/23, 83 s (mem row) | **PASS 26/26**, 81 s, mac          | **PASS 26/26**, 188 s, node2 |
| none-long    | yes                                            | FAIL 21/23, 238 s (mem row) | **PASS 26/26**, 246 s, mac        | **PASS 26/26**, 1196 s, node2 (limit 1800 s since 7aa4efb) |
| counts-short | no: 3 kill steps (6 kills), kill SE ~40%       | FAIL 15/23, 143 s         | FAIL 15/23, 141 s                  | FAIL 15/23, 261 s, node2 |
| counts-long  | no: kill flow's best error 9.2% with the true knots given (tolerance 10%) | FAIL 20/23, 770 s | FAIL 20/23, 800 s | FAIL 20/23, 893 s, node2 (4 spurious, was 6) |

Commands: `uv run sdlab-ladder job 281`, `uv run sdlab-ladder job 284`, `uv run sdlab-ladder show 310-k8s-memory-oom --strategy milp --variant V`.
`analyse` does not cover this truth ("not analysed": effect tables and a hidden stock), so the data limits below
were checked by hand.

The found model on none-short (job 281), the mem block:

```
outside -> mem_hidden = 1
mem_hidden -> outside = 1 x mem_hidden x table(mem)      (the kill share's table, polished on mem's row)
outside -> mem        = 75.4959 + 0.499981 mem_hidden + 1.00002 inflight / max(1, ready)
mem -> outside        = 0.499987 mem
```

The scorer matched `mem_hidden` to the truth's `leak` (level = -0.9585 + 1 x leak, R^2 1.0000; none-long 0 + 0.9961 x leak).

## Diagnosis (rule 4b)

- **The mem row was a method fault, now fixed.** The truth's inflow is `0.5 (150 + leak + 2 inflight / max(1, ready))`,
  with `leak' = 1 - leak x table(mem)` (the same table as the OOM kills). milp wrote it as a 4-segment schedule over
  traffic, retries, queue and the counters, and bent the drain to 0.39 (truth 0.5). Since 198baf2 the scorer credits a
  found hidden stock, and a schedule standing in for one is "fits, not robust". On none data, the row less its drain is
  exactly `c + g H + k inflight / max(1, ready)` once H is stepped with the kill share as its drain, so it is identifiable.
- **The borrowed drain table must be polished.** The kill table milp finds is 1% off in slope (0.297 at 512 for 0.3).
  With it, the scorer's match fitted an offset of 2.48, and `leak -> outside` got a spurious constant (25/26 with one
  spurious part). Polishing the drain's table on mem's own row (scale and level shift) makes the offset about 0:
  `hidden_match._fit_start` with the found table gives alpha 2.476, and with the slope 1.05% higher it gives -0.0125
  (scratchpad `m310/alpha.py`).
- **counts-short is data-limited** (round-1 doc): 3 kill steps, kill amount SE about 1/sqrt(6), against 10%. Also, the
  mem row's misfit is within the Poisson scatter of its gross flow (rss 124k against 89k noise, 300 steps), and the
  hidden model explains only 36% of the excess, so the step leaves it alone.
- **counts-long is data-limited on the kill flow.** There are 44 kill steps (91 kills). Above mem 512 there are 5 steps
  with 17 kills, and that is where the whole-flow comparison on the run's states weighs most (mem reaches 682 there,
  where the truth's table flattens at 0.8). With the truth's knots given (480, 512, 560, 5000) and only the heights
  fitted by Poisson ML on the measured kills, the kill flow's error is **9.2%** against the 10% tolerance (scratchpad
  `m310/oracle_tab.py`: the truth's flows with that table, `score.equations`). A method that must also find the knots
  cannot be expected to get under 10%. engine_forms' agent finds the same (Fisher SE 0.20 with the truth's knots,
  491632e). The other counts-long misses (spurious `outside -> cpu` terms, a `retries -> queue` MIN, `queue ->
  responses_total`) are the 309 sub-structure on counts-long, which is data-limited (309 counts-long, `analyse` p 0.25).

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| hidden-integrator | `milp/hidden.py`, `refine(flows, stocks, run, opts, skip)`, run last in `identify` (after the output-error refit). For each measured stock S with a declared "estimate" inflow side: the target is S's change less every flow on S other than its own outside flows. A hidden stock H is filled at 1 a step (its scale is carried by the inflow's coefficient) and drains by a per-step fraction E. E is none, a constant (13-point log grid from 1e-4 to 1, then bounded polish), or **the per-unit rate of a flow already in the model whose rate is proportional to its own measured source (with its effects)**, as the leak goes with the killed pods. H is stepped from 0 on the measured levels. The inflow's columns are chosen by BIC forward selection (at most 8, each must lower BIC by 2) over the constant, measured levels, inputs and per-unit ratios `X / max(1, Y)`. S's drain is fitted with them. The same selection without H is a candidate, so H is written only where it beats every model without one. **Kept** when BIC over S's row beats S's current outside flows (every schedule piece's numbers counted) by more than 10 and explains at least half the misfit above the noise floor. **Written** as `outside -> S_hidden` (constant 1), `S_hidden -> outside` (proportional, with the source flow's effects), `outside -> S` (an expression when it reads ratios), `S -> outside`. | cd7383f | Copy `hidden.py` along with milp's `hinge.py` (`_amount`, `_env`, `_resolution`) and `steps.py`. Call it after the strategy's final refit. The strategy must already have the drain's source flow (here the counted OOM move with its table, effects.py). |
| hidden-drain-polish | `hidden._polish`: where H's drain is borrowed from a flow with table effects, the tables are refitted on S's own row by Nelder-Mead over one value scale and one level shift (all the drain's tables together). The inflow's columns are held, then chosen again on the polished H (2 rounds). The hidden drain is its own flow, so its table may differ from the source flow's. | cd7383f | Part of `hidden.py`. Any strategy that borrows a fitted table for a hidden stock should refit it on the row that reads the hidden stock: a 1% slope error was enough to make the scorer's match fit an offset (a spurious constant on the drain). |
| noise-floor share | `hidden.py` measures "explains half the misfit" above the noise: the levels' rounding (`_resolution / sqrt 6`), or for counts the Poisson scatter of what moves through S in a step (sum of the gross amounts of the flows on S). It skips a row only when its misfit is within 1% of that. Two models of one row on the same steps differ by far less than the noise's own spread, so BIC decides above it. | 9bbd66a | A share test (effects.py's SHARE and copies of it in other strategies) on count data should compare with the misfit above the Poisson floor, not the raw misfit. |
| counted-replaces-schedule | `effects._Rows`: a counted-move candidate may replace its counter's declared outside inflow even when the program wrote that inflow as a schedule (byTime). In the comparison the schedule is held at its amounts and charged one number per piece. Only a final counter's inflow qualifies, never a general stock's: the earlier general version (reverted in round 1) admitted proxy effects on mem's stepped inflow. On job 273's counts-long answer the 15-piece counter schedule is replaced (gain 3835), and the kill move's error goes from 99% to 30% (still over 10%: data-limited, above). | 9bbd66a | In a strategy that adds counted moves (combined2/structures `counted.py`, engine_forms `reread.py`): when the counter's inflow is stepped, compare against it at its amounts with its pieces' numbers, instead of refusing the candidate. |

none-long took 1196 s on node2 in job 284 (246 s on the Mac in job 281). That is under the kubernetes limit of 1800 s,
but it is the slowest cell: the program's inflow-step search dominates (round 0's prune budget), not the hidden step
(about 1-7 s locally).

Tested only on 310, per the plan. The hidden step on the stored 307-309 answers of milp (all four variants each, run
locally on the stored flows) adds no hidden stock anywhere. It is not a regression run: the later full regression
should confirm it. Risk: a row whose schedule stands in for a slow drift could get a constant-drain hidden stock where
the truth has none. The without-H candidate and the BIC margin guard against this, but it is untested beyond the ladder.

Tests: `tests/test_milp_hidden.py` (a hidden integrator with a constant drain recovered with its per-unit ratio
column; a row explained by measured columns gets none) and `tests/test_milp_effects.py::test_counted_move_replaces_a_stepped_counter_inflow`
(fails on the code before 9bbd66a).

## Round 0 (before the scorer change, 8ff75a7 and 573c5a5)

The table-effect flows, counted moves, effects in hinge amounts, the move bound, gap-avoid, prune budget and one flow per
declared side are recorded in `docs/research/fix-ledger.md` (milp rows) and in this file's history (`git show 09f2794:sdlab/docs/research/fixes/310-milp.md`).
They took none-short and none-long from 13/23 (and a 900 s timeout) to 21/23, leaving only the mem row, which this round fixes.
