# The declared boundary in six more strategies: hidden_transit, loop_transit, latent_eras, drifting_drain, mass_balance, shared_noise

**Status:** built (commit e8c036a); paired runs on the CPU pool: see [Results](#results).
The design is matrix's ([declared-boundary.md](declared-boundary.md)); this page says what each of
the six copies and where each one's own search was changed.

## What every one of the six got

- **Its own copy of `matrix/boundary.py` at 723f72c** (`<strategy>/boundary.py`): `HIDDEN_PRICE = 0.0`
  (a hidden stock is inside the boundary and pays only for its numbers, the user, 2026-10-20),
  `CLAIM_PRICE = 2.0`. One addition in each copy: **`GUARD_FITS = 200`**. Once a guard call has spent
  that many refits, any flow still outside the boundary is dropped instead of refitted. The guard
  runs on every main-line candidate, and on the largest models (316, 317) its refits were where
  matrix's two new timeouts came from (job 11). Dropping is still legal: nothing outside the boundary
  survives.
- **The main line inside the boundary.** Five of the six carry a copy of matrix's `earned.py`,
  `earned_rows.py` and `earned_joint.py`; shared_noise carries `earned_rows.py` only. Each got matrix's
  67f5b9e change, so every main-line candidate is built and judged inside the boundary:
  - a row's outside term only on an `estimate` side, measured inputs only on a `measured` side, and
    other-unit links only on an `estimate` side;
  - a source with no declared outflow is tied (its drain is all moves);
  - each candidate is guarded before the judge sees it.
- **`boundary.apply` last in `identify`**, after the errors-in-variables refit. Where a boundary is
  declared, it runs the guard and then the moves. Where none is, it runs the moves and prices each
  claim; `r["boundary"]` and `r["boundary_claims"]` are filled.

## Each strategy's own search

A final guard is not enough where a strategy searches structures itself, so each search now proposes
outside flows only on declared sides:

| strategy | its own search | what changed |
|---|---|---|
| hidden_transit | pairs A -> H -> B (Kalman likelihood), hidden stages on one stock's inflow | B's outside constant (`cB_on`) tried only where B may have an estimated outside flow. B's own drain only where B may have an estimated outflow; a new `kb_on=False` fit, ported from loop_transit's `transit/fit.py`, handles the rest. A share of A's loss to outside only where A may have an estimated outflow. A transit or stage whose built model has an undeclared outside flow is not proposed. A stage only on a stock with a declared inflow. |
| loop_transit | effect curves (screen, placements, joint refit), then its `transit/` copy of hidden_transit | Effect placements end at outside only on a declared side (`search.placement_fits(..., ok=)`). A finished model with an undeclared outside flow is not a candidate. With no boundary declared, the effect search's one-step BIC adds `CLAIM_PRICE x log T` per claim. `transit/` changed as hidden_transit's pair search did (its `kb_on` was already there). |
| latent_eras | regime candidates (`identify_one` with the regimes as eras) | Each regime candidate refitted inside the boundary (`earned.refit` with the boundary), then guarded, as the main line's are. |
| drifting_drain | per-row rewrite: constant outside inflow plus a drifting drain to outside | Tried only on a stock with a declared estimated outflow, and never when the rewrite would leave an undeclared outside flow (for example a constant inflow on a stock with no declared inflow). With no boundary declared, claims are priced in its BIC (`CLAIM_PRICE x log T` each). |
| mass_balance | pairs A -> H -> B from the unit's balance | "Rest to outside" (`mb_rest`) only where A may have an estimated outflow. A proposal whose model has an undeclared outside flow is not taken. `mb_all`'s per-variant candidates refitted inside the boundary and guarded. |
| shared_noise | its own matrix copy, with moves and links told apart by shared draws | `earn()` reselects each row inside the boundary (as matrix's `refit`), and each candidate is guarded. Its copy of `pair_moves` leaves links alone (inflows with a `driver`). See below. |

**shared_noise and `pair_moves`.** The reference `pair_moves` adds back an outflow from A or an inflow
into B, then compares the two flows. A link into B and A's drain both scale with A's level, so they
always look anti-correlated (z -36.7 on tests/test_strategy_shared_noise.py's case). The one-step BIC,
with one variance per stock, then prefers the move by one number. That is exactly what shared_noise
decides from which rows share draws, and it overrode the link that shared_noise exists to find. Its
copy therefore leaves links alone; constant and piecewise outside flows are still paired. The test now
passes the case's declared boundary, as every ladder case has one. With no boundary declared, the link
is a claim priced at 2 log T, and the final claim pass still turns it into a move (and drops c's drain).
That is how the approved rule 3 prices claims, not something this copy changes.

## Results

In progress (pool jobs 39-89 by `bnd-ht6`).
