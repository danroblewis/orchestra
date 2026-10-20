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
| `codetable.py` | the code-table versions (v1 default; v2 noise options eta-lean/joint, phi-lean/joint, tau-priced, phi-prior), one global choice each, selected by `--code-table` (unified-objective-test.md, section 6) |
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

**Smoke test only** (commit d59a98a, 19 October 2026; cache `objective_test/v1-f6443f802e`), ten small
counted cells, 12 minutes with 3 workers:

    uv run sdlab-ladder objective-test --cases 007,008,009,010,011,015,016,019,020,024 --variants counts-short --jobs 3 --timeout 1200

| cell (counts-short) | label | wrong groups | analysis | note |
| --- | --- | --- | --- | --- |
| 007-link | **E** | 3 OK, 1 TIE-unexplained, 1 X, 1 E | achievable | the E: a move A -> B with a constant (realistic_flows, schedules), delta -2.4 = D -0.2, P_num +0.7, P_struct -2.9; its phi went to 0 and tau took the noise ("noise absorbing structure", risk R2) |
| 008-link-loop | OK | 3 OK | data-limited | T* restarts disagree by more than eps |
| 009-births-and-deaths | S | none (4 right groups) | achievable | phi fitted at 0.06 with births and deaths both large (0.63, 0.65): phi trades against the gross flow size (risk R1) |
| 010-loop-branch | S | 5 OK, 3 X | data-limited | tau on B 1.9 (the declared "near 0" threshold); T* restarts disagree |
| 011-goal-gap | OK | 10 OK, 3 X | achievable | |
| 015-hidden-stock | OK | 7 OK | achievable | |
| 016-coflow | S | 8 OK | data-limited | tau on A 0.77 |
| 019-announced-era | OK | 7 OK | achievable | |
| 020-unannounced-step | OK | 3 OK, 1 X | achievable | T* restarts disagree |
| 024-floor-binds | S | 14 OK, 1 X | achievable | tau on A 2.9; beta fitted at 1.0; T* restarts disagree |

The truth ranks first among the wrong groups in 9 of 10 cells (in 007 the X group and the E group beat
it). Under one-step BIC on the same fits (arm A-bic): 7 OK, 1 TIE, 1 E. Read: the corner and the replica
hold; on these cells the objective already prefers the truth to almost every stored wrong model; the
sanity block fails on 4 of 10 cells, three of them on the declared "tau near 0" threshold (tau 0.8-2.9
against counting variances of order 10) and one on phi trading against gross flows. Neither is fixed
here: a change to the data model or to the declared thresholds is a new code-table version, decided
with the user (R9).

## Verdict

None yet: the objective test is built and smoke-tested; the pilot (P0) and the phases P1-P5 are not run.
