# Own tables: a stock's outside flows as a table of its own level

**Status:** in progress (distilled cases 122 and 123; whole-ladder check and hard cases pending)  
**Verdict:** pending.

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

## Results

In progress.
