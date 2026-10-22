# 310 (k8s-memory-oom): kalman_lna, round 2 check (2026-10-22, agent kalman-r2-310)

**Status: kalman_lna passes every achievable variant of 310. No code change was needed this round; no fix was added.**
none-short and none-long PASS 26/26 at 423dbb6 (pool job 280); counts-short and counts-long fail and are data-limited,
so they are not targets. The rung passes for kalman_lna.

## What I checked (commands rerunnable at HEAD eb88f3f)

- `uv run sdlab-ladder show 310-k8s-memory-oom --strategy kalman_lna --variant V`:

  | variant | achievable? | result (code 423dbb6, job 280) | discovery |
  |---|---|---|---|
  | none-short | yes | **PASS 26/26** (mem_hidden matched to the leak) | 80.1 s |
  | none-long | yes | **PASS 26/26** | 321.7 s |
  | counts-short | no: data-limited | FAIL 9/23 | 118.5 s |
  | counts-long | no: data-limited | FAIL 11/23 | 368.9 s |

- The results are current: `runner.plan(['310-k8s-memory-oom'], select_strategies('kalman_lna'), [the four variants],
  every_variant=True)` returns no items (case, strategy and score hashes all equal the stored rows'). 423dbb6 is the last
  commit touching `sdlab/discovery/strategies/kalman_lna`; the only harness commits since (8e064d3 diagram naming,
  7aa4efb the 1800 s time limit, a6e6294 the Now page) change no score hash.
- `uv run sdlab-ladder analyse 310-k8s-memory-oom --variant V`: none-* "hidden stock without noise: exact if
  identifiable"; counts-* "not analysed: a truth this analysis does not cover". Achievability of the counts variants is
  therefore judged by the oracle check in `310-combined2.md` (round 2): the truth's own model with only the kill table
  refitted at its **true knots** misses `ready -> pending [ready]` and its effect by 28.7% (counts-short, 6 kills on 3
  steps) and 16.4% (counts-long, 91 kills on 44 steps) against a 10% tolerance with no SE allowance. No method can place
  that part, so neither counts variant is a target (standing rule: a rung passes on its achievable variants).

## Fixes

None new. The fixes that make 310 pass are recorded in `310-kalman_lna.md`: derived columns (switch, ratio),
derived move with an effect table, hidden-integrator row (065afa3, c058aae, b373e39, f9e24d4), and the hidden-stock
write-out (423dbb6), each with how another strategy adopts it.

## Not done

- No pool job: nothing was stale and no code changed, so a re-run would reproduce job 280's cells.
- Regression on earlier rungs is still untested (the plan: once, later).
- counts-long remains open as research only (Poisson-weighted or errors-in-variables table fit, a second table corner
  past 512 MiB); not a target under the oracle above.
