# 312 (k8s-cluster-autoscaler): engine_forms, round 1

**Status (2026-10-22, agent ef312-r1, engine_forms lock held and released): none-short passes; none-long reads the
whole truth but fails on one part because of a scorer inconsistency at announced injections (below, reported, not
fixed here: the harness is not this agent's).** Code at 18e29e8, pool job 308 (`uv run sdlab-ladder job 308`).
counts-short and counts-long are data-limited (the OOM-kill bound of 310/311), so they are not targets.

| variant | achievable? | before (store: strategy hash 22ef05156; none-long 12/28 from the local stage trace) | after (18e29e8, job 308) |
|---|---|---|---|
| none-short | yes | FAIL 14/28 | **PASS 28/28** (254 s, node2) |
| none-long | yes | FAIL 12/28 | FAIL 27/28 (652 s): only `outside -> oom_kills_total [as a whole]` (error 0.0202 vs 0.02), a scorer issue |
| counts-short | no: data-limited | FAIL | FAIL 7/25 (169 s) |
| counts-long | no: data-limited | X (error) | FAIL 8/25 (616 s; job 308 shows its promotion pending) |

## Diagnosis (rule 4b)

`diff 312-k8s-cluster-autoscaler --strategy engine_forms` showed three blocks wrong on both noise-free variants, and
a stage trace (scratchpad `ef312/stages.py`: the score after base, oefit, tidy, capmin.restore, reread, controller,
hidden) placed every fault in reread's exact re-read, plus a missing reader for the new feature:

1. **requests block (queue, inflight, retries).** `dispatched = min(0.6 queue, 40 ready)`. With the autoscaler adding
   nodes, ready is high and the cap binds on only 6 of 300 steps (24 of 2,000 long), against 123 on 311. capmin's
   offer then guesses theta 61 (truth 66.7), and in the re-read: (a) `regime` asks a piece to hold on 5% of all
   steps, so the second branch is never a piece; (b) the hinge reader now reads each row as linear plus a hinge
   (`min(u, v) = u - max(0, u - v)`), so queue carries an inflow hinge on its `input` side and inflight an equal and
   opposite outflow hinge, and the block is refused; (c) on none-long queue's hinge was read on the exactly collinear
   responses_total/errors_total (numbers ~2e4, tolerance inflated), because the COND guard was in `exact` and
   `regime` but not `floored`.
2. **pods block (ready, pending).** `started = min(0.5 pending, max(0, 4 nodes - ready))`. The floor piece (pending
   0) coincides with the u piece, so only two pieces appear, and the v piece (room binds, 17 steps) drops the kills
   column (zero there), so "lin = the common columns" was empty. On none-long the room binds on 90 of 2,000 steps
   (4.5%) with 158 steps left over.
3. **nodes (new).** `provisioned = DELAY1(0.075 max(0, pending - max(0, 4 nodes - ready)), 2)`, `removed = 0.05 max(0,
   nodes - max(2, (ready + pending) / 2))`. No reader handled a stock fed through a hidden stage whose inflow is a
   floored function of the state. In and out never act on the same step (measured on the truth: 0 overlaps), the
   removal is small (tens of roundings), and on none-long the `max(2, ...)` binds on 84 steps.

All three are method faults: on exact data each row is reproduced by the truth's form to the rounding.

## Fixes kept (commit 18e29e8)

| type | mechanism | where | how another strategy adopts it |
|---|---|---|---|
| **rare MIN branch** (extends 311's floored-MIN move) | A later linear piece may hold on 5% of the steps *left* (at least 5), not 5% of all; tried only after the strict reading fails, so every earlier success is unchanged. Two pieces whose lin column is 0 (within rounding) on the other piece's steps still give lin = common columns plus that column | `reread.py` `_Rows.pieces(relaxed=)`, `two_regimes` / `_two_regimes`, `SMALL` | Any piecewise (regime) reader: retry with the share taken over the remaining steps when a branch binds rarely |
| **hinge pair is a move** (conserving drawing; ledger "hinge row" type) | Two rows of one unit with equal and opposite hinges carry one amount from one to the other: read them as a pair joined by a MIN move (`_pair`), and a row left beside a hinged row of its unit likewise. Falls back to the hinges when the pair does not reproduce the rows | `reread.py` `_block` | Wherever a strategy writes floored outside flows on two same-unit stocks: test for equal and opposite hinge functions and draw a move (the user prefers the conserving drawing) |
| **COND everywhere** (precision guard, 311) | `floored` skips column sets more collinear than COND, as `exact` and `regime` do | `reread.py` `_Rows.floored` | Every exact-row search whose tolerance grows with the numbers |
| **hidden DELAY1 stage** (new type; the 310 hidden-integrator type for a stage fed by a state function) | Exact data, a measured stock S whose row the answer misses and which declares an estimated inflow. Model `dS = g H - out`, `H' = in - g H`. (1) `out` from the steps S does not rise: one floored rate (`floored`), else a floored MIN of two read from the steps where out is above 30 roundings, then fitted on every step by branch alternation (`_min_of_two`). (2) `x = dS + out = g H`; `1 - g` is the fraction x keeps on the most consecutive pairs (`_decay`). (3) `g in_t = x_{t+1} - (1 - g) x_t`, read as one floored rate over the levels, inputs, a constant and the answer's own floored terms (each `max(0, ...)` in its expression flows, e.g. the MIN move's room). Written as `outside -> stage_S` (in), `stage_S -> S` (g stage_S, the conserving DELAY1), `S -> outside` (out), with the stage's levels as `inferred_levels`; kept only when the written flows reproduce the row. A rows reader counting the rounding down to 1% of a part's largest amount (`_Small`, `_Rows.fine`) reads the small removal | `delay.py` (new), called last in `__init__.identify` after hidden.py | Copy `delay.py` with reread's `_Rows` (numpy/scipy only) and hidden.py's `_change`/`_evaluate`; call it on the final answer. Strategies without an exact re-read can still use steps (1)-(3) on their residual row |

Found on 312 (none-long): `stage_nodes -> nodes = 0.49957 stage_nodes` (delay 2.002 steps; truth 2),
`outside -> stage_nodes = max(0, 0.07504 pending - 0.07510 max(0, 4.00007 nodes - 1.00002 ready))`,
`nodes -> outside = max(0, min(0.05 nodes - 0.025 ready - 0.025 pending, 0.05 nodes - 0.1))`; the requests block
with `queue -> inflight = min(0.6 queue, max(0, 40.0 ready))`; the pods block with the 311 MIN move.

Tests: `tests/test_engine_forms_delay.py` (a MIN branch binding on 10 of 300 steps; a stock fed through a DELAY1
stage; a removal with a minimum read as a floored MIN; noisy levels left alone). The other engine_forms tests,
`test_isolation.py` and `test_frozen.py` pass, except `test_engine_forms_boundary.py::test_a_form_that_leaves_the_boundary_is_undone`,
which **fails at HEAD 201a23d without these changes too** (checked in a clean worktree; judge.py's trace no longer
says "undone"); not touched here.

## The none-long miss: a scorer inconsistency at injections (harness; reported, not fixed)

The only failed part on none-long is `outside -> oom_kills_total [as a whole]`, error 0.02018 against `rel_exact`
0.02. The found flow is the truth's: `ready x T(mem)` with knots 195.95/480.0000/503.66 (the data's mem range) and
height 0.22182 at 503.66 (truth 0.3 x 23.66/32 = 0.22182). The whole error sits on the two announced node failures
(t 706 and 1282: ready -3). The truth's amount there comes from the engine's counters (`sim.amounts`, `flow(...)` read
from `data["counters"]`), computed after the injection; the found flow is evaluated on `score._levels_at(data)`, which
does not apply announced injections. Evaluated on the injected states (as discovery's `Data` does), the same found
flow matches the measured kills to rel rms 0.00012 (scratchpad `ef312/kc.py`). **Needed harness fix:**
`_levels_at` (or the whole-flow comparison) should add announced injections to the step-start states, as the engine
and `boundary.Data` do. This can turn fail into pass, so it must be reported to the user with before/after
(CLAUDE.md rule 5). 311 none-long passed because no kills fell on its injection steps.

## Data limits of the counts variants (rule 4b, measured)

The truth's own kill table (knots 480/512/560 given, heights free), Fisher information on each counts run's ready
and mem (scratchpad `ef312/bound.py`, the 311 script):

| variant | expected kills (steps) | rel. SE of the total killed | expected rel. rms error of the kill flow | tolerance |
|---|---|---|---|---|
| counts-short | 19.4 (8) | 0.23 | 0.35 | 0.10 |
| counts-long | 123.0 (77) | 0.09 | 0.20 | 0.10 |

No method can be expected to meet the tolerance on the kill flow, so both are data-limited and not targets.

## Notes for the regression run

- The relaxed pieces run only after a strict two-regime reading fails, and the hinge-pair and left-beside-hinge
  pairings only where some moving row is exact. The COND guard in `floored` can change a hinge read on collinear
  columns elsewhere (309/310/311 none-*): check them once.
- delay.py acts only on exact data, a stock with a declared estimated inflow, no hidden stock of its own, whose row
  the answer misses, and only when the written stage reproduces the row.
