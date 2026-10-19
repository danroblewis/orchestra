# archetypes: classic SD structures fitted by their free run, chosen by AICc, for short series

**Status:** work in progress (first version done). **Code:** `sdlab/discovery/strategies/archetypes/`
(commits 445aabf, 13aff55 vendoring, 7656c20, 3c3e009). **Tests:** `tests/test_ladder_archetypes.py`.
**Distilled case:** `112-distilled-short-logistic` (logistic growth seen for 10 / 20 steps).

## The question

29 of the 52 real cases give discovery fewer than 21 samples (24 of 29 Gause cultures, the flu,
4 adoption series) and every strategy returned no model ("Too few steps"); on all 52 twins (the
published model at the data's length and noise) every strategy failed, held-out skill -9.2% to
-1.3% against the published model's 35.5%. Can a method built for short, noisy series do better?

## Where the 21-sample minimum lives

- `sdlab/discovery/matrix.py:69` `if T < 20: return {"flows": [], "note": "Too few steps."}` (and
  `:97` for a mask of kept steps). Everything built on the matrix method inherits it.
- `sdlab/discovery/identify.py`, `judge()`: horizons `h < len(t) / 4` of (5, 20, 100), so below 20
  steps no horizon is left and every candidate scores inf: lowering the matrix minimum alone would
  leave the first variant chosen blindly.
- Further floors: `strategies/lna/run.py` (fewer than 30 samples: lna returns the matrix's model),
  `strategies/structures/discover.py` (T < 30), `discovery/effects.py` (T < 40),
  `discovery/periodic.py` (T < 60), `discovery/balance.py` (T < 20).
- The real cases' training part follows it: `ladder/real/build.py`, `MIN_SEEN = 21`.

The shared library is frozen (CLAUDE.md invariant 11), so the short-series behaviour lives in this
package, not in a relaxed matrix: below 20 steps archetypes answers with its own method.

## What it does

1. **Terms** (`terms.py`): every flow is theta >= 0 times a monomial of the measured levels of
   degree 0-2 with a route: constant inflows, growth, links, drains, crowding X_i X_j as a loss or a
   gain, linear moves and product moves (S x I, Bass imitation N x A).
2. **Fit by the free run** (`fit.py`, `sim.py`): numbers and starting levels fitted to the levels the
   model runs to (output error: the error is in the measurements, which biases one-step fits),
   stepped exactly as the engine steps (Euler dt 1, outflows share what a stock holds, levels
   floored at 0, injections; numba). Three error models (sd constant, ~sqrt level, ~level, with a
   floor of 5% of the stock's largest level), scales concentrated out, priced by **AICc**.
   **Bounded:** a model whose free run, continued from the fit's end and from every measured state,
   takes a stock above 3x its largest level is rejected (the SD prior that nothing grows without
   limit; a fit on one path that explodes next to it forecasts nothing).
3. **Archetypes** (`families.py`), each fitted whole and in its backward-pruned form: exponential,
   logistic, competition, predation (both ways, with and without the predator's crowding), signed
   generalised Lotka-Volterra (each monomial fitted as gain and loss, written by its net sign),
   linear compartments, linear / Bass / SI moves. A **search** (forward selection with screening,
   backward elimination, from empty and from the gLV start; for one stock every subset) may compose
   other structures but pays 2 log(library size) - 2 per term beyond AICc (risk inflation).
4. **Conserved totals:** when the measured stocks' total never changes (adoption's N = 100 - A),
   only moves between them are allowed.
5. **Hidden source** (`hidden.py`): for a stock that peaks inside the run and falls by 20%, two
   unmeasured stocks S -> I (beta S I) -> the stock (gamma I), starting levels fitted, from a small
   grid, with the measured stocks' linear chain trimmed and extended; their levels are returned as
   `inferred_levels`.
6. **Length** (`__init__.py`): below 20 steps the answer is the search's. From 20 steps (and at most
   120 steps and 3 stocks, no announced eras) combined runs first (a vendored copy, `_vendored/`,
   identical flows on 10 real cells) and the search's model replaces it only when it forecasts the
   run's last quarter better when both are refitted on the rest (`holdout.py`; a base that cannot
   run on the first part is replaced only if the search beats holding the last level). Beyond that
   range (every realistic case, BLS) archetypes returns combined's model unchanged.

## Results

All from `uv run sdlab-ladder sync --strategies archetypes --cases tag:real --jobs 3 --timeout 300`
(single-threaded, archetypes code at 3c3e009, 19 October 2026, a heavily loaded machine) and
`python -m sdlab.ladder.real report [--by source]`. The other strategies' rows are the stored runs
of 9fe0afd (LADDER.md).

| strategy | real: held-out (48 graded) | real: found nothing | real: agreement recall / precision, agrees | twin: held-out (52) | twin pass / equiv / fail |
|---|---|---|---|---|---|
| **archetypes** | **4.9%** | 2 | **57.1% / 70.1%, 13** | **10.0%** | **12 / 20 / 20** |
| combined | -2.3% | 29 | 5.5% / 9.5%, 0 | -9.2% | 0 / 0 / 52 |
| lna | -2.5% | 29 | 4.9% / 7.6%, 0 | -1.3% | 0 / 0 / 52 |
| earned_pieces | 0.9% | 29 | 4.7% / 9.0%, 0 | -1.4% | 0 / 0 / 52 |

(The published model refitted on the same samples: real -11.1%, twin 35.5%.) "equivalent" on the
twins comes from the ladder scorer's current equivalence check, not from this strategy.

By family (archetypes vs the best of the others):

| family | real held-out | twin held-out | twin pass + equiv | agreement recall (real) |
|---|---|---|---|---|
| Gause and other gLV (29) | -7.0% (combined -4.2%, earned_pieces -2.3%; published -26.5%) | -1.9% (earned_pieces 2.8%; published 32.0%) | 5 + 10 (0) | 52.2% (4.5%) |
| Bass adoption (21) | 25.1% (earned_pieces 12.4%; published 12.9%) | 31.7% (lna -9.2%; published 38.6%) | 7 + 10 (0) | 62.7% (6.3%) |
| SIR flu (1) | -5.2% (all others 0.0%, nothing found; published 97.2%) | -100% (0.0%; published 11.1%) | 0 | 80% (0) |
| BLS flows (1) | 17.5% (= combined) | 7.8% (= combined) | 0 | 58.3% (= combined) |

Distilled cases (`sdlab-ladder status`, same code): **112** short logistic 6/6 (4 pass, 2
equivalent; counts-short is data-limited, p 0.38); **120** short chain 3/4 pass (counts-long fails:
a 7-term search model beats the linear chain under counting noise); **136** crowding short run 4/4
(2 pass, 2 equivalent). combined, lna and earned_pieces fail all of 112 and 120 and 3 of 4 of 136.
**052** run-length sweep (the only other standard cells in archetypes' own range): 24/24 pass, as
combined. Every other standard and realistic cell gets combined's model unchanged.

### Diagnosis of the twins (invariant 4)

- **gLV twins are data-limited for numbers and forecasts.** The published structure refitted by the
  same free-run fit (it knows the structure, not the numbers) reaches 4.5% held-out skill on the 29
  gLV twins and passes 6 of them (diagnostic script, not committed); the published 32% uses the true
  numbers. With 7% error on 6-23 samples and Euler steps at r ~ 1-2 per day, other numbers fit
  better than the truth's (a3-mixture twin: nll 96 refitted vs 118 at the true numbers).
  `sdlab-ladder analyse` reports these twins as noise "none" and so gives noise-free bounds.
- **Adoption twins:** the move structure is identifiable; 17 of 21 pass or are equivalent.
- **Flu twin:** C carries 65% measurement error; the published model itself has 11.1% skill.
- **BLS twin:** the search alone reached 93.5% held-out (published 94.3%, combined 7.8%) in a scratch
  run, but BLS is beyond `max_steps` (321 steps) and gets combined's model.

## Verdict

Adopt for short series and for the twins' classic structures: it returns a model where every other
strategy returns nothing, recovers the published structure 10x more often (recall 57% vs 5%), and
is the only strategy with twin passes. Not yet a forecasting win on the Gause cultures (real
held-out -7.0% against combined's -4.2%, which is mostly "nothing found" = 0), and process (counting)
noise misleads the free-run fit on a longer chain (120 counts-long).

## Proposed shared changes

1. `sdlab/ladder/checks.py` (`problems`): fails with `StatisticsError` for a case whose longest
   counts run is under 20 steps (`w = len(lv) // 10` leaves one sample per window); 112's long
   variant had to be 20 steps for `sdlab-ladder check` to run.
2. `sdlab/ladder/analysis.py`: a real case's twin is analysed as noise "none" (variant noise), so
   its bounds are noise-free (SE ~1e-8) and its labels meaningless; it should use the twin's
   measurement error (`real.twin`).
3. The real scorer's held-out run starts from the last noisy measured level: on saturated series
   persistence is then very hard to beat, even for the true model (gLV twins: 32%).

## Open ideas

- Process noise: judge free-run fits against a one-step (equation-error) likelihood too, or a
  Kalman-smoothed start, so counting noise does not reward flexible structures (120 counts-long).
- Raise `max_steps` with a time cap, so BLS's twin gets the search's model (93.5% in scratch).
- Model averaging over the AICc weights for the forecast on very short series.
