# 310 (k8s-memory-oom): milp

Status (2026-10-21): **none of the 4 plan variants pass, and none can pass as the case is scored today**
(the mem inflow, below).
The OOM kills (the move ready -> pending with a table effect of mem, and the counter that counts it) and
the pod gaps are now right on none-short, none-long and counts-long. What still fails is the mem row: its
inflow reads the hidden `leak`, and the scorer cannot credit a found model that reads a hidden stock of its
own (below). counts-short is also data-limited.

Where the results come from: pool job 267 (8ff75a7, `uv run sdlab-ladder job 267`), and
`uv run sdlab-ladder show 310-k8s-memory-oom --strategy milp --variant V`. Pool job **273** (573c5a5, the
final commit) was still queued behind coordinator job 271 (about 134 min left) when I stopped. It is
**not run yet**: `uv run sdlab-ladder job 273`. The 573c5a5 column comes from local single-process
diagnostic runs of the same code (scratchpad `m310/run.py`, the strategy's `identify` plus
`score.equations`; the Mac was loaded by 14 pool slots). They are not pool results.

| variant      | analyse                                    | before (a660e75)  | job 267 (8ff75a7, node2) | local, 573c5a5 code |
|--------------|--------------------------------------------|-------------------|--------------------------|---------------------|
| none-short   | "not analysed" (a truth it does not cover) | FAIL 13/23, 66 s  | FAIL 21/23, 193 s: mem row, plus 2 outflows from mem (a MIN beside the drain: fixed in 573c5a5) | FAIL 21/23: mem row only |
| none-long    | "not analysed"                             | TIMEOUT (900 s)   | TIMEOUT (900 s)          | FAIL 21/23, 220 s: mem row only (run just before the one-per-side step) |
| counts-short | "not analysed"; data-limited (below)       | FAIL 16/23, 142 s | FAIL 14/23, 389 s        | FAIL 15/23 (post-program steps on a cached program answer) |
| counts-long  | "not analysed"                             | TIMEOUT (900 s)   | TIMEOUT (900 s)          | FAIL 20/23, 867 s: OOM move and counter wrong (program answer stepped the counter), 6 spurious |

counts-long is still close to the 900 s limit: the program and its prunes took 844 s on the loaded Mac.

## Diagnosis (rule 4b)

`sdlab-ladder analyse` does not cover this truth (effect tables, a hidden stock), so I judged each part
myself.

- **The OOM move and its counter were a method fault.** The truth is `ready -> pending` at
  `ready x table(mem)` (0 below 480 MiB, 0.3 at 512) and `oom_kills_total` fed `flow(oom_killed)`. The
  program's columns are linear in the levels, so it fitted a constant into the counter (0.0094 a step)
  and dropped the move. The pods rows were then left with the kill spikes, and hinge.py's gap search on
  them failed: its trials were invalid, so `outside -> pending` stayed a constant and `ready -> outside`
  stayed `0.003 ready`. On none data the counter's increments divided by ready give the table exactly,
  so these parts are identifiable.
- **The long variants timed out because of the program's inflow-step starts.** The profile (cProfile,
  none-long) showed `refit.prune` taking 460 s over 2 of the 3 searches. A start with about 100 inflow
  steps (the mem inflow chasing the leak's ramp) gave a structure with about 120 numbers on 2000 steps,
  so each refit's SVD took 0.47 s.
- **The mem inflow cannot pass for any model with the true structure (scorer limitation).** The truth is
  `0.5 (150 + leak + 2 inflight / max(1, ready))`, where `leak` is hidden (1 MiB a step, partly freed
  by each OOM kill). A whole flow is scored by its amounts on the truth's states (`score._levels_at`,
  `all_levels`). A found model's own hidden stock is not one of those states. I gave the scorer the
  truth itself with `leak` renamed to `hmem` (scratchpad `m310/truthscore.py`), and
  `score.equations` raised `ExprError: flow allocated reads ['hmem']: not a stock, input or auxiliary`.
  A linear rewrite would read the hidden stock as 0, about 40% of the inflow's rms. The only way to pass
  is a proxy built from measured stocks: a least-squares fit of the true leak on the measured levels
  comes within 0.6% of the inflow (none-short) and 1.5% (none-long), against an allowed 2%. That
  proxy reads `responses_total` as a clock and `oom_kills_total` as the resets. It is not the leak, so I
  did not tune milp towards it. `mem -> outside` (0.5) fails with it, at 0.34-0.42, because the program
  bends the drain to make up for the inflow.
  **Harness fix needed (not mine to make):** score a whole flow that reads the found model's own hidden
  stock on the found model's simulated states, or compare the mem row as a whole.
- **counts-short is data-limited.** The run has 3 kill steps (6 kills in 300 steps). The kill amount's
  relative SE is about 1/sqrt(6), roughly 40%, against an allowed 10%. milp's amount error is 31%.
  queue <-> retries (0.0895 for 0.08, 0.681 for 0.6) is the same limit as on 309 counts-short: bound SE
  0.127, p 0.010.

## Fixes kept

| type | mechanism | commit | how another strategy adopts it |
|------|-----------|--------|--------------------------------|
| table-effect | `milp/effects.py`, `refine(flows, stocks, run, opts, skip)`. **Candidates:** every flow the boundary allows. That is a move between two measured stocks of one unit (reading its source), an outside inflow on an "estimate" side (reading a same-unit measured stock, or nothing), an outside outflow on such a side, and a **counted move**: a move whose amount a counter's declared inflow also counts, the same amount on both. Each is tried with every non-counter measured level X as the effect's driver (any unit). **Form:** `R x sum_m s_m max(0, X - h_m)`, or with `h - X` instead. For a given hinge h, it is one least-squares column, fitted with the plain flows on the rows it touches. Those flows' numbers are refitted unfloored. The flow it would replace (same pair, or the counter's outside inflow) is in the comparison and out of the candidate. h runs over 40 quantiles of X, is then polished continuously between grid neighbours, and a second hinge is tried as a bend. **Kept** when BIC over the touched rows beats the answer by more than 10, it moves something on 5 or more steps, and it explains at least half of one touched row's misfit (a proxy for other missing structure trims, it does not explain). A second effect of the same X on a row already carrying one is refused, because it is that flow's adjustment. **Written** as `{"rate": 1 x R, "effects": [{"stock": X, "shape": "table", "points": ...}]}`, with points at the hinges and one span beyond the run's range. | 8ff75a7 | Copy `effects.py` together with milp's `hinge.py` (for `_amount`, `_env`, `_plain`, `_resolution`) and `steps.py`. Call `flows, note = effects.refine(flows, stocks, run, opts, skip=<controller stocks>)` after the strategy's own search. |
| effect-polish | The same module re-fits each effect flow it wrote (hinges and slopes, kept in `effect_fit`), along with the counter inflow that counts it, against the flows as they now stand. In `identify` the order is effects, then gaps (hinge.py), then effects again if the gaps were used (polish plus new candidates), then gaps again if anything new was added. The first slope (0.00927) was fitted beside the gap misfit, and the first round also added a spurious `ready -> oom_kills_total` correction. | 8ff75a7 | Part of the copied `effects.py`: call `refine` again after any later step that changes the touched rows. |
| effects-in-amounts | `hinge._amount` multiplies by a flow's effects (a copy of the engine's `effect_value`; tables through `np.interp`). `hinge._plain` treats a flow with effects as not plain, so it is held fixed and never refitted as a linear rate. Moves already carried by an effect flow are not offered again as extra plain moves. | 8ff75a7 | Copy `hinge.py` again, or patch `_amount` and `_plain` the same way in your copy. |
| move-bound | `hinge._Fit.fit`: a move's number on its own source is bounded at 0 or above. A move pushed below 0 moves nothing, its gradient vanishes, and the gaps absorbed its role: a start at `pending -> ready = -42` with `ready -> outside = r - d - 0.5 p`. | 8ff75a7 | One line in the copied `hinge.py` (the bounds passed to `least_squares`). |
| gap-avoid | `hinge.refine(..., avoid)`: when every start is invalid because a new gap cannot act on 5 or more steps on a side whose answer flow is not plain (a stepped inflow, so there is nothing to go back to), the search runs again without that side. On counts-short the mem inflow's gap made every trial infinite, so no pod gap was used. | 8ff75a7 | Part of the copied `hinge.py`. |
| prune-budget | `refit.prune` stops (keeping what it has) after refit work of `sum(T x stocks x numbers^2)` of 1.5e10, about 25 s of 120-number refits on 2000 steps. The budget is counted, not timed, so results stay deterministic. | 8ff75a7, 573c5a5 | Any local search that refits whole structures. Count the work and stop on it, not on a clock. |
| one-per-side | `milp._one_per_side`, after `persistent`: on a declared outside side holding a MIN beside its plain flow (or two MINs), each is tried alone, refitted, and BIC keeps one. The program picks MIN columns and term columns independently. Job 267 (node2) had `mem -> outside = 0.047 mem` plus `min(0.0136 mem, 14.6 pending)`, and two flows out of cpu, both "invented boundary". | 573c5a5 | A strategy whose search can put two flows on a declared side: the same post-step over its structure. |

Tried and reverted (not committed): (a) bends of either sign in the effect table (to follow 310's
table flattening past 512-560 MiB on counts-long, where mem reaches 682): the OOM amount error went from
30% to 20%; (b) letting an effect flow replace a stepped (byTime) flow, holding it at its amounts in the
comparison. That let the counted move replace counts-long's stepped counter constant. On none-short both
admitted proxy effects on the mem row (`outside -> mem` x effect(cpu), `mem -> outside` x effect(retries)):
the leak's misfit is level-switched enough to pass the half-misfit test. A sharper guard against proxies
is needed before either goes in.

Not run: per the plan, no regression run on earlier rungs. Risks to check in the later full regression:
the prune budget can truncate the inflow-step searches on long variants (309 none-long ran 266 s before),
and effects.py can add an effect flow wherever a level-switched misfit stays above half of a row's misfit.

Tests: `tests/test_milp_effects.py`. The first test recovers a counted move switched on past 470 from
an answer holding a constant in the counter. The second checks that a model with no effect is left alone.
