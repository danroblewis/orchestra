# 310 (k8s-memory-oom): structures, round 2

**Status (2026-10-22, agent structures-310-r2): structures passes every achievable variant of 310.** none-short and
none-long PASS 26/26 at 824f241 (pool job 292, both on **node2**), and they did so at de2b09c too (job 290, both on
the Mac). counts-short and counts-long fail and are data-limited, so they are not targets. One fix was kept: a
counter is no longer a reader in hidden.py. I held the structures lock for the work and released it after the commit.

Round 1 of this rung is in `310-structures.md`.

## Where the numbers come from

`uv run sdlab-ladder submit --strategies structures --cases 310-k8s-memory-oom --variants
none-short,none-long,counts-short,counts-long --priority 400 --by structures-310-r2 --check-tree strategies
--every-variant`, then `uv run sdlab-ladder job N --json` (status, parts, machine, seconds):

| variant | achievable? | job 287 (498c81d, round 1) | job 290 (de2b09c, structures unchanged) | job 292 (824f241, this fix) |
|---|---|---|---|---|
| none-short | yes | PASS 26/26, Mac | PASS 26/26, Mac, 113 s | **PASS 26/26**, node2, 163 s |
| none-long | yes | PASS 26/26, Mac | PASS 26/26, Mac, 277 s | **PASS 26/26**, node2, 374 s |
| counts-short | no: data-limited | FAIL 12/23 | FAIL 12/23, Mac | FAIL 11/23, node2 |
| counts-long | no: data-limited | FAIL 9/23 | FAIL 9/23, Mac | FAIL 7/23, node2 |

`analyse 310-k8s-memory-oom` still says "not analysed: a truth this analysis does not cover" (and on none-short its
z3 report fails to import, a harness issue). I used the achievability verdicts that four strategies' agents reached
on their own (310-kalman_lna.md, 310-milp.md, 310-combined2.md, 310-structures.md):

- counts-short: 3 kill steps (6 kills) in 300 steps, so the kill rate's relative SE is about 40% against the 10%
  tolerance. It also carries 309's retries split, which `analyse 309 --variant counts-short` finds DATA-LIMITED.
- counts-long: 91 kills give a relative SE of about 10.5% against 10%. With the truth's own knots given and only the
  heights fitted (Poisson ML), the kill flow's error is 9.2% (milp's `m310/oracle_tab.py`), so a method that also has
  to find the knots cannot be expected to get under 10%. The 309 sub-structure is DATA-LIMITED there too (p 0.25).

## What round 2 checked

- **Machine dependence (round 1's risk).** Job 286 (7e7ed5c) failed none-long on node2 (20/26) because node2's
  time-capped search lost `pending -> ready`. 498c81d's fix, the counted move judged with its rows repaired, had been
  confirmed only on the Mac (job 287). Job 292 ran both none variants on node2 and both pass, so the fix carries to
  node2.
- **The junk counter term.** On none-short, round 1 wrote `outside -> mem = 75.49 + 1.00004 x inflight / max(1,
  ready) - 0.042 x oom_kills_total + 0.49997 x h_mem`. The counter term was within tolerance on the run. But a
  counter's running total only grows, so off the run the term keeps growing and is not robust. This was a method
  fault, and it is fixed below.

## Fix kept

| type | mechanism | commit | where | how another strategy adopts it |
|---|---|---|---|---|
| counter-not-a-reader | hidden.py's level columns (the library a row's hidden-integrator search picks from) leave out counters (stocks announced `final`), as its per-unit ratio columns already did. A running total that only grows is a trend standing in for a misfit, not a reader. Now none-short's mem inflow is `74.93 + 1.00007 x inflight / max(1, ready) + 0.49990 x h_mem` (the truth: `75 + inflight / max(1, ready) + 0.5 x leak`), and none-long's is unchanged (`75.03 + 0.99974 x ... + 0.50007 x h_mem`). | 824f241 | `structures/hidden.py` (`levels_cols`) | in any row search that offers measured levels as columns (milp `hidden.py`, combined2 `hiddenrow.py`, repair stages), drop stocks with `final: true` from the readers. Keep them as targets of their own counted rows. |

## Risks and what is not done

- counts-short went from 12 to 11/23 and counts-long from 9 to 7/23 between jobs 290 (Mac) and 292 (node2). Both
  are data-limited, and structures' search has a wall-clock cap, so the machine changes its answer. I did not
  separate that effect from the fix's.
- There has been no regression run, per the plan of finishing the current rung first. The fix only removes columns,
  so where a true rate reads a counter, hidden.py can no longer write that rate. No ladder case so far has such a
  rate.
- Still proposed from round 1 (not made): eiv-table (refit counted.py's table by errors in variables on counts), and
  the counter-censoring guard in the vendored censored candidate.
