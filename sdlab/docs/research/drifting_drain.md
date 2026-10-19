# Drifting drain: a drain whose rate drifts, beside a steady inflow

**Status:** done (ladder, commit 453358e, strategy hash ae808809)  
**Verdict:** keep as a specialist: 121 in all four variants (every leader failed it), no pass of
the main line lost; it does not reach the BLS flows, whose drift is in moves.

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

Later changes (before the numbers below): only rows the main line could not read as steady (an
inflow in pieces, or no flows) are tried (17b51c7); a drift must beat one steady drain read the same
way by 2 log T, and the counting-noise reading is used only for a stock the main line left with no
flows, least squares elsewhere: read from the noise everywhere, the inflow followed any misfit
(041-random-chain-3#8 counts-long, 042-random-two-chains-of-two#8 and 051-sweep-level-scale#5
counts-short lost their pass) (6892fe2, 453358e).

## Results

`uv run sdlab-ladder run --strategies drifting_drain --jobs 2 --timeout 300` (single-threaded), the
whole ladder at 453358e (strategy hash ae808809), 19 October 2026: 1288 cells, 412 pass, 132
equivalent, 690 fail, 2 timeouts (sd-k8s-platform, as for every strategy). Against matrix's stored
results on the same cells no pass is lost; new passes: 121 in all four variants and
040-random-chain-2#7 counts-short.

| case | matrix (ns nl cs cl) | drifting_drain |
|---|---|---|
| 121-drifting-drain | F F F F | P P P P |

**The hard case does not carry back.** real-bls-labour-flows (real and twin) is unchanged: the
three stocks exchange people through six moves whose rates drift; this strategy drifts only a
stock's own drain beside an outside inflow, and the main line's BLS rows have no inflow pieces to
replace. A drifting rate on a move (and a distilled case for it) is the next step.
