# Canonical coverage: how much of SDXorg/test-models SD Lab's case format holds exactly

**Status:** done (measurement; queue items 2 and 2c). **Code:** the importer at 2deb86d
(`sdlab/ladder/pysd_import.py`, `sdlab/ladder/canonical/`: arrays, macros, external data and DELAY N /
SMOOTH N added in e83aa25, item 2c; the first measurement was on 3660a5d, item 2). **Measured** on
2026-10-18 with
`uv run --with pysd --with sympy python -m sdlab.ladder.canonical.coverage <test-models> --markdown ...`,
on [SDXorg/test-models](https://github.com/SDXorg/test-models) at 21aab02 (MIT), PySD 3.14.3, sympy
1.14.0. The test-models files are fetched at run time, not committed (except the models copied with
their MIT licence into `canonical/models/`: the SIR and teacup samples and `subscript_switching`).

**Verdict:** of the 165 models (12 samples, 153 one-function tests), **90 now convert exactly** (SD
Lab's engine with noise `none` gives PySD's Euler levels at every recorded step), up from 37. 27
convert but differ, 24 of them because a rate or a stock goes negative (SD Lab floors both at 0), 46 are blocked, and 2 test folders hold no model. The converter alone moved 53 models to exact and
12 from blocked to "differs"; no model that was exact before changed. What blocks now is mostly the
**engine**: two-way flows and stocks that go negative (39 models, 37 with nothing else missing).

| status | before (3660a5d) | after (2deb86d) |
|---|---|---|
| exact | 28 | 75 |
| exact with inputs | 9 | 15 |
| **exact, total** | **37** | **90** |
| differs | 15 | 27 |
| blocked | 111 | 46 |
| no model | 2 | 2 |
| total | 165 | 165 |

Samples alone: 2 exact before, 3 after (the `arrays` sample); the other 9 lack engine features (below)
or cannot be read by PySD.

## What item 2c added (the converter only; no engine change)

- **Arrays.** A subscripted variable is flattened into one variable per element: a subscripted stock
  is one SD Lab stock per element, id `<stock>__<element>[__<element>...]` (the case format's ids are
  letters, digits and _; `Stock_A__Entry_1__Column_2` is `Stock A[Entry 1,Column 2]`, which is also
  the name PySD's output gives it, so the check reads it directly). PySD's own `SubscriptManager`
  reads the ranges (subranges, copies, numeric ranges, ranges from files, mappings); `:EXCEPT:`,
  definitions in parts, numeric and tabbed arrays, `SUM / PROD / VMIN / VMAX` over `x[A!]` (written
  out element by element), XMILE's one-argument `MIN(x)`, `ELMCOUNT` and a range read as a number
  (`x[A] = A`) are taken. 44 of the 53 new exact models were blocked by arrays alone.
- **Macros.** Each call is inlined: the macro's equations are read with its parameters bound to the
  call's arguments. A stock inside a macro becomes a stock of the model per call, measured through the
  model's auxiliary that equals it (`macro output = MACRO(...)`), else hidden. All 6 macro tests are
  exact.
- **External data.** GET XLS / GET DIRECT CONSTANTS, DATA and LOOKUPS are read through PySD itself (the
  model's folder is copied so the files sit beside it): a constant becomes a number, a data series a
  measured input (PySD's value at every Euler step, one per recorded step), an external lookup a
  lookup table. 7 of the new exact models read data files. Two tests stay blocked because the files
  their models name are not in the repository (`data.xls` beside `data.xlsx`): PySD cannot run them either.
- **DELAY N / SMOOTH N of any whole order.** Written out as the case format compiles `delay3` and
  `smooth3`: a material DELAY N is a chain of n hidden stocks at n / T each, a SMOOTH N (or an
  information DELAY N) n hidden stages with exact flows. Orders 1 and 3 keep their `delay1/3`,
  `smooth/smooth3` forms, so cases 100-110 rebuild byte for byte. No test model is newly exact through
  this alone: `arguments` converts but differs (one of its stages is faster than a step, below), and
  `delays`, `smooth`, `subscripted_smooth` change their order or time during the run. The unit tests
  (`tests/test_ladder_canonical.py`) check orders 2 and 4 against PySD.

Every converted model is still checked against PySD's own run, at every recorded step, by
`equivalent()`. Two reasons for a difference are new names: **a drain faster than one step**
(`arguments`: a DELAY3 of time 2 has stages at 1.5 per step; Euler overshoots, SD Lab's floor caps the
outflow at the level) and **external data in a file that is not there**.

## Remaining blockers, by count (all 165 models; a model can have several)

For **queue item 2d (the engine)**:

| feature | models | only blocker | examples |
|---|---|---|---|
| a two-way flow (a rate goes negative) | 30 | 28 | lookups, rounding, subscript_transposition, the harmonic oscillator; 19 convert and differ |
| a stock that goes negative | 9 | 9 | abs, exp, trig (stocks that start below 0), special_characters, variable_ranges |
| fixed delay (DELAY FIXED) | 3 | 2 | delay_fixed, delay_pipeline, Query_file |
| a delay or smoothing whose time, or order, changes | 3 | 0 | delays, smooth, subscripted_smooth (each also has an order that changes) |
| MIN / MAX of stocks | 2 | 1 | Workforce (capacity-limited completion), Query_file |
| ratios of stocks | 0 here | - | World3's assimilation and Forrester's market growth (below) |
| sqrt and power of a stock | 0 here | - | the `sqrt` and `power` tests apply them to numbers or to TIME; `power` is blocked by a two-way flow |
| an outflow larger than the stock within one step / a drain faster than one step | 2 | 2 | Lotka-Volterra, arguments (the floor caps outflows against the level before the step's inflows) |
| trigonometry of a stock; a nonlinear polynomial | 1 + 1 | 2 | pendulum (sin of the angle); Roessler (x z) |
| Vensim's pipeline stock (a measured stock that holds a delay's contents) | 3 | 3 | the Population sample, delay_numeric_error, subscripted_delays |
| TREND / FORECAST | 3 | 3 | trend, forecast, subscripted_trend (two smoothings and a ratio) |

Left in the converter or outside SD Lab's scope: vector and matrix functions (VECTOR SELECT, VECTOR
REORDER, INVERT MATRIX: 3), ALLOCATE (2), SAMPLE IF TRUE (1), a simulation setting that changes
(2), a number that is not finite (3), PySD cannot read or run the file (4: XMILE modules, a drawing
test, GET TIME VALUE relative to the run, a model that broadcasts data PySD cannot), data files that
are not in the repository (2), random functions (with other blockers, 1), no stocks (1), and one
model whose runs differ for a parsing reason (`exponentiation`, below).

## What "exact" means here

A model counts as exact when `pysd_import.convert` writes a case body and `equivalent` finds SD Lab's
run within 1e-4 + 1e-7 x the stock's largest level of PySD's at every recorded step
(`docs/LADDER.md`, "Canonical cases"). Read the numbers with three caveats:

- **Most one-function tests have no stocks.** The importer wraps each auxiliary nothing reads in an
  accumulator stock (`acc_x = INTEG(x)`), so the function under test becomes a flow. 56 of the 90
  exact models are wrapped this way (36 of the 53 new ones), and most of the subscript tests that do
  have stocks feed them constants or one-stock rates: they show that the flattening is exact, not
  that discovery has much to find.
- **A function of constants or of TIME is not a function of a stock.** The `sqrt`, `ln`, `log`,
  `xidz_zidz` and `logicals` tests apply their function to numbers, which the importer folds into a
  number. `builtin_max`, `if_stmt` and `comparisons` apply theirs to TIME, which becomes a measured
  input. So "exact" means this file as written, not the function in general. Where a function meets a
  stock, it is counted as a missing feature: SQRT, MIN/MAX, IF THEN ELSE and EXP of a stock are all
  blocked (`tests/test_ladder_canonical.py` checks each is named).
- **The samples are the realistic measure.** 3 of 12 convert. The `arrays` sample (a2a) is new, but it
  holds no dynamics (two constant sales accumulated, at dt 1/4). The other 9 lack: the Population
  sample a pipeline stock (`Population = INTEG(Births - DELAY3(...))`, its arrays now flatten), MIN
  (Workforce), trigonometry of a stock (pendulum), a two-way flow (harmonic oscillator), a nonlinear
  polynomial (Roessler), fixed delays, random numbers and MIN (Query_file). Two cannot be read by PySD
  at all (hares and lynxes uses XMILE modules; display is a drawing test). Lotka-Volterra converts but
  differs, at its own numbers, for a reason worth knowing: when predators peak, the prey's deaths in
  one Euler step exceed what the prey holds before that step's births. SD Lab's floor caps outflows
  against the level before inflows, so the prey is emptied. PySD's prey stays positive because it nets
  births against deaths.
- **One test differs for a parsing reason.** In `exponentiation`, the importer reads `-2^2` as
  (-2)^2 = 4, but PySD's own run treats `associativity = 4` as false. The importer follows PySD's
  parsed tree, so this is a disagreement in PySD's code generation, not in a feature.

## New canonical case

The only sample newly convertible, `arrays` (a2a), has no dynamics, so it was not made a case. One test
model with real dynamics was: **111-canonical-arrayed-switching** (SDXorg `tests/subscript_switching`,
MIT, copied unchanged to `canonical/models/sdxorg-subscript-switching.mdl`). Five categories
`Categories[Cats]` switch through a doubly stochastic 5 x 5 transition matrix with gain 0.1 (`SUM` over
`Cats!`); flattened, each category drains at 0.1 x its level and fills from outside at a linear
combination of the other four, so the total is conserved. The model starts with a total of 1, so the
recipe adds an announced 4999 into c1 at step 1 and then, every 100 steps, moves 1000 into c1 from the
other four (announced injections of -250 each; `build.py` gained one-off injections, `inject:`).
PySD and SD Lab agree to 5e-5 over the model's 100 steps. The model
writes the switching as an inflow and an outflow per category, not as 20 pairwise moves, so that is
its answer key.

## The leaders on the canonical cases

Run on 2026-10-18 with `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
NUMBA_NUM_THREADS=1 uv run sdlab-ladder run --strategies combined,lna_stack,lna,earned_pieces,effect_hats,censored,matrix
--cases ... --jobs 3 --timeout 300`. Cases 100 and 104 ran on commit 3660a5d and the others on 08ef0d7
(the dt-1 rebuild; the cases are the same in both commits apart from that). Some strategies ran with
other agents' uncommitted edits (`code_dirty` in the store). Each cell gives the four variants in the
order none-short, none-long, counts-short, counts-long (P pass, E equivalent, f fail, X error), then
the mean fresh-run skill@100 over the variants. The table is from `sdlab.ladder.store.latest`.

| case | combined | lna_stack | lna | earned_pieces | effect_hats | censored | matrix |
|---|---|---|---|---|---|---|---|
| 100-canonical-sir | fPff 91% | ffff 97% | ffff 97% | ffff 99% | fPff 99% | ffff 97% | ffff 97% |
| 101-canonical-seir | ffPf 100% | ffPf 99% | ffff 97% | ffff 94% | ffff 99% | ffff 98% | ffff 99% |
| 102-canonical-bass | fffP 100% | ffff 95% | ffff 94% | ffff 95% | fffP 98% | ffff 95% | ffff 94% |
| 103-canonical-logistic | ffff 100% | ffff 100% | ffff 100% | ffff 100% | ffff 100% | ffff 100% | ffff 100% |
| 104-canonical-teacup | fffE 100% | ffEE 100% | ffEE 100% | fffE 100% | fffE 100% | ffEE 100% | ffEE 100% |
| 105-canonical-inventory-supply-line | ffff -62% | fffX -63% | ffff -84% | ffff -43% | ffff -90% | ffff -73% | ffff -73% |
| 106-canonical-workforce | ffff 98% | XXXX nan% | ffff 93% | ffff 97% | ffff -3% | ffff -0% | ffff 97% |
| 107-canonical-rework | ffff 99% | ffff 100% | ffff 99% | ffff 100% | ffff 99% | ffff 99% | ffff 99% |
| 108-canonical-commodity-cycle | ffff 97% | ffff 55% | ffff 55% | ffff 35% | ffff 96% | ffff 42% | ffff 42% |
| 109-canonical-limits-to-growth | ffff 99% | ffff 99% | ffff 98% | ffff 99% | ffff 99% | ffff 99% | ffff 99% |
| 110-canonical-world3-pollution | ffff 84% | XXfX 88% | ffff 79% | ffff 52% | ffff -40% | ffff 41% | ffff 79% |

**Pass rate:** 6 passes and 11 "equivalent" in 308 cells (7 strategies x 11 cases x 4 variants), 8 errors;
no strategy passes more than 3 of its 44. combined 3 pass + 1 equivalent of 44; effect_hats 2 + 1; lna_stack 1 + 2 (8 errors); lna, censored and
matrix 0 + 2; earned_pieces 0 + 1. Behaviour is far better than the equations: fresh skill@100 is 94-100%
on SIR, SEIR, Bass, logistic, teacup, rework and limits to growth for most leaders.

**What they fail at** (`uv run sdlab-ladder show <case> --strategy combined --variant none-long`):

- **Products of two stocks** (SIR, SEIR, Bass, logistic: rate x effect of another or the same stock).
  The linear strategies write S x I as links and outside flows (SIR matrix: 7 flows, 521 pieces).
  combined and effect_hats find the Bass word-of-mouth flow, but as one move with a table effect
  instead of p x P plus q x P x A / N (recall 100%, the move's number 2% off). No leader finds
  logistic crowding deaths, (r/K) X x X: they fit a drain k X and an inflow cut into about 88 pieces.
- **Sub-steps** (teacup, SIR; dt 1/8, 1/32): with no noise the teacup's drain is found as 0.0957
  against 0.1 (1 - (1 - 0.1/8)^8 = 0.0957), and the constant -7 as a +6.7 inflow. That is
  "equivalent" under counts noise and a fail without noise. This is the data's limit, not the
  method's: the per-step truth of sub-step data is not the per-time-unit model the scorer compares
  against (see "Blocked and open" below).
- **Hidden structure**: the rework cycle's undiscovered rework (a hidden loop W -> U -> W) is never
  found; leaders write a link from work done instead. The commodity cycle's construction delay and
  the World3 transmission delay are not found either.
- **Gap rules reading two stocks and an input** (workforce): leaders get assimilation and expert
  quits exactly, but write hiring as about 145 pieces of an outside inflow, not (desired - R - E) / 6.
- **lna_stack errors** on 105, 106 and 110 (8 cells): `sdlab/discovery/strategies/impulses.py:42`
  indexes the stocks with a measured input's name (`ValueError: 'customer_demand' is not in list`).
  It treats an input column as a stock. This is for the owner of `impulses.py` (not changed here).

## Blocked and open

- **Scoring of a delay fed from outside.** In 105 (orders through a DELAY3 into inventory), 108
  (construction) and 110 (pollution appearance), the delay chain starts outside. The answer key
  (`parts.py`) reads a DELAYn chain only between two measured stocks, so those inflows are not parts:
  105 and 110 score one part each. A pass on them checks less than their `tests:` say. Proposed: score
  an outside-fed chain as a hidden inflow with its delay. A scoring change needs the user's sight
  (CLAUDE.md rule 5).
- **Sub-step data.** The scorer compares a dt < 1 case with the model's per-time-unit numbers. The
  best per-step description differs by O(k^2), up to 10% for k = 0.2. Either the oracle accounts for
  dt, or discovery fits continuous time. 100 and 104 are the probes; the cases written for SD Lab use
  dt 1. (A first run with them at dt 0.25-0.5 on 3660a5d showed this confound everywhere; they were
  rebuilt at dt 1 in 08ef0d7, an hour after they were added.)
- **World3**: the full persistent pollution sector is blocked by its ratio (Michaelis-Menten
  assimilation). Case 110 is the sector below its 1970 level. Market growth (Forrester) was not
  attempted, for the same reason (backlog / capacity).

## Tables (generated by `coverage.py` at 2deb86d)

### Sample models (12)

| status | models |
|---|---|
| exact | 3 |
| exact with inputs | 0 |
| differs | 1 |
| blocked | 8 |
| no model | 0 |
| total | 12 |

### One-function tests (153)

| status | models |
|---|---|
| exact | 72 |
| exact with inputs | 15 |
| differs | 26 |
| blocked | 38 |
| no model | 2 |
| total | 153 |

### Missing features (all 165 models)

A blocked model can lack several features; "only blocker" counts the models that lack this one and nothing else (adding it would convert them, unless the runs then differ).

| feature | models | only blocker |
|---|---|---|
| a two-way flow (a rate goes negative) | 30 | 28 |
| a stock that goes negative | 9 | 9 |
| a delay whose material sits in a measured stock (Vensim's pipeline stock) | 3 | 3 |
| fixed delay (DELAY FIXED) | 3 | 2 |
| a number that is not finite | 3 | 1 |
| a delay or smoothing whose time changes | 3 | 0 |
| a DELAY N / SMOOTH N whose order changes | 3 | 0 |
| TREND / FORECAST | 3 | 3 |
| vector and matrix functions (VECTOR SELECT, VECTOR ELM MAP, ...) | 3 | 3 |
| MIN / MAX | 2 | 1 |
| PySD cannot read it | 2 | 2 |
| ALLOCATE | 2 | 2 |
| a simulation setting that changes | 2 | 2 |
| PySD cannot run it | 2 | 2 |
| external data in a file that is not there | 2 | 2 |
| an outflow larger than the stock within one step (the engine's floor ignores the step's inflows) | 1 | 1 |
| random functions | 1 | 0 |
| IF THEN ELSE | 1 | 0 |
| a nonlinear polynomial (not a product of linear factors) | 1 | 1 |
| trigonometry of a stock | 1 | 1 |
| no stocks | 1 | 1 |
| a drain faster than one step (k x dt > 1: the engine's floor caps it at the level, Euler overshoots) | 1 | 1 |
| the runs differ | 1 | 1 |
| SAMPLE IF TRUE | 1 | 1 |

### Functions of time held as measured inputs (in the "exact with inputs" models)

| function | models |
|---|---|
| IF_THEN_ELSE | 5 |
| CMP_GT | 4 |
| LOOKUP | 4 |
| CMP_LT | 3 |
| CMP_EQ | 2 |
| STEP | 2 |
| SIN | 2 |
| CMP_AND | 2 |
| CMP_OR | 2 |
| MAX | 1 |
| MIN | 1 |
| CMP_GE | 1 |
| CMP_LE | 1 |
| CMP_NE | 1 |
| TIME | 1 |
| PULSE | 1 |
| PULSE_TRAIN | 1 |
| RAMP | 1 |
| MODULO | 1 |
| CMP_NOT | 1 |

### Every model

| folder | file | status | features or reason |
|---|---|---|---|
| samples/Lotka_Volterra | samples/Lotka_Volterra/Lotka_Volterra.mdl | differs | an outflow larger than the stock within one step (the engine's floor ignores the step's inflows) |
| samples/Population | samples/Population/Subscripted Population Model.mdl | blocked | a delay whose material sits in a measured stock (Vensim's pipeline stock) |
| samples/Query_file | samples/Query_file/Query_file.mdl | blocked | fixed delay (DELAY FIXED), random functions, IF THEN ELSE, MIN / MAX |
| samples/Roessler_Chaos | samples/Roessler_Chaos/roessler_chaos.mdl | blocked | a nonlinear polynomial (not a product of linear factors) |
| samples/SIR | samples/SIR/SIR.mdl | exact |  |
| samples/Workforce | samples/Workforce/workforce.mdl | blocked | MIN / MAX |
| samples/arrays | samples/arrays/a2a/a2a.stmx | exact | accumulated |
| samples/bpowers-hares_and_lynxes_modules | samples/bpowers-hares_and_lynxes_modules/model.xmile | blocked | PySD cannot read it |
| samples/display | samples/display/1style.stmx | blocked | PySD cannot read it |
| samples/pendulum | samples/pendulum/Single_Pendulum.mdl | blocked | trigonometry of a stock |
| samples/simple_harmonic_oscillator | samples/simple_harmonic_oscillator/simple_harmonic_oscillator.mdl | blocked | a two-way flow (a rate goes negative) |
| samples/teacup | samples/teacup/teacup.mdl | exact |  |
| tests/abs | tests/abs/test_abs.mdl | blocked | a stock that goes negative |
| tests/active_initial | tests/active_initial/test_active_initial.mdl | exact |  |
| tests/active_initial_circular | tests/active_initial_circular/test_active_initial_circular.mdl | blocked | no stocks |
| tests/allocate_available | tests/allocate_available/test_allocate_available.mdl | blocked | ALLOCATE |
| tests/allocate_by_priority | tests/allocate_by_priority/test_allocate_by_priority.mdl | blocked | ALLOCATE |
| tests/arguments | tests/arguments/test_arguments.mdl | differs | a drain faster than one step (k x dt > 1: the engine's floor caps it at the level, Euler overshoots) |
| tests/arithmetics | tests/arithmetics/test_arithmetics.mdl | blocked | a two-way flow (a rate goes negative), a number that is not finite |
| tests/arithmetics_exp | tests/arithmetics_exp/test_arithmetics_exp.mdl | blocked | a number that is not finite, a two-way flow (a rate goes negative) |
| tests/array_with_line_break | tests/array_with_line_break/test_array_with_line_break.mdl | exact | accumulated |
| tests/builtin_max | tests/builtin_max/builtin_max.mdl | exact with inputs | accumulated; inputs: MAX |
| tests/builtin_min | tests/builtin_min/builtin_min.mdl | exact with inputs | accumulated; inputs: MIN |
| tests/case_sensitive_extension | tests/case_sensitive_extension/teacup-upper.MDL | exact |  |
| tests/chained_initialization | tests/chained_initialization/test_chained_initialization.mdl | exact |  |
| tests/comparisons | tests/comparisons/comparisons.xmile | exact with inputs | accumulated; inputs: CMP_EQ, CMP_GE, CMP_GT, CMP_LE, CMP_LT, CMP_NE |
| tests/conditional_subscripts | tests/conditional_subscripts/test_conditional_subscripts.mdl | exact | accumulated |
| tests/constant_expressions | tests/constant_expressions/test_constant_expressions.mdl | exact | accumulated |
| tests/control_vars | tests/control_vars/test_control_vars.mdl | blocked | a simulation setting that changes |
| tests/data_from_other_model | tests/data_from_other_model/model_to_generate_data.mdl | blocked | PySD cannot run it |
| tests/delay_fixed | tests/delay_fixed/test_delay_fixed.mdl | blocked | fixed delay (DELAY FIXED) |
| tests/delay_numeric_error | tests/delay_numeric_error/test_delay_numeric_error.mdl | blocked | a delay whose material sits in a measured stock (Vensim's pipeline stock) |
| tests/delay_parentheses | tests/delay_parentheses/test_delay_parentheses.mdl | exact with inputs | accumulated; inputs: STEP |
| tests/delay_pipeline | tests/delay_pipeline/test_pipeline_delays.mdl | blocked | fixed delay (DELAY FIXED) |
| tests/delay_xmile | tests/delay_xmile/test_delay_xmile.xmile | exact |  |
| tests/delays | tests/delays/test_delays.mdl | blocked | a delay or smoothing whose time changes, a DELAY N / SMOOTH N whose order changes |
| tests/dynamic_final_time | tests/dynamic_final_time/test_dynamic_final_time.mdl | blocked | a simulation setting that changes |
| tests/elm_count | tests/elm_count/test_elm_count.mdl | exact | accumulated |
| tests/euler_step_vs_saveper | tests/euler_step_vs_saveper/test_euler_step_vs_saveper.mdl | differs | a two-way flow (a rate goes negative) |
| tests/eval_order | tests/eval_order/eval_order.xmile | exact | accumulated |
| tests/except | tests/except/test_except.mdl | exact with inputs | inputs: SIN, TIME |
| tests/except_multiple | tests/except_multiple/test_except_multiple.mdl | differs | a two-way flow (a rate goes negative) |
| tests/except_subranges | tests/except_subranges/test_except_subranges.mdl | exact | accumulated |
| tests/exp | tests/exp/test_exp.mdl | blocked | a stock that goes negative |
| tests/exponentiation | tests/exponentiation/exponentiation.mdl | differs | the runs differ |
| tests/forecast | tests/forecast/test_forecast.mdl | blocked | TREND / FORECAST |
| tests/fully_invalid_names | tests/fully_invalid_names/test_fully_invalid_names.mdl | exact | accumulated |
| tests/function_capitalization | tests/function_capitalization/test_function_capitalization.mdl | blocked | a stock that goes negative |
| tests/game | tests/game/test_game.mdl | exact |  |
| tests/get_constants | tests/get_constants/test_get_constants.mdl | blocked | external data in a file that is not there |
| tests/get_constants_incomplete_subscript | tests/get_constants_incomplete_subscript/test_get_constants_incomplete_subscript.mdl | exact | accumulated |
| tests/get_constants_subranges | tests/get_constants_subranges/test_get_constants_subranges.mdl | exact | accumulated |
| tests/get_data | tests/get_data/test_get_data.mdl | blocked | external data in a file that is not there |
| tests/get_data_args_3d_xls | tests/get_data_args_3d_xls/test_get_data_args_3d_xls.mdl | differs | a two-way flow (a rate goes negative) |
| tests/get_lookups_data_3d_xls | tests/get_lookups_data_3d_xls/test_get_lookups_data_3d_xls.mdl | differs | a two-way flow (a rate goes negative) |
| tests/get_lookups_subscripted_args | tests/get_lookups_subscripted_args/test_get_lookups_subscripted_args.mdl | differs | a two-way flow (a rate goes negative) |
| tests/get_lookups_subset | tests/get_lookups_subset/test_get_lookups_subset.mdl | differs | a two-way flow (a rate goes negative) |
| tests/get_mixed_definitions | tests/get_mixed_definitions/test_get_mixed_definitions.mdl | exact with inputs | accumulated; inputs: LOOKUP |
| tests/get_subscript_3d_arrays_xls | tests/get_subscript_3d_arrays_xls/test_get_subscript_3d_arrays_xls.mdl | exact | accumulated |
| tests/get_time_value | tests/get_time_value/test_get_time_value.mdl | blocked | PySD cannot run it |
| tests/get_values_order | tests/get_values_order/test_get_values_order.mdl | exact | accumulated |
| tests/get_with_missing_values_xlsx | tests/get_with_missing_values_xlsx/test_get_with_missing_values_xlsx.mdl | exact with inputs | accumulated; inputs: LOOKUP |
| tests/get_xls_cellrange | tests/get_xls_cellrange/test_get_xls_cellrange.mdl | differs | a two-way flow (a rate goes negative) |
| tests/if_stmt | tests/if_stmt/if_stmt.mdl | exact with inputs | accumulated; inputs: CMP_GT, IF_THEN_ELSE |
| tests/initial_function | tests/initial_function/test_initial.mdl | exact |  |
| tests/input_functions | tests/input_functions/test_inputs.mdl | exact with inputs | inputs: PULSE, PULSE_TRAIN, RAMP, STEP |
| tests/invert_matrix | tests/invert_matrix/test_invert_matrix.mdl | blocked | vector and matrix functions (VECTOR SELECT, VECTOR ELM MAP, ...) |
| tests/limits | tests/limits/test_limits.mdl | exact |  |
| tests/line_breaks | tests/line_breaks/test_line_breaks.mdl | exact | accumulated |
| tests/line_continuation | tests/line_continuation/test_line_continuation.mdl | exact |  |
| tests/ln | tests/ln/test_ln.mdl | exact |  |
| tests/log | tests/log/test_log.mdl | exact | accumulated |
| tests/logicals | tests/logicals/test_logicals.mdl | exact | accumulated |
| tests/lookups | tests/lookups/test_lookups.mdl | differs | a two-way flow (a rate goes negative) |
| tests/lookups_funcnames | tests/lookups_funcnames/test_lookups_funcnames.mdl | differs | a two-way flow (a rate goes negative) |
| tests/lookups_inline | tests/lookups_inline/test_lookups_inline.mdl | differs | a two-way flow (a rate goes negative) |
| tests/lookups_inline_bounded | tests/lookups_inline_bounded/test_lookups_inline_bounded.mdl | exact | accumulated |
| tests/lookups_inline_spaces | tests/lookups_inline_spaces/test_lookups_inline_spaces.mdl | differs | a two-way flow (a rate goes negative) |
| tests/lookups_with_expr | tests/lookups_with_expr/test_lookups_with_expr.mdl | exact with inputs | accumulated; inputs: LOOKUP, SIN |
| tests/lookups_without_range | tests/lookups_without_range/test_lookups_without_range.mdl | differs | a two-way flow (a rate goes negative) |
| tests/macro_cross_reference | tests/macro_cross_reference/test_macro_cross_reference.mdl | exact | accumulated |
| tests/macro_expression | tests/macro_expression/test_macro_expression.mdl | exact | accumulated |
| tests/macro_multi_expression | tests/macro_multi_expression/test_macro_multi_expression.mdl | exact | accumulated |
| tests/macro_multi_macros | tests/macro_multi_macros/test_macro_multi_macros.mdl | exact | accumulated |
| tests/macro_stock | tests/macro_stock/test_macro_stock.mdl | exact |  |
| tests/macro_trailing_definition | tests/macro_trailing_definition/test_macro_trailing_definition.mdl | exact | accumulated |
| tests/min_max_1arg | tests/min_max_1arg/test_min_max_1arg.xmile | exact | accumulated |
| tests/model_doc | tests/model_doc/model_doc.mdl | exact | accumulated |
| tests/multiple_lines_def | tests/multiple_lines_def/test_multiple_lines_def.mdl | exact | accumulated |
| tests/na | tests/na/test_na.mdl | blocked | a number that is not finite |
| tests/nested_functions | tests/nested_functions/test_nested_functions.mdl | exact with inputs | inputs: CMP_LT, IF_THEN_ELSE, MODULO |
| tests/non_negative_all | tests/non_negative_all/test_non_negative_all1.xmile | differs | a stock that goes negative |
| tests/non_negative_flows | tests/non_negative_flows/test_non_negative_flows.xmile | differs | a two-way flow (a rate goes negative) |
| tests/non_negative_stocks | tests/non_negative_stocks/test_non_negative_stocks.xmile | differs | a two-way flow (a rate goes negative) |
| tests/number_handling | tests/number_handling/test_number_handling.mdl | exact | accumulated |
| tests/odd_number_quotes | tests/odd_number_quotes/teacup_3quotes.mdl | exact |  |
| tests/parentheses | tests/parentheses/test_parens.mdl | exact | accumulated |
| tests/partial_range_definitions | tests/partial_range_definitions/test_partial_range_definitions.mdl | exact with inputs | accumulated; inputs: LOOKUP |
| tests/pi | tests/pi/test_pi.xmile | blocked | a two-way flow (a rate goes negative) |
| tests/power | tests/power/power.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/reality_checks | tests/reality_checks/test_reality_checks.mdl | exact | accumulated |
| tests/reference_capitalization | tests/reference_capitalization/test_reference_capitalization.mdl | exact | accumulated |
| tests/repeated_subscript | tests/repeated_subscript/test_repeated_subscript.mdl | exact | accumulated |
| tests/rounding | tests/rounding/test_rounding.mdl | differs | a two-way flow (a rate goes negative) |
| tests/sample_if_true | tests/sample_if_true/test_sample_if_true.mdl | blocked | SAMPLE IF TRUE |
| tests/smaller_range | tests/smaller_range/test_smaller_range.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/smooth | tests/smooth/test_smooth.mdl | blocked | a DELAY N / SMOOTH N whose order changes, a delay or smoothing whose time changes |
| tests/smooth_and_stock | tests/smooth_and_stock/test_smooth_and_stock.mdl | exact |  |
| tests/special_characters | tests/special_characters/test_special_variable_names.mdl | differs | a stock that goes negative |
| tests/special_characters_xmile | tests/special_characters_xmile/test_special_variable_names.xmile | differs | a stock that goes negative |
| tests/sqrt | tests/sqrt/test_sqrt.mdl | exact |  |
| tests/subrange_merge | tests/subrange_merge/test_subrange_merge.mdl | exact | accumulated |
| tests/subscript_1d_arrays | tests/subscript_1d_arrays/test_subscript_1d_arrays.mdl | exact |  |
| tests/subscript_2d_arrays | tests/subscript_2d_arrays/test_subscript_2d_arrays.mdl | exact |  |
| tests/subscript_3d_arrays | tests/subscript_3d_arrays/test_subscript_3d_arrays.mdl | exact |  |
| tests/subscript_3d_arrays_lengthwise | tests/subscript_3d_arrays_lengthwise/test_subscript_3d_arrays_lengthwise.mdl | exact | accumulated |
| tests/subscript_3d_arrays_widthwise | tests/subscript_3d_arrays_widthwise/test_subscript_3d_arrays_widthwise.mdl | exact | accumulated |
| tests/subscript_aggregation | tests/subscript_aggregation/test_subscript_aggregation.mdl | exact |  |
| tests/subscript_constant_call | tests/subscript_constant_call/test_subscript_constant_call.mdl | exact | accumulated |
| tests/subscript_copy | tests/subscript_copy/test_subscript_copy.mdl | exact |  |
| tests/subscript_definition | tests/subscript_definition/test_subscript_definition.mdl | exact | accumulated |
| tests/subscript_docs | tests/subscript_docs/subscript_docs.mdl | exact | accumulated |
| tests/subscript_element_name | tests/subscript_element_name/test_subscript_element_name.mdl | exact | accumulated |
| tests/subscript_exceptions |  | no model |  |
| tests/subscript_individually_defined_1_of_2d_arrays | tests/subscript_individually_defined_1_of_2d_arrays/subscript_individually_defined_1_of_2d_arrays.mdl | exact |  |
| tests/subscript_individually_defined_1_of_2d_arrays_from_floats | tests/subscript_individually_defined_1_of_2d_arrays_from_floats/subscript_individually_defined_1_of_2d_arrays_from_floats.mdl | exact |  |
| tests/subscript_individually_defined_1d_arrays | tests/subscript_individually_defined_1d_arrays/subscript_individually_defined_1d_arrays.mdl | exact |  |
| tests/subscript_individually_defined_stocks | tests/subscript_individually_defined_stocks/test_subscript_individually_defined_stocks.mdl | exact |  |
| tests/subscript_logicals | tests/subscript_logicals/test_subscript_logicals.mdl | exact with inputs | accumulated; inputs: CMP_AND, CMP_GT, CMP_OR, IF_THEN_ELSE |
| tests/subscript_mapping_simple | tests/subscript_mapping_simple/test_subscript_mapping_simple.mdl | differs | a two-way flow (a rate goes negative) |
| tests/subscript_mapping_vensim | tests/subscript_mapping_vensim/test_subscript_mapping_vensim.mdl | differs | a stock that goes negative |
| tests/subscript_mixed_assembly | tests/subscript_mixed_assembly/test_subscript_mixed_assembly.mdl | exact | accumulated |
| tests/subscript_multiples | tests/subscript_multiples/test_multiple_subscripts.mdl | exact |  |
| tests/subscript_numeric_range | tests/subscript_numeric_range/test_subscript_numeric_range.mdl | exact |  |
| tests/subscript_selection | tests/subscript_selection/subscript_selection.mdl | exact | accumulated |
| tests/subscript_subranges | tests/subscript_subranges/test_subscript_subrange.mdl | exact |  |
| tests/subscript_subranges_equal | tests/subscript_subranges_equal/test_subscript_subrange_equal.mdl | exact |  |
| tests/subscript_switching | tests/subscript_switching/subscript_switching.mdl | exact |  |
| tests/subscript_transposition | tests/subscript_transposition/test_subscript_transposition.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/subscript_updimensioning | tests/subscript_updimensioning/test_subscript_updimensioning.mdl | exact | accumulated |
| tests/subscripted_delays | tests/subscripted_delays/test_subscripted_delays.mdl | blocked | a delay whose material sits in a measured stock (Vensim's pipeline stock) |
| tests/subscripted_eqns |  | no model |  |
| tests/subscripted_flows | tests/subscripted_flows/test_subscripted_flows.mdl | exact |  |
| tests/subscripted_if_then_else | tests/subscripted_if_then_else/test_subscripted_if_then_else.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/subscripted_logicals | tests/subscripted_logicals/test_subscripted_logicals.mdl | exact with inputs | accumulated; inputs: CMP_AND, CMP_GT, CMP_LT, CMP_NOT, CMP_OR, IF_THEN_ELSE |
| tests/subscripted_lookups | tests/subscripted_lookups/test_subscripted_lookups.mdl | differs | a two-way flow (a rate goes negative) |
| tests/subscripted_ramp_step | tests/subscripted_ramp_step/test_subscripted_ramp_step.mdl | differs | a two-way flow (a rate goes negative) |
| tests/subscripted_round | tests/subscripted_round/test_subscripted_round.mdl | differs | a two-way flow (a rate goes negative) |
| tests/subscripted_smooth | tests/subscripted_smooth/test_subscripted_smooth.mdl | blocked | a delay or smoothing whose time changes, a DELAY N / SMOOTH N whose order changes |
| tests/subscripted_trend | tests/subscripted_trend/test_subscripted_trend.mdl | blocked | TREND / FORECAST |
| tests/subscripted_trig | tests/subscripted_trig/test_subscripted_trig.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/subscripted_xidz | tests/subscripted_xidz/test_subscripted_xidz.mdl | blocked | a two-way flow (a rate goes negative) |
| tests/subset_duplicated_coord | tests/subset_duplicated_coord/test_subset_duplicated_coord.mdl | exact | accumulated |
| tests/tabbed_arrays | tests/tabbed_arrays/tabbed_arrays.mdl | exact | accumulated |
| tests/time | tests/time/test_time.mdl | exact with inputs | inputs: CMP_EQ, IF_THEN_ELSE |
| tests/trend | tests/trend/test_trend.mdl | blocked | TREND / FORECAST |
| tests/trig | tests/trig/test_trig.mdl | blocked | a stock that goes negative |
| tests/unchangeable_constant | tests/unchangeable_constant/test_unchangeable_constant.mdl | exact | accumulated |
| tests/unicode_characters | tests/unicode_characters/unicode_test_model.mdl | exact | accumulated |
| tests/variable_ranges | tests/variable_ranges/test_variable_ranges.mdl | differs | a stock that goes negative |
| tests/vector_order | tests/vector_order/test_vector_order.mdl | blocked | vector and matrix functions (VECTOR SELECT, VECTOR ELM MAP, ...) |
| tests/vector_select | tests/vector_select/test_vector_select.mdl | blocked | vector and matrix functions (VECTOR SELECT, VECTOR ELM MAP, ...) |
| tests/with_lookup | tests/with_lookup/test_with_lookup.mdl | exact | accumulated |
| tests/xidz_zidz | tests/xidz_zidz/xidz_zidz.mdl | exact | accumulated |
| tests/zeroled_decimals | tests/zeroled_decimals/test_zeroled_decimals.mdl | blocked | a two-way flow (a rate goes negative) |
