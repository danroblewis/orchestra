# 308 (k8s-hpa): engine_forms, the noise-free and counts variants

**Status:** 3 of 4 pass, 2026-10-21, agent k8s-308-EF (engine_forms lock held for the work, released after).
Fix commit 6b0d2c5; pool job 247 (run at 6b0d2c5): `uv run sdlab-ladder job 247`: **none-short pass, none-long pass,
counts-long pass, counts-short fail** (data-limited, below).

## Before (store, code dfd94cb; `uv run sdlab-ladder show 308-k8s-hpa --strategy engine_forms --variant V`)

| variant | status | what was wrong |
|---|---|---|
| none-short | FAIL | ready's two HPA flows read as linear drifts (`outside -> ready = 0.00292 inflight`, `ready -> outside = 0.00248 queue + 0.0429 ready`): both whole flows off by ~1,100% |
| none-long | FAIL | same (`outside -> ready = 1.299`, `ready -> outside = 1.18 - 0.00073 inflight + 0.0505 ready`) |
| counts-short | FAIL | same HPA misread (both ~99%), and retries' split (retries -> queue 0.72 vs 0.6, retries -> outside 0.22 vs 0.4) |
| counts-long | FAIL | HPA misread only (both ~99%) |

## Diagnosis (rule 4b)

**ready (all four variants): method fault.** ready is a whole number (pods), unchanged on most steps; its one-step changes are
only -1, 0, +1, and in every variant they are separated exactly by a threshold on cpu / ready (up: cpu / ready in
(192.468, 192.598] on none-short, (191.917, 192.778] on counts-short; down: cpu / (ready - 1) in [157.42, 157.58)), with ready
held at 16 while cpu asks for more (scratchpad `thr.py`). The controller acts exactly on the measured levels (the case's flows are
`exact: true`; counts' ready is whole and its changes still follow the measured cpu), so the data identify it fully; a linear rate
cannot express an event-driven count, so the forms the strategy had could not reach it.

**retries on counts-short: data limit.** `uv run sdlab-ladder analyse 308-k8s-hpa --variant counts-short`: DATA-LIMITED, p 0.094;
the Cramér-Rao bound SE is 0.13 on retried (0.6) and 0.115 on gave_up (0.4) against an allowed 0.06 / 0.047 (p 0.36 and 0.31 at
the bound). Found 0.719 / 0.223 is 0.9 and 1.5 bound SEs off. The move-vs-link equivalence (retries -> queue vs a link reading
retries) is told apart only by the noise. On 308 the scorer has **no oracle** (`se None` on every part): the HPA's `ceil` is not
piecewise linear, so `oracle.py` gives up and the tolerance falls to 10% alone (on 307 the oracle's z x SE covers the same split).
This is a harness matter (oracle.py could take the truth's whole flows' amounts on the run's states as known offsets, as it already
does regime by regime for a MIN), reported here, not changed (rule 12).

## Fix kept

| type | mechanism | where | commit | how another strategy adopts it |
|---|---|---|---|---|
| quantized-controller | a stock whose levels are whole numbers, unchanged on at least half the steps, with no move, is tried as a controller per direction: up = `max(0, min(HI, ceil(X / a)) - S)`, down = `max(0, S - max(LO, ceil(X / b)))`, each optionally `min(c, ...)` (step cap where the events are smaller than the gap). X is any measured stock or input; a is the middle of the interval separating X / S on up steps from the rest (b: X / (S - 1) on down steps); HI / LO are written only where the data show them binding (a step at the top / bottom where the threshold says move and S did not). Taken only when the two expressions reproduce every one-step change exactly, each on a declared side (`Boundary.may(s, side, "estimate")`), replacing S's outside flows; otherwise nothing changes. Reads only levels, inputs and the boundary | `engine_forms/controller.py`, called in `__init__.identify` last, after `capmin.restore` | 6b0d2c5 | copy `controller.py` into the package (it imports only numpy and the package's own `_kalman/boundary.py`; a strategy without that copies `Boundary.may` or passes the declared sides) and call `controller.apply(result, stocks, run, opts)` on the final answer, after any pass that rewrites rates (oefit, tidy, capmin), so the expression flows are not refitted as linear |

After (none-short): `outside -> ready = max(0, min(16.0, ceil(cpu / 192.533183)) - ready)`,
`ready -> outside = min(1.0, max(0, ready - ceil(cpu / 157.50237)))`; every other flow unchanged.

## Notes

- Test: `tests/test_engine_forms_controller.py` (a synthetic count stock is read as its controller; a stock whose whole-number
  changes are not a threshold of anything is left alone; an undeclared side is not used).
- `tests/test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone` still fails, as before this change
  (noted in 307-engine_forms.md).
- Not run: earlier rungs (no regression run during the climb, by the plan) and the noise variants other than counts.
