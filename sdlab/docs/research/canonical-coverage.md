# Canonical coverage: how much of SDXorg/test-models SD Lab's case format holds exactly

**Status:** done (measurement; queue item 2). **Code:** commit 3660a5d (`sdlab/ladder/pysd_import.py`,
`sdlab/ladder/canonical/`). **Measured** on 2026-10-18 with
`uv run --with pysd --with sympy python -m sdlab.ladder.canonical.coverage <test-models> --markdown ...`,
on [SDXorg/test-models](https://github.com/SDXorg/test-models) at 21aab02 (MIT), PySD 3.14.3, sympy
1.14.0. The test-models files are fetched at run time, not committed (except the SIR and teacup samples,
copied with their MIT licence into `canonical/models/`).

**Verdict:** of the 165 models (12 samples, 153 one-function tests), **37 convert exactly** (SD Lab's
engine with noise `none` gives PySD's Euler levels at every recorded step): 2 samples (SIR, teacup) and
35 tests, 9 of them with functions of time held as measured inputs. **15 convert but differ** (13 of
them because a rate or a stock goes negative, which SD Lab floors at 0), **111 are blocked** by a
feature the format lacks, and 2 test folders hold no model. The one missing feature that matters most
is **arrays** (79 models; the only blocker in 71). Next, by count: **two-way flows / negative stocks**
(21 models), **macros** (6), **DELAY N / SMOOTH N of other orders** (5), **external data** (4) and
**DELAY FIXED** (3). Arrays, macros, external data and other delay orders could be handled in the
importer alone, by flattening, inlining, reading the data into inputs, and writing out n-stage chains.
Two-way flows and fixed delays need the engine.

## What "exact" means here

A model counts as exact when `pysd_import.convert` writes a case body and `equivalent` finds SD Lab's
run within 1e-4 + 1e-7 x the stock's largest level of PySD's at every recorded step
(`docs/LADDER.md`, "Canonical cases"). Read the numbers with three caveats:

- **Most one-function tests have no stocks.** The importer wraps each auxiliary nothing reads in an
  accumulator stock (`acc_x = INTEG(x)`), so the function under test becomes a flow. 20 of the 37
  exact models are wrapped this way.
- **A function of constants or of TIME is not a function of a stock.** The `sqrt`, `ln`, `log`,
  `xidz_zidz` and `logicals` tests apply their function to numbers, which the importer folds into a
  number. `builtin_max`, `if_stmt` and `comparisons` apply theirs to TIME, which becomes a measured
  input. So "exact" means this file as written, not the function in general. Where a function meets a
  stock, it is counted as a missing feature: SQRT, MIN/MAX, IF THEN ELSE and EXP of a stock are all
  blocked (`tests/test_ladder_canonical.py` checks each is named).
- **The samples are the realistic measure.** 2 of 12 convert. The other 10 lack arrays (Population,
  arrays), MIN (Workforce), trigonometry of a stock (pendulum), a two-way flow (harmonic oscillator), a
  nonlinear polynomial (Roessler), fixed delays, random numbers and MIN (Query_file). Two cannot be
  read by PySD at all (hares and lynxes uses XMILE modules; display is a drawing test). Lotka-Volterra
  converts but differs, at its own numbers, for a reason worth knowing: when predators peak, the
  prey's deaths in one Euler step exceed what the prey holds before that step's births. SD Lab's
  floor caps outflows against the level before inflows, so the prey is emptied. PySD's prey stays
  positive because it nets births against deaths.
- **One test differs for a parsing reason.** In `exponentiation`, the importer reads `-2^2` as
  (-2)^2 = 4, but PySD's own run treats `associativity = 4` as false. The importer follows PySD's
  parsed tree, so this is a disagreement in PySD's code generation, not in a feature.

## Top missing features (what to add next)

Counted over all 165 models; a model can lack several. "Only blocker" is the number that would
convert once that feature exists, unless their runs then differ.

| # | feature | models | only blocker | where it would go |
|---|---|---|---|---|
| 1 | arrays (subscripts) | 79 | 71 | the importer: one stock per element, flows per element (no engine change) |
| 2 | two-way flows and stocks that go negative | 21 (13 + 8) | 20 | the engine: a flow whose rate may be negative (net flows, heat exchange, the oscillators), and stocks without the floor |
| 3 | macros | 6 | 6 | the importer: inline each macro call |
| 4 | DELAY N / SMOOTH N of order other than 1 or 3 | 5 | 2 | the case format: `delayn(rate, T, n)` as n hidden stocks (an additive rewrite, like delay3) |
| 5 | external data (GET XLS, GET DIRECT, DATA) | 4 | 2 | the importer: read the data into measured inputs |
| 6 | DELAY FIXED (pipeline delay) | 3 | 1 | the engine: a pure delay (or a long chain as an approximation, which the rule "exact" excludes) |
| 7 | a delay or smoothing whose time changes | 2 | 0 | the engine |
| 8 | TREND / FORECAST | 2 | 1 | the case format: a TREND is two smoothings and a ratio, so it needs ratios too |
| 9 | MIN / MAX of stocks | 2 (+ the Workforce sample) | 1 | the engine: a rate form min(a, b) (capacity limits) |
| 10 | division by a stock (a ratio) | 0 here; World3 and Forrester's market growth (below) | - | the engine: a ratio or Michaelis-Menten form, x / (a + b x) |

Writing the canonical cases by hand turned up more limits that the test-models barely exercise:

- **Ratios of stocks.** World3's pollution assimilation, PPOL / (1.4 x AHL70 x AHLM(PPOL / PPOL70)),
  is a ratio. AHLM is linear, so this is a saturating Michaelis-Menten form, and
  `canonical/models/world3-pollution-full.mdl` is blocked by it (a test checks this). Case 110 is
  that sector below its 1970 level, where AHLM = 1 and the sector is exact. Forrester's market-growth
  model reads delivery delay as backlog / capacity, so it was not attempted; case 109 is the
  limits-to-growth archetype instead.
- **Vensim's pipeline stock.** `Stock = INTEG(in - DELAY3(in, T))` makes the delay's contents a
  measured stock: the stock is the sum of three hidden stages. SD Lab cannot measure a sum of hidden
  stocks. The importer names this pattern ("a delay whose material sits in a measured stock"), and
  case 105 keeps the supply line inside the delay instead.
- **MAX(0, x) and MIN(capacity, demand).** `MAX(0, x)` over a whole rate is SD Lab's own floor, and the
  importer takes it (case 105's orders, case 106's hiring). MIN of two rates (capacity-limited
  completion, the Workforce sample) has no form.

## Tables (generated by `coverage.py`)

### Sample models (12)

| status | models |
|---|---|
| exact | 2 |
| exact with inputs | 0 |
| differs | 1 |
| blocked | 9 |
| no model | 0 |
| total | 12 |

### One-function tests (153)

| status | models |
|---|---|
| exact | 26 |
| exact with inputs | 9 |
| differs | 14 |
| blocked | 102 |
| no model | 2 |
| total | 153 |

### Missing features (all 165 models)

A blocked model can lack several features; "only blocker" counts the models that lack this one and nothing else (adding it would convert them, unless the runs then differ).

| feature | models | only blocker |
|---|---|---|
| arrays (subscripts) | 79 | 71 |
| a two-way flow (a rate goes negative) | 13 | 12 |
| a stock that goes negative | 8 | 8 |
| macros | 6 | 6 |
| DELAY N / SMOOTH N of order other than 1 or 3 | 5 | 2 |
| external data (GET XLS / DATA) | 4 | 2 |
| fixed delay (DELAY FIXED) | 3 | 1 |
| MIN / MAX | 2 | 1 |
| PySD cannot read it | 2 | 2 |
| a simulation setting that changes | 2 | 2 |
| a delay or smoothing whose time changes | 2 | 0 |
| a reference PySD did not define | 2 | 0 |
| TREND / FORECAST | 2 | 1 |
| an outflow larger than the stock within one step (the engine's floor ignores the step's inflows) | 1 | 1 |
| random functions | 1 | 0 |
| IF THEN ELSE | 1 | 0 |
| a nonlinear polynomial (not a product of linear factors) | 1 | 1 |
| trigonometry of a stock | 1 | 1 |
| no stocks | 1 | 1 |
| PySD cannot run it | 1 | 0 |
| the runs differ | 1 | 1 |
| a number that is not finite | 1 | 1 |
| SAMPLE IF TRUE | 1 | 0 |

### Functions of time held as measured inputs (in the "exact with inputs" models)

| function | models |
|---|---|
| IF_THEN_ELSE | 3 |
| CMP_EQ | 2 |
| CMP_GT | 2 |
| CMP_LT | 2 |
| STEP | 2 |
| MAX | 1 |
| MIN | 1 |
| CMP_GE | 1 |
| CMP_LE | 1 |
| CMP_NE | 1 |
| PULSE | 1 |
| PULSE_TRAIN | 1 |
| RAMP | 1 |
| LOOKUP | 1 |
| SIN | 1 |
| MODULO | 1 |

### Every model

| folder | file | status | features or reason |
|---|---|---|---|
| samples/Lotka_Volterra | samples/Lotka_Volterra/Lotka_Volterra.mdl | differs | an outflow larger than the stock within one step (the engine's floor ignores the step's inflows) |
| samples/Population | samples/Population/Subscripted Population Model.mdl | blocked | arrays (subscripts) |
| samples/Query_file | samples/Query_file/Query_file.mdl | blocked | fixed delay (DELAY FIXED), random functions, IF THEN ELSE, MIN / MAX |
| samples/Roessler_Chaos | samples/Roessler_Chaos/roessler_chaos.mdl | blocked | a nonlinear polynomial (not a product of linear factors) |
| samples/SIR | samples/SIR/SIR.mdl | exact |  |
| samples/Workforce | samples/Workforce/workforce.mdl | blocked | MIN / MAX |
| samples/arrays | samples/arrays/a2a/a2a.stmx | blocked | arrays (subscripts) |
| samples/bpowers-hares_and_lynxes_modules | samples/bpowers-hares_and_lynxes_modules/model.xmile | blocked | PySD cannot read it |
| samples/display | samples/display/1style.stmx | blocked | PySD cannot read it |
| samples/pendulum | samples/pendulum/Single_Pendulum.mdl | blocked | trigonometry of a stock |
| samples/simple_harmonic_oscillator | samples/simple_harmonic_oscillator/simple_harmonic_oscillator.mdl | blocked | a two-way flow (a rate goes negative) |
| samples/teacup | samples/teacup/teacup.mdl | exact |  |
| tests/abs | tests/abs/test_abs.mdl | blocked | a stock that goes negative |
| tests/active_initial | tests/active_initial/test_active_initial.mdl | exact |  |
| tests/active_initial_circular | tests/active_initial_circular/test_active_initial_circular.mdl | blocked | no stocks |
| tests/allocate_available | tests/allocate_available/test_allocate_available.mdl | blocked | arrays (subscripts) |
| tests/allocate_by_priority | tests/allocate_by_priority/test_allocate_by_priority.mdl | blocked | arrays (subscripts) |
| tests/arguments | tests/arguments/test_arguments.mdl | blocked | DELAY N / SMOOTH N of order other than 1 or 3 |
| tests/arithmetics | tests/arithmetics/test_arithmetics.mdl | blocked | arrays (subscripts) |
| tests/arithmetics_exp | tests/arithmetics_exp/test_arithmetics_exp.mdl | blocked | arrays (subscripts) |
| tests/array_with_line_break | tests/array_with_line_break/test_array_with_line_break.mdl | blocked | arrays (subscripts) |
| tests/builtin_max | tests/builtin_max/builtin_max.mdl | exact with inputs | accumulated; inputs: MAX |
| tests/builtin_min | tests/builtin_min/builtin_min.mdl | exact with inputs | accumulated; inputs: MIN |
| tests/case_sensitive_extension | tests/case_sensitive_extension/teacup-upper.MDL | exact |  |
| tests/chained_initialization | tests/chained_initialization/test_chained_initialization.mdl | exact |  |
| tests/comparisons | tests/comparisons/comparisons.xmile | exact with inputs | accumulated; inputs: CMP_EQ, CMP_GE, CMP_GT, CMP_LE, CMP_LT, CMP_NE |
| tests/conditional_subscripts | tests/conditional_subscripts/test_conditional_subscripts.mdl | blocked | arrays (subscripts) |
| tests/constant_expressions | tests/constant_expressions/test_constant_expressions.mdl | exact | accumulated |
| tests/control_vars | tests/control_vars/test_control_vars.mdl | blocked | a simulation setting that changes |
| tests/data_from_other_model | tests/data_from_other_model/model_to_generate_data.mdl | blocked | arrays (subscripts), PySD cannot run it |
| tests/delay_fixed | tests/delay_fixed/test_delay_fixed.mdl | blocked | fixed delay (DELAY FIXED) |
| tests/delay_numeric_error | tests/delay_numeric_error/test_delay_numeric_error.mdl | blocked | DELAY N / SMOOTH N of order other than 1 or 3 |
| tests/delay_parentheses | tests/delay_parentheses/test_delay_parentheses.mdl | exact with inputs | accumulated; inputs: STEP |
| tests/delay_pipeline | tests/delay_pipeline/test_pipeline_delays.mdl | blocked | DELAY N / SMOOTH N of order other than 1 or 3, fixed delay (DELAY FIXED) |
| tests/delay_xmile | tests/delay_xmile/test_delay_xmile.xmile | exact |  |
| tests/delays | tests/delays/test_delays.mdl | blocked | a delay or smoothing whose time changes, DELAY N / SMOOTH N of order other than 1 or 3 |
| tests/dynamic_final_time | tests/dynamic_final_time/test_dynamic_final_time.mdl | blocked | a simulation setting that changes |
| tests/elm_count | tests/elm_count/test_elm_count.mdl | blocked | a reference PySD did not define, arrays (subscripts) |
| tests/euler_step_vs_saveper | tests/euler_step_vs_saveper/test_euler_step_vs_saveper.mdl | differs | a two-way flow (a rate goes negative) |
| tests/eval_order | tests/eval_order/eval_order.xmile | exact | accumulated |
| tests/except | tests/except/test_except.mdl | blocked | arrays (subscripts) |
| tests/except_multiple | tests/except_multiple/test_except_multiple.mdl | blocked | arrays (subscripts) |
| tests/except_subranges | tests/except_subranges/test_except_subranges.mdl | blocked | arrays (subscripts) |
| tests/exp | tests/exp/test_exp.mdl | blocked | a stock that goes negative |
| tests/exponentiation | tests/exponentiation/exponentiation.mdl | differs | the runs differ |
| tests/forecast | tests/forecast/test_forecast.mdl | blocked | arrays (subscripts), TREND / FORECAST |
| tests/fully_invalid_names | tests/fully_invalid_names/test_fully_invalid_names.mdl | exact | accumulated |
| tests/function_capitalization | tests/function_capitalization/test_function_capitalization.mdl | blocked | a stock that goes negative |
| tests/game | tests/game/test_game.mdl | exact |  |
| tests/get_constants | tests/get_constants/test_get_constants.mdl | blocked | external data (GET XLS / DATA) |
| tests/get_constants_incomplete_subscript | tests/get_constants_incomplete_subscript/test_get_constants_incomplete_subscript.mdl | blocked | arrays (subscripts) |
| tests/get_constants_subranges | tests/get_constants_subranges/test_get_constants_subranges.mdl | blocked | arrays (subscripts) |
| tests/get_data | tests/get_data/test_get_data.mdl | blocked | external data (GET XLS / DATA) |
| tests/get_data_args_3d_xls | tests/get_data_args_3d_xls/test_get_data_args_3d_xls.mdl | blocked | arrays (subscripts) |
| tests/get_lookups_data_3d_xls | tests/get_lookups_data_3d_xls/test_get_lookups_data_3d_xls.mdl | blocked | arrays (subscripts) |
| tests/get_lookups_subscripted_args | tests/get_lookups_subscripted_args/test_get_lookups_subscripted_args.mdl | blocked | arrays (subscripts), external data (GET XLS / DATA) |
| tests/get_lookups_subset | tests/get_lookups_subset/test_get_lookups_subset.mdl | blocked | arrays (subscripts) |
| tests/get_mixed_definitions | tests/get_mixed_definitions/test_get_mixed_definitions.mdl | blocked | arrays (subscripts) |
| tests/get_subscript_3d_arrays_xls | tests/get_subscript_3d_arrays_xls/test_get_subscript_3d_arrays_xls.mdl | blocked | arrays (subscripts) |
| tests/get_time_value | tests/get_time_value/test_get_time_value.mdl | blocked | arrays (subscripts) |
| tests/get_values_order | tests/get_values_order/test_get_values_order.mdl | blocked | arrays (subscripts) |
| tests/get_with_missing_values_xlsx | tests/get_with_missing_values_xlsx/test_get_with_missing_values_xlsx.mdl | blocked | external data (GET XLS / DATA), arrays (subscripts) |
| tests/get_xls_cellrange | tests/get_xls_cellrange/test_get_xls_cellrange.mdl | blocked | arrays (subscripts) |
| tests/if_stmt | tests/if_stmt/if_stmt.mdl | exact with inputs | accumulated; inputs: CMP_GT, IF_THEN_ELSE |
| tests/initial_function | tests/initial_function/test_initial.mdl | exact |  |
| tests/input_functions | tests/input_functions/test_inputs.mdl | exact with inputs | inputs: PULSE, PULSE_TRAIN, RAMP, STEP |
| tests/invert_matrix | tests/invert_matrix/test_invert_matrix.mdl | blocked | arrays (subscripts) |
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
| tests/macro_cross_reference | tests/macro_cross_reference/test_macro_cross_reference.mdl | blocked | macros |
| tests/macro_expression | tests/macro_expression/test_macro_expression.mdl | blocked | macros |
| tests/macro_multi_expression | tests/macro_multi_expression/test_macro_multi_expression.mdl | blocked | macros |
| tests/macro_multi_macros | tests/macro_multi_macros/test_macro_multi_macros.mdl | blocked | macros |
| tests/macro_stock | tests/macro_stock/test_macro_stock.mdl | blocked | macros |
| tests/macro_trailing_definition | tests/macro_trailing_definition/test_macro_trailing_definition.mdl | blocked | macros |
| tests/min_max_1arg | tests/min_max_1arg/test_min_max_1arg.xmile | blocked | arrays (subscripts) |
| tests/model_doc | tests/model_doc/model_doc.mdl | exact | accumulated |
| tests/multiple_lines_def | tests/multiple_lines_def/test_multiple_lines_def.mdl | blocked | arrays (subscripts) |
| tests/na | tests/na/test_na.mdl | blocked | a number that is not finite |
| tests/nested_functions | tests/nested_functions/test_nested_functions.mdl | exact with inputs | inputs: CMP_LT, IF_THEN_ELSE, MODULO |
| tests/non_negative_all | tests/non_negative_all/test_non_negative_all1.xmile | differs | a stock that goes negative |
| tests/non_negative_flows | tests/non_negative_flows/test_non_negative_flows.xmile | differs | a two-way flow (a rate goes negative) |
| tests/non_negative_stocks | tests/non_negative_stocks/test_non_negative_stocks.xmile | differs | a two-way flow (a rate goes negative) |
| tests/number_handling | tests/number_handling/test_number_handling.mdl | exact | accumulated |
| tests/odd_number_quotes | tests/odd_number_quotes/teacup_3quotes.mdl | exact |  |
| tests/parentheses | tests/parentheses/test_parens.mdl | exact | accumulated |
| tests/partial_range_definitions | tests/partial_range_definitions/test_partial_range_definitions.mdl | blocked | arrays (subscripts) |
| tests/pi | tests/pi/test_pi.xmile | blocked | a two-way flow (a rate goes negative) |
| tests/power | tests/power/power.mdl | blocked | arrays (subscripts), a two-way flow (a rate goes negative) |
| tests/reality_checks | tests/reality_checks/test_reality_checks.mdl | blocked | arrays (subscripts) |
| tests/reference_capitalization | tests/reference_capitalization/test_reference_capitalization.mdl | exact | accumulated |
| tests/repeated_subscript | tests/repeated_subscript/test_repeated_subscript.mdl | blocked | arrays (subscripts) |
| tests/rounding | tests/rounding/test_rounding.mdl | differs | a two-way flow (a rate goes negative) |
| tests/sample_if_true | tests/sample_if_true/test_sample_if_true.mdl | blocked | arrays (subscripts), SAMPLE IF TRUE |
| tests/smaller_range | tests/smaller_range/test_smaller_range.mdl | blocked | arrays (subscripts) |
| tests/smooth | tests/smooth/test_smooth.mdl | blocked | DELAY N / SMOOTH N of order other than 1 or 3, a delay or smoothing whose time changes |
| tests/smooth_and_stock | tests/smooth_and_stock/test_smooth_and_stock.mdl | exact |  |
| tests/special_characters | tests/special_characters/test_special_variable_names.mdl | differs | a stock that goes negative |
| tests/special_characters_xmile | tests/special_characters_xmile/test_special_variable_names.xmile | differs | a stock that goes negative |
| tests/sqrt | tests/sqrt/test_sqrt.mdl | exact |  |
| tests/subrange_merge | tests/subrange_merge/test_subrange_merge.mdl | blocked | arrays (subscripts) |
| tests/subscript_1d_arrays | tests/subscript_1d_arrays/test_subscript_1d_arrays.mdl | blocked | arrays (subscripts) |
| tests/subscript_2d_arrays | tests/subscript_2d_arrays/test_subscript_2d_arrays.mdl | blocked | arrays (subscripts) |
| tests/subscript_3d_arrays | tests/subscript_3d_arrays/test_subscript_3d_arrays.mdl | blocked | arrays (subscripts) |
| tests/subscript_3d_arrays_lengthwise | tests/subscript_3d_arrays_lengthwise/test_subscript_3d_arrays_lengthwise.mdl | blocked | arrays (subscripts) |
| tests/subscript_3d_arrays_widthwise | tests/subscript_3d_arrays_widthwise/test_subscript_3d_arrays_widthwise.mdl | blocked | arrays (subscripts) |
| tests/subscript_aggregation | tests/subscript_aggregation/test_subscript_aggregation.mdl | blocked | arrays (subscripts) |
| tests/subscript_constant_call | tests/subscript_constant_call/test_subscript_constant_call.mdl | blocked | arrays (subscripts) |
| tests/subscript_copy | tests/subscript_copy/test_subscript_copy.mdl | blocked | arrays (subscripts) |
| tests/subscript_definition | tests/subscript_definition/test_subscript_definition.mdl | blocked | a reference PySD did not define, arrays (subscripts) |
| tests/subscript_docs | tests/subscript_docs/subscript_docs.mdl | blocked | arrays (subscripts) |
| tests/subscript_element_name | tests/subscript_element_name/test_subscript_element_name.mdl | blocked | arrays (subscripts) |
| tests/subscript_exceptions |  | no model |  |
| tests/subscript_individually_defined_1_of_2d_arrays | tests/subscript_individually_defined_1_of_2d_arrays/subscript_individually_defined_1_of_2d_arrays.mdl | blocked | arrays (subscripts) |
| tests/subscript_individually_defined_1_of_2d_arrays_from_floats | tests/subscript_individually_defined_1_of_2d_arrays_from_floats/subscript_individually_defined_1_of_2d_arrays_from_floats.mdl | blocked | arrays (subscripts) |
| tests/subscript_individually_defined_1d_arrays | tests/subscript_individually_defined_1d_arrays/subscript_individually_defined_1d_arrays.mdl | blocked | arrays (subscripts) |
| tests/subscript_individually_defined_stocks | tests/subscript_individually_defined_stocks/test_subscript_individually_defined_stocks.mdl | blocked | arrays (subscripts) |
| tests/subscript_logicals | tests/subscript_logicals/test_subscript_logicals.mdl | blocked | arrays (subscripts) |
| tests/subscript_mapping_simple | tests/subscript_mapping_simple/test_subscript_mapping_simple.mdl | blocked | arrays (subscripts) |
| tests/subscript_mapping_vensim | tests/subscript_mapping_vensim/test_subscript_mapping_vensim.mdl | blocked | arrays (subscripts) |
| tests/subscript_mixed_assembly | tests/subscript_mixed_assembly/test_subscript_mixed_assembly.mdl | blocked | arrays (subscripts) |
| tests/subscript_multiples | tests/subscript_multiples/test_multiple_subscripts.mdl | blocked | arrays (subscripts) |
| tests/subscript_numeric_range | tests/subscript_numeric_range/test_subscript_numeric_range.mdl | blocked | arrays (subscripts) |
| tests/subscript_selection | tests/subscript_selection/subscript_selection.mdl | blocked | arrays (subscripts) |
| tests/subscript_subranges | tests/subscript_subranges/test_subscript_subrange.mdl | blocked | arrays (subscripts) |
| tests/subscript_subranges_equal | tests/subscript_subranges_equal/test_subscript_subrange_equal.mdl | blocked | arrays (subscripts) |
| tests/subscript_switching | tests/subscript_switching/subscript_switching.mdl | blocked | arrays (subscripts) |
| tests/subscript_transposition | tests/subscript_transposition/test_subscript_transposition.mdl | blocked | arrays (subscripts) |
| tests/subscript_updimensioning | tests/subscript_updimensioning/test_subscript_updimensioning.mdl | blocked | arrays (subscripts) |
| tests/subscripted_delays | tests/subscripted_delays/test_subscripted_delays.mdl | blocked | arrays (subscripts) |
| tests/subscripted_eqns |  | no model |  |
| tests/subscripted_flows | tests/subscripted_flows/test_subscripted_flows.mdl | blocked | arrays (subscripts) |
| tests/subscripted_if_then_else | tests/subscripted_if_then_else/test_subscripted_if_then_else.mdl | blocked | arrays (subscripts) |
| tests/subscripted_logicals | tests/subscripted_logicals/test_subscripted_logicals.mdl | blocked | arrays (subscripts) |
| tests/subscripted_lookups | tests/subscripted_lookups/test_subscripted_lookups.mdl | blocked | arrays (subscripts) |
| tests/subscripted_ramp_step | tests/subscripted_ramp_step/test_subscripted_ramp_step.mdl | blocked | arrays (subscripts) |
| tests/subscripted_round | tests/subscripted_round/test_subscripted_round.mdl | blocked | arrays (subscripts) |
| tests/subscripted_smooth | tests/subscripted_smooth/test_subscripted_smooth.mdl | blocked | arrays (subscripts) |
| tests/subscripted_trend | tests/subscripted_trend/test_subscripted_trend.mdl | blocked | arrays (subscripts) |
| tests/subscripted_trig | tests/subscripted_trig/test_subscripted_trig.mdl | blocked | arrays (subscripts) |
| tests/subscripted_xidz | tests/subscripted_xidz/test_subscripted_xidz.mdl | blocked | arrays (subscripts) |
| tests/subset_duplicated_coord | tests/subset_duplicated_coord/test_subset_duplicated_coord.mdl | blocked | arrays (subscripts) |
| tests/tabbed_arrays | tests/tabbed_arrays/tabbed_arrays.mdl | blocked | arrays (subscripts) |
| tests/time | tests/time/test_time.mdl | exact with inputs | inputs: CMP_EQ, IF_THEN_ELSE |
| tests/trend | tests/trend/test_trend.mdl | blocked | TREND / FORECAST |
| tests/trig | tests/trig/test_trig.mdl | blocked | a stock that goes negative |
| tests/unchangeable_constant | tests/unchangeable_constant/test_unchangeable_constant.mdl | exact | accumulated |
| tests/unicode_characters | tests/unicode_characters/unicode_test_model.mdl | exact | accumulated |
| tests/variable_ranges | tests/variable_ranges/test_variable_ranges.mdl | differs | a stock that goes negative |
| tests/vector_order | tests/vector_order/test_vector_order.mdl | blocked | arrays (subscripts) |
| tests/vector_select | tests/vector_select/test_vector_select.mdl | blocked | arrays (subscripts) |
| tests/with_lookup | tests/with_lookup/test_with_lookup.mdl | blocked | arrays (subscripts) |
| tests/xidz_zidz | tests/xidz_zidz/xidz_zidz.mdl | exact | accumulated |
| tests/zeroled_decimals | tests/zeroled_decimals/test_zeroled_decimals.mdl | blocked | a two-way flow (a rate goes negative) |
