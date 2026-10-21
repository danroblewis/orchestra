# 309 (k8s-pod-startup): milp

Status (2026-10-21, 15:50 PDT): **3 of the 4 plan variants pass at 5787b7f. counts-short still fails, and it is
data-limited.**

Where the results come from: pool jobs 257 (239a97f), 260 (2eb3828) and 261 (5787b7f, the final one: `uv run sdlab-ladder job 261`), and
`uv run sdlab-ladder show 309-k8s-pod-startup --strategy milp --variant V`:

| variant      | analyse (`sdlab-ladder analyse`) | before (4f04ce1)   | after (5787b7f, job 261) |
|--------------|-----------------------------------|--------------------|------------------|
| none-short   | "unidentifiable" (retries only)   | FAIL 13/18, 39 s   | PASS 18/18, 72 s |
| none-long    | "unidentifiable" (retries only)   | FAIL 13/18, 183 s  | PASS 18/18, 266 s |
| counts-short | data-limited, p 0.010             | FAIL 10/18, 53 s   | FAIL 16/18, 55 s |
| counts-long  | data-limited, p 0.253             | FAIL 12/18, 141 s  | PASS 18/18, 239 s |

On the none variants, analyse says "unidentifiable" only because the move retries -> queue with retries'
drain gives the same levels as a link. milp already got that right, as it did on 308. The parts that failed
(the pod flows) have bound SEs of about 1e-5, so I treated none-short and none-long as targets.
counts-long (p 0.25) passes anyway.

## Diagnosis (rule 4b)

- **The pod flows were a method fault.** The truth is `created = max(0, desired - pending - ready)` and
  `deleted = max(0, ready - desired)`. The engine floors every rate at 0, so these are plain linear rates
  that move nothing on the steps where they are negative, which is most steps where desired falls.
  milp's program fits the *unfloored* linear rate to the one-step changes. To match those zero amounts it
  shrank the gap (none-long: `0.34 desired - 0.338 ready - 0.333 pending`), or swapped it for a
  constant with pieces (none-short), or dropped it (counts-long: `1e-10`, and the pending -> ready move
  disappeared). Deletion became `0.003 ready`, and pending -> ready bent to 0.63 to make up the
  difference. Bound SEs are 1e-5 (none) and about 0.1 (counts-long) against allowed errors of 0.02 and
  0.1, so the data pin the numbers.
- **counts-short is a data limit.** Two parts fail. retries -> queue is 0.528 against a true 0.6, with an
  allowed error of 0.06. The bound SE is 0.127, so milp is 0.56 SE off, and p = 0.363 even for an
  estimate at the bound. The other failure is that cpu's inflow reads `desired` where the truth reads
  `ready`. The two are equal except on 38 of 300 steps, and a least-squares fit of cpu's row prefers
  ready by only 3.2 in -2 log L (on counts-long the margin is 42, and that variant passes). The case
  as a whole is p 0.010. I did not tune anything to this seed.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| floored-gap | `milp/hinge.py`, `refine(flows, stocks, run, opts, skip)`. It runs after the strategy's own search and the controller rules, and before the output-error refit. **Candidates:** each measured stock that is not a counter and not a whole-unit controller (`skip`), on each side where the boundary declares an estimated outside flow (or, with no boundary declared, on any side where the answer has one). **Rate:** `max(0, w . x)`, reading the constant, the measured non-counter stocks of the stock's own unit (a gap compares like with like), and whatever the stock's present flow on that side reads (at most 4 levels). **Fit:** the candidates are fitted together with the floor (scipy `least_squares`) on the one-step changes of the rows they touch. Alongside them go the plain moves on those stocks and, absent at first, every same-unit move touching a candidate stock. Expression flows on those rows (MIN, controller rules) are evaluated and held fixed. If one cannot be evaluated, nothing changes. **Search:** two starts, all readers or the answer's own readers, then stepwise by BIC: drop a reader of a gap, put a gap back to the answer's own readers, add or drop an absent move. **Kept** when BIC over the touched rows beats the answer as it stood by more than 10. The result is written as plain linear rates, because the engine's floor makes them `max(0, .)`. | 239a97f | Copy `hinge.py` with milp's `steps.py` (its only import). After the strategy's search and any controller rules, call `flows, note = hinge.refine(flows, stocks, run, opts, skip=<stocks whose flows are rules>)`, before any output-error refit. |
| gap-guards | This is the same mechanism with three guards, added after re-scoring milp's stored answers on every case showed false gaps. (1) A new gap must bind (unfloored rate below 0, and for an outflow only while its stock holds something) on at least 5 steps, and every free flow must act on at least 5 steps. Otherwise the gap goes back to the answer's own readers. (2) The answer is left as it is unless a gap or a move is new: no refit of numbers alone. (3) A row's misfit floor in BIC is the levels' rounding (resolution / sqrt 6; the 309 levels have 4 decimals) or 1e-5 of its typical change, and the rounding does not count on whole-number counts data. Without these, the re-scoring produced inflow/drain splits (`7.04 - 0.168 A` in, a dead `-0.06 A` out) on 039/044/045 none-short, `16 x gap - 15` on 309 none-short (fitting the 4-decimal rounding), and `0.55 A - 0.21` on 056-sweep-zero-floor#6 counts-long (the engine's whole-unit rounding of amounts). | 2eb3828, 5787b7f | Part of the copied `hinge.py`. Nothing extra to wire. |

Scope: I re-scored milp's stored answers with `refine` applied to them (`store.latest`, every non-realistic
case, none-short and counts-long; scratchpad scripts `scope.py` and `one.py`). These are re-scorings of
stored flows, not runs. At 2eb3828, the only cells that changed status were these:

- fail -> pass: 104-canonical-teacup and 106-canonical-workforce, counts-long.
- fail -> equivalent: 046-random-link-loop#6 and 224-distilled-inflow-switched-on-by-other-stock, counts-long.
- pass -> fail: 056-sweep-zero-floor#6, counts-long.

5787b7f fixes the 056 cell: `refine` leaves its answer unchanged, as I checked directly. Kubernetes 300-308 are
unchanged: wherever `refine` touched them, pass stayed pass. 317 was not reached before the check's time
limit. Per the plan, I ran no regression on earlier rungs.

Cost: on 309, `refine` takes 2-8 s. I did not time it on large cases. Its search tries every reader of
every candidate each round, so a case with many stocks of one unit could be slow (rung 317 has the most).
Watch for this on later rungs.

Tests: `tests/test_milp_hinge.py`. The first test recovers the gap and the move from a shrunk linear answer
on a pods model. The second checks that a plain drain is left alone.
