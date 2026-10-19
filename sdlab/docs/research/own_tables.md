# Own tables: a stock's outside flows as a table of its own level

**Status:** done (ladder, commit 67a604b, strategy hash a51b1be9)  
**Verdict:** keep as a specialist: passes 122, 123 and 196 in every variant the data allow, no cell
that the main line passes is lost, and phys-draining-tank gets its concave H <- H; a candidate for
combined.

Strategy: `own_tables` (`sdlab/discovery/strategies/own_tables/`).

## Why the leaders fail 122 and 123

- **122-concave-drain** (`H -> outside = table(H)`, sqrt-shaped). Every leader writes the bend as
  `c + k H` and copies what is left into inflow pieces (none-long: `0.045 H`, a constant drain in
  142 pieces). The main line's rows are straight; effect_hats looks for curves in what the main
  line's rows leave unexplained, and the pieces leave nothing.
- **123-inflow-shut-by-own-level** (`outside -> T = 5 x table(T)`, shut between 18 and 22; drain
  `0.1 T`). Noise-free, T never leaves 20.2-35.4: the main line finds the drain and copies the
  switch into 67 inflow pieces and a constant outflow; with counts, a constant inflow 3.8 and a
  drain 0.189 (the switch's slope folded into the drain).

## What it does

The main line's model; then per stock, its flows to and from outside are replaced by a curve of the
stock's own level (`curve.py`): a piecewise-linear curve with free points (backward elimination
from a 40-point grid, each small count's points moved by Nelder-Mead, the count by BIC, every
segment holding at least max(5, T/200) steps), beside the levels and inputs the replaced flows read.
Rows are weighted by their noise when it grows with the level. The curve is read back as flows
(`split.py`): one table flow when it keeps one sign; otherwise a drain `k x level` and an inflow
table, `k` the length-weighted median slope of the curve (so the table is flat where it can be), or
a constant and a table, whichever table moves least. Table points near 0 are then set to 0 and the
rest refitted with the drain (the zeros pin the drain down) when BIC agrees. The rewrite is kept when
the curve beats a straight line by BIC, fits each half of the run from the other, and the whole
model's one-step BIC (censored's `onestep.py`, copied, counting the table's values and point
positions) beats the main line's by 2 log T.

Later additions (all before the numbers below):

- **Moves** (`moves.py`, 67a604b): a move between measured stocks that reads its source is offered
  as `c x table(source)`, fitted on the destination's row (beside its own level and a constant, and
  the levels and inputs its replaced flows read), or on both rows at once when the source's outside
  flows are dropped (three versions; BIC decides). Found on phys-coupled-tanks, distilled as
  196-concave-move-between-tanks.
- **No reinforcing curve** the main line did not find (rises over 25% of the curve's variation):
  an inflow stepping in time imitated an inflow table of its own level on 053-sweep-excitation
  counts-long (80fda76).
- **Tables continued past the visited levels** along their end slopes (to 0 below, one range
  above), added after the choice and not priced: a flat SD table beyond its points made the
  draining tank's fresh run 88% against 98% for the straight line (0c0e5b7).
- Segments hold max(10, T/100) steps; 3% of the main line's worst steps are left out of the
  comparison; readings within 2 log T are taken in preference order (087-noisy-injection
  outliers-long: a curve bent by outlier steps) (0c0e5b7).

## Results

`uv run sdlab-ladder run --strategies own_tables --jobs 2 --timeout 300` (single-threaded), the whole
ladder at 67a604b (strategy hash a51b1be9), 19 October 2026: 1288 cells, 417 pass, 129 equivalent,
687 fail, 3 timeouts (sd-k8s-small counts-long, sd-k8s-platform counts-long and counts-short, which
time out for censored and drifting_drain as well). Against matrix's stored results on the same
cells, no pass is lost; new passes: 122 (none-short, none-long, counts-long), 123 (the same), 196
(the same), 210-control-on-off-heater (none-short, none-long, counts-long), phys-coupled-tanks
none-short.

| case | matrix (ns nl cs cl) | own_tables |
|---|---|---|
| 122-concave-drain | F F F F | P P F P |
| 123-inflow-shut-by-own-level | F F F F | P P F P |
| 196-concave-move-between-tanks | F F F F | P P F P |
| phys-draining-tank (ns nl ms ml) | P P P P | P P P P (H <- H concave, matrix linear) |
| phys-coupled-tanks (ns nl ms ml) | F P F F | P P F F |
| phys-thermostat | F F F F | F F F F |
| sd-sawmill (cs cl) | F F | F F |

The counts-short cells: 122 and 196 are data-limited (`sdlab-ladder analyse`: p 0.41); 123 is
marginal (p 0.57): 300 steps give a 6-point curve whose points in the thin data above 34 swing, and
the table reading is chosen over the drain reading.

**Hard cases that do not carry back, and why:**
- phys-coupled-tanks none-long and meas: both flows bend (H1 -> H2 and H2 -> outside are sqrt).
  The move is fitted with a straight drain on H2 beside it, which misfits, and the whole-model BIC
  keeps the main line's model; a joint fit of two curves (one per level) is needed.
- phys-thermostat: the heater switches on T against a measured setpoint (and with memory); a
  table of T alone cannot express it.
- sd-sawmill: sharpening is a table of sharpness, but under an announced era (a second station);
  rows with era segments are left alone.
- 108-canonical-commodity-cycle: unchanged (FFFF).
