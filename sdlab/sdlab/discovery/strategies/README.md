# Discovery strategies

Each module here is one strategy, `identify(stocks, run, opts) -> result`, run alone with
`tests/bench/evaluate.py --strategy <name>`. `matrix` is the main line; every other strategy is an
experiment kept side by side with it. A strategy's changes to shared modules (`matrix.py`, `flows.py`,
`simulate.py`, ...) sit behind options that default to the main line's behaviour, so `matrix` is unchanged.
Topic documents are in [docs/research](../../../docs/research/README.md).

Strategies marked *research* need the optional packages (`uv sync --extra research`); without them they
raise `MissingExtra` (`sdlab/discovery/optional.py`).

| strategy | what it does | topic document |
|---|---|---|
| `matrix` | the main line: one-step regression per stock, candidates chosen by multi-step behaviour | [../DISCOVERY-EXPERIMENTS.md](../../../docs/DISCOVERY-EXPERIMENTS.md) |
| `change_price` | an honest BIC price for changes in the outside inflow, with a gate | [change-price](../../../docs/research/change-price.md) |
| `held_out` | candidates chosen by blocked cross-validation | [held-out-judge](../../../docs/research/held-out-judge.md) |
| `held_out_blend` | the in-sample judge nudged by the held-out error | [held-out-judge](../../../docs/research/held-out-judge.md) |
| `output_error` | the chosen model's rates refined by multi-step error | [output-error](../../../docs/research/output-error.md) |
| `shared_noise` | moves, links and co-flows told apart by shared draws in the residuals | [shared-noise](../../../docs/research/shared-noise.md) |
| `floors` | rates floored at zero and outflows capped by what a stock holds (hinge columns) | [floors-and-caps](../../../docs/research/floors-and-caps.md) |
| `hidden_delays` | unmeasured stocks as delayed copies of a level | [hidden-stocks](../../../docs/research/hidden-stocks.md) |
| `sindy` | PySINDy with SD-shaped libraries and conservation constraints (*research*: pysindy, cvxpy) | [pysindy](../../../docs/research/pysindy.md) |
| `symbolic` | effect curves found by a symbolic search, offered as candidates | [symbolic-regression](../../../docs/research/symbolic-regression.md) |
| `symbolic_anchor` | symbolic effects accepted only by an addition test inflow pieces cannot fake | [symbolic-addition-judge](../../../docs/research/symbolic-addition-judge.md) |
| `numopt_fd` | the matrix model's numbers (and optional terms) fitted by multi-step error, finite differences | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_fd_coarse` | `numopt_fd` with coarse, learnable outside-inflow pieces | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_fd_profile` | `numopt_fd` with outside inflows re-measured at every evaluation | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_lbfgs` | `numopt` with L-BFGS-B | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_nm` | `numopt` with Nelder-Mead | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_powell` | `numopt` with Powell | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_bo` | `numopt` with Bayesian optimisation | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `numopt_cma` | `numopt` with CMA-ES (*research*: cma) | [numerical-optimisation](../../../docs/research/numerical-optimisation.md) |
| `gradient` | numbers (and a generous structure) fitted through a differentiable simulator (*research*: jax) | [gradient-descent](../../../docs/research/gradient-descent.md) |
| `gated` | a behaviour-consistency gate before the judge | [behaviour-consistency](../../../docs/research/behaviour-consistency.md) |
| `gated_no_high` | `gated` without the runs from high states | [behaviour-consistency](../../../docs/research/behaviour-consistency.md) |
| `piece_proof` | candidates judged with outside inflows they did not tailor | [inflow-conditioned-judge](../../../docs/research/inflow-conditioned-judge.md) |
| `periodic_inflows` | outside inflows as a repeating profile | [periodic-inflows](../../../docs/research/periodic-inflows.md) |
| `latent_eras` | unannounced regimes found in the rows, then fitted as eras | [latent-eras](../../../docs/research/latent-eras.md) |
| `starved_coflows` | co-flows fitted on the steps where the used stock did not run dry | [starved-coflows](../../../docs/research/starved-coflows.md) |
| `recession` | drains measured on quiet steps (no inflow), as extra candidates | [recession-drains](../../../docs/research/recession-drains.md) |
| `impulses` | one-step pulses and short bursts found jointly with each row | [impulse-inputs](../../../docs/research/impulse-inputs.md) |
| `row_crossover` | the judge's pick with rows swapped in from other candidates where the model behaves better | [row-crossover](../../../docs/research/row-crossover.md) |
| `paced_moves` | the matrix read as stoichiometry x rates: paced moves and (option `paced_readings`) gap inflows | [paced-moves](../../../docs/research/paced-moves.md) |
| `inflow_attribution` | flagged rows refitted: drains within stretches, inflow with the drain held | [inflow-attribution](../../../docs/research/inflow-attribution.md) |
| `inflow_attribution_refine` | inflow attribution on the chosen model only | [inflow-attribution](../../../docs/research/inflow-attribution.md) |
| `inflow_attribution_both` | repaired and unrepaired candidates side by side | [inflow-attribution](../../../docs/research/inflow-attribution.md) |
| `pieces_gate` | the matrix with the pieces-gate fix (`pieces_gate = "noise"`) | [inflow-attribution](../../../docs/research/inflow-attribution.md) |
| `mass_balance` | hidden stocks reconstructed from a unit's mass balance (Kalman filter) | [mass-balance-hidden](../../../docs/research/mass-balance-hidden.md) |
| `mass_balance_all` | `mass_balance` tried on every candidate | [mass-balance-hidden](../../../docs/research/mass-balance-hidden.md) |
| `odefit` | per-step models fitted by output error (segment starts estimated), products where earned; the main line kept where it predicts better | [odefit](../../../docs/research/odefit.md) |
| `loop_transit` | realistic_hats with hidden stages that close a loop: injections in the pair's rows, the return move refitted with shared noise | [loop_transit](../../../docs/research/loop_transit.md) |
| `inflow_effects` | effect_hats with outside inflows read as a schedule or a measured input times a table of a stock (gate.py) | [inflow_effects](../../../docs/research/inflow_effects.md) |
| `schedules` | censored's model searched again with every number refitted jointly: era-only flows dropped, constants on moves, periodic pulses and top-ups, co-flows | [schedules](../../../docs/research/schedules.md) |
