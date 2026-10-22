# Port of the kubernetes climb's fixes to censored (rungs 308-311)

**Status:** done, 2026-10-22, agent port-censored. Three rounds of fix and pool test. Final code: commit 3de593d
(pool job 398). The plan (the user, 2026-10-22): apply the climb's fixes (docs/research/fix-ledger.md) to five more
strategies and run 308-311; this is censored's part.

**Result:** censored now passes 308-311 on none-short and none-long, and 308 counts-long, the same cells as the
top 5 after the climb (308 PPFP, 309 PPFF/PPFP, 310 PPFF, 311 PPFF). Before the port it passed none of the 16 cells.
The 32 cells of 300-307 pass before and after, so there is no regression there.

## Before and after, per cell

Cells are status and parts right, from `uv run sdlab-ladder job <id> --json`. Before is job 378 at 7c3fb13 (the
sdlab HEAD the port started from). After is job 398 at 3de593d. The rounds in between were job 383 (cce1df6) and
job 395 (3ee7e17).

| rung | variant | before (378) | round 1 (383) | round 2 (395) | after (398) | target? |
|---|---|---|---|---|---|---|
| 308 | none-short | F 10/12 | P 12/12 | P 12/12 | **P 12/12** | yes |
| 308 | none-long | F 10/12 | P 12/12 | P 12/12 | **P 12/12** | yes |
| 308 | counts-short | F 8/12 | F 10/12 | F 10/12 | F 10/12 | no: data-limited (analyse p 0.094) |
| 308 | counts-long | F 10/12 | P 12/12 | P 12/12 | **P 12/12** | yes |
| 309 | none-short | F 11/18 | P 18/18 | P 18/18 | **P 18/18** | yes |
| 309 | none-long | F 7/18 | P 18/18 | P 18/18 | **P 18/18** | yes |
| 309 | counts-short | F 5/18 | F 8/18 | F 8/18 | F 7/18 | no: data-limited (p 0.010) |
| 309 | counts-long | X (LinAlgError in oefit) | F 15/18 | F 15/18 | F 15/18 | no: data-limited (p 0.25) |
| 310 | none-short | F 4/23 | P 26/26 | P 26/26 | **P 26/26** | yes |
| 310 | none-long | X (LinAlgError in oefit) | P 26/26 | F 21/26 | **P 26/26** | yes |
| 310 | counts-short | F 7/23 | F 9/23 | F 9/23 | F 9/23 | no: data-limited (measured bounds, ledger) |
| 310 | counts-long | F 4/23 | F 16/23 | F 15/23 | F 7/23 | no: data-limited |
| 311 | none-short | F 10/23 | P 26/26 | P 26/26 | **P 26/26** | yes |
| 311 | none-long | F 10/23 | F 18/26 | F 26/26 (an extra term) | **P 26/26** | yes |
| 311 | counts-short | F 8/23 | F 9/23 | F 12/23 | F 12/23 | no: data-limited |
| 311 | counts-long | F 7/23 | F 7/23 | F 10/23 | F 8/23 | no: data-limited |

The parts count goes up from /23 to /26 on 310-311 because the found hidden stock is matched to the truth's leak
(`hidden_match.py`), and its flows are then scored.

Discovery times in job 398: at most 448 s (310 counts-long) and 417 s (311 none-long), against the 1800 s limit.
The baseline's slowest run was 644 s.

Achievable cells: 9 of the 16 (none-short and none-long on all four rungs, and 308 counts-long). censored passes
all 9. The 7 it fails are the ledger's data-limited cells. 309 counts-long is data-limited (p 0.25), although
combined2, milp and kalman_lna pass it; censored is at 15/18 there.

## Regression check, 300-307

Jobs 378 (before) and 398 (after), 300-307 x {none-short, none-long, counts-short, counts-long}: 32/32 pass before,
and 32/32 after (also 32/32 in rounds 1 and 2). Locally, `tests/test_ladder_censored.py` (024, 025, 003, 062, 125,
200, 218, 216, phys-newton-cooling and the new k8s tests) passes at 3de593d. Other ladder cases (001-2xx) were not
re-run on the pool. The post-stages run on every case, so the main line's backlog will re-score censored there.
That is the open risk; see below.

## What was ported

censored's base is the earned matrix main line plus its own floor, cap, gap and exact rewrites. The climb's
mechanisms are stages that run after a base. The most complete self-contained set is structures' (it passes
308-311 none-* and 317 none-short), so its post-stages were copied whole into `censored/post/` from structures at
dd9d8d1 (the package as of sdlab 7c3fb13). They run in structures' order (`post/__init__.py`):

| ledger type | what | where in censored |
|---|---|---|
| 2 controller | quantized controller rule (HPA) | `post/controller.py` |
| 3 floored rate, 4 actuator's smeared moves | declared estimated sides refitted as `max(0, c + w.X)`, with a stock's move dropped | `post/floor.py` |
| 5 capmin guards | source-row guard and unit guard (from engine_forms 740ed95), trimmed-gain guard (from structures c6fa9ea) | `capmin.py` (censored's own offer) |
| 6 counted flow | counter as `A x table(X)`, placed as the move it counts | `post/counted.py` |
| 9 repair | missing plain moves added and rows refitted, active set | `post/repair.py` |
| 10 guards and budgets | each stage under the runner's timer less 90 s; a stage that raises leaves the answer as it was (refit-guard) | `post.timed` |
| 11 hidden integrator | the leak written as the model's own stock `h_<S>`, with `inferred_levels` | `post/hidden.py` |
| 12 room-limited move | `min(a X, max(0, b Y - d Z))`, then polished last | `post/room.py` |
| 13, 16 best-subset rows and moves | rows rebuilt by best subset and paired into moves | `post/rebuild.py`, `post/moves.py` |
| 14 delay stage | hidden DELAY1 into a measured stock | `post/delay.py` |
| 15 injection- and expression-aware rows | `steps.adjust`; `judge.Model` runs MIN, room and controller expressions | `post/steps.py`, `post/exprs.py`, `post/judge.py` |
| 17 earn | coflow-earn (`moves.coflows`); new here: room earn and term earn (below) | `post/moves.py`, `post/room.py`, `post/earn.py` |
| 0 declared last | a declared side the stages dropped is filled again | `post.declared_last` |

### Changes the copy needed for censored's base (each found by the diff, rule 4b)

1. **A flow in pieces is read as its pieces** (`post/hidden._amount`, `post/steps.TIMES`). censored's main line
   writes declared sides and counters' inflows as pieces (`inflow`), with a placeholder `rate`. The copied stages
   read the placeholder as a constant. On 024 that made rebuild replace A's true pieces (a regression in the
   censored tests), and on 311 none-long it hid ready's row and the counter's row from room and repair. The pieces
   are now evaluated at the step times, as `simulate._Segments` evaluates them.
2. **On a declared estimated side, the floor may replace a profile** (`post/floor.py`). Before, a side in pieces
   was always kept. The judge charges every piece (params.numbers), so the BIC decides. This fixed 311 none-long,
   where ready's scale-down had been written as 36 pieces. On undeclared cases a profile is still kept (024's
   pieces are the truth).
3. **capmin's source-row guard and unit guard** (type 5). Without them, censored offered `MIN(desired, theta
   ready)` on 309, whose kink is the pod floors, and the gap rows then read it (309 none-short F -> P).
4. **The room is refitted inside the counted-move try** (`post/counted.py`, the same idea as milp's
   counted-move-after-room, ec2164b). The room move, fitted before the OOM kill move was in, had absorbed the kills
   (311 none-short: `4.96 nodes - 1.26 ready`), so the kill move did not pay. It is now polished with the move in,
   before the move is judged (311 none-short F -> P).
5. **Room earn** (`room.earn`, type 17). A room fitted before the counted and hidden stages can stand in for them
   (310 none-short: `min(0.5 pending, max(0, 0.006 inflight - 0.03 desired))`, a room no capacity sets). At the end,
   each room move is tried as its plain arm with its rows refitted. The room is kept only when it wins by room.py's
   own price, 6 log n (310 none-short F -> P).
6. **The trimmed-gain limit guard, and no offered series in rebuilt rows** (`capmin._trimmed`, `post/rebuild.py`).
   Once pieces were readable (change 1), rebuild rewrote 310 none-long's gap sides on the offered
   `MIN(ready, 2801 pending)`, and the floor keeps any side that reads an offered series. That was the round-2
   regression, P -> F 21/26. Rebuild no longer reads offered series; the floor fits those sides.
7. **Term earn** (`post/earn.py`, type 17, with milp's pair drop idea from d44d014 written anew). A floored side
   fitted mid-pipeline kept terms that move nothing on the run. 311 none-long had `max(0, 12 + ready - desired -
   4 nodes)`: while a node is down, ready stays at least 4 below desired, so `12 - 4 nodes` never acts. Each number,
   and each pair of numbers, of an estimated outside linear rate is tried dropped, and the drop is kept when the
   judge's BIC falls (311 none-long F 26/26 -> P).

### Not ported, and why

- **Type 1 zero-term prune** and **type 18 conserving drawing**: no failing cell of 300-311 needed them.
- **Types 7 (milp/kalman_lna effect tables, derived columns) and 8 (schedules)**: structures' `hidden.py` (type
  11) already reads the per-unit ratio `inflight / max(1, ready)`, and type 8 is superseded.
- **structures' own capmin offer** (several limits, fixed pools; types 12 and 13 on 316-317), and the 19 lines of
  structures' oefit that go with it: censored keeps its own single offer and oefit, because 300-311 need neither.
  Rungs 312-317 would need them, along with structures' shared room (`room._family` is copied but is fed only
  single-limit offers).
- **combined2's oefit-guard**: not needed separately, because `post.timed` catches any exception in the refit. This
  removed the two baseline errors (LinAlgError in oefit on 309 counts-long and 310 none-long).

## Commands and jobs

- Lock: `sh scripts/strategy-lock.sh acquire censored port-censored` (released at the end).
- Baseline: `uv run sdlab-ladder submit --strategies censored --cases 300,...,311 --variants
  none-short,none-long,counts-short,counts-long --priority 400 --by port-censored`, which gave job 378 (7c3fb13).
- Round 1: cce1df6, job 383. Round 2: 3ee7e17, job 395. Round 3: 3de593d, job 398 (the same 48 cells each time).
- Diagnosis: `uv run sdlab-ladder diff <case> --strategy censored --variant <v>` (and `--summary`), plus a stage
  trace run in-process the way `runner.discover` runs it, to see what each post-stage changes.

## Open risks

- The post-stages run on every case. Only 300-311 and the censored unit tests were checked. The earlier ladder
  (001-2xx, the realistic examples) and the demos' cached found models (`~/.cache/sdlab/demos/`, not touched) may
  differ when they are re-run. The profile refit applies only on a declared boundary, but rebuild, moves, floor,
  room, repair, counted, hidden, delay and earn run everywhere.
- `post/earn.py` runs the full judge once per candidate drop: 12-34 s on 311 (2000 steps). It runs under the stage
  timer.
- The meas (noise) variants were not tested. Neither were 312-317.
