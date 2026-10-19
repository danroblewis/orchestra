# kalman_lna: the stocks as hidden states, the levels as reports

**Status:** done (ladder: noisy cases 080-088 and the whole ladder; bench v2.1).
**Strategy:** `sdlab/discovery/strategies/kalman_lna/`; numbers below from commit `ec2f9e8`; commit
`6a93270` replaces the imports of combined and lna by copies (`_vendored/`, as at `ec2f9e8`, flows
identical on 9 checked cells). Tests `tests/test_ladder_kalman_lna.py` (9). Queue item 0b.
**Verdict:** adopt for noisy reports. On the achievable cells of 080-087 it passes 85 of 97 against
combined's 35 (meas 13/15 vs 2, gaps 14/15 vs 2, weekly 9/11 vs 0, outliers 12/15 vs 2, bias 7/11
vs 1, lag 15/15 vs 13, counts 15/15 vs 15), and it reaches the bound on the 088 sweep's long runs
(every point to 20% passes; every other method fails from 2%). On clean data it is combined
(639 test passes each; one cell lost, one gained).

## The question

Every leader breaks under real-world reporting (LADDER.md, "Real-world noise"): measurement error
biases drains through errors in variables, gaps and weekly reports are read one point per step,
outliers drag the least-squares rows, a biased stock is read as a spurious link, and a reporting
delay puts announced injections at the wrong step. The noise analysis says the data allow the
rates in almost every one of these cells. The fault is the methods': they treat the reported levels
as the true ones.

## What it does

**The model.** The stocks are hidden states on a grid of every step from the first report to the
last; they move by lna's flow atoms (inflow, outflow, move, link, growth, drain, goal gap), with
counting noise as the process noise (lna's linear noise approximation: each flow a Poisson draw,
a move's draw shared by both ends, an outside inflow and its gap terms one draw):

    x_k = A_k (x_(k-1) + inj_k) + u_k + w_k,   w_k ~ N(0, V diag(q_k) V' + tau)

The counting noise's sizes q_k are evaluated on a reference path (the smoother's, refreshed after
each fit), so the filter stays linear-Gaussian. A report is

    y_i = s_r x(t_i)  or  s_r mean(x over the `span` steps ending at t_i)  +  v,
    v ~ N(0, 1/12 + alpha + rho2 * level^2)

- **uneven times** are simply the grid steps that are observed: each interval spans its Δt steps;
- **weekly reports** are the mean over the window, followed by an accumulator beside the state;
  the span (mean over L steps, or the level at the period's end) is chosen by the likelihood;
- **measurement error** has an absolute and a relative part (alpha, rho2), each kept only where it
  pays the BIC price;
- **gross errors** are left out: a pre-screen (one value far from both neighbours, in the same
  direction, while they agree) and the filter's own innovations (|z| > 5, three rounds);
- **a reporting delay** shifts the announced injections and eras by `lag` steps (0-8 tried where
  injections or eras pin it, by the likelihood);
- **a bias** is a scale s on one stock's reports, freed only for a stock that a move between two
  measured stocks joins (conservation pins it: what leaves A arrives in B) and kept by BIC;
- **an unmeasured stock** between two measured ones (A -> H -> B) is one more state, tried where
  B gains in proportion to A, or A drains to outside while B has an inflow.

**The numbers** come from Fisher scoring with bounds: the filter returns the exact gradient and the
Fisher information by forward sensitivities (numba, `kf.py`; checked against finite differences in
the tests for points, window means, masks, scales and pooled gaps). Scoring converges in about 10
information evaluations where L-BFGS-B took 300-400 gradient evaluations.

**The flows** are chosen as lna chooses them, with the filter's likelihood in place of lna's
one-step one: the superset (every atom up to 4 stocks; beyond, lna's restricted set; with 3+ stocks
pairs that show no coupling in a regression on the reference path are screened out), the variance
beyond counting noise (tau) freed only where it pays, backward elimination by BIC (Wald-screened,
the cheapest batch first), drain <-> gap swaps, outside inflows cut where the smoothed process noise
changes level (PELT, then the merges of its pieces tried at a few counts; a piece costs 1.5 numbers,
its value and its place), era numbers merged. As in lna, the search runs with and without pieces
first and the lower BIC wins. One more thing was needed: a stock that grows with itself beside its
outflow (births and deaths) can stand in for a stepping inflow as a random walk, and then the
inflow's steps show only as bursts in the process noise; so the cuts are also read off the model
without that growth.

**When the filter is used** (`__init__.py`):

- reports at uneven times, or one per window: always;
- every step, up to 4 stocks (or with announced injections): the superset is fitted first, and a
  measurement error that gains 4 BIC prices of one number (twice what BIC asks; the clean ladder
  runs reach 2.4 at most) sends the data to the filter, unless a stock sits at zero on more than 5%
  of the points (floors bind there, outside the atoms, and an error would stand in for them: case
  056 reached 76 without this guard);
- otherwise `combined` runs, on the levels with the values the filter left out as gross errors
  replaced by their neighbours' mean; its answer stands unless the filter finds a reporting delay
  (injections), or a scale where `combined` reads a link beside a move into the same stock;
- beyond 4 stocks with every step reported, the data go to `combined` unchanged.

## Ladder: the noisy cases (`sdlab-ladder run --strategies kalman_lna --jobs 3 --timeout 300`, commit `ec2f9e8`, 2026-10-19)

Passes over the cells the analysis calls achievable, 080-087 both lengths (equivalent in brackets;
the leaders' columns from LADDER.md's run at 10f1d24, combined re-read from the store):

| noise | kalman_lna | combined | lna | lna_stack |
|---|---|---|---|---|
| counts | 15/15 | 15/15 | 12/15 | 13/15 |
| lag | 15/15 | 13/15 | 11/15 | 11/15 |
| meas | 13/15 | 2/15 | 0/15 (3) | 0/15 (2) |
| outliers | 12/15 (3) | 2/15 | 1/15 | 1/15 |
| gaps | 14/15 | 2/15 | 2/15 | 2/15 |
| bias | 7/11 | 1/11 (1) | 1/11 (1) | 1/11 (1) |
| weekly | 9/11 | 0/11 | 0/11 | 0/11 |
| **all** | **85/97** | 35/97 | 27/97 | 28/97 |

Still failing, achievable (`sdlab-ladder show <case> --strategy kalman_lna --variant <v>`):
- 085 (hidden stock) meas-short/long, gaps-long, bias-short/long: the hidden stock is found
  (delay 9-10 for 10) but with a spurious small inflow into B, or (bias) no scale is tried, since
  B is reached only through the unmeasured stock;
- 087 weekly-short/long: injections inside a reporting window; 087 outliers-long (equivalent): 14
  of the 39 gross errors are small enough (A near 10, floored at 0) to pass the filter's check and
  pull the move into a move plus a link;
- 080 bias-short: the scale gains -1.1 in BIC (the true structure with the scale is 1 short of
  beating the spurious link); 082 bias-long; 080 and 082 outliers (equivalent).

**The 088 sweep** (`sweep.findings('088', ...)`): long runs pass at every error size from 0 to 20%,
where the bound on B's drain grows from 2.7% to 5.0% and every other method fails from 2%; short
runs pass to 15% and are equivalent at 20% (combined fails from 10%). So on this case the method
breaks no earlier than the data. The 2% long point is read as noisy by a narrow margin (4.07 BIC
prices against the threshold 4).

**Run time** on the 140 noisy cells: median 3.5 s, 90th percentile 16 s, longest 82 s (084, four
stocks, long); combined's median on the same cells 1.7 s, longest 172 s.

## Ladder: everything else (same run; 1110 items, 3 jobs, 6285 s)

Against combined, cell by cell on the 991 test cells both have (`kalman_lna` rows at `ec2f9e8`,
combined's latest): 639 pass each, 736 vs 737 pass or equivalent. Flips: 022-pulse none-long
pass -> fail (the noise-free pulses read as a measurement error, 5.3 BIC prices: pulses are
outside the atoms) and 055-sweep-loop-gain#7 counts-short equivalent -> pass. Earlier versions
lost every noise-free long run (a misfit transient read as gross errors: fixed in `c124a98`),
019 none-short (a delay read from eras: only injections now) and sd-supply (co-flows read as a
measurement error: the misfit guard).

Realistic cases (sd-*, 64 cells, fresh skill): 56 within 2 points of combined at skill@20, 2
better, 6 worse (sd-services long, sd-support-tiers long, sd-webshop-stock long, sd-reservoirs
long, sd-university long, sd-orders short). Those with more than 4 stocks and every step reported
go to the base unchanged, so these differences are combined's own run-to-run differences (its time
budget under load, and combined's rows are from other commits), not the filter's.

## Bench: the examples (`tests/bench/evaluate.py --strategy kalman_lna --baseline v2.1 --jobs 3`, `ec2f9e8`, saved `2026-10-19T07-38-43-035Z.json`)

Parts 54.7% (+1.1 against v2.1), mean skill@20 37.5% (+7.9), skill@100 48.0% (+18.7); paired with
v2.1 at skill@20 35 better, 17 worse, 10 same (Wilcoxon p = 0.017). Against combined's own bench
run (`2026-10-19T03-56-42-443Z-combined-696189d.json`) 52 of 62 runs are within 2 points; 6 better,
4 worse (sd-bakery default, sd-moderation long, sd-pipeline long, sd-university long), as above
mostly combined's run-to-run spread. Summed discovery time 10861 s against combined's 11048 s.

## How the gate was set

- A per-stock AR(1)-plus-error test, and the lag-one covariance of the regression residuals, were
  tried first: neither separates measurement error from the misfit of multi-stock dynamics
  (counts-only realistic cases read as noisy, several noisy cells missed). The filter's own
  likelihood-ratio test on the superset does: over 856 cells (every case up to 4 stocks), clean
  runs reach at most 2.4 BIC prices except where floors bind (case 056, up to 76: guarded by the
  share of points at zero), a pulse (022 none-long, 5.3), a canonical model with nonlinear flows
  (110, 18.6) and sd-supply (16-30: guarded by the misfit share). The threshold is 4.
- Gross errors: a value enters the filter's count only if its standardised innovation passes 10,
  it is off by a quarter of its level, it is alone and its neighbours agree (a decaying pulse and a
  noise-free transient are not errors).
- A piece of an outside inflow costs 1.5 numbers (its value and its place). At 3 the stepping
  inflow of 086 long was not earned against a random walk (births and deaths on the same stock).

## Proposed shared changes

- A shared **uneven-time helper** in `sdlab/discovery/` (the grid of every step under the reported
  times, the window-mean accumulator, injections and eras shifted by a delay): every strategy
  that regresses one point on the next reads gaps and weekly reports as steps.
- A **measurement-error option in `matrix`**: regress each step's change on the smoothed level (the
  smoother of the fitted linear system) instead of the reported one, or use the instrument of the
  level two points back; it would remove the errors-in-variables bias at small cost.
- A **robust row option** (Huber or Student-t weights, or the filter's gross-error mask) in
  `regression.py`.
- The noise analysis's bias cells: a scale is pinned by a move between two measured stocks; through
  an unmeasured stock (085) only weakly. The analysis calls 085 bias achievable; a method that
  frees a scale there gains less than one BIC price on these runs.

## Open ideas

- A Student-t observation model instead of detect-and-drop (the small gross errors of 087).
- The hidden stock's spurious companions (085 meas): a search step that offers removing B's inflow
  jointly with re-fitting the delay.
- Co-flows, effects and floors as atoms of the filter (lna has co-flows; floors are what keeps the
  gate off for case 056).
- Speed: four stocks on long runs take up to 80 s (the information matrix is O(P^2) per point).
