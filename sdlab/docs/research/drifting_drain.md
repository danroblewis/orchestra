# Drifting drain: a drain whose rate drifts, beside a steady inflow

**Status:** in progress (distilled case 121; whole-ladder check and real-bls-labour-flows pending)  
**Verdict:** pending.

Strategy: `drifting_drain` (`sdlab/discovery/strategies/drifting_drain/`).

## Why the leaders fail 121

121-drifting-drain: inflow 20, drain `k_t A` with `k_t = 0.1 + 0.04 sin(2 pi t / 600)` in 20-step
windows (from the BLS labour flows, whose transition rates drift with the business cycle).

- **Noise-free:** the main line reads a constant drain (0.086 A) and copies the drift into 92 inflow
  pieces; every leader returns that model.
- **counts-long:** no model at all. The stock sits near its moving balance (`A ~ 20 / k_t`), so it
  barely changes, and a one-step least-squares fit cannot tell a model with 20 in and 20 out per step
  from one with no flows: the inflow and drain are told only by how the level lags the drift, and
  under counting noise by how large the noise is.

## What it does

Per stock, its outside inflow (constant or pieces) and own-level drain are replaced by a constant
inflow c and a drain `k_t x level` in stretches (era segments, `byTime`), the other flows kept
(`segment.py`). For a given c, each step says what the drain's rate was, `(c - change) / level`; an
optimal partition (dynamic programming, a price of 2 log T x the noise variance per stretch, the
variance read robustly from 10-step local fits) cuts it into stretches. c is profiled: a grid over
`max change <= c <= min(change + level)` (every rate between 0 and 1 per step), then golden-section
between the best point's neighbours, then c and the rates refitted with the stretches held. When the
levels are whole numbers (counts), c is also read from the size of the noise (a step's variance is
what moved in and out, `c + k_t x = 2c - mean change`, plus 1/6 for the levels' rounding), and models
are priced by the counting-noise likelihood (`counts.py`, per row, Gaussian with that variance)
instead of the least-squares BIC; otherwise by censored's one-step BIC (`onestep.py`, copied,
counting every stretch's rate and cut). The rewrite is kept when its price beats the main line's by
2 log T.

## Results

In progress.
