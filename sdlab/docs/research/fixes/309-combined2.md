# 309 (k8s-pod-startup), combined2: noise-free and counts variants

Agent combined2-309, 2026-10-21. Plan: climb kubernetes 307-311 on none-short, none-long, counts-short and
counts-long only (the user, 2026-10-21). No regression runs on earlier rungs.

## Status: 3 of 4 pass (counts-short fails on a data limit)

Pool job 256 at 2a1db63 (`uv run sdlab-ladder show 309 --strategy combined2 --variant V`, read 2026-10-21 21:31Z):

| variant | before (4f04ce1) | after (2a1db63) | discovery s | complexity found / true |
|---|---|---|---|---|
| none-short | FAIL 14/18 (desired's two flows, ready's outflow, a move desired -> ready) | PASS 18/18 | 97 | 33 / 33 |
| none-long | TIMEOUT (> 300 s) | PASS 18/18 | 252 | 33 / 33 |
| counts-short | FAIL 10/18 | FAIL 15/18 (retries' split, cpu [ready]) | 16 | 33 / 33 |
| counts-long | FAIL 13/18 (pending's creation, ready's outflow) | PASS 18/18 | 119 | 37 / 33 |

`sdlab-ladder analyse 309`: none-short / none-long "unidentifiable" only for the retries move-vs-link equivalence
(the scorer accepts the move; the same verdict 308 had, where these passed): targets. counts-short data-limited
(p 0.01: retries -> outside p 0.28, created [ready] p 0.28): not a target. counts-long data-limited (p 0.25): not a
target, passed anyway.

## Diagnosis

- **ready -> outside = max(0, ready - desired) and outside -> pending = max(0, desired - pending - ready): a method
  fault.** The engine floors every flow at 0, so these gaps are linear rates that sit at 0 on most steps. The linear
  fit over every step smeared them (counts: `0.0027 ready`, a constant `0.03` for pending; none: `0.082 ready` plus a
  move `desired -> ready` at `0.08 desired`). The exact law is linear on the steps where it is positive.
- **desired's hpa_up / hpa_down on none (a method fault).** desired changes by exactly +/-1 on 7% of steps, which
  308's switch handles; but the fit's spurious move `desired -> ready` was subtracted from desired's row first, so
  the residual was no longer sparse and the switch did not fire. On counts the fit had no such move and the switch
  already fired.
- **none-long's timeout:** with the smeared rows, the output-error refit (oefit) fired and ran long; with exact rows
  it no longer does (252 s on the pool now; 300 s is the limit, so little headroom).
- **counts-short:** retries' split (bound SE 0.113-0.127 vs allowed 0.04-0.06) and cpu [ready] (16.4 vs 20, bound SE
  1.66, allowed 2): the data's limit, not fixed.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| floored-side | `hinge.py`: for each measured, non-final stock X (no hidden neighbours, no switch), each outside side the model already has (declared sides only where a boundary is declared; none is invented) is refitted on X's row (its change less its moves, less its other side) as `max(0, c + w . Z)` on at most 3 measured stocks or inputs, with or without a constant, by active-set least squares (fit on the active steps, recompute, from 3 start thresholds). Column set by BIC on X's row (SSE floored at 1e-9 of the row's scale so exact fits tie and parsimony picks); the rate must sit at its floor on >= 10% of steps (else it is an ordinary linear rate, left alone); kept only where X's row BIC falls by > 2 log n. Written as an ordinary `linear` rate (the engine floors it). | 2a1db63 | copy `hinge.py` (identical) and call `hinge.apply(result, stocks, run, opts)` after the strategy's switch / final answer |
| switch-drop-moves | `switch.py` `_try(..., drop=True)`: when a stock's residual after its moves is not a sparse quantized series, retry with its moves to other measured stocks dropped (a stock that holds exactly still on most steps cannot carry a smooth move); if the switch then fits, the dropped moves are removed and each partner stock's row is repaired with `hinge.refit_row(force=True)`; kept only where every partner's row SSE ends no worse than before | 2a1db63 | strategies with 308's `switch.py`: copy the new `switch.py` with `hinge.py` (switch imports it) |
| pipeline order | in `identify`: `hinge.apply(switch.apply(r))` before oefit and again after capmin's restore (both reading no capmin series) | 2a1db63 | run the floored refit right after each switch pass, before any output-error / simulation refit |

## Tests

`tests/test_hinge_combined2.py`: a synthetic actuator / pending / ready record (a smeared `0.003 x have` outflow becomes
`have - want` exactly, an exact row is untouched; the switch drops a smeared move `want -> have` and repairs `have`).
Before commit: `tests/test_hinge_combined2.py`, `tests/test_switch_combined2.py`, `tests/test_ladder_combined2.py`,
`tests/test_isolation.py`, `tests/test_frozen.py` pass (14 passed).

Local diagnostics (not results): `discover("combined2", ...)` on 309 none-short, none-long, counts-long, single-threaded
(about 2, 5 and 2 CPU-minutes, three at once), plus the new passes on the stored 4f04ce1 answers, to diagnose and check.

## Left open

- counts-short (data-limited, above).
- none-long runs 252 s of a 300 s timeout on the pool: a slower worker could time out. The candidates' budget
  (combined2's DEFAULTS) is the lever; not changed here.
- The floored refit runs on every stock of every case; earlier rungs were not re-run (the plan). Its guards (an existing
  side only, at the floor on >= 10% of steps, BIC gain > 2 log n) target this; a counts stock that sits at 0 often is
  the place to check in the regression run.
