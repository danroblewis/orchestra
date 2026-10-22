# 316 (k8s-shared-database): milp, round 1

Status (2026-10-22, code f01cf7a; pool job 352): **milp passes every achievable variant of 316**: none-short,
none-long and counts-long pass 16/16, complexity 32 against 32 (1.00x). counts-short fails and is
**data-limited** (`analyse`: p 0.407, so it is not a target). Three fix commits: 2846e1f, 2a2e196 and f01cf7a.

| variant      | achievable? (`analyse`)                                   | before (59d2ccf)                 | round 1 (f01cf7a, job 352) |
|--------------|-----------------------------------------------------------|----------------------------------|----------------------------|
| none-short   | yes (p 1.000)                                             | FAIL 12/16 (110 s)               | **PASS 16/16** (278 s)     |
| none-long    | yes (p 1.000)                                             | FAIL 12/16 (354 s)               | **PASS 16/16** (501 s)     |
| counts-short | **no**: p 0.407 (the two query links' SE 18% and 12% against an allowed 10%) | FAIL 12/16           | FAIL 14/16 (348 s)         |
| counts-long  | yes (p 0.844)                                             | FAIL 2/16 (1739 s of 1800)       | **PASS 16/16** (729 s)     |

Commands: `uv run sdlab-ladder job 345|349|352`, `uv run sdlab-ladder diff 316-k8s-shared-database --strategy milp --variant V`
(none, 17 unchanged, at f01cf7a), `uv run sdlab-ladder show ... --variant V`, `uv run sdlab-ladder analyse 316-k8s-shared-database --variant V`.

Intermediate jobs: job 345 (2846e1f) gave PPFF: counts-long had no room and junk inflows. Job 349 (2a2e196) gave
none-short "fits" (`db_active -> outside` written as `min(0.80 db_active, 0.40 pricing_inflight)`), none-long and
counts-long pass, counts-short fail.

## Diagnosis (rule 4b)

The truth adds `db_waiting -> db_active = min(0.8 db_waiting, 80 - 0.2 db_active)`, fed by two links
(`0.06 pricing_inflight`, `0.1 cart_inflight`) and drained by `0.8 db_active`. The diff before the fix (59d2ccf):
the db flows were missing, and `hidden.py` had invented a hidden stock `db_waiting_hidden` with a ratio expression.
A trace of the passes (scratch script running `_identify_program`, then each `_after_program` pass) found three method
faults. None of them is a data limit: on the none variants the truth reproduces every row to rounding.

1. **The move was never offered.** db_waiting is in `queries` and db_active in `connections`. milp offers a move
   only between stocks of one unit (`Steps.same_unit`). The declared boundary gives db_waiting only inflows and
   db_active only an outflow, so no drawing other than the move exists (a link plus a drain would be an invented
   boundary). The program had nothing to drain db_waiting with.
2. **No form for a pool.** The room of `room.py` (k8s-311) is `max(0, b Y - D)`: a ceiling proportional to a level,
   less the receiver at weight 1. A pool is a **constant** ceiling with the receiver at its own weight (80 - 0.2
   active: 80% of the connections are released and reused within the step). The program's MIN reads one level and
   cannot write it either.
3. **The program's readers bent around the missing mechanism.** db_waiting's inflow took stand-in readers
   (`traffic`, `pricing_queue`) and time pieces, and the room pass held that byTime flow fixed. Once the room was
   found, its numbers bent to match (`67.7 - 0.032 db_active`). On counts-long the queue inflows also kept counter
   and constant terms, and a spurious move `pricing_inflight -> catalog_queue` took part of catalog_queue's link
   (0.263 against 0.3). On none-short in job 349 the program wrote the drain as a capacity MIN.

Two counts-specific faults showed after (1) and (2):

4. **The room's share test counted Poisson scatter as misfit.** On counts-long the right room won by 1,711 in BIC
   but explained only 0.353 of the rows' misfit (SHARE 0.5), because most of that misfit is count noise no flow
   explains.
5. **"Either side alone" offered too many cross-unit moves.** The first version of (1) let every request queue move
   into the pool. On counts-long the program took `cart_queue -> db_active = 0.0134`, which bent the drain to 0.86.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|---|---|---|---|
| **boundary-forced cross-unit move** (new) | `Steps.same_unit(a, b)` is also true when the boundary is declared, a has no declared outside outflow, b has no declared outside inflow, neither is final, and **each is the only stock of its unit** (a has no same-unit receiver, counters included; b has no same-unit non-final source). Undeclared boundaries are unchanged. | 2846e1f, tightened in 2a2e196 | wherever a strategy pairs moves by unit (capmin's `_same_unit`, the earned family's unit pairing, kalman_lna `rows.py`, combined2/structures move offers): add this exception. It needs only `run["boundary"]` and the units. |
| **pool room** (extends room-min, k8s-311) | `room.py` adds a **constant ceiling** (ceiling reader None) with the receiver's weight e free: `min(a S, b - e D)`. The grid is a x e (1, .5, .25, .1, .05) x the ceiling b/e, log-spaced from the median of D to 10x its top, then polished by least squares and soft-L1. Level ceilings keep e = 1. | 2846e1f | a strategy that has room.py (or a capmin copy) adds the constant column `b - e D` beside its level ceilings. One that lacks a room copies milp/room.py at f01cf7a. |
| **floor written only where seen** | the room's `max(0, .)` is written only if the fitted room falls below 0 on the run (311: on 30-247 steps, so it is kept; 316: never, minimum 56, so the room is written plain). A floor that never bound is "fits", never the truth's equation (rule 5, 2026-10-21). | 2846e1f | any strategy that writes a floored capacity or room: test the inner expression's minimum on the run before wrapping it in `max(0, .)`. |
| **inflow re-read around a room** (reuses the 315 rowwise best-subset type) | `room._reread` / `_settle`: each outside inflow on a room's rows is re-read by **exact best subset** (1-3 readers from the program's offer: the constant, the inputs, the other levels, and its own level as a gap; signs enforced). Every other flow stays at its amount, and the result is judged by row BIC against the inflow as it stands, its pieces paying their numbers. The room is then polished jointly with the plain inflows, and this repeats until the readers stop changing. | 2846e1f | structures' rowwise best subset (ee94317) and combined2's sparseblock.py are the same idea. Run it after any pass that adds a nonlinear flow to a row. |
| **noise-aware share** | `room._share`: the share of misfit a candidate explains is measured against `rss0 - noise`, where noise is the row's expected Poisson residual (the counts its flows move, in the row's weights). It is zero when the levels are not counts, so the none variants are unchanged. | 2a2e196 | any share or explained-fraction gate (room.py copies, hinge gates, effects gates) on counts data subtracts the expected count noise first. |
| **tidy pass** (new, `milp/tidy.py`) | at the end, before hidden.py: (0) each program `MIN(a S, b Y)` (not a room) is tried as its demand `a S` alone, with the inflows re-read and the rows' plain flows refitted, and kept if its rows' BIC falls; the rooms are then settled again. (1) Every estimated outside inflow is re-read by exact best subset. (2) Each plain move between measured stocks is tried away (inflows re-read, rows refitted jointly) and dropped when the two rows' BIC falls by more than 2. | 2a2e196, f01cf7a | copy milp/tidy.py with room._reread and _count (they need hinge._amount/_plain/_rate). It is a general final clean-up for any strategy whose search ends with stand-in readers or small moves. |

None of them names a stock, unit or case. On 316 they give: none-short `min(0.800001 db_waiting, 80.0003 -
0.200003 db_active)`, inflow `0.0600002 pricing_inflight + 0.1 cart_inflight`, drain `0.800001`. On counts-long
(local trace) the room is `min(0.828, 81.4 - 0.193)` and the drain 0.826.

Cost: none-short 110 -> 278 s, none-long 354 -> 501 s, counts-long 1739 -> 729 s. The program's searches are larger
with the cross-unit move, but counts-long no longer ends in a misfit search that runs against the limit.

## For the regression run

- **311** (room with level ceiling): its room goes negative on the run (30-247 steps), so `max(0, .)` is still
  written, and e stays 1 for level ceilings. Changes there: `_settle` re-reads pending's and ready's inflows after a
  room is placed, and the share gate is noise-aware on counts (311 counts are data-limited). Check 311 none-short and
  none-long.
- **tidy.py runs on every case.** It changes a flow only when a row's BIC falls. Check era and step cases (an
  inflow's pieces are re-read and kept only if they lose), 309 gap flows (own level as a gap reader), 312 (MINs
  tried as demand alone), and 315 counts-long (inflow re-read; it should agree with net-gross and pair-drop).
- `Steps.same_unit`'s exception needs a declared boundary and two stocks each alone in its unit. On the earlier
  rungs every pair of moving stocks shares a unit, so no new offer is expected; 317 has the same database.
- counts-short remains data-limited: the pricing query link is lost and cart's absorbs it (0.161), within the
  `analyse` limit (p 0.407).
