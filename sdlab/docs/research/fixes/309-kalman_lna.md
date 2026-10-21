# 309 (k8s-pod-startup): kalman_lna

Status (2026-10-21, 14:30 PDT): **3 of the 4 plan variants pass at 70bc422 (job 254): none-short, none-long and
counts-long. counts-short fails, and the data limit it (below).**

Where the numbers come from: `uv run sdlab-ladder submit --strategies kalman_lna --cases 309-k8s-pod-startup --variants
none-short,none-long,counts-short,counts-long --priority 400 --by k8s-309-kalman_lna` (job 254, 4 items, Mac pool), then
`uv run sdlab-ladder show 309-k8s-pod-startup --strategy kalman_lna --variant V`:

| variant      | analyse                   | before (4f04ce1) | after (job 254, 70bc422) | discovery |
|--------------|---------------------------|------------------|--------------------------|-----------|
| none-short   | unidentifiable* (p 0.00)  | FAIL 9/18        | **PASS 18/18**           | 10.9 s    |
| none-long    | unidentifiable* (p 0.00)  | FAIL 7/18        | **PASS 18/18**           | 292.3 s   |
| counts-short | DATA-LIMITED (p 0.010)    | FAIL 10/18       | FAIL 14/18               | 8.7 s     |
| counts-long  | DATA-LIMITED (p 0.253)    | FAIL 13/18       | **PASS 18/18**           | 60.6 s    |

\* The analysis says "unidentifiable" because it treats the move retries -> queue as the same thing as a link
outside -> queue reading retries. The declared boundary rules that link out: queue's only inflow from outside is
the input. So the none variants are achievable, as they were on 308.

## Diagnosis (rule 4b)

- **The pod chain (every variant): a method fault.** `outside -> pending = max(0, desired - pending - ready)` and
  `ready -> outside = max(0, ready - desired)` are linear rates floored at 0, and the floor binds on most steps. The
  base (its copy of combined) can only draw them as constant pieces or as linear proxies. Those proxies then bend
  the rest of the model. In none-long the base drew a move desired -> ready (0.284), which hid desired's controller
  from the tracker, and cpu's row came out wrong (0.33 x inflight). In none-short, pending -> desired was 0.12. On
  every noise-free variant both floored flows hold exactly: the residual is at the data's rounding, about 1e-7 SSE.
- **queue, inflight and retries on none-short: a method fault.** The base read them as `queue -> inflight =
  7.62 x retries - 0.000865 x errors_total`, plus `retries -> outside` reading pending. The residual was larger
  than the change itself (rms 17 against 6). The best sparse rows are exact (rms 3e-5): queue = traffic - 0.68
  queue + 0.6 retries, and so on. The levels are nearly collinear (`analyse` shows queue, retries, traffic and
  inflight at a relative size of 3.6e-4), so the base's selection picked the wrong readers. The MIN never binds on
  the short run.
- **counts-short: a data limit.** `analyse` gives DATA-LIMITED, p 0.010. The retries split has bound SE 0.113
  against an allowed 0.04 (p 0.28); we found 0.4756 against a true 0.6, which is 1.0 SE, as on 308. The pending
  inflow's terms have bound SE 0.275 against an allowed 0.1 (p 0.28). This variant is not a target.
- **counts-long: data-limited, but it passed.** In the data, started = 0.394 x pending exactly. That is the plain
  least-squares estimate from ready's change, against a true 0.5 with a bound SE of 0.039. It still lands inside
  the scorer's tolerance.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| row-rebuild (floored rows) | `rows.py`, run on the final answer after the MIN write-back and before the tracker. **1. Rows.** For every measured stock, the one-step change (less injections) is fitted on every measured non-final stock, every measured input and a constant, in two forms. The first is the best sparse linear subset: every subset up to 3 terms, then forward steps to 5. The second is a linear part plus one term `max(0, B . x)` on a side the declared boundary allows. Its always-on part is fitted by least trimmed squares on every support up to 2 readers, trimming only steps where a reader is nonzero. B's readers are fitted on the steps where the term is active and scored on all steps, so B . x <= 0 must hold where it is off. Both parts are then refitted together, with the active steps re-read from B . x > 0. Terms that do not pay for themselves are dropped. Each fit is scored by Gaussian BIC with the data's rounding as a floor. **2. Which stocks.** A stock is rebuilt where its row beats the answer's flows on it by BIC + 6 log T and explains at least 50% of its change's squares. A stock joined to a rebuilt one by a flow is rebuilt too, unless its own row is worse than its answer. Flows to stocks whose answer fits are kept. Flows to stocks whose answer misses them are cut, and the tracker takes those stocks. **3. Flows from rows.** A positive term reading X in T's row becomes a move X -> T, largest first, when X is a rebuilt stock in T's unit with a drain at least that large. What is left of the drain is X's outflow. Every other term is an outside link, positive terms in and negative terms out, one flow per side; the floored term is its own side. A row that needs a side the boundary lacks is refitted without those links, for up to 3 rounds. With no outflow, its drain is fixed at what its moves take. Links that move the stock by less than the rounding are dropped. All rebuilt numbers are then refitted together over the rebuilt rows, each row weighted by its own scale, so a move's number shows in both of its stocks. **4. Gate.** The rebuild is kept only where, over the rebuilt stocks, it beats the answer by BIC + 6 log T. It is skipped where the answer reads a lag, a scale or the filter | 70bc422 | Copy `kalman_lna/rows.py` into the package (it is self-contained) and call `result = rows.revise(result, stocks, run, opts)` on the final answer, after any MIN or expression is written back and before a controller pass (tracker.py), so the controller reads the rebuilt neighbours. Test: `tests/test_kalman_lna_rows.py` (a pending/ready chain whose answer has proxies is rebuilt to the floored gap inflow, the move and the floored surplus outflow, and pending gets no outflow its boundary lacks; a well-fitted noisy chain is left alone) |

Found on 309 none-long (job 254): `outside -> pending = desired - pending - ready` (floored),
`pending -> ready = 0.49999 x pending`, `ready -> outside = ready - desired` (floored), and `outside -> cpu = 1.25 x
inflight + 20 x ready`, `cpu -> outside = 0.5 x cpu`. The tracker then reads desired's HPA controller as on 308.

Checks: `uv run pytest tests/test_ladder_kalman_lna.py tests/test_kalman_lna_boundary.py tests/test_kalman_lna_tracker.py
tests/test_kalman_lna_rows.py tests/test_isolation.py`: 17 pass. Under the plan, I ran no regression on earlier
rungs. rows.py runs on every answer, so the later full regression run is where to look for side effects. The
BIC + 6 log T gate is meant to leave fitted answers alone, as the second test checks.

Not done: counts-short's pending inflow comes out as 0.41 x (desired - ready), with no pending term. The
floored term's active steps are read off the trimmed residual, and counting noise blurs that. A Poisson-weighted
active-set fit may do better, but the variant is data-limited (p 0.010).
