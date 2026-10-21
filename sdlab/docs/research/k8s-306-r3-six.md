# Kubernetes 306, round 3: coflow_hats, held_out, lna_products, milp, realistic_flows, z3exact

**Status:** done (2026-10-21). Code: 3de470a (held_out, milp, z3exact). Baseline: pool job 201 at c7cade0
(the boundary kind `input`: traffic is fixed at 1 x the input). After: pool job 210 at 3de470a. Only 306 was
run; earlier rungs were not re-run (the user: one regression check at the end, in the report step).
Numbers: `sdlab-ladder pool results 201` / `210`, and `sdlab.ladder.store` (latest rows per cell).

## Results on 306 (job 201 at c7cade0 -> job 210 at 3de470a)

| strategy | none-short | none-long | counts-short | counts-long | meas-short | meas-long |
|---|---|---|---|---|---|---|
| coflow_hats | pass | pass | pass | pass | fail | fail |
| held_out | fail -> **pass** | pass | pass | fail -> **pass** | fail | fail |
| lna_products | pass | pass | pass | pass | fail | fail |
| milp | pass | pass | pass | pass | fail | fail |
| realistic_flows | pass | pass | pass | pass | fail | fail |
| z3exact | equivalent -> **pass** | fail -> **pass** | fail -> **pass** | fail -> **pass** | fail | fail |

coflow_hats, lna_products and realistic_flows were not changed and not re-run (job 201's rows stand).
Every pass -> fail: none. The six now fail only meas-short and meas-long.

## held_out: the offered MIN's two halves (fixed)

capmin.py offers m = MIN(queue, theta x ready) as a series only the queue and inflight rows may read. held_out
starts from the pinned `identify_one`, which writes a row's term on m as an outside flow: queue -> outside and
outside -> inflight. The declared boundary's guard replaces outside flows one at a time, greedily, so the
first half is replaced while the second is still there. At c7cade0 the choice turned on rounding:

- none-short failed on node2 and passed on the Mac (same commit, same chosen variant, reproduced in a clone on
  node2). On node2 the guard dropped both halves, then queue -> retries read 0.012.
- The guard prices with an absolute rss floor of 1e-12, so on noise-free data a refit that rounds one stock
  lower wins by T log(ratio). A relative floor (capmin's 1e-8 of the squared changes) removed the platform
  split but then routed m into responses_total: the guard is still greedy.
- counts-long failed on both machines: the MIN landed on queue -> retries.

**Fix** (`held_out/pairing.py`, called in `fit_one` before the guard): where X's outflow and R's inflow both
read m, the m terms become one move X -> R at the mean of the two numbers, and the guard refits it. Other
terms of those flows are kept. A half without its partner is left to the guard. This is the same idea as
common_cause/inflow_effects (f252b8c) and effect_hats/sindy (55b03ed), written for held_out's own code.
Locally all four none/counts variants pass on the Mac and on node2; job 210 confirms them on the pool.

The relative-floor issue is in every copy of `boundary.py` (Fit's `max(data.floor, 1e-12)`). It is reported
here, not fixed: pairing removes this cell's need for it.

**Capability.** held_out is the matrix's candidates (linear rows, outside-inflow pieces, eras), each
judged by blocked cross-validation. It is refitted by the earned refit, kept inside the boundary, and
IV-refitted under measurement error (eiv). It represents MIN only through the offered series, and now as one
move. It has no output-error fit: its structure is chosen on one-step fits. **Limitation: fixable** (meas, below).

## z3exact: the offered series in the "ends" class (fixed)

z3exact tries the exact classes in turn: ends/kinds, ends/sides, any/sides. A move in the "ends" class reads
the level of one of its two ends. The offered m is a measured input to it, so queue -> inflight reading m
existed only in the "any" class. There 9 smallest structures fit, and the least-squares tie-break chose
responses_total -> errors_total reading inflight (none-short: equivalent). It also chose retries -> queue at
1.0 with no outflow (none-long: fail).

**Fix** (`z3exact/core.py`, the strategy's copy of `z3_ident.py` only; the harness tool is untouched): in
the ends class a move X -> R may read the offered series of X (X's level clipped by the capacity). Only the
rows capmin allows read it at all. An outside term reading it is judged as one reading a level, not a
measured input. none-short is now **identifiable** in ends/kinds (10 checks, 0.4 s). On counts the best
effort's backward elimination now has the right column.

**Capability.** The class is linear terms on levels, inputs and constants. The answer is the smallest
structure that fits every step within the data's rounding, proved minimal by Z3. MIN enters only as an offered
column. Noisy data fits nothing, so z3exact returns a best effort: backward elimination on one-step least
squares, labelled "not proved". On 306 meas that best effort keeps 8-9 spurious flows between the counters
(job 210). **Limitation on meas: hard.** The method is exact search within rounding (docs/research/z3.md:
"useless on noisy data by construction"). Handling measurement error would mean a statistical estimator in
place of the exact search, which is a different method. On earlier rungs it also fails 300 meas-short/long
and 303 meas-long, and 304 counts-long and 305 counts-short/long at c7cade0. **Elimination (kind:
impossible) is proposed for the user, pending two skeptics.** The reason is the meas variants, not the MIN,
which it now represents.

## milp: moves keep one unit (small fix; meas not fixed)

On meas, milp's program kept capacity-limited moves between pods and requests:
- ready -> queue = MIN(0.54 ready, 0.0087 inflight) and ready -> retries (meas-short);
- queue -> ready and ready -> queue (meas-long).

A move carries one stock's contents into another, so it must keep one unit.

**Fix** (`milp/steps.py`, `candidates.py`, `counter.py`): a move (plain, MIN, re-routed by the local search,
or into a counter) is offered only between stocks of one unit. A capacity may still read any unit (ready
caps the dispatch). Locally: none-short, none-long, counts-short and counts-long still pass. meas-short
loses its two cross-unit MINs and the MIN is right (whole-flow error 0.053). It still fails: inflight ->
responses_total is split into 0.15 x inflight plus MIN(0.29 inflight, 19.6 ready) and MIN(0.12 inflight,
0.68 retries), MINs fitted to the noise. meas-long took a different path: four spurious MINs, and the MIN
off by 45%. It failed before the change as well, on the retries split plus two cross-unit MINs.

On node2 (job 210), meas-short failed on one flow only: retries -> outside = MIN(0.58 retries, 0.04 queue).
retries is about 0.08 x queue, so which side is lower is decided by measurement error and flips from step to
step. **Second fix** (`milp/persist.py`): a MIN is kept only where its regime holds for stretches. The
Wald-Wolfowitz runs test on the regime sequence must show fewer runs than chance by more than 3 sd. Otherwise
the MIN is read as its demand alone and refitted. 306's true MIN has long stretches (the afternoon peaks).

Results:
- In a clone on node2: meas-short **passes** (MIN 3% off, retries 0.078 / 0.645 / 0.271).
- On the Mac the same code fails meas-short. The MIP takes another path there and keeps MIN(0.29 inflight,
  19.6 ready) beside 0.15 x inflight. Both sides of that MIN move slowly, so its regime holds and the test
  keeps it.
- none and counts (all four) still pass on the Mac.
- meas-long still fails on the Mac.

milp's answer on meas therefore depends on the machine (HiGHS' search under its 60 s limit). The pool
result is reported as it comes (job 212).

**Capability.** One mixed-integer program over every candidate flow, including MIN(a X, b Y) with per-step
regime binaries. It is followed by least-squares refits on one-step changes, counts' capped-drain
expectation, and counters in level space. It represents MIN natively. It is the only strategy that passed
306 before the capacity offer. On meas its misfit is still the one-step change, with the noise in the
regressors, and each MIN column can absorb the MA(1) noise of a stock. **Limitation: fixable** (an
output-error criterion for selection, below). **Should milp enter the roster: yes.** It passes 306 none and
counts (4/4), and 300-305 at c7cade0 except 300 meas-short/long and 305 counts-short. It duplicates no
survivor.

## coflow_hats, realistic_flows, lna_products, and held_out and milp on meas: errors in variables (not fixed)

Is this the data's limit? (rule 4b) No. An output-error fit of 306's **true structure** passes both meas
variants on this seed under the current scorer (H1's SEs, 3747e29; traffic fixed by the `input` kind). The
script is the session scratchpad's `q6/oe_true.py`:

- meas-short: MIN 0.595 / 38.9, drain 0.496, errors 0.031, retries 0.123 / 0.978 / 0.495;
- meas-long: MIN 0.607 / 39.8, drain 0.505, errors 0.031, retries 0.098 / 0.761 / 0.429.

The strategies fail because their structure is chosen on one-step fits whose regressors carry the error:

- **coflow_hats** (meas-long): MIN(0.38 queue, 24.8 ready), attenuated from 0.6. inflight's drain is 0.357,
  plus a link queue -> responses_total reading inflight, and retries -> errors_total. Its eiv refit was
  computed and rejected by its guard (z 3.16 > 2). The instrumented MIN coefficient was 0.24: m enters eiv as
  an exact input, so it is never instrumented. meas-short: capmin offers no MIN (the kink is lost in the
  noise), and inflight's drain is read as a link plus inflight -> queue reading retries.
- **realistic_flows**: the same structure as coflow_hats on meas-short, and close to it on meas-long. They
  are not duplicates: their found models differ on 583 of 1,484 shared cells and their statuses on 71.
- **lna_products**: its likelihood is counting noise (LNA), with no measurement error. On meas-short it keeps
  almost nothing: retries' outflow and a cross-unit move ready -> errors_total that eiv's move pass added (eiv's
  `_moves` does not check units). eiv reported weak instruments. On meas-long a MIN lands on queue ->
  responses_total, with a 501 x ready link into queue.
- **held_out** and **milp**: as above.

No small fix exists. A refit of the numbers keeps the wrong structure: coflow_hats' IV refit was computed
and rejected. What is needed is selection by an output-error (run) likelihood: drop, add, re-route and limit
flows priced on the model's runs against the measured levels. Another agent is building exactly that
(`earned_pieces/oe.py`, "one copy per strategy that uses it", docs/research/k8s-306-r3.md; uncommitted when
this was written). The fix for these five is a copy of it once it is committed and shown on 306. Not done
here: it would duplicate that work.

**Capabilities and limits (meas):**
- coflow_hats, realistic_flows: linear rows with co-flows and hats, the earned refit, and eiv. Fixable.
- lna_products: the LNA likelihood with product columns. Its noise model has no measurement error, but its
  eiv refit and the matrix fallback are what passed 300 and 303 meas. Fixable by the same OE copy, applied
  after its own reading.

None of the five is proposed for elimination.

## Open

- The rss floor in every `boundary.py` copy is absolute (1e-12). On noise-free data it decides near-ties by
  rounding and differs by platform.
- eiv.py does not instrument an offered capacity series. Its move pass ignores units.
- The pre-existing failure `tests/test_strategy_held_out.py::test_held_out_judge_prefers_constant_inflows_when_the_real_inflow_changes`
  also fails at c7cade0 without this change.
