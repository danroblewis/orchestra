# unified: one model class, one data model, one objective

**Status: work in progress.** The design is [unified-design.md](unified-design.md). Built so far: the
objective (code table v1) and the objective test (section 7 of the design). There is **no search**: the
strategy's `identify()` returns the main line's model unchanged (with a note), so its ladder rows are the
main line's and say nothing about this design.

## What is built

The evaluator, `sdlab/discovery/strategies/unified/` (no imports from other strategies or from the
ladder; the quantum estimate is copied from `strategies/combined/judge.py` at c74fe15):

| file | what |
| --- | --- |
| `frontend.py` | the discovery view on the engine's step grid (the leakage guard asserts it is only the view), and any model's flows read into one structure with numbered slots: each rate segment in the normal form c + sum k_j z_j (constant, proportional, gap, linear; z a stock, a measured input or 1), schedules per coefficient (byTime, inflow pieces; runs of equal value share a slot), table and linear effects, co-flows, ratio, two-way flows, signed stocks, ceilings, sub-steps, hidden-stock starts. An expression rate raises `NotExpressible` (class C). `write_back` puts fitted numbers back into the flows for the scorer. |
| `engine.py` | the step in JAX, in the engine's order: rates (floored unless two-way) x effects, x dt per sub-step, outflows sharing what a stock holds (stock by stock), inflows sharing the room under a ceiling, levels floored unless signed. |
| `kalman.py` | the filter and D: an extended Kalman filter on that step (Jacobian by JAX), process noise phi V (diag(a) - beta B) V' + diag(tau), each report a scalar update with variance q^2/12 + alpha + rho^2 mu^2, scored as the probability of its quantisation bin; a report at the floor takes the censoring mass. |
| `price.py` | code table v1: P_num = sum 1/2 ln N_j (N_j: the reports of the measured stocks number j moves, over the steps where it acts), P_struct (section 4.3 of the design), eps = 0.5 nat. |
| `objective.py` | J = D + P_num + P_struct, the fit (eta alone from three declared starts, then everything jointly; L-BFGS-B on JAX gradients), diagnostics (innovation dispersion and Ljung-Box z), the lean start. |

The harness is `sdlab/ladder/objective_test.py` and `objective_report.py`, run as
`uv run sdlab-ladder objective-test` (docs/LADDER.md, "The objective test"). The design's
`tests/study_unified_objective.py` became that CLI command.

## Where v1 departs from the design (stated, not hidden)

- **Filter:** a plain EKF linearised at the filtered mean, not the iterated EKF around an RTS-smoothed
  reference path. No sigma-point fallback and no particle-filter referee yet (label P is never given).
- **Fit:** L-BFGS-B on exact (autodiff) gradients, not Fisher scoring; shape parameters (knot positions,
  delays, hinge thresholds) are not profiled, they stay as written.
- **Noise:** phi scales the split term too (phi V (diag(a) - beta B) V'), so the noise stays positive
  semi-definite for every beta in [0, 1]. The observation is Gaussian (nu = infinity, as code table v1
  says; Student-t is arm A-t, not built). Observation choices (lag, span, scale, bias) are not built, so
  the `lag`, `weekly` and `bias` variants are class C.
- **Class:** hidden-chain tying (one rate for an Erlang chain) is not built: each stage's number is its
  own slot and each hidden stock is priced as a chain of order 1, which over-prices delay truths. No
  hinge, MIN, sqrt, product terms or latent jump states in the grammar yet (truths with an expression
  rate or a 2d engine feature are C). Physics, particle and real cases have no proxy truth yet (C).
- **Starts:** each measured stock starts at its first report (not scored, the same constant for every
  model); a hidden stock starts at its slot with a fixed sd of 0.25 x the measured stocks' mean level.
- **Sanity thresholds** (declared before any result was read): "tau and alpha near 0" for counted data is
  tau <= max(0.1 q^2, 1e-4 x level scale^2); "none": phi < 0.05 and every variance at that floor.
- **Not checked yet:** the Q = 0 corner against `odefit.compare.output_error` and the beta > 0 corner
  against `master_eq` (section 4.5). The alpha = 0 corner and the engine replica are unit tests.
- **Machine load:** JAX's CPU runtime uses about two cores per process during gradients despite the
  single-thread settings; the harness runs its workers at nice 19 with 2 workers by default.

## Checks (tests/test_unified_objective.py)

- the leakage guard rejects `all_levels` and `counters`;
- the engine replica: stepped noise-free from the first report, the compiled truths of 003, 016, 017,
  023 and 024 reproduce the engine's levels (to 1e-3 relative);
- the alpha = 0 corner: on 003, 007 and 016 counts-short, D equals `fisher.TruthParams.nll` + 1/2 ln 2 pi
  per report to within 2e-3 nat per report (measured: 2e-4 to 5e-4);
- orderings: the truth beats itself without a flow (by ~86 nats on 003 counts-short: the extra shock
  variance tau absorbs much of the missing drain, risk R2), with a spurious link, and (noise-free) with
  an unneeded inflow piece;
- the harness's labels on a synthetic cell, and the structure signature.

## Results

See the smoke test below. Nothing beyond it has been run; the phases P0-P5 are not run.

## Verdict

None yet: the objective test is built, the pilot (P0) is not run.
