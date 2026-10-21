# 310 (k8s-memory-oom): engine_forms on the noise-free and counts variants

**Status:** 0 of 4 pass, and no variant can pass at the moment. Work done 2026-10-21 by agent k8s310-engine_forms, which held the engine_forms lock and released it afterwards.
The fix is commit ec6265e. Pool job 265 ran at ec6265e (`uv run sdlab-ladder job 265`):

| variant | before (a660e75, store) | after (ec6265e, job 265) | what is left |
|---|---|---|---|
| none-short | FAIL 13/23 | FAIL **21/23** | only the mem block (`outside -> mem` as a whole, `mem -> outside [mem]`). The scorer blocks it (see below) |
| none-long | FAIL 10/23 | FAIL **21/23** | the same |
| counts-short | FAIL 9/23 | FAIL 9/23 | data-limited (see below) |
| counts-long | FAIL 11/23 | FAIL 8/23 | reread does not act here. The local run at ec6265e reports `reread: None`. The change comes from the base answer, which is unchanged code. The old result ran on a different worker. The scorer blocks this variant too |

## Diagnosis (rule 4b)

`uv run sdlab-ladder analyse 310-k8s-memory-oom --variant V` gives "not analysed: a truth this analysis does not cover" for all four variants, so there is no Cramér-Rao bound. These checks were run by hand instead (scratchpad `ef310/`):

- **The pods block was a method fault (fixed).** Rung 309's exact re-read stopped working on 310 because the pods rows now carry the OOM kills: `ready -> pending = ready x table(mem)`. No row of ready or pending was a linear part plus one hinge any more. The counter `oom_kills_total` measures those kills exactly, one step at a time.
- **The mem block is blocked by the scorer, not by the data (harness fix needed).** The truth's `outside -> mem = 0.5 (150 + leak + 2 inflight / max(1, ready))` reads the hidden stock `leak`. It is scored "as a whole", by evaluating its amounts on the run's states, and those states include the truth's `leak` level. A found model that rebuilds the leak as its own hidden stock has a different name for it:
  - as an expression, the scorer raises `ExprError("flow allocated reads ['hzz']: not a stock, input or auxiliary")`, so the run becomes an error. This was checked by scoring the truth itself with `leak` renamed (scratchpad `ef310/perfect.py`). The truth with its own name passes.
  - as a linear rate, the hidden level reads as 0, so about half of the inflow goes missing.
  - **A measured-only model cannot pass either.** Without the leak, the best fit of mem's row on measured columns (ratio inflight/ready included) puts mem's drain at -0.007 to -0.17 against the true -0.5 (scratchpad `ef310/memrow.py`).
  - So no honest answer can pass none-short, none-long or counts-long. The harness fix needed: evaluate a found flow that reads the found model's own hidden stock on that stock's simulated level, or leave a truth flow that reads a hidden stock unscored, as LADDER.md already does for a rate that reads a smoothing's hidden stock. Until then, rebuilding the hidden leak in engine_forms would only turn a fail into an error, so it was not attempted.
- **counts-short is data-limited.** mem goes above 480 on only 5 of 300 steps, and `oom_kills_total` rises on 3 steps. Counts noise on mem is about ±20 MiB against a table that rises over 480-512.

## Fix kept

| type | mechanism | where | commit | how another strategy adopts it |
|---|---|---|---|---|
| counted-flow (exact re-read) | Applies to a counter (a final stock) whose row no linear set reproduces, but which is exactly X x T(Y) to the row's rounding: X and Y are measured levels, X >= 0, and T is a piecewise-linear table. T has 1, then 2, inner knots. Its heights are fitted by NNLS. The first knot starts from a quantile grid plus the onset (the largest Y where the counter is still 0, and the smallest where it is not), and the knots are refined by least squares. A 16-quantile-knot table first screens out pairs that cannot work. When a counter qualifies, its one-step change becomes one more column for the exact rows. That column is never used inside a floored part, because it is an amount, not a level. A term on it joins as any other column: the row that reads it negatively is the source, and same-unit rows that read it positively get a move (never the counter itself). The move is written as the counter's rate X x T(Y), scaled by the term, and the counter's own term becomes its outside inflow | `engine_forms/reread.py` (`_counter_rate`, `_table`, the `COUNT` columns in `apply` and `_block`, `floored` pool) | ec6265e | Copy `reread.py` whole (it needs numpy, scipy, and `_kalman/boundary.py`'s `Data`, `Boundary`, `violations`). Or copy `_counter_rate` and `_table` into any row reader: add the counter's increments as a column, and translate a term on it into `{proportional X, k}` + `effects: [table of Y]` |
| precision-snap | A matched term's remainder is dropped when it moves less than the row's tolerance (\|v\| x rms(column) <= the row's tol), as well as below 1e-4 of the column's largest number. Before, a counted column's 1.0001 vs 0.9999 split left a 2e-4 outside flow on a side that already had a hinge, and the whole block was refused | `reread.py` `_block` | ec6265e | a one-line condition in the term-joining loop |

After (none-short, job 265): `ready -> pending = 0.99992 ready x T(mem)`, T = [[195.95, 0], [480.0001, 1.8e-8], [483.54, 0.0332]], which is the truth's 0 below 480 and slope 0.3/32 above it. Also `outside -> oom_kills_total = ready x T(mem)`, `pending -> ready = 0.49998 pending`, `outside -> pending = desired - pending - ready`, `ready -> outside = ready - desired` (floored), with the requests block and the desired controller as on 309.

## Notes

- Tests: `tests/test_engine_forms_reread.py::test_a_counter_that_is_a_level_times_a_table_is_a_measured_flow` (a synthetic pod chain with kills counted by a final stock) and `::test_a_noisy_counter_is_left_alone`. `test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone` still fails, as it already did before this change (noted on 307-309).
- Additive: a counter qualifies only when its row is not exactly linear and the data are noise-free, so earlier rungs' counters, which are linear (responses_total, errors_total), never qualify. Not run on earlier rungs, by the plan. The later full regression run should still check 308 and 309, because the precision-snap rule applies to every exact re-read.
- combined2 (8720834) and structures (5cdb3b2) added their own counted-flow mechanisms on 310. This one is engine_forms's own, exact-data version.
