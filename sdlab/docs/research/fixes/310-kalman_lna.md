# 310 (k8s-memory-oom): kalman_lna

Status (2026-10-21, 23:45 PDT, round 2): **none-short and none-long PASS 26/26 at 423dbb6 (job 280)**, with the leak
written as the model's own hidden stock and matched to the truth's (`mem_hidden = 0.081 + 1.000 x leak`, R^2 1.0000
on none-short). Both counts variants fail and are data-limited (below), so they are not targets. The rung's achievable
variants all pass for kalman_lna.

Why round 2 was needed: the scorer change 198baf2 (the user, 2026-10-21) credits a found model's own hidden stock
and calls a schedule standing in for hidden state "fits, not robust". It turned c058aae's two passes into FITS (30 and
200 time blocks for the leak; `uv run sdlab-ladder show 310-k8s-memory-oom --strategy kalman_lna --variant none-short`
at f9e24d4: FITS 23/23, complexity 78 vs the truth's 66; none-long FITS, complexity 249, 3.77x).

Where the numbers come from: `uv run sdlab-ladder submit --strategies kalman_lna --cases 310-k8s-memory-oom --variants
none-short,none-long,counts-short,counts-long --priority 400 --by k8s-310-kalman_lna-r1 --check-tree strategies` (job
280 at 423dbb6, node2/Mac pool; `--check-tree strategies` because another agent's uncommitted `sdlab/ladder/api.py`),
then `uv run sdlab-ladder show 310-k8s-memory-oom --strategy kalman_lna --variant V` and `sdlab-ladder job 280 --json`:

| variant      | achievable?                 | f9e24d4 (after 198baf2) | round 2 (job 280, 423dbb6) | complexity (truth 66) | discovery |
|--------------|-----------------------------|-------------------------|----------------------------|-----------------------|-----------|
| none-short   | yes                         | FITS 23/23              | **PASS 26/26**             | 78 -> 58              | 80.1 s    |
| none-long    | yes                         | FITS 23/23              | **PASS 26/26**             | 249 -> 59             | 321.7 s   |
| counts-short | no: data-limited            | FAIL 9/23               | FAIL 9/23                  | 48                    | 118.5 s   |
| counts-long  | no: data-limited            | FAIL 11/23              | FAIL 11/23                 | 66                    | 368.9 s   |

(26 parts once the hidden stock is matched: the truth's leak inflow and leak drain, with its table, become parts.)

Found on none-short (job 280): `outside -> mem = 74.960 + 0.49999 x mem_hidden + 1.0000 x inflight / max(1, ready)`,
`outside -> mem_hidden = 1`, `mem_hidden -> outside = 0.009372 x mem_hidden` with an effect table on mem from 480.00
(the truth: `0.5 x (150 + leak + 2 x inflight / max(1, ready))`, leak +1 a step, `- leak x table(mem)`, 0.3/32 =
0.009375 per MiB above 480). The OOM move, its counter and the 309 rows are as in round 1.

### Achievability (analyse still says "not analysed: a truth this analysis does not cover")

- **counts-short: data-limited.** 6 kill events in 300 steps, so a fitted kill rate has a relative SE of about
  1/sqrt(6), roughly 40%, against a 10% tolerance. It also contains 309's retries split and pending gap, which `analyse
  309-k8s-pod-startup --variant counts-short` finds DATA-LIMITED (p 0.010).
- **counts-long: data-limited.** 91 kill events: the kill rate's relative SE alone is about 10.5%, against 10%. The same
  309 sub-structure is DATA-LIMITED there too (`analyse 309-k8s-pod-startup --variant counts-long`: p 0.25; retries ->
  outside bound SE 0.0444 vs 0.04 allowed). Round-2 trace (`rows.revise` with `rows_trace` on job 280's answer): the
  derived search takes `retries x max(0, mem - 484.7)` and `queue x max(0, mem - 491)` for the kill column (Poisson
  scatter in ready makes its own switch column no better). The ready row reads no pending term, and the rebuild is
  refused, so the base answer is kept. Recorded, not pursued: it is not a target under the standing rule.

## Round 2 fix kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| hidden-stock write-out (replaces "hidden drive written as a schedule") | When a row's best fit reads the hidden integrator (`h' = 1 - a s h`, derived.py 3), the integrator's own numbers are kept: drain rate a, the switch s (1 or a derived switch `max(0, Y - theta)`), and the row's coefficients on the two response columns and the constant (`p0 h0 + p1 h1 + p2 = p1 H + p2`, H's start p0 / p1). It is written as a hidden stock `<S>_hidden`. Its flows are `outside -> H = 1` and `H -> outside = a x H`, the switch as an effect table on Y (0 at theta, rising 1 per unit). The row reads `m p1 H + m p2 + ...`, where m is the jointly refitted coefficient. Its levels on the run go out as `inferred_levels` (aligned with t), so the judge and the scorer's matcher start it where the fit does. The rebuild's BIC check reads H's levels in the states. No schedule is written. | 423dbb6 | In a strategy that already finds a hidden integrator or other hidden state: write it as a stock with its own constant inflow and a self-proportional drain (with an effect table for a switch), let the reading flow name it, and return `inferred_levels`. The scorer (hidden_match.py) matches it to the truth's up to scale and offset. For kalman_lna's code: `_hidden` (the `integrator` record), `_hidden_name`, `_hidden_flows`, the `hid` branch of `_flow`, and `hidden_lv` in `revise` (rows.py). |

Checks: `uv run pytest tests/test_kalman_lna_rows.py tests/test_kalman_lna_derived.py tests/test_isolation.py
tests/test_kalman_lna_tracker.py tests/test_kalman_lna_boundary.py tests/test_ladder_kalman_lna.py`: 21 pass.
`test_kalman_lna_derived.py` now checks that the synthetic case's hidden drive is a stock (`mem_hidden`: inflow 1,
drain 0.02 on the mem switch at 300, levels returned), not a schedule.

Risks: regressions are still untested (the plan says once, later). The schedule fallback (`_schedule`) is still used
where the integrator does not win, and the scorer calls that "fits", not a pass. Any earlier rung where rows.py
picks the integrator now gets a hidden stock instead of time blocks.

---

# Round 1 (c058aae, before the scorer change 198baf2)

Status (2026-10-21, 17:30 PDT): **none-short and none-long pass at c058aaea (job 269), 23/23 parts each. Both counts
variants fail: counts-short 9/23, counts-long 7/23.** I judged counts-short data-limited. counts-long is at best
borderline, and part of its failure is the method's fault (below).

Where the numbers come from: `uv run sdlab-ladder submit --strategies kalman_lna --cases 310-k8s-memory-oom --variants
none-short,none-long,counts-short,counts-long --priority 400 --by k8s-310-kalman_lna` (job 266 at 065afa3, job 269 at
c058aaea, Mac pool), then `uv run sdlab-ladder show 310-k8s-memory-oom --strategy kalman_lna --variant V`:

| variant      | analyse       | before (a660e75) | after (job 269, c058aaea) | discovery |
|--------------|---------------|------------------|---------------------------|-----------|
| none-short   | not analysed* | FAIL 13/23       | **PASS 23/23**            | 28.1 s    |
| none-long    | not analysed* | FAIL 12/23       | **PASS 23/23**            | 199.3 s   |
| counts-short | not analysed* | FAIL 9/23        | FAIL 9/23                 | 73.8 s    |
| counts-long  | not analysed* | FAIL 11/23       | FAIL 7/23                 | 530.8 s   |

\* `sdlab-ladder analyse` says "a truth this analysis does not cover" (a hidden stock read through an effect table),
so I judged which variants are achievable myself (below).

## Diagnosis (rule 4b)

Three rates are outside what the strategy could write before this change.

1. **OOM kills: `ready -> pending = ready x table(mem)`**, counted by `oom_kills_total`. In the data mem stays
   below 512 (none-short: max 483.5, 21 kill steps), so only the table's first segment acts: `0.009375 x ready x
   max(0, mem - 480)`. The answer drew a constant into `oom_kills_total`. The 309 floored rows of pending and ready
   then missed by this term, so they were not rebuilt. **A method fault.**
2. **mem's inflow: `0.5 x (150 + leak + 2 x inflight / max(1, ready))`**. It is a rate per pod (a ratio) plus a
   hidden stock. The leak gains 1 a step and loses `leak x table(mem)`, so it falls sharply at each OOM step. The
   answer read mem's change off queue, retries and ready. **A method fault.** With the true drain rate (0.009375 on
   the switch `max(0, mem - 480)`), mem's row on [mem, inflight / max(1, ready), the integrator's two columns, 1] is
   exact (SSE 4e-6, scratch probe).
3. **The scorer and a found hidden stock.** It compares mem's inflow as a whole, as its amount on the truth's
   states. A found flow that reads the strategy's own hidden stock raises `ExprError: not a stock, input or
   auxiliary`. I checked this with the truth's flows after renaming `leak` (scratch `sc.py`). So the hidden
   integrator can only be written out as a time schedule. The truth with the leak swapped for a schedule of
   10-step or 25-step block means passes, and one of 50-step means fails at 3.2% (scratch `sc2.py`).
   **This is a harness limit (reported, not changed).**

- **counts-short: data-limited.** It has 6 kill events in 300 steps (the case's counts-short levels). The OOM move
  and its effect are compared as amounts within 10% rms. A rate fitted to 6 Poisson events has a relative SE of
  about 1/sqrt(6), roughly 40%. The retries split is also the one 309 found data-limited (p 0.010). This variant
  is not a target.
- **counts-long: borderline.** It has 91 kill events, so the rate's relative SE alone is about 10.5%, against a
  10% tolerance. mem reaches 682, past the table's 512 and 560 corners, where the single switch column over-reads
  the kill fraction. The rest of its failure is the method's: the answer at c058aaea has cpu's links wrong (1.665
  x inflight, 13.26 x ready) and a dense pending row. Discovery took 517-531 s on a loaded pool, against 306 s
  before. The pod and mem rows were not rebuilt, because the gate did not pass.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| derived-columns (switch, ratio) | `derived.py` + `rows.py`. After the first pass of rows, each row's residual is scored against new columns. One kind is the switch `X x max(0, Y - theta)` (or `max(0, theta - Y)`): every pair of measured stocks, theta on a 40-quantile grid, then golden section. The other is the per-unit rate `X / max(1, Y)`. Each candidate is scored only on what it adds beyond the row's current span: its readers, its floored term and its schedule, orthonormalised. The best column joins the readers when it gains PRICE log T in BIC, net of its numbers, on some row. Up to 3 rounds; the rows are refitted after each. A switch's theta is then refitted on every row that reads it, by golden section with the other terms held. Floored terms read levels only, never derived columns. | 065afa3 | Copy `kalman_lna/derived.py` and the `rows.py` of c058aaea (rows.py at 309 plus these hooks) and call `rows.revise` as at 309 |
| derived-move | In `_pair`, a derived column whose base X loses it in X's row, and that a stock T in X's unit gains, is a move X -> T. When two stocks gain it, the one that is not a counter (final) takes the move; the counter gets an outside link with the same rate. A leftover under TOL_MOVE of the pool is rounding. A flow that is just k x one switch column is written as the engine's own form: rate `k x X` with an effect table on Y (0 at theta, rising 1 per unit over 10 x Y's range). The scorer then sees the move's [X] part and the effect part. | 065afa3 | as above (`_pair`, `_effect_form`, `_finish` in rows.py) |
| hidden-integrator row | A row on an inflow side that its readers leave 100 x above rounding may read a hidden integrator: `h' = 1 - a s h` with s = 1 or a derived switch, giving two columns (response to h0 and to the inflow) plus a constant. a is on a log grid and then refined by golden section; the readers are chosen on what the integrator leaves (a fixed-effects projection). As a fallback, a continuous piecewise-linear schedule with a knot every 10/20/30/50/100 steps. Either is kept only where it beats the plain row by BIC + PRICE log T. It is written out as byTime segments of 10 steps, each at the drive's mean, because the scorer cannot read a found hidden stock. Because the per-unit rate and the integrator only fit together, a joint scan scores every ratio column with the row's readers, its own level and the best integrator. | 065afa3, c058aaea | as above (`_hidden`, `_schedule`, `_ratio_hidden` in rows.py) |

Found on 310 none-short (job 269): `ready -> pending = 0.009375 x ready` with an effect table on mem from 480.00,
`outside -> oom_kills_total` the same. The 309 floored gap and surplus are unchanged (`outside -> pending = desired -
pending - ready`, `ready -> outside = ready - desired`). `outside -> mem = c_block + 1.0000 x inflight / max(1, ready)`
in 30 blocks, and `mem -> outside = 0.49999 x mem`.

Checks: `uv run pytest tests/test_kalman_lna_rows.py tests/test_kalman_lna_derived.py tests/test_isolation.py
tests/test_kalman_lna_tracker.py tests/test_kalman_lna_boundary.py tests/test_ladder_kalman_lna.py`: 19 pass.
`tests/test_kalman_lna_derived.py` is a synthetic pods/mem case with a different threshold, rates and hidden
drain (not the ladder case). It checks that the switch move, its counter, the ratio and the hidden drive are found.

Risks and what is not done:
- Under the plan, I ran no regression on earlier rungs. The derived search and the hidden integrator run on every
  answer rows.py sees. Spurious switch columns appeared on the synthetic case before the joint scan was fixed, so
  the later full regression run is where to look for side effects (extra flows with effect tables, schedules).
- Harness: a found model's own hidden stock cannot be scored in a whole flow (ExprError). Supporting that would
  let the integrator be written as a stock rather than a schedule. This needs the harness owner (rule 12).
- counts-long: a Poisson-weighted fit of the switch, and a two-corner table (a second switch column on the same
  pair), may make it achievable. So may a faster base: its answer was cut short on a loaded pool.
