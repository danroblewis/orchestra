# 307 (k8s-cpu-usage): engine_forms, the noise-free and counts variants

**Status:** fixed, 2026-10-21, agent agent-307-engine_forms (lock acquired after the coordinator released k8s-307-C1's stale locks).
Fix commit c0c4b12; pool job 245 (run at 83ab829, which contains c0c4b12 and does not change engine_forms):
`uv run sdlab-ladder job 245`: **4/4 pass** (none-short, none-long, counts-short, counts-long).

## Before (store, code 1b31e14; `uv run sdlab-ladder show 307 --strategy engine_forms --variant V`)

| variant | status | what was wrong |
|---|---|---|
| none-short | EQUIVALENT | cpu's inflow `1.25 inflight + 20 ready + -1.07e-07 * min(queue, 66.67 ready)` (an `expr`): both cpu links scored missing, the expression spurious |
| none-long | EQUIVALENT | same, with `-1.27e-07 traffic + -2.85e-08 * min(...)` |
| counts-short | PASS | |
| counts-long | PASS | |

## Diagnosis (rule 4b)

Method fault, not a data limit: on none the structure and every number are exact (1.2500000, 20.000002); `analyse` calls
none "unidentifiable" only for the retries move-vs-link equivalence, which the scorer already accepts. On noise-free data each extra column
lowers the residual a little, so the fit keeps terms at the float floor (the offered MIN series, traffic). `capmin.restore` then
writes the MIN-series term back as a MIN, turning a two-link linear rate into an expression. Reproduced in-process (scratchpad run307.py).

## Fix kept

| type | mechanism | where | commit | how another strategy adopts it |
|---|---|---|---|---|
| zero-term-prune | every `linear` rate (also in `byTime` and `rates`): a term or constant whose largest contribution over the record, `max |k x series|`, is below `REL = 1e-4` of the flow's largest amount is dropped, with no refit. A rate left with one term and no constant becomes `proportional`. It reads only the rate, the measured levels and the inputs (the offered capmin series included) | `engine_forms/tidy.py`, called in `__init__.identify` after `oefit.refit` and **before** `capmin.restore`, so a negligible MIN-series term is never written as a MIN | c0c4b12 | copy `tidy.py` into the package and call `tidy.apply(result, run, o)` on the final flows just before `_capmin.restore(r, cap)` (`o` = the opts capmin.offer returned, so the offered series resolves). Where a strategy restores before tidying, the same rule must instead handle `expr` terms |

After: none-short cpu = `1.2500000702 inflight + 20.0000022 ready`, cpu's drain = `0.49999999 cpu` (proportional); counts unchanged.

## Notes

- `tests/test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone` fails already at HEAD 1b31e14 (before
  this change; checked by running it on the HEAD version of `__init__.py`). Not caused by this fix, not fixed here.
- Test: `tests/test_engine_forms_tidy.py`.
