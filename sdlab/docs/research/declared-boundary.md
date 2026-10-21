# The declared boundary in strategy code: outside flows only where the case says so

**Status:** built in `matrix` as the reference (`sdlab/discovery/strategies/matrix/boundary.py`, hooks in
`earned.py`, `earned_rows.py`, `earned_joint.py`, `__init__.py`); tests `tests/test_matrix_boundary.py`.
Paired results on Kubernetes 300-305 and 60 Tests cells: see [Results](#results).

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
`+ 2 log T` per boundary claim `+ 2 log T` per hidden stock (`HIDDEN_PRICE`), so laziness cannot move
from outside flows to hidden stocks. An alternative with a negative rate is not a model (priced
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

## Results

In progress: see below once the paired runs report.

## Limits and next steps

- Hidden stocks: `matrix` offers none, so a case whose truth needs one (107-canonical-rework,
  boundary `{}`) can only come out as moves between measured stocks; it no longer invents outside flows
  there, but still fails.
- A declared `estimate` inflow whose truth reads its own or another stock negatively (a control law,
  207's pump) is found only through the fold alternative, one term at a time.
- Undeclared cases (realistic, real, physics, particles, the page) change too (claims priced on the
  final answer); they were not part of the paired run.
