# A procedural generator of ground-truth SD models

**Status:** built (infrastructure, playbook I2); branch `infra/procedural-generator`  
**Verdict:** the main line does not generalise: on 300 generated dev models it is worse than "nothing
changes" in 73% of runs (on the 31 examples, 26%)

## Why
31 hand-written examples invite tuning to them. Thousands of random models (chains, loops, hidden stocks, co-flows, effects, eras, unannounced changes) made with the same engine would show whether discovery generalises, and are the training data for [simulation-based-inference](simulation-based-inference.md).

## What was built
- **`tests/bench/generator.py`**: a model is a spine (an outside inflow through 2-4 stocks and out,
  with occasional leaks) plus motifs, one function each: `branch`, `merge`, `rework` (a flow back
  upstream), `reinforcing` (growth in proportion to itself, limited by a falling table on births or
  crowding on deaths, births sometimes seasonal), `goal_gap` (a replenishing gap flow, or a supply
  line whose orders fall as stock on hand and on order rise, against a demand that changes),
  `hidden_delay` (order 1-3, delay 3-20, replacing a move or on a new branch), `link` (an inflow
  linear in a stock of another unit), `coflow` (a flow using up a resource with a constant or
  goal-seeking grant), `effect_linear`, `effect_table` (rising, falling, s-curve), `floor` (an
  overflow drain, or an inflow that stops when another stock is high: the equation is below zero
  5-95% of the time), `cap` (a stock drained by a steady demand near its supply: empties 2-70% of the
  time), `eras` (announced changes to internal rates), and the unannounced changes to every outside
  inflow: `inflow_steps` (each level held at least max(10, P/8) steps), `inflow_spikes`,
  `inflow_season`. 3-15 measured stocks (padding lengthens the spine; `chain` = three or more in a
  row). Parameters that depend on typical levels (goals, thresholds, effect scales, co-flow use,
  demands) are set from a noiseless run; initial levels from a second one.
- **Checks, reject and redraw**: valid; finite, never negative and bounded (5x the first period's
  maximum + 50) over 5x and then 50x the default length; still exercising its model (the
  examples' test); every flow moving late in the run; every measured stock averaging at least 3; a
  floor or cap motif actually binding; every planned structure motif present. Up to 25 parameter
  draws per motif plan, then a new plan; most models pass in 1-3 draws.
- **Deterministic and stable**: `gen1-dev-00042` is (generator version 1, pool, index); the model
  carries `generated.motifs` and details. Ids are neutral and stocks shuffled, so their order and
  names say nothing.
- **Pools**: `dev` (any index) and `sealed` (300 fixed indices, other seeds). Held out of dev
  entirely: the family `effect_peaked` (a hump-shaped table) and the combinations
  `hidden_delay`+`coflow` and `reinforcing`+`eras`; half the sealed models are built around one of
  them. `evaluate.py --pool sealed` is refused without `--i-am-adopting` and a `--label`, and every
  sealed scoring is appended to `runs/generated/sealed-log.jsonl`. (No sealed scoring has been run.)
- **Bench mode** (`tests/bench/generated.py`): `evaluate.py --generated N [--pool] [--features]`
  runs a strategy on each model at its default length (400-1000 steps) and long length (5x), grades
  with `grade.py` (parts against `Truth.truth()` via `grade.key_of`, skill@5/20/100, fresh runs),
  and reports by motif family and by size, the worst runs, and "the true model's own skill@20" (the
  truth's static flows: below 100% where the truth changes an internal rate unannounced).
  Models and datasets are cached under `<bench cache>/generated/`, keyed by generator version and
  source and the engine; runs are saved under `runs/generated/`.
- Tests (`tests/test_generator.py`): determinism, the examples' checks on sample dev and sealed
  models, the grader's simulator stepping generated models as the engine does, held-out families
  never planned in dev, the sealed pool refused without the flag.

**Speed** (4 workers on a shared, loaded machine): about 42 models a minute generated and checked;
the main line benches about 30 models a minute (both lengths, 600 runs in 10 minutes).

## Results: the main line (`matrix`, 550a8f0 + bench changes) on dev models 0-299
600 runs (300 models x 2 lengths); baseline saved as `gen-main` (`--generated 300 --baseline gen-main`).
Means clip each run at -100%, as on the examples.

| motif | models | skill@20 | skill@100 | median skill@20 | better than no change | meeting the goal |
|---|---|---|---|---|---|---|
| inflow_steps | 98 | -25.2% | -22.8% | -43.6% | 40% | 13 of 196 |
| eras | 59 | -40.8% | -42.8% | -113.6% | 31% | 6 of 118 |
| hidden_delay | 56 | -42.5% | -48.6% | -153.1% | 30% | 5 of 112 |
| cap | 59 | -43.0% | -43.3% | -128.6% | 32% | 4 of 118 |
| goal_gap | 51 | -46.4% | -46.8% | -163.0% | 28% | 2 of 102 |
| inflow_spikes | 114 | -47.0% | -53.5% | -192.4% | 29% | 10 of 228 |
| rework | 55 | -47.2% | -52.1% | -145.2% | 28% | 2 of 110 |
| effect_table | 54 | -48.6% | -43.1% | -156.2% | 25% | 5 of 108 |
| coflow | 45 | -48.8% | -42.7% | -185.6% | 28% | 0 of 90 |
| chain | 292 | -50.1% | -50.4% | -189.8% | 26% | 19 of 584 |
| branch | 54 | -52.3% | -53.5% | -222.6% | 28% | 3 of 108 |
| floor | 66 | -54.0% | -50.2% | -149.7% | 23% | 1 of 132 |
| reinforcing | 47 | -54.2% | -58.4% | -218.9% | 23% | 3 of 94 |
| merge | 72 | -56.2% | -53.2% | -207.2% | 23% | 5 of 144 |
| link | 64 | -56.3% | -58.9% | -252.6% | 25% | 1 of 128 |
| effect_linear | 67 | -64.2% | -63.8% | -280.5% | 19% | 2 of 134 |
| inflow_season | 141 | -71.2% | -66.6% | -355.9% | 14% | 1 of 282 |
| **all** | 300 | **-49.0%** | **-49.0%** | -188.7% | 27% | **22 of 600** |

By size: 3-5 measured -40.8%, 6-9 -56.7%, 10-15 -47.0% at skill@20. Parts 71.2%; fresh runs the same
as the fitted run (-49.0%), so this is not overfitting to the run's own draws. The truth's own
skill@20 averages 88.4%.

**Against the 31 examples** (same commit, both lengths, 62 runs): mean skill@20 29.6%, skill@100
29.3%, median skill@20 62%, 74% of runs better than no change, 12 of 62 meeting the goal, parts 53.6%.
On generated models: -49.0%, -49.0%, median -189%, 27%, 22 of 600 (3.7%), parts 71.2%. Discovery
finds more of the generated models' parts (their structure is simpler per stock) but behaves far
worse: the examples' numbers do not transfer.

## What the failures look like
- Even a plain spine with stepped inflows (no other motif; a control of 12 models outside the
  pools) is worse than no change in half the runs. The two inspected failures share one signature:
  the outside-fed stock gets a spurious drain to outside, paid for by an inflated constant inflow
  (68 found vs 23.7 true; 15.2 vs 5.2). In its own run the pair balances; graded with the truth's
  inflows (as every run is), the extra drain empties the stock and the run diverges. The structure
  is otherwise right (all parts found in model 6, skill -323%). Order of stocks does not matter
  (checked by permuting).
- Seasonal inflows are the worst family (14% of runs better than no change): a slowly varying
  input that change detection does not catch is absorbed into rows as spurious dynamics.
- Linear effects and links are next worst; unannounced steps are the least bad.

## Open ideas
- A validation pool (the playbook's third pool, same distribution as dev, other seeds) reported on
  every bench run as a generalisation gap; the generator supports it as a new pool name.
- First experiment this enables: the spurious drain on fed stocks (a mechanism test on a generated
  spine model, then the motif table).
- Tune thresholds and prices on dev models, never on the 31 (playbook rule 9).
- Simulation-based inference: the generator is its training data.

## Literature
From the [playbook](PLAYBOOK.md) (citations checked there, Appendix A).
- Playbook I2: three pools (development, validation scored every run as a generalisation gap, sealed test with held-out motif families scored only at adoption).
- Cobbe, Hesse, Hilton, Schulman (2020). Leveraging procedural generation to benchmark reinforcement learning. ICML, PMLR 119:2048-2056.
- Dwork et al. (2015). The reusable holdout. Science 349(6248):636-638, doi:10.1126/science.aaa9375.
- Recht, Roelofs, Schmidt, Shankar (2019). Do ImageNet classifiers generalize to ImageNet? ICML, PMLR 97:5389-5400.
- La Cava et al. (2021). Contemporary symbolic regression methods and their relative performance. NeurIPS Datasets and Benchmarks, arXiv:2107.14351 (per-system tuning makes methods look better than they are).
- Kaptanoglu et al. (2023). Benchmarking sparse system identification with low-dimensional chaos. Nonlinear Dynamics 111(14):13143-13164, doi:10.1007/s11071-023-08525-4.
