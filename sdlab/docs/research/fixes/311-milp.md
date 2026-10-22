# 311 (k8s-node-pool): milp, round 1

Status (2026-10-22, milp code ec2164b, pool job 297): **milp passes every achievable variant of 311.**
none-short and none-long pass 26/26. counts-short and counts-long fail and are **data-limited** by the same kill
table as 310 (measured below), so they are not targets.

| variant      | achievable?                                                   | before (cae16d8) | after (job 297, ec2164b) |
|--------------|---------------------------------------------------------------|------------------|--------------------------|
| none-short   | yes                                                           | FAIL 15/26       | **PASS 26/26** (223 s) |
| none-long    | yes                                                           | FAIL 14/23       | **PASS 26/26** (679 s) |
| counts-short | no: P(kill flow within 10%) = 0.25 at the bound, knots given  | FAIL 14/23       | FAIL 14/23 (204 s) |
| counts-long  | no: P = 0.36 at the bound, knots and the 5000 height given    | FAIL 17/23       | FAIL 17/23 (935 s of 1800) |

Commands: `uv run sdlab-ladder job 297`, `uv run sdlab-ladder show 311-k8s-node-pool --strategy milp --variant V`,
`uv run sdlab-ladder diff 311-k8s-node-pool --strategy milp --variant V`.

## Diagnosis (rule 4b)

The diffs before the fix (cae16d8): `pending -> ready` came out as `0.0155 x pending` (97.9% off as a whole flow),
the gap flows on pending and ready were bent (ready's deleted 1.14 / -1.16), the kill move `ready -> pending` was
missing (only the counter's inflow carried it), and mem's hidden stock was drained by a constant instead of the kill
table. All of it comes from one missing form. The truth's start rate is `min(0.5 pending, max(0, 4 nodes - ready))`,
and the room binds on 172 of 300 steps (none-short) and 1,094 of 2,000 (none-long), because ready sits at 12 = 4 x 3
nodes at the peak and the node failures cut the room. milp's program offers `MIN(a X, b Y)` with one capacity
level, not a room (a ceiling less the receiver's own level). So the ready and pending rows were left misfit, and the
gaps, the kill move and mem's hidden drain were each fitted around that misfit. The truth's flows reproduce every
row to rounding (scratchpad `rows.py`), so on the none variants the failure was the method's fault.

**The counts variants are data-limited** (the bound script from 310-milp-r2.md run on the 311 data,
`scratchpad m311/fisher_kill.py`). The kill flow `ready -> pending x table(mem)` is scored as a whole within 10%.
Kills are Poisson about `ready x table(mem)`. Holding the truth's knots and giving only the heights shown:

| variant      | kill steps / kills | states with mem > 512 | heights free | median error | P(error <= 10%) |
|--------------|--------------------|-----------------------|--------------|--------------|-----------------|
| counts-short | 4 / 9              | 0                     | 512          | 0.206        | **0.25** |
| counts-long  | 46 / 88            | 5                     | 512          | 0.065        | 0.69 |
| counts-long  | 46 / 88            | 5                     | 512, 560     | 0.125        | **0.36** |
| counts-long  | 46 / 88            | 5                     | 512, 560, 5000 | 0.153      | 0.22 |

An estimator has to find the 560 height from the 5 states above 512, as well as the knots. So, as on 310, counts-long
is data-limited (0.36 < 0.5) and counts-short more so.

## Fixes kept (ec2164b)

### room-min: a room-limited move, MIN(a S, MAX(0, b Y - D)) (new type)

- **What:** a move S -> D between same-unit measured stocks carries the source's demand, or the room left in the
  receiver under a ceiling proportional to another level Y (any unit, not a counter, or an input). `room.py`
  tries every such pair against every such Y. For a given (a, b) the move is one fixed column, and the plain flows
  on the two rows are refitted with it by least squares (profiled). An outside flow on those rows also reads its
  unit's levels and a constant, in both the base and the candidate. (a, b) start from a grid and are polished,
  first by least squares and then with a soft-L1 loss at the residual's MAD. A candidate is kept on BIC > 10 over
  the two rows, at least half of one row's misfit explained, and each arm binding on at least 5 steps where the move
  carries something (otherwise it is a plain move or a plain capacity, which the program already offers). For the
  best 3 candidates by gain whose share falls short, the comparison is redone with the outside flows **floored** as
  the engine runs them (`hinge._Fit`), with (a, b) fitted jointly with them. On none-long the unfloored gaps had left
  the share at 0.44, while the floored check gives 0.84 and a gain of 6,466. The move is written as an expression,
  `min(a * S, max(0, b * Y - D))`.
- **Room polish:** after each later pass, each room move is refitted jointly with the plain flows on its two rows
  (floored, each with its own readers, including a same-pair plain move, which is dropped if it is refitted to
  nothing), and all of them are written back.
- **Pipeline (`__init__._after_program`):** program -> room -> (if a room was found) hinge -> room -> effects ->
  room.counted -> hinge (-> effects -> hinge) -> room polish -> oefit -> hidden. With no room move, the pipeline is
  exactly as before.
- **Effect:** none-short and none-long go from fail to pass. The room comes out at 0.499997/3.99999 (none-short)
  and 0.499762/3.99971 (none-long).
- **Port:** copy `milp/room.py` (it needs `hinge._Fit`, `_amount`, `_plain`, `_rate`, `_resolution`, `_env` and
  `steps.Steps`; a strategy without them copies those from milp/hinge.py at ec2164b). Call `room.refine(flows,
  stocks, run, opts, skip)` on the structural answer before the floored-gap refit, then the refit, then
  `room.refine` again (which polishes). A strategy with a capmin offer could instead add a room column `max(0, b Y -
  D)` to its MIN capacities. Every strategy fails 311 for want of this form.
- **Guard measured:** `room.refine` on the 280 stored milp answers (none-short and counts-long, every non-realistic
  case) fires only on 311 (scratchpad `m311/fires.py`).

### counted-move-after-room (extends type 6, counted flow)

- **What:** `effects.py` tries the counted move `ready -> pending` with the other flows' numbers as they stand. The
  room move had been fitted while the kills were missing, and its ceiling binds on the same steps, so it had bent to
  absorb them. The counted move then scored below the counter's inflow alone (1,571 against 1,762 in BIC).
  `room.counted` takes a counter's effect inflow reading R (in the counter's unit) and tries each move R -> X with
  the same amount, replacing a plain R -> X move. It polishes the room moves with the move in and with it out, and
  keeps the move when the two rows' BIC falls by more than 10 (the move adds no numbers). Gains were 1,569
  (none-short) and 62,477 (none-long). With the kill move in place, mem's hidden stock is drained by the kill table
  (310's mechanism), and leak and its reset are matched.
- **Port:** wherever a counted flow is chosen beside another nonlinear flow on the same rows, re-polish that flow
  before comparing the two placements.

### gap-side-unblock (extends type 3, floored rate)

- **What:** in `hinge.refine`, if a gap candidate cannot act and the side has no plain rate to go back to (here mem's
  outflow, a MIN expression in the program's answer), that failed the whole full-reader trial. The search then kept
  the answer's own readers whenever that second start fitted, so pending's and ready's gaps stayed a constant and
  `0.0069 ready`. Now a failed full-reader trial with such a side reruns the search with that side left as the
  answer has it (the existing `avoid` recursion, which before ran only when both starts failed). On none-long the
  gaps became 1.00002 / 0.999998.
- **Port:** a one-line change wherever a joint gap fit reverts all sides because one side is invalid.

## Not fixed (not targets: data-limited variants)

- counts-short: the room is found (0.5046 / 4.0124), but a plain `0.0168 pending` stays beside it on the same pair
  (whole flow 31.9% off). Also retried, errors, cpu's ready link and mem's drain are 15-26% off.
- counts-long: the room move is not found in the pool run (`pending -> ready = 0.0404 pending`). `room.refine` on the
  old stored counts-long answer does fire (gain 3,418), so in the new pipeline something earlier on the ready and
  pending rows keeps it out. This is not diagnosed. mem's hidden stock does not fire on counts, as on 310
  (310-milp-r2.md). For the noise variants later, the room's comparison needs a Poisson-weighted fit, and polish
  should drop a same-pair plain move by BIC, not only when it is refitted to zero.
- Run time: counts-long took 935 s, none-long 679 s, against the case's 1,800 s limit.
