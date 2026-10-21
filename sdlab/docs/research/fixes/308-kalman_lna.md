# 308 (k8s-hpa): kalman_lna

Status (2026-10-21, 13:45 PDT): **3 of the 4 plan variants pass at 938a080 (job 251, run at 3483526);
counts-short fails on the retries split, which is a data limit (below).**

Where the numbers come from: `uv run sdlab-ladder submit --strategies kalman_lna --cases 308 --variants
none-short,none-long,counts-short,counts-long --priority 400 --by k8s-308-kalman_lna` (job 251, 4 items, Mac
pool), then `uv run sdlab-ladder show 308-k8s-hpa --strategy kalman_lna --variant V`:

| variant      | before (dfd94cb) | after (job 251, 3483526) | parts | discovery |
|--------------|------------------|--------------------------|-------|-----------|
| none-short   | FAIL 10/12       | **PASS**                 | 12/12 | 6.6 s     |
| none-long    | FAIL 10/12       | **PASS**                 | 12/12 | 108.4 s   |
| counts-short | FAIL 8/12        | FAIL                     | 10/12 | 3.7 s     |
| counts-long  | FAIL 10/12       | **PASS**                 | 12/12 | 26.9 s    |

## Diagnosis (rule 4b)

- **The HPA flows (all four variants): a method fault.** The two flows of `ready` came out as linear proxies,
  for example `outside -> ready = 0.00292 x inflight` and `ready -> outside = 0.00248 x queue + 0.0429 x ready`,
  with errors of 700-1200% of the amount. In every variant `ready`'s step change is exactly
  `max(0, min(16, ceil(cpu/192.5)) - ready) - (ready > max(3, ceil(cpu/157.5)))`. The residual is 0 on all
  steps (scratchpad check, levels from `data.load`), and the controller is exact under counts too. So the data
  pin it, and the cause was that the strategy had no form that can express it.
- **counts-short's retries split: a data limit.** `retries -> queue` is 0.7215 against a true 0.6, and
  `retries -> outside` is 0.2206 against 0.4; their sum is right. `uv run sdlab-ladder analyse 308-k8s-hpa
  --variant counts-short` gives DATA-LIMITED, p = 0.094. The Cramér-Rao SE is 0.13 for retried against an
  allowed 0.06 (p 0.355), and 0.115 for gave_up against an allowed 0.0465 (p 0.314). The analysis also notes
  that the move and the "link plus drain 1" are told apart only by the noise. The found errors are 0.93 SE and
  1.56 SE, which is normal scatter for an estimator at the bound. I made no fix. The answer comes from the base
  copy of combined, with oefit unchanged. The tracker does not touch these rows.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| quantized-target-controller (tracker) | `tracker.py`, run after the final answer. For each measured, non-final stock S with an estimated outside side (or any side where no boundary is declared), the outside net is S's change less injections and the answer's flows between S and other measured stocks. Each side is offered as a controller toward a whole-number target T = ceil(X / a), read off another measured stock or input X. The rise can be the gap `max(0, min(H, T) - S)` or a step `d x (S < min(H, T))`. The fall can be the gap `max(0, S - max(L, T))` or a step `d x (S > max(L, T))`. The search over a is exact: every interval between the breakpoints X_t / m (m whole, near S_t) is tried, and a is the middle of the best interval. The clamp H or L is tried at the extreme level reached, and every choice is priced by BIC. The tracker replaces S's outside flows only where it explains 90% of the outside net's squares and beats them by BIC + 6 log T. It is skipped where the answer reads a lag, a scale or the filter (a different frame), and it has a 20 s budget, spent on the worst-fitted stocks first | 938a080 | Copy `kalman_lna/tracker.py` into the package (it is self-contained) and call `result = tracker.revise(result, stocks, run, opts)` on the final answer, after any MIN or expression is written back. Test: `tests/test_kalman_lna_tracker.py` (a synthetic controller is recovered exactly; a linear stock is left alone; declared sides are respected) |

Found on 308 none-short: `outside -> ready = max(0, min(16.0, ceil(cpu / 192.533)) - ready)` and
`ready -> outside = 1.0 x (ready > ceil(cpu / 157.502))`. minReplicas 3 never binds on the short run, so no
floor is priced. The long counts run reads it as `max(3.0, ...)`.

Checks: `uv run pytest tests/test_ladder_kalman_lna.py tests/test_kalman_lna_boundary.py
tests/test_kalman_lna_tracker.py tests/test_isolation.py`: 15 pass. A first version broke
`test_reporting_delay_read_from_injections` (087 lag-short): there the tracker fitted the lagged answer's noise.
The lag/scale/filter skip and the 90% explained gate fixed that. No regression run on earlier rungs (the plan).
