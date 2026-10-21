# 308 (k8s-hpa), combined2: noise-free and counts variants

Agent k8s-308-combined2, 2026-10-21. Plan: climb kubernetes 307-311 on none-short, none-long, counts-short and
counts-long only (the user, 2026-10-21). No regression runs on earlier rungs.

## Status: 3 of 4 pass (counts-short fails on a data limit)

Pool job 252 at b0117e0 (`uv run sdlab-ladder show 308 --strategy combined2 --variant V`, read 2026-10-21 20:58Z):

| variant | before (dfd94cb) | after (b0117e0) | complexity found / true |
|---|---|---|---|
| none-short | FAIL 10/12 (ready's two flows) | PASS 12/12 | 24 / 24 |
| none-long | FAIL 10/12 (ready's two flows) | PASS 12/12 | 24 / 24 |
| counts-short | FAIL 8/12 (ready's two flows, retries' split) | FAIL 10/12 (retries' split) | 24 / 24 |
| counts-long | FAIL 10/12 (ready's two flows) | PASS 12/12 | 24 / 24 |

## Diagnosis

- **ready's inflow and outflow (all four): a method fault.** The HPA moves `ready` by exactly +1 or -1 on 7% of the
  steps and not at all on the rest. On the record, the truth's law is exactly the half-planes `cpu > 192.5 ready`
  (while ready < 16) for a pod added and `cpu <= 157.5 (ready - 1)` for one removed (checked on the data: 0 steps
  wrong). combined2's linear rows wrote this as a small drift (`0.057 + 0.0055 x inflight`), 94-99% wrong as a whole
  flow. In none-long the smear also made oefit (C1's output-error refit) fire on non-white residuals and bend cpu's
  correct row into `-0.74 ready + 0.34 queue` with a drain of 0.09 (seen in job 250, reproduced locally with a trace).
  In counts-long one run's pick carried a hidden stage `ready~stage` for the jumps.
- **retries -> queue / retries' drain on counts-short: the data's limit.** `sdlab-ladder analyse`: data-limited (p 0.09);
  the bound SE is 0.13 against an allowed 0.06 (queue) and 0.115 against 0.0465 (drain). combined2's 0.741 and 0.200
  are 1.1 and 1.7 bound SEs off. Not fixed: no method can pass this reliably (same verdict as kalman_lna, structures,
  engine_forms on 308).

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| discrete-switch | `switch.py`: a measured, non-final stock X whose one-step change, after its moves with other measured stocks, is 0 on most steps (moves on at most half) and exactly +s / -s on the rest (one step per side, at least 3 moves a side) has each declared outside side written as a switch `s x ((c + w_X X + w_Y Y) > 0)`. The line is a max-margin LP separator (|w|_1 <= 1 on standardised columns; an L1 soft margin when nothing separates) over X alone, Y alone, or X and Y, Y any other measured stock or input; fewest misclassified steps, then fewest columns, then widest margin. Where the half-plane alone misclassifies, X's own level range the moves happened in is added as a bound (`X < hi`, `X > lo`, halfway to the next level seen: an actuator's ceiling / floor). Kept only with at most 2% of steps wrong and at most 25% of the replaced flows' squared error on X's row. Reads only the levels. | 9a5ee5c | copy `switch.py` into the package (identical copy) and call `switch.apply(result, stocks, run, opts)` on the answer |
| switch-before-oefit | the switch runs on the fit's answer before the output-error refit (oefit), then again after capmin's MIN write-back; it never reads capmin's offered series (`readable=`). A stock's own hidden chain (unmeasured stocks linked only to X) is removed with X's outside flows when the switch replaces them; outside flows the switch cannot evaluate (effects, pieces) are compared as no flow. | b0117e0 | in a strategy with an output-error or simulation refit, call `switch.apply` before that refit (and once more at the end); pass `readable` to keep switches off any derived series the strategy offers |

## Tests

`tests/test_switch_combined2.py` (a synthetic pod/load controller: both sides found, one flow a side, the engine's
`sim.amounts` of the written expressions equals the record's changes; a smooth stock is untouched). Locally before
commit: `tests/test_ladder_combined2.py`, `tests/test_frozen.py`, `tests/test_isolation.py` pass.

Local diagnostics (not results): `discover("combined2", ...)` on 308 none-long and none-short with `SDLAB_COMBINED2={"trace":
true}`, single-threaded, about 4 and 1 CPU-minutes, to find what moved cpu's row (oefit) and to check the reorder.

## Left open

- counts-short's retries split (data-limited, above).
- The switch's ceilings and floors are written only where the record shows them binding (`ready < 15.5`; `ready > 3.5`
  only on counts-long). A fresh record that drives ready to a limit the run never reached would not see it.
- Earlier rungs were not re-run (the plan). The switch's gate (sparse, exactly quantized changes) should leave smooth
  stocks alone, but counts stocks with long runs of zero change are the place to check in the regression run.
