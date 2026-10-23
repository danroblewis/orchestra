# Port of the kubernetes climb's fixes: common_cause

**Status (2026-10-22, final at 5bb4c2b):** every achievable plan cell of 308-311 passes (job 405). Before the port,
none of the 16 passed. The 5 cells that still fail are the data-limited ones (309 counts-short, and the counts variants
of 310 and 311). On 300-307 nothing regressed (job 406: 32 of 32 pass). The wider check over every non-kubernetes
case (job 407) lost no pass to the port; see Regressions.

Where the numbers come from (pool, committed code):
- `uv run sdlab-ladder submit --strategies common_cause --cases 308,309,310,311 --variants none-short,none-long,counts-short,counts-long --priority 400 --by port-common_cause`
  gave job 381 at 7778159 (round 1) and job 388 at 09b045c (round 2).
- The same command with `--cases 300,...,307` gave job 382 at 7778159 and job 390 at 1a640aa (common_cause's code
  there is identical to 09b045c's).
- I read the cells with `uv run sdlab-ladder job ID --json` (status, right/of), `show` and `diff`.
- The baseline is the latest stored row before the port (code bab9156 or 793b5b5), from `sdlab.ladder.store.history`.

## Before and after, 308-311

| cell | baseline | round 1 (7778159, job 381) | after (09b045c, job 388; same at 5bb4c2b, job 405) | target? |
|---|---|---|---|---|
| 308 none-short | F 10/12 | P 12/12 | **P 12/12** | yes |
| 308 none-long | F 9/12 | F 9/12 | **P 12/12** | yes |
| 308 counts-short | F 8/12 | P 12/12 | **P 12/12** | no (data-limited, p 0.094); passes anyway |
| 308 counts-long | F 10/12 | P 12/12 | **P 12/12** | yes |
| 309 none-short | F 11/18 | P 18/18 | **P 18/18** | yes |
| 309 none-long | F 11/18 | P 18/18 | **P 18/18** | yes |
| 309 counts-short | F 5/18 | F 17/18 | F 17/18 | no (data-limited, p 0.010) |
| 309 counts-long | F 11/18 | F 16/18 | **P 18/18** | yes |
| 310 none-short | F 11/23 | P 26/26 | **P 26/26** | yes |
| 310 none-long | F 10/23 | F 24/26 | **P 26/26** | yes |
| 310 counts-short | F 9/23 | F 9/23 | F 9/23 | no (measured data-limited in the climb) |
| 310 counts-long | F 3/23 | F 14/23 | F 14/23 | no |
| 311 none-short | F 10/23 | P 26/26 | **P 26/26** | yes |
| 311 none-long | T (300 s) | P 26/26 | **P 26/26** (130 s) | yes |
| 311 counts-short | F 8/23 | F 10/23 | F 10/23 | no |
| 311 counts-long | F 7/23 | F 12/23 | F 12/23 (467 s) | no |

That is 0 of 16 cells before and 11 of 16 after. All 10 target cells pass, plus 308 counts-short.

## Diagnosis (rule 4b)

- **308, all variants:** the HPA's two flows on `ready` came out as linear proxies (`outside -> ready = 0.00292 x
  inflight`). The method had no form for a quantized controller. On none-long, a cross-unit move
  `retries -> ready` (0.18 x retries) also smeared the actuator.
- **309-311:** besides the controller (on `desired`), the base had no floored gap flows (`outside -> pending =
  max(0, desired - pending - ready)`, `ready -> outside = max(0, ready - desired)`), no counted OOM move with its
  table, no hidden leak in `mem`'s inflow, and no room-limited `pending -> ready`. These are all method faults.
  The other strategies show the data identify them on the none variants.
- **Round 1's misses:**
  - 308 none-long: the smeared move kept the tracker off `ready`.
  - 310 none-long and 309 counts-long: `desired`'s outside inflow was a pieced inflow (`inflow` segments), and the
    copied tracker cannot run pieces, so it skipped the stock.

## What was ported

common_cause's tail already matched kalman_lna's: the capmin offer, the linear identify, the oefit refit, then
capmin.restore. Its `oefit.py` and `capmin.py` are byte-identical to kalman_lna's. So I copied kalman_lna's
post-passes at 7c3fb13 as they are and call them after `capmin.restore`, the way kalman_lna does:
`krows.revise(restore(r, cap), ..., cap)` and then `tracker.revise`. The copies are:
- `krows.py`, from kalman_lna's `rows.py` (renamed because common_cause has its own `rows.py`);
- `derived.py`, `delayed.py`, `subsets.py` and `tracker.py`.

Fix-ledger types these carry:
- **2**: quantized controller (`tracker.py`).
- **3**: floored rate on a declared side, with the hinge reread (`krows`).
- **6**: counted flow / derived move (`krows`).
- **7**: table effects and derived columns, including the ratio `inflight / max(1, ready)` (`derived.py`).
- **11**: hidden integrator written as the model's own stock (`krows`).
- **12**: capped / room-limited move (`krows`, `derived.py`).
- **13**: the `movable` cross-unit rule (`krows`).
- **14**: delayed inflow (`delayed.py`).
- **10**: batched subsets, row budgets and staged rows (`subsets.py`, `krows`).

Mine, in common_cause's `tracker.py` copy (round 1 is 7778159, round 2 is 09b045c), and in `krows.py` and
`__init__.py` (rounds 3 and 4, 02a3f60 and 5bb4c2b, driven by the wider regression check):
- **A hidden stage is an outside inflow** (round 1). On 308 and 309 none-short, krows' delayed inflow
  (`outside -> H -> ready`) stayed beside the controller, which made two inflows on one declared side ("invented
  boundary"). Now a stock nobody measures, whose only outflow is `H -> S` and whose inflows come from outside, is
  part of S's inflow side. It is priced at its inferred levels and replaced together with that side.
- **common_cause's constant form is read** (round 1). Its constants carry `value`, which the tracker copy read as
  0. On 032 and 038 none-long that made a constant inflow look unexplained, and the tracker wrote it as a step rule
  that is on all the time. As a guard, a rule that acts on every step (idle on fewer than MIN_FIRES steps) is a
  rate, not a controller.
- **Smeared move carried by its partner** (type 4, round 2). When the tracker loses with S's moves in place, it is
  tried again with S's plain moves to and from other measured stocks taken off S's row. Each move's rate is merged
  into the partner's own outside flow on that side, or becomes a new one where the side is free and the boundary
  allows it. The partner's row is therefore unchanged exactly, and only S's row decides. On 308 none-long,
  `retries -> ready 0.18` went into `retries -> outside`, which became 0.4.
- **Pieced inflows and byTime rates are read on the step's clock** (round 2), as krows does. This is what fixed 310
  none-long and 309 counts-long.
- **Already at resolution, not rebuilt** (round 3, krows). Below the rounding floor the BIC reads rounding. On 045#7
  none-long an exact answer (rows at 0.04 and 0.8 of the floor) was rebuilt with a capped move that never binds,
  which turned equivalent into fail.
- **A time-only integrator is a schedule** (round 3, krows `_hidden`). A hidden stock now needs a drain switched by
  the state, which is the ledger's own rule that no constant drain earns a stock. On 056#7 none-long, A's start
  transient had been read as a hidden stock beside a binding floor (pass -> fail).
- **Unbound floor** (round 3, krows `row`; type 3 addition). A floored term that never goes below minus the rounding
  on the run joins the always-on part, so a drain is written as a drain. On 060 none-long the answer had been
  `outside -> C = 10.5 - 0.0374 C` (pass -> fits).
- **refit-guard** (round 3, type 10). krows and the tracker each keep their input on LinAlgError,
  FloatingPointError, ValueError or ZeroDivisionError.
- **Stage budget from the runner's timer** (round 4, type 10). krows gets half of what the timer leaves less 20 s,
  its rebuild 15% and the tracker 10%, each capped at its own constant. On sd-print-shop counts-long, krows had
  taken 230 s of the 300 s limit; now it takes 113 s (191 s in all, locally).

Tests: `tests/test_common_cause_port.py` (the stage, a partner with other flows, the carried move), plus the
existing `tests/test_ladder_common_cause.py` and `tests/test_isolation.py`.

## Not ported, and why

- **1, zero-term prune, and 5, capmin guards:** nothing on 300-311 needed them. 307 already passed.
- **9, joint active-set repair; 16, best-subset block re-read; 17, flow-earn; 18, conserving drawing:** krows'
  rebuild already covers what 308-311 needed (rows read by best subset, moves paired). Their own mechanisms target
  312-317, which were out of scope.
- **15, injection-aware rows:** krows and the tracker already subtract announced injections. The judge is not
  expression-aware, but common_cause does not judge after writing expressions.
- **19, count-noise share tests:** only the counts variants of 310 and 311 would use them, and those are
  data-limited.

## Regressions

- **300-307 (none and counts, 32 cells):** 32 pass before and 32 pass after (jobs 382, 390, 402 and 406; the last one
  at 5bb4c2b).
- **032 and 038 none-long** (common_cause's own unit test) failed partway through round 1. Fixed before the
  round-1 commit by the constant and always-on-step fixes above.
- **The wider check, every non-kubernetes case** (none and counts variants, 1164 cells, `submit --exclude-cases
  tag:kubernetes`). Job 391 ran at round 2, job 403 at round 3, and job 407 at round 4. Each was compared with the
  latest stored row before the port; that comparison script is in the scratchpad, not committed.
  - Job 391 lost 38 cells. Most of them were "equivalent -> fits": stale rows from before the scorer's
    proven-equivalent rule (bab9156), which give the same status at 7c3fb13.
  - For every loss that was not "-> fits", plus a sample of the "-> fits" ones, I ran an A/B locally: a scratch
    worktree at HEAD with common_cause's package reset to 7c3fb13, against mine, using `runner.run_item` and the
    same scorer.
  - **The port caused four:** 056#7 none-long (P -> F), 055#2 none-long (E -> F), 045#7 none-long (E -> F) and 060
    none-long (P -> fits). All four are back at 02a3f60 (local A/B).
  - **These fail at 7c3fb13 too, so they are not from the port:** 016 counts-long, 054#8 counts-long, 152 none-long,
    157 counts-long, 158 (three variants), 159 none-long, 201 counts-long and 215 counts-short.
  - **Job 407 (5bb4c2b) against the pre-port store:** 590 pass, 155 equivalent, 40 fits, 345 fail, 15 error and 19
    timeout. 31 cells are "lost", 20 of them -> fits as above. The others are the pre-existing ones just listed,
    034 none-short and 035 none-long (below), and part-capacity-gate counts. That one is a harness error,
    `systems.SYSTEMS[...]` KeyError, which hits every part-* counts cell and comes from no strategy. **No pass or
    equivalent is lost to the port.** 38 cells were gained, for example 024 floor-binds x4, 222 x4, 226 x3, 195 x3,
    124 x2, and phys draining-tank, newton-cooling, mass-spring-damper and lotka-volterra.
  - **Timeouts:** 14 realistic `sd-*` counts-long cells, sd-fishery counts-short, 154 counts-long and 138
    counts-short time out at 300 s. **None of them passed before:** they failed, errored or timed out. 154
    counts-long and sd-support-tiers already run past the limit at 7c3fb13 (local, over 150 s and over 310 s), so
    those are pre-existing. sd-sawmill and sd-university finish at 7c3fb13 locally (108 s and 128 s). With the
    port, sd-sawmill takes 164 s locally, but it times out on the loaded pool. So the port's extra passes turn some
    scored fails into timeouts on slow slots. That loses no pass, but the budget shares (0.5, 0.15 and 0.1 of what
    is left) could be cut further if those cells matter.
- **Pre-existing, not from this port: 034 and 035 noise-free.** `tests/test_ladder_common_cause.py`
  (034/035 none-long) fails at HEAD before the port. A bisect in a scratch worktree puts it at c7cade0 (boundary.py:
  "input kind and one outside flow per declared side"): it passes at 6e18658 and fails at c7cade0. The identical
  twins' drains come out spread as `0.0667 (A + B + C)`, the collinear spread that common_cause's exact tiebreak used
  to avoid. It depends on the machine: in job 407, node2 passes 034 none-long but fails 034 none-short, while the Mac
  passes none-short and fails none-long. I left it. The fix belongs in common_cause's boundary.py
  `enforce_sides`/`_around` refit, which should keep the plain row.

## Commands and jobs

| job | commit | what |
|---|---|---|
| 381 | 7778159 | 308-311 x 4, round 1: 8/16 pass |
| 382 | 7778159 | 300-307 x 4: 32/32 |
| 388 | 09b045c | 308-311 x 4, round 2: 11/16 |
| 390 | (09b045c code) | 300-307 x 4: 32/32 |
| 391 | (09b045c code) | non-kubernetes x 4 variants, 1164 cells |
| 401, 402, 403 | 02a3f60 | 308-311 (11/16), 300-307 (32/32), non-kubernetes |
| 405, 406, 407 | 5bb4c2b | 308-311 (11/16), 300-307 (32/32), non-kubernetes |

## For the fix ledger

`common_cause (port-common_cause, 5bb4c2b, jobs 405/406/407): kalman_lna's rows.py (as krows.py), derived, delayed,
subsets and tracker copied at 7c3fb13 and run after capmin.restore (types 2, 3, 6, 7, 10, 11, 12, 13, 14). The tracker
copy reads a hidden stage as an outside inflow, carries a smeared move into the partner's outside flow (type 4), reads
pieced inflows, and refuses an always-on step rule. krows skips rows already at resolution, gives no hidden stock a
time-only drain, dissolves an unbound floor (type 3), and gets budgets from the runner's timer (type 10). 308-311
0/16 -> 11/16, every achievable cell; 300-307 32/32 kept; no pass lost on the non-kubernetes ladder (1164 cells).`

Also worth adding to the ledger's type 2 and type 4 sections: kalman_lna's `tracker.py` treats a hidden delay stage
(type 14) feeding the controlled stock as an inside flow. Since febd195 (delayed.py), that can leave a second inflow
on the stock's declared side beside the controller. kalman_lna's own 308 pass is at f9e24d4, before delayed.py, so
it may be worth re-running kalman_lna on 308 and 309 none-short at HEAD.
