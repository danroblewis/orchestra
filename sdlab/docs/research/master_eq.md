# master_eq: per-region transition probabilities fitted to counted levels

**Status:** done for the particle cases and distilled 170, 171, 195, 226 (commits `948c0a2`, `aef4b5f`);
standard tests run by the watcher (1,360 cells, below).
**Strategy:** `sdlab/discovery/strategies/master_eq/` (`terms.py` the candidate terms, `fit.py` GLS and
the noise covariance, `ml.py` maximum likelihood, elimination and swaps, `run.py` the selection and the
choice, `write.py` the flows). Tests `tests/test_master_eq.py` (3). No other strategy is imported; the
main line comes from the shared library (`sdlab.discovery.identify`).
**Verdict:** adopt for particle and counted data with conserved units. Equations on the exact and
measured particle runs **5 of 8** (best before 2 of 8: lna, effect_hats, matrix); mean fresh gap@20 to
the mean-field reference on those 8 runs **-2.7 points** (best before -59.5, combined_lean). Galton
board, conveyor and the reaction's long run pass; the stirred chambers are 19-21 of 26 parts with a
gap of -5.6 / -11.9 points (before -19 / -60 at best). Not a replacement for the main line on the
standard tests: against matrix 112 fail -> pass and 14 pass -> fail (unannounced inflow steps: 053, 048, 020).

## The question

Particle data come from units moving one by one with per-step probabilities that depend only on where
they are. The mean-field (master-equation) model is then exact in expectation, and the noise is known
exactly too: the units of one region split among its moves as a multinomial, arrivals are Poisson.
Every leader fits one-step regressions with no noise model; they read slow bins' drains as constant
inflows and bin-to-bin moves (Galton board), fold two-way exchanges into drains (stirred chambers),
and write A + B -> C as linear moves (reaction).

## What it does

1. **Terms** (`terms.py`): every move between stocks of one unit, every drain, a share of every
   measured input, a constant arrival; with announced eras, the moves and drains one per era label.
   Later: links (a stock read without being drawn down), binds A + B -> C and catalysed moves (models of
   at most 6 stocks).
2. **Noise from the numbers** (`fit.py`): each step's change has mean sum theta_m base_m e_m and a
   covariance from the same numbers: Poisson per term, or **binomial** (the multinomial: moves out of
   one region are quieter by (1 - p) and negatively correlated). Both readings are fitted and the
   likelihood picks one; particles come out binomial (Galton board, conveyor), the ladder's counting
   noise Poisson.
3. **GLS, then maximum likelihood** (`ml.py`): GLS (non-negative least squares on whitened steps)
   finds the means; ML on -2 log L = Q + sum log det S_k (L-BFGS-B, exact gradient, numbers >= 0) also
   uses the noise, which is what identifies a two-way exchange (it cancels in the mean and doubles the
   noise). Every move's reverse is offered to ML. The dispersion is fitted or **held at 1** (BIC
   decides): held at 1, the noise's size measures the flows' size; this removed a 7-10% shrinkage of
   every number on 171 counts-long (a stock fed and drained in proportion).
4. **Selection by BIC** with ML refits: backward elimination (Wald-ranked), **swaps** of a term's
   destination priced by the likelihood with the covariance the swap implies (a slow bin's drain and a
   move into its neighbour have the same size; the RSS at fixed covariance preferred the wrong one on
   the Galton board), then extras one at a time, each followed by a fresh selection with it in the pool.
   Products cost 2 numbers (170 counts-short had taken a catalysed drain for a 3-point gain).
   Era-split numbers are merged (two labels sharing one number, or all) while BIC falls.
5. **The choice**: both the main line and the master equation refitted on the first 70%, judged by the
   main line's behaviour judge on the last 30%. On the whole run the main line's inflow pieces follow
   the counts' noise and win the judge (reaction counts-short: 0.47 vs 0.58 in sample, 2.64 vs 0.58
   held out). Levels that are not whole numbers, uneven times or more than 16 stocks go to the main line.

## Results

Commands (single-threaded, 19 October 2026, at `aef4b5f`): `sdlab-ladder run --strategies master_eq
--cases tag:particles,170,171,195,226 --jobs 1 --timeout 1800` (32 items, 533 s); numbers from the store
(`api.summary()["particles"]`, `store.latest`). Before: the leaders' table in LADDER.md ("Results: the
leaders on the particle cases").

| case (counts-short, counts-long) | before: best leader | master_eq status, parts | gap@20 / @100 (points) |
|---|---|---|---|
| part-galton-board | fail, fail (gap -135 / -9 at best) | **pass 26/26, pass 26/26** | -5.0 / -4.6, -0.6 / -0.7 |
| part-conveyor-bottleneck | pass, pass (effect_hats -4.6, -0.2) | pass 9/9, pass 9/9 | -0.8 / -0.2, -0.0 / -0.0 |
| part-reacting-particles | fail, fail (-15, -7) | fail 7/8, **pass 8/8** | +1.6 / +0.9, 0.0 / +0.2 |
| part-stirred-chambers | fail, fail (-60, -19) | fail 21/26, fail 19/26 | -11.9 / -2.5, -5.6 / -1.8 |
| part-capacity-gate (prediction) | near, near | near, near | +105 / +352, +349 / +234 (the refitted reference is a poor SD model of a gate) |
| part-diffusion-chambers (prediction) | far (-162, -40) | far, far | -101 / -108, -46 / -44 |
| part-shelves-overflow (prediction) | far (-44, -149) | far, far | -11 / -17, -209 / -118 |
| part-ball-plant (prediction; 32 stocks) | far | main line (more than 16 stocks) | -282 / -96, -123 / -66 |

Aggregate (`summary()["particles"]`): master_eq 7 of 16 (equations 5 of 8, near 2 of 8) against
matrix and lna 4, odefit 4, combined 3.

Distilled cases (none-short, none-long, counts-short, counts-long; the none cells are the main line's):

| case | before (any strategy) | master_eq |
|---|---|---|
| 170 fast cells under a daily input | counts: matrix F F; lna, combined P F (LADDER.md) | P P **P P** |
| 171 A + B -> C fed by inputs | no stored strategy passes any cell (odefit.md) | F F F **P** (counts-short: 6/8, drains 11-36% off on 300 steps) |
| 195 two-way exchange, 2 x 2 chambers | counts: matrix F F; lna, combined E E (LADDER.md) | P P E F |
| 226 exchange shut in announced eras (new) | matrix F F on counts | F F E **P** |

**What remains, diagnosed:**
- **195 counts-long**: D -> C is read as more D -> B. The data's limit: the true structure's likelihood
  (29,341, refitted) is worse than the found one's (29,323); D is small (drained at 0.16), so its two
  exits are barely told apart.
- **Stirred chambers**: the search's limit, not the data's. With the true structure (era-split moves) the
  likelihood is 7,688 against the found 7,768 (counts-short): the selection over 9 chambers x 8 moves x 2
  eras stops in a local optimum (missing C12 <-> C22, C22 -> C23, C33 -> C32). Distilled to 3 chambers as
  226, which master_eq passes long: the failure needs the larger search to show.
- **Reaction / 171 counts-short**: right structure, drains 11-36% off on 300 steps (short-run
  precision).
- **Prediction-only systems** (capacity gate, unstirred chambers, shelves): no mean-field form is exact;
  the master equation is no better there (shelves long -209).
- **Ball plant**: 32 stocks, over the 16-stock limit (the pool of moves grows as the square).

### Standard tests

The watcher ran master_eq on every standard cell (read from `store.latest()` at 19:20 PDT, 19 October
2026; master_eq at `948c0a2`, matrix at its latest stored commits). 1,360 paired cells (52 real-data
cells 'differs'), matrix -> master_eq: pass -> pass 376, fail -> fail 632, equivalent -> equivalent
126, **fail -> pass 112**, fail -> equivalent 31, equivalent -> pass 1, **pass -> fail 14**, equivalent
-> fail 16. The losses are counts cells of 053-sweep-excitation (9), 048-random-stepping-inflow-drain
(3), 020-unannounced-step and 049#6: unannounced inflow steps, which the master equation's constant
terms cannot write and the held-out choice did not catch. The gains include 057, 058, 060, 061, 084,
101-canonical-seir, 120, 157, 170, 171, 226 and many sweep draws.

## Lessons

- The noise of counted data is not a nuisance: its size and correlations come from the same numbers as
  the mean, and the likelihood uses them. Two-way exchanges, a flow's scale, and binomial vs Poisson
  noise are all read from it.
- Price a swap with the covariance it implies: at a fixed covariance a move looks as good as a drain.

## Open ideas

- A forward search over moves for many regions (the stirred chambers' local optimum), or a
  spatial prior (moves between regions whose counts co-vary negatively).
- Guard the choice against unannounced inflow steps (053, 048, 020 counts): offer the main line's inflow pieces as
  terms.

## The declared boundary (2026-10-20)

master_eq keeps outside flows to where the case declares them (docs/research/declared-boundary.md;
`master_eq/boundary.py` is a copy of `matrix/boundary.py` at 723f72c, HIDDEN_PRICE 0, with one change:
`kept_sides`, below):

- the main line (`earned*.py`) has matrix's hooks: rows filtered per stock, sources with no
  estimated outflow tied (`decide(forced=...)`), the guard on every candidate before the judge;
- the master equation's term pool holds only the outside terms the boundary allows
  (`terms.inside`: a drain only on a stock with an `estimate` outflow; a constant or link only on an
  `estimate` inflow; an input's arrivals only on a `measured` inflow; a bind or catalysed move to
  outside only on its source's `estimate` outflow). With none declared, every term is in the pool and
  each outside flow pays `CLAIM_PRICE` numbers in the BIC (`ml.bic`, `P.claim_price`);
- the answer goes through `boundary.apply` (`__init__.identify`).

`kept_sides` (this copy): where a boundary is declared, no alternative or move may take away the last
outside flow on a declared side (an `estimate` side's flow exists). Without it the reference's
`pair_moves` made a counted chain's declared `outside -> A = 6` and `B -> outside = 0.05 B` into a
closed loop `B -> A` (the move A -> B's counting noise makes A's and B's unexplained changes
anti-correlated; the loop fits nearly as well for one number fewer). tests/test_master_eq_boundary.py.
`tests/test_master_eq.py::test_levels_not_counted_go_to_the_main_line` compared with the shared
`identify` since master_eq's main line became its own earned_pieces copy (it failed before this
change); it now compares with that copy.
