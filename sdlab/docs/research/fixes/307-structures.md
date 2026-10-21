# 307 (k8s-cpu-usage): structures, the noise-free and counts variants

**Status:** diagnosed, **not fixed**: 2026-10-21, agent structures-307-agent. `sh scripts/strategy-lock.sh acquire structures ...`
returned exit 1 because k8s-307-C1 holds the structures lock, together with all 44 strategies' locks, since 12:15 (59 min, under the 3 h stale limit). Rule 12 then says
edit something else, so I changed no strategy code and submitted no pool job. Everything below was read-only or run in-process
(1 item each, nothing stored), on HEAD 1b31e14.

## Where structures stands (store, code 1b31e14)

`uv run sdlab-ladder show 307 --strategy structures --variant V`:

| variant | status | what is wrong |
|---|---|---|
| none-short | EQUIVALENT | cpu's inflow written as an expression `1.25 inflight + 20 ready + -1.07e-07 * min(queue, 66.67 ready)`, so both cpu links score as missing and the expression scores as a spurious whole flow |
| none-long | PASS | (an extra `-5.5e-07 traffic` term merged into responses_total: harmless) |
| counts-short | FAIL | spurious co-flow `retries -> queue uses 0.1995 inflight per unit` (11.6 per step); also a parallel `queue -> inflight = 0.012 queue` beside the MIN (an extra part, not the cause of the fail) |
| counts-long | PASS | |

## Diagnosis (rule 4b)

1. **none-short: method fault (a numerical-zero term).** The data are exact. The capmin series `capmin__queue__ready` gets a
   coefficient of -1.07e-7 in cpu's merged inflow (from combined's path; capmin says only the limited flow's rows may read it).
   `capmin.restore` then writes that coefficient back as a MIN, so the flow becomes an `expr`. Probe
   (scratchpad prune.py, in-process): the same found flows with every term whose largest contribution over the run is < 1e-6 of the
   flow's largest term dropped, and an expression of plain terms written back as `linear`: equivalent -> **pass**.
2. **counts-short: method fault (an unearned co-flow).** `analyse` calls the cell data-limited only for the retries split (p 0.30),
   and the found split is inside tolerance (both parts "ok"). The fail is the co-flow: it comes from combined's chosen `lna`
   candidate (atom `move retries->queue driver retries uses [[inflight, 0.1995]]`). Probe (scratchpad cs.py): the same flows with the
   co-flow's `uses` removed and no refit: fail -> **pass**. Removing the parallel 0.012 queue -> inflight as well also passes.

## Fixes proposed (not made: lock held)

| type | mechanism | where in structures | how another strategy adopts it |
|---|---|---|---|
| zero-term-prune | before writing, drop every term (k*V or a*MIN) whose largest contribution over the run is < 1e-6 of the flow's largest term, and write an expression left with plain terms as `linear` | the last step of `__init__.identify` after `_capmin.restore` (or inside `capmin._expr`: a MIN term with negligible size is dropped, not written) | the same post-pass over its final flows; every copy of capmin.py has the same `_expr` |
| capmin-readers | enforce `capmin.readers`: a rate that is not on the limited flow's pair does not read the offered series (drop the term, then refit that flow's row) | `capmin.restore` | identical capmin.py copies in 43 packages |
| coflow-earn | a co-flow `uses` term (and a linear move on the same pair as a MIN move) is kept only if dropping it and refitting costs more than its price on the judge's likelihood (BIC: price log n per number) | the lna atom selection in combined's lna candidate, or a post-pass on the final result | a post-pass over any strategy's co-flows, the judge being its own likelihood |

The next round should apply these once the structures lock is released, then run
`uv run sdlab-ladder submit --strategies structures --cases 307 --variants none-short,none-long,counts-short,counts-long --priority 400 --by <agent>`.
