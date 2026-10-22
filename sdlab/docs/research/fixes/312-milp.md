# 312 (k8s-cluster-autoscaler): milp, round 1

Status (2026-10-22, milp code b96a79e, pool job 310): **none-short passes 28/28.** none-long finds 27 of 28 parts
(job 307 on the Mac, 710 s; attempt 2 gave the same locally). In job 310 it **timed out on node2** at 1,800 s, as
the original code did there. The part it misses is the scorer's fault, not milp's: the truth itself fails that part
when its counter is written in its algebraically equal form (below). Fixing it needs a harness change, which is reported here and not made. counts-short and
counts-long are **data-limited** by the kill table, as on 310 and 311 (measured below), so they are not targets.

| variant      | achievable?                                                        | before (22ef051) | attempt 1 (d0e2b96, job 307) | attempt 2 (b96a79e, job 310) |
|--------------|--------------------------------------------------------------------|------------------|------------------------------|------------------------------|
| none-short   | yes                                                                | FAIL 17/28       | FAIL 22/28 (237 s)           | **PASS 28/28** (238 s) |
| none-long    | yes, but not as scored (the truth fails the same part)             | TIMEOUT (1800 s) | FAIL 27/28 (710 s)           | TIMEOUT on node2 (1800 s); 27/28 locally |
| counts-short | no: P(kill flow within 10%) = 0.36 at the bound, knots given       | ERROR            | ERROR (a bounds check)       | FAIL 15/28 (268 s) |
| counts-long  | no: P = 0.39 at the bound, knots given, heights at 512 and 560 free | TIMEOUT          | ERROR (a bounds check)       | FAIL 19/25 (388 s) |

Commands: `uv run sdlab-ladder job 310`, `uv run sdlab-ladder show 312-k8s-cluster-autoscaler --strategy milp --variant V`,
`uv run sdlab-ladder diff 312-k8s-cluster-autoscaler --strategy milp --variant V`.

## Diagnosis (rule 4b)

`analyse` gives "not analysed" on every variant (effect tables plus hidden stocks). The truth's flows reproduce every
row to the levels' rounding (scratchpad `m312/nodes_row.py`, `m312/truthrows.py`): on nodes, 0.5 H - 0.05 max(0, n -
max(2, pods / 2)) with H_{k+1} = H_k + 0.075 max(0, pending - max(0, 4 nodes - ready)) - 0.5 H_k. So on the none
variants every failure was the method's fault. The diff at 22ef051 (none-short) had five problems, each with its own cause:

1. **pending -> ready was not a room move** (`min(0.93 nodes, pending)`). The program wrote a MIN on the pair, and
   `room._Rows` refused any pair whose existing move was not a plain rate. On 311 the program happened to write a
   plain move there.
2. **pending's creations** (`max(0, desired - pending - ready)`) stayed a constant. hinge.py offers a gap on the
   stock's own unit plus the readers of the present flow. That flow read traffic and queue, which made 5 readers in
   all, over MAX_READS = 4, so the side was skipped.
3. **The nodes row** (new on this rung): the inflow is a DELAY1 of the pods that cannot be placed, and the outflow is a
   surplus over a target in another unit, with a floor (`max(2, pods / 2)`). milp offered neither form.
4. **none-long**: the program reads 150 evenly spaced steps. The dispatch cap `40 x ready` binds on 24 of 2,000 steps
   (the three node failures and one more stretch), so it wrote `queue -> inflight` as three flows, two of them MINs
   reading the wrong level (cpu and nodes). Then: the kill flow went to the counter's inflow alone, and the room's
   floored share was 0.26 < 0.5, because the kills were still in both rows. With the kill move placed by hand, the
   room is exact (share 1.0, `m312/hyp.py`).
5. **Spurious effect flows** (slopes of 1e-6 to 2e-6 on queue's and inflight's rows) fitted three things: the levels'
   rounding amplified 40 times through the binding MIN arm (the truth itself leaves 0.0018 there), the program's
   slightly-off numbers on rows no pass refits (`inflight -> responses_total = 0.499986`), and the 6-digit writing of
   the numbers.

The pool's first attempt (job 307) also showed that **the program's answer is not reproducible**. HiGHS stops at a
60 s time limit, so the pod block varies with the machine's load. In job 307 it was `pending -> ready = min(1.93
pending, 1.83 nodes)` with `ready -> pending = min(0.43 ready, 1.57 pending)`, which my cached local answer did not
have. Attempt 2 was tested on both answers (`m312/poolike.py` swaps job 307's pod block into the cached one).

## The none-long miss is the scorer's (harness fix needed, not made)

The last none-long part, `outside -> oom_kills_total [as a whole]`, is 2.018% off against a 2% tolerance. All of that
error sits on steps 704 and 1280, the steps just before the node failures inject `ready -= 3`:

- The data's counter follows the engine. Its increase on step 704 is 0.4145 = (ready - 3) x table(mem): the counted
  amount reads the injected level.
- The scorer computes the truth's `flow(oom_killed)` from the recorded engine amounts (`data["counters"]`, sim.py),
  so it gets 0.4144. It computes a found effect flow `ready x table(mem)` on the run's states **without** the step's
  injections (`score._levels_at`), so it gets 0.5191.
- The kill move `ready -> pending` itself is computed the same way on both sides, so it passes (error 7.6e-6).

**Proof:** the truth's flows, with the counter written as its algebraic equal `1 x ready x table(mem)` (the same
amount as `flow(oom_killed)` on every state), fail none-long on the same part at 2.018% (scratchpad
`m312/truthcounter.py`; none-short passes, since its kills are zero at the injection step). So none-long is not
achievable as scored by any model that writes the counter as a rate, which is the only option a found model has:
`flow(id)` reads the truth's recorded counters, and a found model has none.

**Harness fix proposed:** evaluate whole and effect flows on the states the engine's rates read, with the step's
injections added (milp's `Steps` does this: `read[i, k] = L + amount`). Or compare a truth `flow(x)` counter through
x's own rate on the same states. That is a scoring change (rule 5), so it goes to the user with before and after
statuses. 310 and 311 none-long passed only because their kills are zero at the injection steps.

## Data limit on the counts variants (rule 4b)

The bound script from 311-milp.md (scratchpad `m312/fisher_kill.py`) was run on the 312 data, with the truth's knots
given and only the listed heights free, the kills Poisson about `ready x table(mem)`. It reports the Monte Carlo
probability that the scorer's whole-flow error is within 10%:

| variant      | kill steps / kills | states with mem > 512 | heights free | median error | P(error <= 10%) |
|--------------|--------------------|-----------------------|--------------|--------------|-----------------|
| counts-short | 7 / 19             | 2                     | 512          | 0.142        | **0.36** |
| counts-short | 7 / 19             | 2                     | 512, 560     | 0.284        | 0.08 |
| counts-long  | 50 / 128           | 11                    | 512          | 0.050        | 0.82 |
| counts-long  | 50 / 128           | 11                    | 512, 560     | 0.119        | **0.39** |

The data reach past 512 on both counts runs, so the 560 height is read from those states, and the knots have to be
found too. Both variants are below 0.5, as on 310 and 311.

## Fixes kept

### hidden-delay: a DELAY1 in front of an estimated inflow, with a surplus outflow (new type; credits a hidden stock)

- **What (`delay.py`, d0e2b96):** for every measured stock S whose outside inflow side is declared "estimate", the
  row's target is S's change less the other flows on it. The inflow is (1 / tau) H, with H_{k+1} = H_k + sum_j k_j g_j
  - H_k / tau and H_0 = 0, and the k_j >= 0 by NNLS for a given tau. The drives g_j are chosen by forward selection
  (BIC) from the constant, the levels and inputs, and **each room move's unmet demand** max(0, x - max(0, b Y - D))
  for x = S or a S (the asking a capacity limit turns away). Where S's outflow side is declared, the outflow is fitted
  with it: none, a drain, or a **surplus c max(0, S - max(m, w . x))** over a target in any unit, the floor m tried at
  each reader step. tau is scanned on 12 values and polished. Drives and outflow are chosen in turn until neither
  changes (at most 3 rounds). The same search without a delay is the comparison. The stage is written only when it
  beats both that and the answer by 10 BIC and explains half the misfit above the rounding. It is written as
  `outside -> S_delay`, `S_delay -> S` (1 / tau) and `S -> outside`. It runs last, after hidden.py.
- **Effect:** on none-short the stage is exact: `0.0750016 x max(0, pending - max(0, 3.99999 nodes - ready))`, tau
  1.99998, and the outflow is `0.05 max(0, nodes - (0.5 ready + 0.5 pending))` (the floor never binds on the short run).
  On none-long the floor binds on 84 steps, and the hidden part and nodes' outflow are right (27/28).
- **Port:** copy `milp/delay.py`. It needs `hinge._amount`, `_env`, `_resolution` and `steps.Steps`, and reads room
  moves from their expression (`min(a * S, max(0, b * Y - D))`), so it works without milp's room module. Call it on
  the finished flows. A strategy that searches hidden stocks (hidden_transit, loop_transit, kalman_lna) could instead
  add "a first-order stage between a drive column and the stock" as one more hidden-stock shape.
- **Fires on** (stored milp answers, 281 of them, none-short and counts-long, non-realistic): 312, 134 (a DELAY1 on an
  input: the right structure), 136 and 142 (not delays). milp currently fails all three. Check them in the regression
  round.

### pair-revision: a pair's flows revised on every step (extends type 5 / type 9)

- **What (`pairs.py`):** a measured pair of one unit that the answer joins by a MIN or by more than one flow is
  compared on both rows (room._Rows: plain flows with both ends on the rows refitted, the rest held, the answer's
  non-plain flows at their amounts and charged their numbers). The plain move is compared with MIN(a S, b Y) for every
  capacity reader Y (grid, then least squares), and the best replaces the pair's flows on BIC > 10, each MIN arm
  binding on at least 5 steps. It runs first after the program, and again after the floored gaps.
- **Effect:** none-long `queue -> inflight` goes from three flows to `min(0.6 queue, 39.76 ready)` (gain 16,388), and
  after the gaps to `39.9928` (then 39.9992 after the polish).
- **Port:** any strategy whose structural search reads a sample of the steps, or whose MIN offers are fixed early:
  re-judge each MIN's capacity reader on all steps. Copy `pairs.py` with room._Rows.
- **Fires on** 7 stored answers (310 counts-long, 130, 311 counts-long, 101, 212, 312, 114). All fail today.

### joint-polish: every plain flow and MIN refitted on every row (extends type 9)

- **What (`polish.py`):** every plain flow and every `min(a S, b Y)` or room expression's (a, b) are refitted jointly
  on all measured rows, floored as the engine runs them (a declared input inflow held at 1 x the input, rows with a
  flow that reads a hidden stock left out). It is kept when the rows' BIC falls. It runs before each effect search, but
  only when pairs.py revised something, so other cases are unchanged.
- **Port:** a joint floored least-squares pass over the whole model before any search that reads residuals.

### room changes (extend room-min, 311)

- **room-replaces-MIN:** the room move may replace a non-plain program move on its pair. That move is held at its
  amounts in the answer's side and charged its numbers.
- **room-check-per-pair:** the CHECK list takes each pair's best ceiling. One bogus pair's six ceilings had filled it.
- **room-with-counted-move (extends type 6, counted flow):** when a room candidate's floored share falls short, it is
  re-judged with each counter's effect flow (an inflow, or a move into the counter) placed as the move it counts
  between the pair's stocks, with the program's stand-in on that pair removed. The placement and the room are kept
  together when they beat the answer by 10 BIC and the room explains half the misfit. None-long gain: 64,605.
- **room-retry:** if the first pass finds no room, it is tried again after the effects and gaps, followed by hinge,
  polish of the room, room.counted and hinge.
- **Port:** wherever a capacity form and a counted flow share rows, judge them together. Neither wins alone, because
  each one's misfit hides the other.

### gap-reader-fallback (extends type 3, floored rate)

- **What:** `hinge.refine` skips a side whose own-unit readers plus the present flow's readers exceed MAX_READS. Now
  it falls back to the own-unit readers. pending's creations become `-ready + desired - pending`.
- **Port:** a one-line change in any gap search that unions readers.

### effect guards (extend type 7, and type 10)

- **quiet-rows:** a row whose misfit under the current flows is within 2 times its rounding noise is not counted in
  an effect candidate's share. The noise is the row's own rounding plus the readers' rounding carried through the
  flows' slopes, at the run's finest resolution, since a stock whose levels happen to be whole is not rounded to 1. On
  281 stored answers it changed nothing.
- **materiality:** an effect flow must move at least 1e-5 of the rms gross amount through its rows. Numbers are written
  to 6 digits, so a smaller flow fits their rounding.
- **effect-own-MIN:** an effect candidate may replace a MIN the program wrote on its own pair, held at its amounts.
- **effect-prune:** at the end, an effect flow that is not a counted kill is dropped when its rows, with the rest
  refitted, are within the quiet bound without it.
- **pass-guard (type 10):** every new pass keeps its input if it raises. Job 307's counts items errored with
  `Initial guess is outside of provided bounds`. Least-squares starts are now also clipped into their bounds.

## Not fixed

- **none-long's counter**: a scorer fault (above), reported for a harness change.
- **counts-short and counts-long** (not targets: data-limited): the room, the delay and the surplus are not found
  (nodes' outflow is 42x and 2.1x off, and the hidden stage is missing). The kill and mem flows are 18-51% off. For
  the noise round later, the delay's fit needs a Poisson weighting, as the room's does (311-milp.md).
- **Run time:** none-long took 710 s on the Mac (job 307), of which the program is about 520 s, but it **timed out on
  node2** (job 310 at b96a79e, and 22ef051 before this round). Locally the passes after the program take 180 s, most of
  it in four hinge.refine calls of 25-114 s each (two of them come from the room retry). The next round should give
  hinge a work budget, as prune has, and measure on node2.
- **The program is not deterministic** (a time-limited MIP). The post-program passes now recover from both pod
  blocks seen, but a third answer could differ. A node limit in place of the time limit would make runs reproducible.
  That is a larger change, and it would move every case.
