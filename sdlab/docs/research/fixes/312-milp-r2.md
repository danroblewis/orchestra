# 312 (k8s-cluster-autoscaler): milp, round 2

Status (2026-10-22, milp code 67c8919, pool job 320, all four items on the Mac): **none-short passes 28/28.**
**none-long finds 27 of 28 parts in 669 s** (round 1: 710 s on the Mac, and a timeout at 1,800 s on node2). Its one
miss is still the scorer's counter, not milp's: re-checked today on the current scorer, the truth with its counter
written as `1 x ready x table(mem)` fails the same part at 2.018% (scratchpad `m312/truthcounter.py`; 312-milp.md has
the cause and the proposed harness fix). counts-short and counts-long stay data-limited on the kill flow (312-milp.md,
"Data limit"), so they are not targets. So no achievable variant is left failing for a method reason.

| variant      | achievable?                                              | round 1 (b96a79e, job 310)            | round 2 (67c8919, job 320) |
|--------------|----------------------------------------------------------|---------------------------------------|----------------------------|
| none-short   | yes                                                      | PASS 28/28 (238 s)                    | **PASS 28/28** (247 s) |
| none-long    | yes, but not as scored (the truth fails the same part)    | TIMEOUT on node2; 27/28 on the Mac    | FAIL 27/28 (669 s): the scorer's counter only |
| counts-short | no: P(kill flow within 10%) = 0.36 at the bound            | FAIL 15/28                            | FAIL 14/28 (312 s) |
| counts-long  | no: P = 0.39 at the bound                                  | FAIL 19/25                            | FAIL 21/25 (433 s) |

Commands: `uv run sdlab-ladder job 320 --json`, `uv run sdlab-ladder diff 312-k8s-cluster-autoscaler --strategy milp
--variant V`, `... --between b96a79e 67c8919`.

## Diagnosis (rule 4b)

Round 1 left one method problem on an achievable variant: **none-long ran past the 1,800 s limit on node2.** A
profile of the program on none-long (scratchpad `m312/profprog.py`, Mac, single-threaded) gave 531 s, of which 285 s
were the SVDs inside scipy's `least_squares` (trf, exact solver). 145 s of it was one call: `_with_steps` at factor 2.
The change-point partition (`_changes`) of what an estimated inflow's row leaves found about 450 steps per inflow
in the 2,000 steps' rounding. All of them (959 numbers) were refitted together on every step, five rounds, and then
all but the largest 20 per inflow were dropped anyway. An SVD of 24,000 x 959 per iteration is the cost. node2's
OpenBLAS is about 2x slower than the Mac's Accelerate at these SVDs (measured: 24,000 x 100, 151 ms vs 67 ms;
scratchpad `m312/svdbench.py`), which explains why the Mac finished and node2 did not.

Capping those steps made the program's answer different, the third answer seen (HiGHS is time-limited). From it the
post passes reached **23/28**. The pending gap `desired - pending - ready` bent to 1.075 with a constant of -0.077,
the room's a to 0.4948, and the kill table's height fell to 2.99 (3.6% off). Every flow had the right form. Each pass
refits its own numbers with the others held: the kill table was fitted while the room was still missing, and
the gap was fitted beside the low table. Each one's error held the others in place (scratchpad `m312/trace.py`
traces every stage).

## Fixes kept

### step-budget (type 10, guards and budgets; new)

- **What (`__init__._largest`, `_step_cap`, `STEP_HEADROOM`):** `_with_steps` keeps at most 2 x the steps it will
  finally keep per estimated inflow (`max(2, T / 100)`). The partition's change points are kept by the size of the jump
  between their stretches' means. The cap that was applied after the refit is unchanged.
- **Effect:** `_with_steps` 145 s -> 3.4 s and 49 s -> 4.9 s on none-long. The program took 528 s before and 288 s
  after on the same HiGHS answers (`m312/prog3.py` replays them). On none-short the steps stage is unchanged in size
  (77 numbers) and the result passes.
- **Port:** any strategy that offers a piecewise-constant inflow from a change-point partition on long runs
  (`_changes`-style optimal partitioning): bound the change points before the joint refit, not after. The SVD cost
  grows with the square of the numbers.

### joint-polish-tables (extends type 9, the joint polish)

- **What (`polish.refine(..., tables=True)`, `polish._tabled`):** the joint floored refit of the plain flows and the
  MIN and room expressions now also frees the heights of each table effect on a proportional rate. The amount is
  linear in the heights. A move and the counter inflow that counts it share one table, so they share its heights.
  A knot the effect search put at 0 stays at 0. It runs once at the end of the post passes (after effects.prune), when
  a room and an effect were both found. It is kept only if the BIC over the rows falls.
- **Effect:** on the new answer it goes from 23/28 to 27/28 (gap -1.00089 / 1.00089 / -1.00063, room `min(0.500028
  pending, max(0, 4.00001 nodes - ready))`, table height 3.105). On round 1's answer it stays at 27/28, with numbers to 6
  digits. none-short passes on the round-1 answer, on job 307's pod block and on a fresh program answer.
- **Port:** wherever a capacity form, a floored gap and an effect table share rows, refit their numbers together at
  the end. Polishing each one alone leaves a stable wrong point: each one's misfit is fitted by the others. In
  strategies with a final joint least squares (structures' moves.py, combined2, kalman_lna rows), the change is to
  add the table heights as linear columns `table_basis_m(x) x reader`, tied across the move and its counter.

## Not fixed

- **none-long's counter:** the scorer's fault (312-milp.md). The harness fix is still proposed, not made: evaluate
  whole and effect flows on the states with the step's injections added.
- **node2 run time is not measured.** Job 320's four items all ran on the Mac. With the steps budget, the program's
  least squares is 288 s on the Mac's answers, against 528 s before. At node2's 2x SVD cost that is about 1,100-1,300 s
  in all, under the 1,800 s limit, but that is an estimate. The rest of the time goes to three prunes (160 s,
  budgeted by PRUNE_WORK) and the post passes' hinge.refine calls (about 100 s).
- **counts (not targets):** counts-long now finds the kill move and its table, and misses the hidden nodes stage
  (a 27-span schedule stands in for it, which is not robust and is scored as missing), the hidden leak, the room
  (46%) and the counter (51%). counts-short gained a spurious `inflight -> queue` (0.093). A Poisson-weighted delay
  fit remains the proposal for the noise round.
- **The program is not deterministic** (a time-limited MIP). Three different answers have now been seen. The post
  passes recover from all three, but a fourth could differ.
