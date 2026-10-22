# 312 (k8s-cluster-autoscaler): engine_forms, round 2

**Status (2026-10-22, agent ef312-r2, engine_forms lock held and released): none-short passes (28/28); none-long reads
the whole truth and fails only the scorer's counter part (the harness inconsistency at announced injections that
round 1 found; every strategy, and the truth written as a rate, fails it the same way); counts-short and counts-long are
data-limited (round 1's bound) and not targets. Round 2 changed no discovery result on the noise-free variants: it
made counts-long fail instead of error, and fixed a stale test.** Code at 104ee76, pool job 318
(`uv run sdlab-ladder job 318`).

| variant | achievable? | round 1 (18e29e8, job 308; re-run at e81d1d2, job 316) | round 2 (104ee76, job 318) |
|---|---|---|---|
| none-short | yes | PASS 28/28 (job 316: 97 s, Mac) | **PASS 28/28** (100 s, Mac) |
| none-long | blocked by the scorer (below) | FAIL 27/28 (job 316: 457 s) | FAIL 27/28 (456 s): only `outside -> oom_kills_total [as a whole]`, 0.02018 vs 0.02 |
| counts-short | no: data-limited | FAIL 7/25 | FAIL 7/25 (88 s) |
| counts-long | no: data-limited | **ERROR** on the Mac in job 316 (`LinAlgError: SVD did not converge in Linear Least Squares`); FAIL 8/25 on node2 in job 308 | FAIL 2/25 (724 s), no error |

## Diagnosis (rule 4b)

- `diff 312-k8s-cluster-autoscaler --strategy engine_forms` on none-short and none-long: no hunk except the hidden stage's
  name (`stage_nodes` for the truth's `provisioned_d1`; credited by hidden_match). All 31 other lines are unchanged.
  The found removal on none-long, `max(0, min(0.05 nodes - 0.025 ready - 0.025 pending, 0.05 nodes - 0.1))`, is
  algebraically `0.05 max(0, nodes - max(2, (ready + pending) / 2))`: the truth's.
- none-long's one failed part is round 1's harness finding, unchanged: the truth's counter `flow(oom_killed)` is read
  from the engine's counters (computed after the step's injection), while the found `ready x table(mem)` is evaluated
  by `score._levels_at`, which does not apply announced injections. All the error sits on the two node failures
  (t 706, 1282). structures, milp, kalman_lna and combined2 report the same 2.018% miss, and the truth's own counter
  written as `ready x table(mem)` fails it too. Writing the counter as `flow(id)` would read the truth's recorded
  counters (sim.amounts), which discovery must never see, so no honest model passes this part until the harness adds
  announced injections to the step-start states. **Harness fix needed (not this agent's module; a scoring change
  that can turn fail into pass, so it goes to the user with before/after, rule 5).**
- counts-long errored on the Mac (job 316) and failed on node2 (job 308) with the same code: a platform-dependent
  LAPACK failure in the output-error refit. The model's run through the record blows up on counts data, and the
  variance fit `a + b x level^2` in `oefit._weights` hands non-finite numbers to `lstsq`. combined2 hit the same thing on
  310 counts-long (7539346).

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| **oefit-guard** (fix-ledger type 10, ported from combined2 7539346) | `oefit._weights` keeps the previous weights where the model's run is not finite or the variance fit's SVD fails; `_noise0` falls back to its floors on an SVD failure | 104ee76 (`oefit.py`) | Every oefit copy (39 of them): the same two `try/except np.linalg.LinAlgError` and the finiteness check |
| **refit-guard for every later pass** (fix-ledger type 10, structures 3bf52d6, widened) | `__init__._guarded`: oefit, tidy, reread, controller, hidden and delay each keep their input when they raise `LinAlgError` or `FloatingPointError`, and add `<pass>: LinAlgError at <file:line> (...); its input kept` to the trace. Any other exception still raises, so bugs are not hidden | 104ee76 (`__init__.py`) | A strategy built as a chain of passes wraps each pass's call the same way (numerical failures only) |
| test upkeep | `test_a_form_that_leaves_the_boundary_is_undone` read only the word "undone"; `judge.improve` now refuses such a form before weighing it ("leaves the declared boundary"). The test accepts either wording and checks the form is never chosen. This was the failure round 1 reported at 201a23d | e81d1d2 (`tests/test_engine_forms_boundary.py`) | - |

Cells fixed: 312 counts-long, error to fail. It is data-limited, so the rung's verdict does not change. No noise-free
result changed: the guards act only when a pass raises.

Tests: `tests/test_engine_forms_delay.py::test_a_pass_whose_svd_fails_keeps_its_input`. All engine_forms tests,
`test_isolation.py` and `test_frozen.py` pass (23).

## For the rung and the regression run

- With the harness's injection fix, engine_forms should pass none-long as well (round 1 measured the found counter on
  the injected states: rel rms 0.00012). It would then pass every achievable variant of 312.
- The guards change no answer unless a pass raises. Round 1's regression notes still apply (relaxed pieces, hinge
  pairs, COND in `floored`, delay.py: check 309/310/311 none-* once).
