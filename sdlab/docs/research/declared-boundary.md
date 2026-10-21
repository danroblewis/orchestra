# The declared boundary in strategy code: outside flows only where the case says so

**Status:** done (2026-10-20). The user approved the change on 2026-10-20 (CLAUDE.md invariant 2).
Harness: 48ab938 (the `boundary:` case field, the announcement `run["boundary"]`, the "invented boundary"
diagnosis). Cases: 9827eaa (every numbered ladder case declares its boundary, derived from its truth;
data, seeds and engine fingerprints unchanged). Reference: `matrix` (67f5b9e, 723f72c:
`sdlab/discovery/strategies/matrix/boundary.py`, hooks in `earned.py`, `earned_rows.py`,
`earned_joint.py`, `__init__.py`; tests `tests/test_matrix_boundary.py`). Every other roster strategy
carries its own copy, wired into its own search (see [Per-family work](#per-family-work)).
**Verdict:** keep. No result on either measured set fails for an invented outside flow any more (1,750
old answers would); Tests +485 passes net; Kubernetes 300-305 -30 passes, almost all one cell
(303 meas-long) lost to the errors-in-variables refit, not to the boundary search.

## Why

Since 2026-10-20 a case declares its boundary (the user's approval, CLAUDE.md invariant 2; docs/LADDER.md
"The boundary"): per measured stock, its outside inflows and outflows, each `measured` (driven by a
measured input series) or `estimate` (exists; form and rate to estimate). Discovery is told
`run["boundary"] = {stock: {"in": [kinds], "out": [kinds]}}` and `run["boundary_declared"] = True`; a
stock not listed has no outside flow. Nothing else about the truth is announced. The scorer fails an
outside flow a declared boundary does not have ("invented boundary").

Before this work, 65% of all invented parts across failing results were outside flows (41% outflows,
24% inflows), and the commonest mistake was a move A -> B written as "A -> outside" plus
"outside -> B" (012-rework: `A -> outside = 0.30 A` and `outside -> B = 13.2 (6 pieces)` beside the
true `A -> B`). Re-grading `matrix`'s stored Tests results against the declared boundaries
(offline, nothing written) gave 307 of 1,192 cells with an invented boundary.

The user's question that started it (2026-10-20): odefit's answer on 303-k8s-daily-traffic meas-long
wrote `inflight -> outside`, `queue -> outside` and `outside -> inflight` beside the true chain. Could
models simply be banned from producing outside inputs and outputs? There was never a menu of pieces to
remove: each strategy fitted outside terms (a constant, pieces, an input, a link to another unit)
freely, and those came out as outside flows. The ban therefore has to be information the case gives
(which outside flows exist) and a rule every strategy follows (none elsewhere).

How the case declares it (Sterman's model-boundary chart): `boundary: {stock: {in: [kinds], out:
[kinds]}}` in the case file, each kind `measured` (an inflow whose rate reads only measured inputs) or
`estimate` (every other outside flow: it exists, its form and rate are to be found); `boundary: {}`
declares none; only the stock and kind are given, never the form or rate. `cases._build` checks each
declaration against the truth (`caseformat.boundary_problems`), and a unit test checks every declared
boundary equals the truth's outside flows. Undeclared (no key): real data, realistic `sd-*`, physics,
particles; there outside flows are allowed as priced boundary claims. Re-scoring every stored row
before any case declared a boundary (93,318 rows, `tests/study_rescore_boundary.py`, scorer d8cfaf0 vs
48ab938) gave 0 status changes: the field and diagnosis alone change nothing.

## The design

One rule, used the same way everywhere (no branch on case type): **an outside flow is a modelling
decision the case makes, not something discovery may invent.**

1. **Candidates only where declared.** The row regressions are fitted inside the boundary from the
   start, not cleaned up afterwards:
   - a stock gets an outside term (constant or pieces) only if an `estimate` side is declared on it;
   - a row reads a measured input only if a `measured` side is declared on its stock (a declared
     `measured` inflow is an inflow reading the input, never pieces);
   - a row reads a stock of another unit (a link from outside, or a drain to outside that follows it)
     only if an `estimate` side is declared;
   - a source with no `estimate` outflow is **tied**: its drain is exactly what its same-unit receivers
     gain from it (no exit to outside). In `matrix` this is the joint fit's tie (`earned_joint.decide`,
     `forced`), started tied and never untied.
2. **Moves from anti-correlated changes.** An outside outflow from A and an outside inflow into B whose
   *unexplained* changes (the stock's change less what every other flow explains) are anti-correlated
   beyond z = 3 (corr x sqrt T) are tried as the move A -> B, replacing both, and kept if it prices
   better (`pair_moves`). What one stock loses, the other gains: counting noise makes the two
   residuals anti-correlated even when the move is steady.
3. **The guard.** After the fit, and again on the final answer, any flow still outside a declared
   boundary (by the scorer's own reading of outside ends, through hidden stocks too) is replaced by its
   best-priced alternative, refitted (`guard`), largest first, until none is left:
   dropped; an outflow from A made a move into another stock of A's unit (with or without that stock's
   estimated outside inflow, which the move may replace); an inflow into B replaced by the move from a
   stock of B's unit that drains to outside, or a link reading A made the move A -> B; an estimated
   inflow on a side declared `measured` replaced by an inflow reading the input; and, where only an
   inflow is declared on A, A's outflow folded into A's estimated inflow as a falling term (a gap
   inflow, `c - k X`: 011-goal-gap's `outside -> P = (300 - I) / 5` is found that way). The guard never
   keeps a flow outside the boundary, whatever it costs.
4. **No boundary declared** (real data, realistic `sd-*`, physics, particles, the page): outside flows
   are allowed, but each is a **boundary claim** priced at **2 log T** on top of its numbers
   (`CLAIM_PRICE`). On the final answer every claim is offered its alternatives (dropped, made a move;
   not folded, since an inflow and an outflow of one stock are two claims, not a net one) and replaced
   while that lowers the price (`price_claims`). The claims left are listed in
   `r["boundary_claims"] = [{stock, side, kind, flow}]`.

**The price.** Every structure compared is refitted (its numbers by least squares on the one-step
changes, Gauss-Newton with each stock weighted by its residual spread) and priced as BIC:
`-2 log L` (Gaussian, one variance per stock, rss floored at the levels' rounding) `+ log T` per number
`+ 2 log T` per boundary claim. A hidden stock is part of the system inside the boundary and pays only
for its numbers, like any other part (`HIDDEN_PRICE = 0`, the user, 723f72c): priced the same as
everything else, so laziness has nowhere cheaper to move to. An alternative with a negative rate is not a model (priced
infinite). Wiggle the model does not explain is noise: pieces exist only where an `estimate` side
allows them, and must still earn their BIC.

`matrix` offers no hidden stocks, so the hidden-stock price only matters for strategies that do.

What the result says: `r["boundary"] = {declared, sides, changed: [what the guard and passes did]}`,
`r["boundary_claims"]` (empty when declared).

## For copiers

Strategies are isolated (CLAUDE.md invariant 11): **copy `boundary.py` into your package** (note
"copied from matrix/boundary.py at <commit>"); it imports only the shared simulator
(`sdlab/discovery/simulate.Model`).

What to call:

| hook | when | what it does |
|---|---|---|
| `b = Boundary(run)` | start of `identify` | the announcement; `b.declared`, `b.may(stock, side, kind)` |
| `b.pieces_ok(s)`, `b.inputs_ok(s)`, `b.links_ok(s)` | building each stock's candidate terms | which outside terms a stock's equation may hold |
| `b.must_tie(s)` | fitting drains / conservation | the stock's drain must be all moves |
| `apply(result, stocks, run, opts, final=False)` | on each candidate before your judge (declared cases) | the guard only; cheap when nothing is outside |
| `apply(result, stocks, run, opts)` | last line of `identify` | guard + moves (declared), or moves + priced claims (not declared); fills `boundary`, `boundary_claims` |

The minimum, for any strategy: one call, `return boundary.apply(r, stocks, run, opts)` at the end.
That alone removes every invented boundary (the guard) and lists claims. The candidate-level hooks
(item 1) are what make the answer *good* rather than just legal: a model fitted with free outside
terms and then cleaned up has its other numbers biased by the terms it lost (the refit fixes the
numbers, not the structure the search chose around them).

Adapting to a strategy that fits differently:

- **Row regressions (matrix, matrix_v2, lna, earned_pieces, ...):** filter the columns and the
  outside-term form per row with `pieces_ok` / `inputs_ok` / `links_ok`; force conservation for
  `must_tie` stocks (a move's number in the receiver equals the source's drain).
- **Likelihood or state-space fits (kalman_*, lna):** give an undeclared outside flow no place in the
  parameter vector instead of a prior; where none is declared, add `CLAIM_PRICE x log T` per outside
  flow to the criterion your model selection already uses.
- **Whole-model searches (structures, evolve, combined2's judge):** enumerate outside flows only on
  declared sides; price candidates with `price(Fit(flows, data), data, b)` or add the claim price to
  your own criterion; call `guard` before returning.
- **A strategy with hidden stocks:** `ends()` follows outside flows through hidden stocks as the scorer
  does, so `violations` catches `outside -> H -> A`; `Fit` cannot refit flows on hidden stocks (their
  levels are unknown), so the guard then just drops the offending flow. Price your hidden stocks with
  `HIDDEN_PRICE` in your own criterion.
- **Never branch on the case type.** The boundary is information like eras and inputs: read it, never
  infer it from the case's name, tags or shape.

Costs: the per-candidate guard does nothing when the fit is already inside (the usual case after the
row hooks). Every comparison refits only the numbers of flows on the stocks the change touches
(`Fit(..., free=touched(old, new))`, the current structure refitted the same way, so the two are
compared fairly); each number's slope comes from the one flow that holds it, and the normal equations
are built stock by stock. The optional passes stop after `MAX_FITS = 120` refits (deterministic, not a
clock). On the largest model measured (sd-k8s-small counts-short, undeclared: 125 flows, 34 stocks,
10,080 steps) the final passes took 99 s (with a budget of 200 refits; now 120) beside matrix's own 495 s (a dense refit of the whole model
took 1,327 s); on the ladder's small cases they take well under a second.

## Per-family work

Each agent copied `matrix/boundary.py` at 723f72c into its strategies (HIDDEN_PRICE 0, CLAIM_PRICE 2) and
wired it into the strategy's own search; results per family are in its doc:

| strategies | commits | doc |
|---|---|---|
| matrix_v2, held_out, recession, starved_coflows, periodic_inflows | 8a73872, ca00790, c0f0e7a | [matrix_v2.md](matrix_v2.md) and each strategy's doc |
| lna, lna_levels, lna_loops, lna_products, lna_pulses, lna_stack | 7050136, dae7fc5 | [lna.md](lna.md), [revisit.md](revisit.md) |
| odefit, master_eq, kalman_lna, engine_forms, common_cause, sindy | c2a4894, b984413 | [odefit.md](odefit.md) and each strategy's doc |
| combined, combined2, combined_lean, combined_misfit, combined_r2, archetypes | a578c86, d323b6e | each strategy's doc |
| structures, blockwise, censored, earned_pieces, gap_prior, schedules | f76591e, 728efec, 85beeb9 | [declared-boundary-six.md](declared-boundary-six.md) |
| effect_hats, inflow_effects, coflow_hats, realistic_flows, realistic_hats, own_tables | 71ec999, 9cfeb75, d5cd56a, 66a901f | each strategy's doc |
| hidden_transit, loop_transit, latent_eras, mass_balance, drifting_drain, shared_noise | e8c036a | [declared-boundary-transit.md](declared-boundary-transit.md) |
| numopt_bo, numopt_cma, numopt_nm, numopt_powell | 7d2a370, ab73e30, 7982f41 | [numerical-optimisation.md](numerical-optimisation.md) |

Fixes some copies made that the reference lacks (found by several agents, not in `matrix`):

- **Self-move:** `alternatives()` can replace an inflow into B by "moving" B's own drain into B, which
  only deletes the drain (305 retries). Fixed in the matrix_v2 family, the hats family and others.
- **Last declared outflow:** `pair_moves` can turn a declared `outside -> A` and `B -> outside` into a
  false loop or move, leaving a declared side empty (`kept_sides` in the odefit family's copies).
- **Kind reading:** `kind_of` calls any outside flow that reads a measured input "measured", so
  `inputs_ok` refuses inputs on an `estimate` side; but cases declare `estimate` for every flow not
  driven by inputs alone (208's valve `75 - 0.25 H + 0.8 demand`). Fixed in the six-copies family
  (728efec) and the hats family (9cfeb75).
- **Cycling ties:** `earned_joint.decide` can cycle once ties are forced (317: 25,000 fits); bounded in
  the matrix_v2 family. Refit budgets (`GUARD_FITS` 60-200) in most copies.

## Results

**Commands.** Both sets ran on the CPU pool at c0f0e7a, priority 300, only out-of-date cells re-run:
job 129 (Kubernetes 300-305, all variants) and job 130 (Tests sample: 120 numbered non-kubernetes cases x
none-short, counts-short; every 2nd or 3rd of the 278 in sorted order, about half draws). "Before" is the
last stored result for each cell from before 9827eaa, re-graded by c0f0e7a's scorer to count invented
outside flows. From an export of c0f0e7a (`git archive c0f0e7a | tar -x -C <dir>`):

```
PYTHONPATH=<dir>/sdlab .venv/bin/python tests/study_boundary_pairs.py before JOB beforeJOB.json
PYTHONPATH=<dir>/sdlab .venv/bin/python tests/study_boundary_pairs.py report JOB beforeJOB.json
```

with JOB = 129 or 130. The roster has 44 survivors; milp and z3exact have no stored results from before
the change, so their cells are unpaired and left out below. Counts are paired cells only.

**Kubernetes 300-305** (1,232 cells, 1,176 paired):

| | pass | equivalent | fail |
|---|---|---|---|
| before | 1173 | 2 | 1 |
| after | 1143 | 5 | 28 |

- Invented boundary: 60 old answers held one (58 of them passed under the old scorer); after, 0.
- Flips: pass -> fail 28, pass -> equivalent 3, fail -> pass 1. The one gain is **odefit 303
  meas-long**, the cell the user asked about: it now finds `queue -> inflight`, `inflight ->
  responses_total` and `outside -> queue x traffic`, with no outside flow beside the chain.

**Tests sample** (10,164 cells, 9,702 paired):

| | pass | equivalent | fail | error | timeout |
|---|---|---|---|---|---|
| before | 4719 | 1380 | 3599 | 4 | 0 |
| after | 5204 | 1347 | 3136 | 14 | 1 |

- Invented boundary: 1,690 old answers held one; after, 0. Of the 1,508 old failing (fail or
  equivalent) answers with one, 493 now pass and 200 more are equivalent.
- Gains: fail -> pass 439, fail -> equivalent 304, equivalent -> pass 126.
- Losses: equivalent -> fail 232, pass -> fail 55, pass -> equivalent 22, new errors 14, new timeout 1.

## Regressions and their causes

1. **303 meas-long, pass -> fail in 24 strategies** (all the matrix line's descendants that run eiv).
   The structure is right; the numbers are 13% high (`inflight -> responses_total` 0.568 for 0.5). Before,
   the invented `outside -> inflight` flows made the errors-in-variables refit (`eiv.py`) prune them,
   and it kept its instrumented numbers (0.559 / 0.466 / 0.933) as a side effect. Now the candidate
   arrives inside the boundary, eiv has nothing to prune, and its 5/20/100-step judge prefers the
   biased least-squares numbers (0.2093 vs 0.2124). Fix, already shown in the hats family (d5cd56a):
   hold the eiv refit to the pruned model's longest-horizon test; the odefit family's alternative is to
   send the unguarded model to eiv and guard afterwards. Each strategy's own `eiv.py` needs it.
2. **305-k8s-retries, 6** (schedules, shared_noise, structures; equivalent in effect_hats and
   inflow_effects). The declared `retries -> outside` outflow is dropped and moved into the queue; the
   reference lacks the "no declared side loses its last flow" and self-move fixes above.
3. **104-canonical-teacup, 51** (33 strategies). The truth is `k x (T - room)`. Before, strategies wrote
   it as an outflow `k T` plus a constant inflow, which was "equivalent"; that inflow is no longer
   allowed, and no strategy fits an outflow holding a negative constant, so k comes out 0.027 against
   0.096. The same happens to inflows with a minus sign: 152's `300 - 0.08 A`, the goal gaps 047#3/#5/#7
   and 083 (the lna family fails there; 17 matrix-family strategies gain on 047#5). Needed: a flow form
   `c - k X` (an outflow with an offset, the fold alternative generalised) in every search.
4. **152-move-driven-by-third-stock, 41** (all but matrix_v2, which gains). Pairing an outflow with an
   inflow makes false moves (A -> B at 0.08 A, and S -> B, which also removes S's declared outflow). The
   reference's `pair_moves` reads both flows' deterministic amounts, not just their noise, so any outflow
   and inflow driven by the same level pass its z test; plus the missing last-declared-side guard.
5. **Control cases 204, 208, 215, 218, 125, about 120** (equivalent -> fail). The found inflow keeps
   only its constant and loses its setpoint and demand terms: the reference's kind reading (an input
   read on an `estimate` side refused). Copies with the fix (blockwise, censored, own_tables, the hats
   family) gain on 208 and 215; copies of the unfixed reference regress.
6. **engine_forms, 14 new errors** (102, 106, 109, 113, 129, 138, 196, 211, 221, 224): `judge.py:219`
   `TypeError: 'list' object is not callable`, because line 200 reuses the name `outside` for a list.
7. **One new timeout:** common_cause on 138 counts-short (over 600 s).

## What is left

- ~~Port the reference fixes~~ **Done in 14e1351** for self-move (d5cd56a, ca00790), last declared side
  (c2a4894's `kept_sides`) and kind reading (728efec): `matrix/boundary.py` and every copy lacking one
  (46 files, vendored lna and `_kalman` copies included; the hats family keeps its own kind reading,
  9cfeb75). Paired on the pool at 3f2557e (before) vs 14e1351 (after), 46 strategies, `--stale`:
  - jobs 139 / 141 (125, 152, 204, 208, 215, 218 x none-short, counts-short; 552 cells): fail -> equivalent
    186, fail -> pass 6, no losses (125 +36, 204 +11, 208 +58, 215 +57, 218 +30). **152 unchanged** (all
    fail): its truth `outside -> A = 300 - 0.08 A` needs the `c - k X` form (cause 3), not a boundary fix.
  - jobs 140 / 142 (Kubernetes 300-305, all variants; 1,288 cells): pass 1275 -> 1278; 305 retries +4
    (combined_misfit, numopt_cma counts-long fail -> pass; effect_hats, inflow_effects counts-short
    equivalent -> pass); one loss, shared_noise 301 counts-short pass -> fail (an extra `inflight -> outside`
    reading traffic, now allowed on the estimate outflow side, pushes the other numbers 13% high).
  - Not ported (not in `boundary.py`): cycling ties (`earned_joint`); noise-only `pair_moves` is in no copy.
- Each strategy's `eiv.py` acceptance (cause 1) before the Kubernetes competition resumes: 303 must pass
  again for its 24 strategies. Then 305's retries (cause 2); then 305 can be the next rung.
- A `c - k X` flow form for teacup and goal gaps (cause 3).
- engine_forms' name clash (cause 6), a one-line fix by its owner.
- `notruth_core.check_view` and the unified frontend's `VIEW_KEYS` must accept `boundary` and
  `boundary_declared` once their views carry them.
- Not measured: the other variants of the Tests cases, 306-317 as a set, and undeclared cases
  (realistic, real, physics, particles), where outside flows are now priced as claims.
- **Backlog:** the watcher is paused (`~/.sdlab/watch.paused`). `sdlab-ladder cost --stale` at c0f0e7a:
  46,032 stale items for 41 strategies over 394 cases, 77.3 h CPU, about 19.3 h wall at 4 workers (tests
  29,689 items 34.0 h; realistic 2,542, 27.7 h; physics 1,517, 8.5 h; noisy 6,161, 4.6 h; canonical
  1,859, 2.0 h; real 4,264, 28 min).

## The kind input (2026-10-21)

**Why.** combined2 on 306-k8s-ready-replicas-cap meas-short found `outside -> queue = 0.007 x traffic`
(truth 1 x traffic), and on meas-long 0.877 x traffic plus a second outside inflow into queue
(`min(0.0495 queue, 3.23 ready)`). The user (2026-10-21): a measured input must not be rescaled or
supplemented. "measured" meant "driven by a measured input, form and gain estimated", and a declared
side admitted any number of outside flows.

**What changed** (approved by the user, 2026-10-21; harness 284de71, strategies c7cade0):

- **Cases.** New kind `input`: the inflow IS the measured series, exactly 1 x one input, no constant.
  36 of the 42 declared "measured" inflows are exactly that in their truth and now declare `in: input`
  (34 files: the kubernetes requests 300-317, 115, 117, 142, 170, 171 A and B, 195, 201 I, 202, 203, 207
  H1 and I, 209 I, 213-216, 226); 6 keep `measured` (062's 2 x pump, 0.05 x outdoor in 200, 201, 210,
  211, 209's 9.8 x downhill). 142's `V <- 1 x force` is exactly 1 x its input, so it is `input` too.
  Data and simulations unchanged (digests pinned in `tests/test_ladder_case_boundaries.py`).
- **Scorer.** An `input` side's found gain on its input must be 1 within 1e-6 relative, with nothing
  else on a side that declares only inputs ("input altered", never equivalent); on every declared side,
  more found outside flows than declared is an "invented boundary" (one flow per declared side).
- **Strategies.** Every `boundary.py` (matrix's reference and the 45 copies, vendored ones included)
  gets one identical hunk. `Boundary` reads an `input` side as `measured` for the search (`fixed`,
  `limit`, `original` keep the declaration). `apply` (candidates and the final answer) ends with
  `enforce_sides`. It sets apart the side's input-reading inflows (all of them on an input-only side) and
  puts back exactly 1 x the input whose fixed flow leaves the best-pricing refit. It strips that input's
  terms from the side's other flows. It caps every declared side at its declared count (summable rates
  merged into one, else the smallest dropped). Finally it refits the touched stocks' other flows on
  their changes less the fixed inflow (`_around`), and never refits the fixed flow. milp and z3exact
  (no `boundary.py`) read `input` as a measured side and set the final gain at 1 (`fixed_inputs`, no
  refit). Tests: `tests/test_boundary_input_kind.py` (every copy), `tests/test_ladder_input_boundary.py`.
- **Not kept:** matrix's row search with the input taken off the row before reselection
  (`earned.refit`). It lost 303 meas-long (it chose `inflight -> queue` instead of
  `inflight -> responses_total`), so rows still see a measured side.

**Re-score of stored results** (`tests/study_rescore_input.py`). It grades the 87,558 latest numbered
rows that are not errors (frozen before job 200 wrote any), offline, by 3747e29 (old cases and scorer)
and by the working tree at c7cade0 (new). **1,060 flips, every one toward fail, none toward pass:**

| set | rows | pass before -> after | flips |
|---|---|---|---|
| kubernetes | 3,296 | 1,692 -> 753 | pass -> fail (input altered) 939 |
| tests | 84,262 | 36,414 -> 36,358 | equivalent -> fail 65 (input altered 59, second outside flow 3, both 3); pass -> fail 56 (input altered 53, second outside flow 3) |

By case: kubernetes 303 (202), 300 (147), 305 (138), 302 (100), 301 (97), 304 (97), 306 (77), 313 (33),
315 (25), 314 (21), 307 (2); tests 195 (41), 142 (23), 170 (22), 171 (10), 226 (7), 214 (5), 215 (3),
216 (3), 201 (2), 207 (2); second outside flow only: 139 (2), 136 (1). By strategy, 2 to 29 flips
each across every strategy with stored rows there (matrix_v2 and structures also lose 3 and 2 to a second
outside flow). The old answers estimated the requests' gain (e.g. 0.93 x traffic on matrix 303
meas-long), within the old 10% tolerance.

**Kubernetes 300-306 on the pool** (job 200 at c7cade0, roster:kubernetes, 44 strategies, every
variant, 1,494 cells, 0 errors). 1,382 cells pair with the stored result from before:

| | pass | equivalent | fail |
|---|---|---|---|
| stored before (old scorer) | 1,283 | 1 | 98 |
| before, re-graded by the new scorer | 533 | 1 | 848 |
| after (job 200) | 1,282 | 2 | 98 |

- Against the stored results: 7 gains (z3exact fail -> pass 5 and fail -> equivalent 1, on 300-303
  counts-short; shared_noise 303 meas-short fail -> pass). 7 losses, all structural, none for an
  altered input or a second outside flow: 303 counts-long engine_forms and kalman_lna (`inflight ->
  queue` for `inflight -> responses_total`); 303 meas-long numopt_bo (an effect of queue) and own_tables;
  303 meas-short numopt_cma (a co-flow) and structures; 306 none-short held_out.
- Against the stored answers re-graded by the new scorer: fail -> pass 750 (13 to 21 per strategy),
  pass -> fail 1 (held_out 306 none-short).
- 112 cells have no stored "before": 306 meas-short and meas-long (88, all fail, as before the change
  in rung 306's diagnosis), 306 none-long and a few more. combined2 on 306 now has exactly
  `outside -> queue = 1 x traffic` and no second inflow in all six variants (meas-short and meas-long
  still fail on the rest of the model).

**Tests sample** (120 numbered non-kubernetes cases: the 16 with an `input` side plus every ~2nd of the
rest, none-short, roster:kubernetes; pool jobs 206-209 at c7cade0, 4,972 cells, 0 errors; 4,968 pair
with a stored result). The stored rows come from mixed older commits (the main line's backlog), so the
fair "before" is those answers re-graded by the new scorer (study above):

| | pass | equivalent | fail |
|---|---|---|---|
| before, re-graded by the new scorer | 2,385 | 836 | 1,747 |
| after (jobs 206-209) | 2,479 | 884 | 1,605 |

- Gains: fail -> pass 105 (226 +37, 054 +25, 195 +9, 170 +7, 043 +5, 053 +5, ...), fail -> equivalent
  71 (154 +38, 216 +18, 214 +4, ...), equivalent -> pass 12.
- Losses: equivalent -> fail 27 (215: 16, 214: 9, 216: 1, 016: 1), pass -> equivalent 16 (016: 5, 054: 3,
  ...), pass -> fail 7 (201: 2; 049, 058, 063, 135, 142: 1 each). None of 214/215's failures carries an
  "input altered" or second-outside-flow note: the I and Y numbers refitted around the fixed setpoint
  inflow miss the tolerance.
- Against the stored statuses instead: pass 2,395 -> 2,479, equivalent 890 -> 884, fail 1,683 -> 1,605
  (202's 34 equivalent -> fail are already fails when its stored answers are re-graded at 3747e29: a
  scorer change before this one).

## Limits and next steps

- Hidden stocks: `matrix` offers none, so a case whose truth needs one (107-canonical-rework,
  boundary `{}`) can only come out as moves between measured stocks; it no longer invents outside flows
  there, but still fails.
- A declared `estimate` inflow whose truth reads its own or another stock negatively (a control law,
  207's pump) is found only through the fold alternative, one term at a time.
- Undeclared cases (realistic, real, physics, particles, the page) change too (claims priced on the
  final answer); they were not part of the paired run.
