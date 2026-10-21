# Effects as tent columns, fitted jointly (strategy `effect_hats`)

**Status:** done (ladder rungs 017-018; benchmark v2.1 and 100 generated models), code at commit `d95fb2d`  
**Verdict:** adopt candidate for effects and for re-cut inflows, with work left: passes 017 and 018 without
noise and 018 with counting noise on 2000 steps (no strategy passed 018 before); the whole ladder 475 pass /
159 equivalent of 720 (matrix 345 / 116), no cell worse than matrix; examples 46.6% / 43.1% (+17.0 / +13.8
vs matrix, Wilcoxon p = 0.004 at @20), but sd-sawmill gets worse and run time is ~24x matrix; generated
models neutral (+4.8 / -2.5, p = 0.21)

## Question
The ladder's effect rungs failed for every strategy: 017-linear-effect (A -> B at 0.3 x A x C/50)
passed only without noise (`symbolic`, `symbolic_anchor`: only none-short; `sindy`: both noise-free),
and 018-table-effect (the same move times a table of C with a kink at 50) failed in every variant for
every strategy. Why, and can a strategy pass both, with counting noise too, without breaking 001-016?

## Why the existing strategies failed (`sdlab-ladder show 017|018 --strategy symbolic`)
None of it is the ladder's effect matching (but see "The scorer" below for the counting variants).

- **matrix** has no effects: it reads A x f(C) as links from C (C -> B, A -> outside reading C) and
  tens of outside-inflow pieces into A and B (018 none-long: 12 parts wrong or spurious).
- **symbolic, 017 none-long: the right curve, read back as the wrong flows.** A x C/50 is the
  product A x C, the same column whichever stock is called the base. The screen picked base C,
  curve lin(A); `effects.translate` pairs a drain and a link into a move only when the drain leaves
  the base stock, so the found model is A -> outside = 0.33 x C x lin(A) plus outside -> B = 0.33 x C
  x lin(A): the same amounts as the truth (behaviour exact), but keys (flow, A, -, C) and (flow, -, B,
  C) with effects of A, all wrong or spurious.
- **symbolic, 018: the curve is not in the grammar.** The table bends at 50 (slope 0.016 below,
  0.008 above). No grammar shape fits it within the noise-free 2% (a straight line is 8% off at the
  kink), so in none-short the judge keeps matrix (whose inflow pieces imitate the effect); in
  none-long the curve is taken, but the rows disagree on its number (each row is fitted alone, and
  each takes a different share of the misfit through its other columns): A -> B 0.038, A -> outside
  0.30, outside -> B 0.11, all with the effect.
- **symbolic, counts:** the screen finds nothing on 300 steps; on 2000 steps the judge keeps matrix.
- **sindy** has products A x C in its library (so 017 noise-free passes) but no kinked curves (018)
  and its sparse fits do not survive counting noise.

## What was done
Strategy package `sdlab/sdlab/discovery/strategies/effect_hats/` (no shared module changed):

- `basis.py`: a curve of C as tents (hat functions) over K knots; the tents sum to 1, so base x f(C) is
  linear in the K table values and an SD Lab table effect is exactly what is fitted (flat beyond the
  end knots, as `effect_value`).
- `screen.py`: every (base: a stock or 1, C) as a group of K tent columns, projected on what the rows
  leave after their levels (and pelt pieces); a pair that clearly explains one or two rows is a
  candidate. Both readings of a product (A x f(C), C x f(A)) are kept; the price decides.
- `search.py`: for every way the flow can run (between the two rows, out of or into one, or out of
  its base stock into a row), the tent weights are fitted **jointly in both rows** (one shared group,
  with the flow's signs), knot count 2-8 by BIC, every placement compared on the same rows. The curve
  (normalised to 1 at C's mean level) becomes a virtual stock offered to the matrix method in those
  rows; `translate.py` reads it back (a drain and a link on the curve become a move; a leftover drain
  of a third stock on the same curve becomes the move's co-flow, `uses`).
- `joint.py`: every number of the model refitted at once in a stacked least squares across all rows
  (each flow's columns enter every row it touches with its sign; an effect flow's columns are its
  tents; a co-flow's `per` re-read from the used stock's row in alternation), rows weighted by their
  own noise. A least squares that does not converge leaves the model unfitted (priced as infinite).
- `pieces.py`: outside inflow pieces pooled into a few values and re-cut (Viterbi, a change costing
  2 log T in the row's noise; the number of values by BIC, each extra value priced 2 log T more), and
  the steps within 2 of a change left out of the fit (`guard`). Why: see "Inflow pieces bias drains".
- `price.py`: the price (one-step BIC, a pooled inflow costing one number per value and per change, a
  table one per knot) and pruning: a flow moving less than a quarter of the model's median flow is
  dropped while the price falls (large terms, such as a gap's feedback, are never pruned: inflow
  values would take over their work and the model would misbehave on the bench).
- Acceptance: the curve must explain both halves of the data; the best-priced model (lowest BIC, a
  flow whose rate is not its source's level paying 2 log T) is taken only if it prices better than
  the base with its inflows re-cut the same way and behaves within 1.1x of it on the judge (the
  judge feeds each model its own pieces, so the base is judged re-cut too). Falling back to a
  worse-priced model that passes the judge picked wrong structures (sd-emergency: a link into
  fatigue read as a move, skill@20 -7.6), so the round's pick is accepted or not. With no effect
  accepted, the base with re-cut inflows is returned when it prices better and behaves within 3x
  (`seg_base`). Next to an effect, a link from outside into X at k x X is dropped before the joint
  fit (it is the curve's misfit in X's row, and it runs away once X's drain slows: sd-sawmill
  -477% -> -114% without it). Effect flows carry `driver` (the grader keeps a constant-rate flow
  with a driver rather than replacing it with the truth's inflow).

Tests: `tests/test_ladder_effect_hats.py` (tents equal a table effect; the joint refit recovers a
table effect exactly; a pooled inflow is re-cut at its true changes with an unbiased drain; 017 and
018 none-short pass; no effect is added to a chain). New ladder case
`027-stepping-inflow-drain`: the C row of 017/018 alone.

## Inflow pieces bias drains under counting noise
The rungs' C stock has an inflow that steps 3 <-> 7 every 100 steps (unannounced) and a drain of
0.1. Even fitted with the true structure, the drain comes out fast:

| C row fitted with | drain k (true 0.1), Monte Carlo of 40 runs of 2000 steps |
|---|---|
| true change times, one inflow value per window | 0.108 (Nickell-type short-panel bias) |
| true change times, two pooled values | 0.101-0.104 |
| PELT pieces (as the matrix cuts them) | 0.122 |
| pooled values, change times re-cut freely | 0.118 (3 values chosen), 0.113 (2) |
| ... and the 2 steps either side of each change left out (2 values) | 0.106 |

(A scratch Monte Carlo, not committed; the committed, rerunnable evidence is case 027 and
`tests/test_ladder_effect_hats.py::test_pooled_inflow_is_recut_at_its_changes`.) A change placed one
step late moves k by about 10% (the jump in the inflow lands in the wrong piece). On the ladder the
matrix reads 027's drain as 0.144 (2000 steps) and 0.376 (300 steps); effect_hats 0.101 on 2000
steps (pass). The same mechanism is why matrix fails 002 counts-long (30 pieces, drain 0.21 for 0.1),
and why re-cutting alone passes the counting variants of 004-006, 012, 014, 020 and many parametric
cases.

## Results: ladder (letters: none-short, none-long, counts-short, counts-long)
Whole ladder (720 cells of the four-variant cases; `uv run sdlab-ladder status --strategies
matrix,symbolic,symbolic_anchor,sindy,effect_hats`, results recorded with the code of `4298f8d` +
`591d339`, reproduced cell for cell on `d95fb2d` by a local run of every case; the board marks them
stale because shared discovery code changed since):

| strategy | pass | equivalent | fail | not run |
|---|---|---|---|---|
| effect_hats | 475 | 159 | 86 | 8 |
| matrix | 345 | 116 | 259 | 8 |
| symbolic | 343 | 116 | 261 | 8 |
| symbolic_anchor | 345 | 116 | 259 | 8 |

No case is worse for effect_hats than for matrix in any variant; 121 cases are better in at least one.
The rungs up to 027:

| case | effect_hats | matrix | sindy | symbolic | symbolic_anchor |
|---|---|---|---|---|---|
| 001-inflow-only | PPPP | PPPP | XXXX | PPPP | PPPP |
| 002-inflow-outflow | PPPP | PPPF | PPPF | PPPF | PPPF |
| 003-chain-2 | PPPP | PPPP | PPPP | PPPP | PPPP |
| 004-chain-3 | PPPP | PPFP | PPFP | PPFP | PPFP |
| 005-chain-4 | PPPP | PPFP | PPFP | PPFP | PPFP |
| 006-chain-exit-middle | PPPP | PPFF | PPFF | PPFF | PPFF |
| 007-link | EEFE | EEFF | EEFF | EEFF | EEFF |
| 008-link-loop | EEEE | EEFF | EEFF | EEFF | EEFF |
| 009-births-and-deaths | EEEE | EEEF | EEEF | EEEF | EEEF |
| 010-loop-branch | EEFF | EEFF | EEFF | EEFF | EEFF |
| 011-goal-gap | EEFE | EEFE | EEFE | EEFE | EEFE |
| 012-rework | PPPP | PPFP | PPFP | PPFP | PPFP |
| 013-merge | PPPF | PPFF | PPFF | PPFF | PPFF |
| 014-split | PPPP | PPFF | PPFF | PPFF | PPFF |
| 015-hidden-stock | FFFF | FFFF | FFFF | FFFF | FFFF |
| 016-coflow | EEEE | EEFF | EEFF | EEFF | EEFF |
| **017-linear-effect** | **PPFF** | FFFF | PPFF | PFFF | PFFF |
| **018-table-effect** | **PPFP** | FFFF | FFFF | FFFF | FFFF |
| 019-announced-era | FPFP | FPFP | PPFF | FPFP | FPFP |
| 020-unannounced-step | PPPP | PPFP | PPFF | PPFP | PPFP |
| 021-daily-inflow | FFFF | FFFF | FFFF | FFFF | FFFF |
| 022-pulse | FFFF | FFFF | FFFF | FFFF | FFFF |
| 023-injection | PPPP | PPPP | FFFP | PPPP | PPPP |
| 024-floor-binds | FFFF | FFFF | FFFF | FFFF | FFFF |
| 025-runs-empty | FFFF | FFFF | FFFF | FFFF | FFFF |
| 026-hidden-stock-driven | FFFF | FFFF | .... | FFFF | FFFF |
| 027-stepping-inflow-drain (new) | PPFP | PPFF | .P.F | PPFF | PPFF |

017 and 018 in detail (`uv run sdlab-ladder show 018 --strategy effect_hats`): without noise the found
model is the truth's (5 flows, complexity 1.00x; the effect a 2-knot table for 017, 3 knots at 30/50/70
for 018, amounts within 1e-6). On 018 counts-long it is the truth's structure too (A -> B 0.311 x A x
table(C), every part within 2.4%, the C inflow 20 pieces of 2 pooled values). What is left:

- **017 counts-long**: the effect and A, B are right (A -> B within 2.5%); C's drain is read 13% fast
  (0.113, C's inflow 18.7% high) and fails the 10% tolerance: the inflow-piece bias below, not the
  effect. The ladder's own analysis (`uv run sdlab-ladder analyse 017-linear-effect`) calls this
  variant data-limited: a fit that knows the true structure passes it with p = 0.03 (018 counts-long:
  p = 0.04, which effect_hats passes).
- **counts-short (300 steps)**: the screen finds no effect. Data-limited too (p = 0.36 for 017, 0.34
  for 018); fitting the truth's own structure fails them (see "The scorer").

## Results: benchmark v2.1 (31 examples x 2 lengths)
`OMP_NUM_THREADS=1 ... uv run python tests/bench/evaluate.py --strategy effect_hats --baseline v2.1
--jobs 3` (run "effect_hats v3", saved `2026-10-19T01-54-29-470Z-effect-hats-v3.json`, on the code of
`591d339`: the same behaviour as `d95fb2d` apart from the error fixed there; the current matrix run on
the examples gives exactly v2.1's numbers):

| | skill@20 | skill@100 | fresh @20 / @100 | goal | discovery time |
|---|---|---|---|---|---|
| matrix (v2.1) | 29.6% | 29.3% | 28.9% / 29.7% | 12 of 62 | 363 s |
| effect_hats | **46.6%** (+17.0) | **43.1%** (+13.8) | 45.8% / 42.9% | 14 of 62 | 8790 s (~24x) |

Paired (runs clipped at -100%): @20 26 better and 11 worse by more than 2 points, Wilcoxon p = 0.004;
@100 22 better, 16 worse, p = 0.19. By what was chosen: an effect in 20 runs (+35.0 / +33.3; 12 better,
5 worse: sd-hospital long -57, sd-manufacturing long -39, sd-restaurant long -20, sd-kanban long -15,
sd-cloud-credits long -13), the base with re-cut inflows in 36 runs (+7.9 / +5.5; 13 better, 6 worse:
sd-brewery long -37, sd-pipeline long -14), the plain base in 6. The effect targets (skill@20,
matrix -> effect_hats):

| example | default | long |
|---|---|---|
| sd-emergency | 5.0% -> **29.5%** | -47.5% -> **82.4%** |
| sd-webshop-stock | 60.8% -> **74.4%** | 63.6% -> **85.8%** |
| sd-farm-soil | 93.7% -> 95.0% | 97.1% -> 95.5% |
| sd-learning-curve | -72.3% -> -76.2% | 44.8% -> 44.4% |
| sd-sawmill | -261% -> **-431%** | -207% -> **-643%** |

sd-sawmill is worse: the effect (logs -> planks x table(sharpness), using up sharpness) is found, but the
model reads sharpness as a constant inflow of 13-21 with a drain, where the truth has an inflow of 6
switched off by sharpness itself (a second effect the screen does not find). The grader feeds the
truth's inflow of 6, sharpness collapses, the curve shuts the sawing off and logs pile up. symbolic
gets 52% / 73% here. sd-moderation long raised an error in this run (least squares did not converge);
fixed in `d95fb2d` (it now runs: -161%, matrix -99%; both clip to -100%).

## Results: 100 generated models
`... evaluate.py --strategy effect_hats --generated 100 --jobs 3` (run "effect_hats gen v3", same code as
the examples run, paired with
the matrix run "matrix generated (censored reference)" on the same 200 runs, clipped at -100%):

| | skill@20 | skill@100 | parts | discovery time |
|---|---|---|---|---|
| matrix | -52.4% | -48.1% | 72.5% | 492 s |
| effect_hats | -47.6% (+4.8; 41 better, 32 worse; p = 0.21) | -50.6% (-2.5; p = 0.90) | 74.0% | 4601 s (~9x) |

By motif (@20): goal_gap +11.1, inflow_spikes +9.8, merge +9.0, inflow_steps +8.9, floor +8.5,
effect_table +6.3 (but -8.2 at @100), effect_linear -2.3, inflow_season -2.8, coflow -11.5, rework
-13.3. The largest losses (0.88 -> -1 and the like) are mostly the base with re-cut inflows: a
seasonal inflow pooled into at most 4 values (dev-98), or an inflow that steps between three values
read as one value with a drain three times too slow (dev-95, s7: the price saves 370 on pieces for a
17% worse fit). Requiring at least as many values as the pieces' values that differ fixes dev-95
(0.66 -> 0.86) but loses 70 ladder cells (the matrix's pieces are cut where values differ most, so
too many look different); not adopted.

## The scorer
1. **No standard-error allowance for the linear parts of a case with effects.** `oracle.py` is
   disabled for the whole case when any true flow has an effect (`Oracle.ok` needs `linear_system`
   of every flow), so C's inflow and drain in 017/018, which are linear and untouched by the effect,
   must be within 10% with no allowance for what the data can say. Fitting the truth's own structure
   by least squares (true effect shape, true change times, per-window inflow) fails 017 counts-short
   (every part 11-23% off), 017 counts-long (C inflow 15%), 018 counts-short (C parts 52% / 31%) and
   018 counts-long (C parts 38% / 20%). The ladder's `analyse` now says as much (017/018 counting
   variants "data-limited", p 0.03-0.36), but the pass/fail itself still has no allowance. Proposed:
   build the oracle per row, for every row that no effect or hidden flow touches (or with the
   effect's true multiplier as a known column), so those parts get the z x SE allowance every
   linear case already has.
2. `sdlab-ladder show` crashes on a stored spurious effect part (`cli.py` line 219 now: an effect
   part's size is `math.inf`, stored as `null`, formatted with `:.3g`): `uv run sdlab-ladder show
   018-table-effect --strategy symbolic` ends in a TypeError.
3. Equivalent effect readings are scored by key: k x C x lin(A) for a move A -> B is the same function
   as k x A x lin(C) but is keyed (flow, A, B, C) with an effect of A, so it fails. Fair as a test of
   SD's usual form (rate = source x effect), worth knowing.

## Measured inputs (2026-10-19, commit 89adae4)

**Bug:** the matrix base takes the input as a flow k x input, but the joint refit held that flow and
stepped it without the inputs, and price, pruning's amounts, the BIC and the judge did the same: the
input's flow moved nothing, so the drain and the pieces were refitted to carry it (062 none-long:
drain 0.0003 against 0.08 beside 2 x pump) and the input counted twice.
**Fix:** `inputs.py`; the inputs are columns of the joint refit (a flow on an input is refitted with
the rest), of the screen and of every curve's fit; every price, BIC (a local onestep.bic with
inputs), pruning amount and judge steps the models with them, and the matrix's chosen model is judged
again with them (identify.judge has no inputs).

Before -> after on the cases with measured inputs (variants in the order shown; skill@20 on the run
it saw, none-long):

| case | variants | before | after | skill@20 none-long |
|---|---|---|---|---|
| 062-tank-fed-by-measured-pump | counts-long / counts-short / none-long / none-short | F F F F | P P P P | -15.70 -> 1.00 |
| 105-canonical-inventory-supply-line | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 1.00 -> 1.00 |
| 106-canonical-workforce | counts-long / counts-short / none-long / none-short | F F F F | F F F F | 0.60 -> 0.59 |
| 110-canonical-world3-pollution | counts-long / counts-short / none-long / none-short | F F F F | F F F F | -15.41 -> 0.97 |
| phys-coupled-tanks | meas-long / meas-short / none-long / none-short | F F F F | F F P F | 0.40 -> 1.00 |
| phys-draining-tank | meas-long / meas-short / none-long / none-short | F F F F | P P P P | -67.23 -> 0.98 |
| phys-mass-spring-damper | meas-long / meas-short / none-long / none-short | F F F F | F F P P | -15.57 -> 1.00 |
| phys-newton-cooling | meas-long / meas-short / none-long / none-short | F F F F | P P P P | -1.09 -> 1.00 |
| phys-thermostat | meas-long / meas-short / none-long / none-short | F F F F | F F F F | -20.36 -> 0.98 |

105, 106 and 110 (canonical models whose input drives hidden delay stocks) fail before and after, as
for matrix, lna and combined. phys-thermostat fails its structure for every strategy (the closed loop
all but hides the outside's coupling; its own reference fails), though its skill rose.

**Cells without inputs:** every (case, variant) without a measured input was run before (parent of
`89adae4`) and after, each from an exported copy of the package that differs only in this strategy's
files, single-threaded: 1074 of 1074 cells gave byte-identical flows and the same status, the 62 realistic sd-* cells among them; 8 of them (realistic sd-* counts-long) hit the ladder's per-case timeout under load in one run or both and were re-run without a timeout, before and after: identical too
(script and outputs: the agent's scratchpad `inp/cells.py`, `cmp.py`, `old.jsonl`, `new.jsonl`).

## Open ideas
- **A second effect.** `rounds` > 1 screens again with the accepted effect's column taken out; it
  finds nothing more on sd-sawmill, whose second effect is a constant inflow switched off by its own
  stock (1 x f(sharpness)). A screen against the grader's view (constant inflows replaced) or one
  that offers "constant x f(own level)" whenever an inflow is pooled might find it.
- **Re-cut only where it is right.** The re-cut base wins on the ladder and loses on seasonal or
  three-valued inflows. Candidates: allow the original pieces as one of the options at the same
  price (now they pay `level_price` per value), or test the re-cut on a held-out half of the steps.
- **Free knots.** 018 passes because the data's range puts a knot on the kink; a 1-D search over one
  interior knot (or knots at the curve's largest second difference) would make kinks exact anywhere.
- **SD shapes as constraints.** Monotone tables (non-negative increments, NNLS) and f(normal) = 1 are
  not imposed; with counting noise they would steady the curve on short runs.
- **Poisson weights per step** (variance proportional to the flows through the stock) instead of one
  weight per row.
- **Speed.** Run time is ~24x matrix on the examples (the matrix variants with the virtual stock, the
  re-cut and pruning); fewer variants per candidate or a cheaper screen would cut it.
- **Combination.** The strategy `combined` already runs effect_hats beside the other specialists.

## Kubernetes 303 (2026-10-20, 631e5b8)

303 counts-short failed on the shared main line's five chance pieces of an outflow from the final
counter; the re-cut base is now pruned by effect_hats' own price (`prune_base`, inflow_effects' rule at
fcc0c9a): 300-303 20 of 20, paired 40 cells +1 pass, +1 equivalent, none worse. See
[k8s-303-hats-odefit.md](k8s-303-hats-odefit.md), which also has its capability remark.


## The declared boundary (2026-10-20)

Outside flows only where the case declares them ([declared-boundary.md](declared-boundary.md)). The package
carries its own `boundary.py`, copied from matrix/boundary.py at 723f72c (HIDDEN_PRICE 0, CLAIM_PRICE 2),
with changes of its own marked "(this copy)": a guard refit budget (GUARD_FITS 60, then a flow outside is
dropped without a refit), an estimated side may hold a flow reading a measured input (the cases declare
"estimate" for any flow not driven by inputs alone, 217), no self-move among the alternatives, and the
helpers `inside`, `keep_inside`, `placement_ok`. In its own search: the pinned main line's base is guarded inside the boundary; an effect's outside placement only on a declared estimated side; each finished trial guarded before it is re-cut, pruned and priced. Every answer ends with
`boundary.apply` (the guard and the moves; with no boundary declared, outside flows are priced boundary
claims, listed in `boundary_claims`). The eiv copy holds an instrumented refit with nothing to prune to the
pruned model's longest-horizon test (303 meas-long).

Paired on the CPU pool (commits 71ec999, 9cfeb75, d5cd56a; before = this strategy at 3cc5c54 on the same
HEAD, branch boundary-before-hats): Kubernetes 300-305 (28 cells, jobs 54 -> 119) 27 -> 27 pass (+1 equivalent: 305 counts-short pass -> equivalent; 305 none-long fail -> pass); 40 Tests
cells (008, 028, 059, 114, 117, 154, 196, 203, 208, 213 x none/counts short/long; jobs 57 -> 120)
8 -> 8 pass, 9 -> 9 equivalent, no status change. Invented boundary (k8s / tests): 1 -> 0 / 11 -> 0. Timeouts unchanged (154 counts-long times out on
both sides where it did). Kubernetes 316-317 (job 122, after only, 8 cells each; none-long skipped by the pool): no pass; timeouts only on 317 (meas-long in five of the six, counts-long in effect_hats and own_tables, meas-short in own_tables), where the stored results at 793b5b5 already timed out on 317's long variants; coflow_hats now finishes 317 counts-long and meas-long.
