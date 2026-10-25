# SD Lab discovery, inside Orchestra

This is SD Lab's discovery research: about fifty strategies, each `identify(stocks, run, opts)`,
for inferring a system dynamics model from measured stock levels. It was developed and
benchmarked in the SD Lab repository (`~/orchestra/sdlab`) and brought in here so Orchestra can
use the strategies directly.

- **Source:** SD Lab commit `7edb72d` (2026-10-24): `sdlab/discovery/` and `sdlab/sdtruth_expr.py`.
- **Changes:** imports rewritten from `sdlab.` to `orchestra.sdlab.`; nothing else.
  `discovery/strategies/z3robust/compare.py` imports SD Lab's ladder, which was not brought in
  (it is a benchmarking script, not part of the strategy).
- **Strategies:** `discovery/strategies/README.md` lists them, one line each; the research behind
  them is in SD Lab's `docs/research/`. Results in that research: `kalman_lna` and `combined2`
  did best.
- **Dependencies:** `uv sync --extra sd` (numpy, scipy, numba, highspy, sympy); the research
  strategies `numopt_cma`, `gradient` and `sindy` also need `--extra sd-research`.
- **How Orchestra uses it:** `orchestra/sd/strategies.py`. Orchestra's own conservation step finds
  the stocks and the counters that measure flows; an SD Lab strategy then finds the equations from
  the stocks' levels, with the other measured gauges as inputs.

Lint (ruff) skips this directory: it is research code kept as it was benchmarked.
