# PySINDy with SD-shaped libraries and conservation constraints

**Status:** done (wave 2, benchmark v2)  
**Verdict:** reject as a strategy; carry two pieces forward (joint conservation fit; products and co-flows for effect/co-flow examples)

## Question
Does discrete-time PySINDy, with a library of levels and pairwise products (a product A x C in a flow
out of A is a linear effect of C), outside inflows as our PELT pieces, and conservation as equality
constraints (ConstrainedSR3), beat stepwise BIC, especially on effects?

## What was done
Branch `exp/pysindy`, commit `3611a2f` (worktree `.claude/worktrees/agent-a843f2443ba1a9862`).
Strategy `sindy` with ablations (`plain`, `levels`, `products`, `constrained`, `uses`, `full`, `combo`);
`library.py`, `sparse.py` (STLSQ and SSR paths, support by information criterion), `conserve_joint.py`
(ConstrainedSR3; a constraint kept if it costs less than log T), `term_flows.py` (products -> linear or
two-point table effects; losses in a stock of another unit -> `uses`). Adds pysindy 2.1 and cvxpy.

## Mechanism tests
- Plain chain: recovered (skill@20 0.955; matrix 0.996).
- Linear effect cut = 0.3 x logs x sharp/100: product found and read as an effect, 0.00278 vs 0.003;
  skill 0.86/0.95 (matrix -2.6/0.57). Needs the change price at 2 log n (at 1 log n the inflow is over-cut).
- Conservation: a move into a noisy receiver, 0.2997 vs 0.3 with no extra flows (matrix 0.3294);
  skill@20 0.87 vs 0.39.

## Results (baseline v2: 31.6% / 32.1% / 17 of 62, parts 55.4%, 326 s)
| attempt | parts | skill@20 | skill@100 | goal | time (s) |
|---|---|---|---|---|---|
| plain PySINDy | 55.0% | -34.3% | -49.6% | 0 | 12 |
| levels (2 log n) | 54.5% | 8.9% | 6.9% | 11 | 80 |
| + products | 51.3% | -3.1% | -14.6% | 9 | 273 |
| + constraints | 52.1% | -3.9% | -15.0% | 9 | 270 |
| + co-flows (any third stock) | 56.7% | -42.4% | -51.1% | 6 | 262 |
| full, round 2 (variants judged) | 59.3% | 20.5% | 16.2% | 8 | 3296 |
| combo (matrix + product candidates) | 56.7% | 29.7% | 33.4% | 17 (a different 17) | 3377 |

Gains (full): sd-webshop-stock default 95.0%/93.6% (meets the goal), sd-cloud-credits default +155,
sd-moderation default +154, sd-print-shop long +112, sd-bakery long 95.3%. Losses: sd-services,
sd-reservoirs long, sd-population long, sd-learning-curve long, sd-support-tiers long, sd-housing default,
sd-emergency.

## Lessons
- Sparse regression paths are no better than stepwise BIC on linear rows.
- Products are flexible enough to stand in for unexplained inflows; such models run away under the true
  inflows while the in-data judge (own inflows) ranks them best.
- Co-flows read from any third stock cost ~38 points; restricted to another unit, they help.

## Open ideas
- Admit a product only if it still pays after the inflow pieces are refitted without it.
- Judge each model also with its inflow pieces replaced by their mean (catches models that only work
  with their own inflows).
- Noise-weighted rows; table-shaped effects from binned residuals; the joint conservation fit alone
  into the main line.


## The declared boundary (2026-10-20)

The strategy is now a package (`sdlab/discovery/strategies/sindy/__init__.py`, the former `sindy.py`
unchanged but for its imports, plus `sindy/boundary.py`, a copy of `matrix/boundary.py` at 723f72c,
HIDDEN_PRICE 0, with `kept_sides` and `GUARD_FITS` as in odefit's copy). Its rows are fitted inside the
announced boundary (docs/research/declared-boundary.md): a measured input's column only on a stock with
a `measured` side, a level of another unit (or a product with one) only on an `estimate` side, an
outside inflow (constant or changing) only on an `estimate` side. The judge sees each candidate
guarded; the candidate's own model goes to the errors-in-variables refit, and the answer through
`boundary.apply`. Conservation is the shared `conserve_joint` (pinned), so a source with no declared
outflow is not tied in the fit: the guard makes its leftover drain a move or drops it.
tests/test_strategy_sindy.py's "products" ablation is read before the boundary step (identify prices
its spurious link into b as an unearned boundary claim and drops it).
