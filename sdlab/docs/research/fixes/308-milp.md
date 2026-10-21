# 308 (k8s-hpa): milp

Status (2026-10-21, 13:45 PDT): **3 of the 4 plan variants pass at 3bfb6ff. counts-short still fails, and I
diagnosed that as a data limit, not a method fault.**

Where the results come from: pool job 249 (`uv run sdlab-ladder job 249`), and
`uv run sdlab-ladder show 308-k8s-hpa --strategy milp --variant V`, code 3bfb6ffcf2:

| variant      | before (dfd94cb)                 | after (3bfb6ff) | parts | discovery |
|--------------|----------------------------------|-----------------|-------|-----------|
| none-short   | FAIL 10/12 (41.0 s)              | PASS            | 12/12 | 4.5 s     |
| none-long    | FAIL 10/12 (281.0 s)             | PASS            | 12/12 | 8.8 s     |
| counts-short | FAIL 7/12 (103.3 s)              | FAIL            | 10/12 | 72.2 s    |
| counts-long  | TIMEOUT (> 300 s)                | PASS            | 12/12 | 104.3 s   |

## Diagnosis (rule 4b)

- **ready's two HPA flows were a method fault.** The scorer compares them as whole flows: the RMS of their
  amounts on the run's states, within 2% (none) or 10% (counts). The truth is a step function of cpu and
  ready, and milp could only fit a linear rate (`0.021 traffic + 0.185 retries - 0.028 queue`), so it
  missed every scaling step. The data pin the rule exactly. ready is a whole number at every step and
  changes by ±1 in 21 of 299 steps (134 of 1,999 on long). The true rule reproduces every step on every
  variant, including counts, because counts noise is in the amounts and the controller reads the counts
  exactly. A single threshold on ready/cpu separates the steps with 0 errors, once the target is clipped
  at 16, the highest ready level (cpu/192.5 is above 16 in 78 steps). On counts-long the 3-pod floor also
  matters: one step falls below it.
- **The counts-long timeout and the slow none-long run** came from that same row. The program searched
  for a linear explanation of ready that does not exist. With ready's row taken out, it solves in 2 to 30 s.
- **counts-short is a data limit.** What fails: retries -> queue is 0.728 (true 0.6) and retries -> outside
  is 0.208 (true 0.4). `uv run sdlab-ladder analyse 308-k8s-hpa --variant counts-short` puts the
  Cramér-Rao bound SE at 0.13 and 0.115, against allowed errors of 0.06 and 0.0465. An estimate at the
  bound would land within tolerance with probability 0.355 and 0.314 (0.09 for the case as a whole:
  "data-limited"). milp's errors are 1.0 and 1.7 bound SE, which is ordinary scatter for an efficient
  estimator. I left it as it is: tuning to this seed would be gaming. The spurious
  `min(0.5 inflight, 0.66 queue)` on responses_total from the earlier run is gone.

## Fix kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| quantized-controller | `milp/quantized.py`. It tries a stock S that holds only whole numbers and changes in at most half the steps as a controller on another positive stock X. The inflow is `1*(S < T)` or `max(0, T - S)` and the outflow is `1*(S > T)` or `max(0, S - T)`, with `T = ceil(X/a)`. For a whole-number S, S < ceil(X/a) holds exactly when S/X < 1/a, and S > ceil(X/b) exactly when (S-1)/X >= 1/b. So each threshold is the cut on a sorted ratio that misclassifies the fewest steps. T is clipped at S's highest level (inflow) or lowest level (outflow) only where the clip removes misclassified steps. The form is one unit a step, or the whole gap, whichever fits better (one unit on a tie). The rule is kept only when it matches S's changes within 5%, with at least 5 events on each side it claims, and only on sides the boundary declares. **Then the program fits the other stocks with S's row taken out**: S's changes are reduced by the rule's, and no flow into or out of S is offered (`Boundary.skip`, `targets`). S's flows are the rule's. They are put back after `oefit.refit`, whose simulator does not run `ceil`. | 3bfb6ff | Copy `quantized.py` into the package. Before the strategy's own search, call `known, notes = quantized.find(stocks, run, opts)`. Take each known stock out of the search: subtract `known[s]["amount"]` from its change row and offer no candidate flow touching it. Afterwards call `flows = quantized.put(flows, known)`, and again after any refit that cannot run `ceil` or comparisons. A strategy that cannot take a row out can just call `put` on its answer: the HPA parts then pass, but the search time is not saved. The time saving is what fixed milp's counts-long timeout. |

Scope check: `quantized.find` on every kubernetes case's none-short and counts-long data fires only on
rungs 308 and later (ready on 308; `desired` on 309-312; the three `*_desired` on 317), so it touches no
earlier rung. On 309-312 it rejects `ready` (miss 72-290 of 146-368: ready is not the controller there),
and on 312 and 317 it rejects `nodes`. Test: `tests/test_milp_quantized.py` (the rule found on an HPA-like
series, rejected on Poisson counts).

Not done: no regression run on earlier rungs (per the plan).
