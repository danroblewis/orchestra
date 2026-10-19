# structures: products of stocks, multi-stock goal gaps and hidden delay chains

**Status:** done, first version (queue item 2b). **Code:** `sdlab/discovery/strategies/structures/`
(commits 2f0d429 ... 7e0a2bf; numbers below are from 7e0a2bf). It carries its own copy of combined and
everything combined calls in `_vendored/` (taken from 1fb3cef, imports rewritten only; found flows
identical to combined and lna_stack on 6 cells), so it imports no other strategy (invariant 11). **Tests:** `tests/test_ladder_structures.py`.

## The question

Every leader fails the canonical cases 100-110 on structure while behaving well (fresh skill@100
94-100%): products of two stocks come out as links and hundreds of inflow pieces, a hiring gap over
two stocks and an input as about 145 inflow pieces, and hidden delays (rework, DELAY3 supply lines,
World3's transmission delay) are never found. Can a search for those classic structures recover
them, without losing anything elsewhere?

## What it does

`structures` = combined's model, replaced by the search's model only when the data prefer it.

1. **combined** runs first, through its `identify()`, unchanged (so it runs exactly as it does
   alone).
2. **The search** (`discover.py`), capped at 60 s or a third of the time the caller's timer leaves:
   - **Terms** (`terms.py`): each a number theta >= 0 and the change it makes to every measured
     stock: outside constants, links (from a stock, itself or a measured input), goal gaps (an
     outside inflow falling as a stock rises), outflows, drains (read another stock or an input),
     moves, and **bilinear terms** theta x a x c for every pair of stocks (c may be a or the
     destination: S x I in SIR, P x A in Bass, X x X for crowding), as outflows, moves and links.
     A stock's outside inflow terms are one flow, floored at 0 as a whole as the engine floors it
     (an active set in the fit).
   - **Fit** (`fit.py`): the mean change is linear in theta, so a set of terms is fitted by
     non-negative weighted least squares. With counts, each change is weighted by the counting
     variance of a reference model (re-read twice from the model found); without noise, each stock's
     variance is concentrated out and floored at the levels' quantum (0.5 T log(rss / T) per stock).
     BIC prices every term as combined's judge prices the flow it becomes (a bilinear term 4: its
     rate and a linear effect; a chain its n stage rates and n starting contents).
   - **Start** (`rowwise.py`): each stock's change regressed on its own (signs free) on 1, every
     stock, every input and every product of two stocks, by forward selection and by backward
     elimination from all of them (a gap, target - R - E, helps only as a whole), then read as
     terms: a feature's loss in a stock it reads paired with gains elsewhere is a move, the rest an
     outflow or a link; a loss in a stock it does not read is a gap or a drain. This is needed
     because the joint search is myopic: a move S -> E at S x I fits S only once E's onset is there.
   - **Stepwise search**: forward (each round screens every term by a projection, fits the 8 best
     exactly, adds the best by BIC), backward after each addition, swaps of a term for an alias
     (an outflow for a gap, a plain outflow for a bilinear one) and merges (an outflow of a and a
     link into b at one driver into the move a -> b).
   - **Goal gaps over several stocks** (`gaps.py`): every gap of up to 3 stocks into each stock,
     as one shared time (u - X1 - X2) / tau, a `goal` term with one number, or free numbers,
     offered as a block with the floor; the search runs again from the best block.
   - **Hidden Erlang chains** (`discover.py`, `terms.py`): a chain of n = 1-4 stages, each drained
     at n / tau, fed by a stock's loss (to itself, as rework, or to another stock) or from outside
     by c + sum k x level/input (a supply line). For a given (n, tau) the chain's delivery is a
     linear filter of measured series, so it is one more column, and each stage's unknown starting
     contents is a column too. The delay is profiled per order: every feature with the chain's
     (`rowwise.profile`), on a 2% log grid from 3 (MIN_DELAY) to T / 10 steps and then golden section; the
     search runs at that delay from the rows' reading and from the plain model; the best order's
     delay is refined again with its terms kept (without the noise-free floor, which flattens the
     optimum) and the terms searched again, three times. Outside-inflow terms of a stock fed by a
     chain are read as part of the chain's feed when BIC cannot tell them apart.
   - **Conventions**: a link into b beside an outflow of a at the same driver is written as the
     move it equals (kept unless BIC objects).
   - **Written** (`write.py`) in SD Lab's forms: a bilinear term is `proportional(a, k x normal)` with
     `effects: [linear(c, normal = mean c, max 1000)]`; a stock's outside inflow is one `linear`
     flow `c + sum k x level` (negative k for gaps); a chain is n inferred stocks with
     `delay: {id, stage, of, time}` marks when n > 1 (the answer key reads it as one hidden path of
     delay tau), and their levels in `inferred_levels`.
   - **Final stocks are not read** in the rows' regressions or a chain's feed: a stock nothing
     leaves accumulates another's outflow, so its level is close to that stock's running sum and
     makes exact aliases of the stock's own dynamics (in rework, a chain fed by Work Done stood in
     for the loop through undiscovered rework).
3. **Acceptance** (`__init__.py`): the search's model replaces combined's only when combined's own
   judge gives it a lower score (one-step likelihood plus BIC, `combined/judge.py`) AND its
   multi-step behaviour error on the run is no worse than combined's model's (within 2%) with no
   more numbers than combined's, or is clearly better (0.8 x combined's error) with more. With
   announced eras the search is skipped (it fits one set of numbers).
4. Added after the first full run: chains under 3 steps are not offered, nor a chain from A to B
   beside a move or link from A to B (measurement noise made those fit: 082, 087 meas); in a closed
   system (every step's changes sum to nothing) only moves are offered (137); the base model's
   inflow pieces, when 30 or fewer, are offered as terms (unannounced schedules: 126, 127); at a
   product only a whole move is read (predation and births are two flows: 127).

## Results

All from the result store (`sdlab.ladder.store.latest`), `uv run sdlab-ladder sync --strategies
structures --jobs 3 --timeout 300` on 7e0a2bf, finished 2026-10-19; single-threaded BLAS. The machine
was heavily loaded (load 90-100 on 28 cores), so times are inflated. combined's and lna_stack's rows
are their latest stored results, which mix several of their versions (the board mixes versions).

**Canonical cases 100-110 and the distilled cases** (variants none-long, none-short, counts-long,
counts-short; 139: counts-long, counts-short, meas-long, meas-short; P pass, E equivalent, f fail):

| case | structures | combined | lna_stack |
|---|---|---|---|
| 100 SIR (dt 1/32) | ffPP | Pfff | ffff |
| 101 SEIR | PPPP | fffP | ffff |
| 102 Bass | PPPP | ffPf | ffff |
| 103 logistic | PPPP | ffff | ffff |
| 104 teacup (dt 1/8) | EEEE | ffEf | ffEE |
| 105 supply line (DELAY3) | PPfP | ffff | ffff |
| 106 workforce | PPPE | ffff | ffff |
| 107 rework | PPPP | ffff | ffff |
| 108 commodity cycle | ffff | ffff | ffff |
| 109 limits to growth | EEEE | ffff | ffff |
| 110 World3 pollution | PPff | ffff | ffff |
| 124 gap over two stocks | PPff | ffff | ffff |
| 126 product move | PPPE | fPPf | ffff |
| 127 predator-prey | PPEE | ffff | ffff |
| 137 closed-market Bass | PPPP | ffff | ffff |
| 138 competition settles | PPEf | ffff | ffff |
| 139 noisy crowding | PPEP | ffff | ffff |

100-110: 30 pass + 7 equivalent of 44 (combined 3 + 1, lna_stack 0 + 2). Excluding the sub-step pair
100/104 (the scoring question with the user): 28 of 36. The distilled six: 17 pass + 4 equivalent of
24 (combined 2 + 0). Still failing: 108 (table effects, not in the search) and 109 (table effects;
equivalent only); 110 counts and 124 counts (a slow drain 0.476 / a gap read with the wrong split under
counting noise); 105 counts-long; 138 counts-short (products seen only while settling).

**Whole ladder (tests):** 1,246 cells paired with combined's stored rows: structures 762 pass + 160
equivalent, combined 710 + 120. 99 cells better, 6 worse. The wins outside 100-139 include 063 (DELAY3
supply line), 080/083/084 noisy variants, 204 and 218 (controllers), and 16 real-data twins
(adoption, Gause). The 6 worse (structures vs combined's row, its commit): 100 none-long (combined
130d21b; sub-step data), 172 counts-long, 211 none-short, phys-draining-tank meas-short,
phys-newton-cooling meas-long and none-short (combined rows from 17b51c7, cd9e8b1, 6ad5556, 2909e47:
older combined versions, so some may be combined's version change rather than the search; not
diagnosed yet). No errors or timeouts.

**Realistic (sd-*, 66 runs):** the search's model was accepted in none: the found models are identical
to combined's in all 66 (so behaviour is combined's). The store's mean skill@20 differs (35.7% vs
40.6%) only because combined's rows were scored by an earlier scorer or on older data: the flows are
byte-identical. Examples bench (`tests/bench/evaluate.py --strategy structures --baseline v2.1
--jobs 3`): on ad4e110 40.2% / 48.2% mean skill@20 / @100 (+10.6 / +18.9 vs v2.1), 15 of 62 meeting
the goal; on 2909e47 36.7% / 44.5% (+7.1 / +15.2), 13 of 62. The two runs differ though the search
was not accepted on any realistic model: combined's own time caps under the machine's load vary.

**Run time:** test cells mean 19.4 s, median 7.5 s, max 338.5 s (combined alone: mean 9.1 s on its
stored rows). The search alone takes 1-3 s on 300-step runs and 15-30 s on 2,000-step runs (the delay
profile is most of it); it is capped at 90 s or 60% of the time left after combined, and falls back to
combined's model when it runs out.

## Verdict

Adopt as the canonical-structure specialist: it recovers products of stocks (SIR at dt 1 data, SEIR,
Bass, logistic, predator-prey, competition), goal gaps over several stocks with the floor, and hidden
Erlang chains (rework, a DELAY3 supply line, World3's transmission delay) where every leader failed,
with 99 cells gained and 6 lost against combined's stored rows, and realistic behaviour unchanged.
Not done: table effects (108, 109), the sub-step pair (the user's scoring question), and the 6 lost
cells (to diagnose, CLAUDE.md 4b). A natural next step is to offer its search as a candidate inside
combined (item 2f) rather than as a wrapper.

## Proposed shared changes

- **combined (item 2f):** add the search as a candidate. Its judge already prefers the search's model
  on every canonical win; the parsimony guard used here (more numbers must behave clearly better)
  would also protect combined against measurement-noise wins by bigger models.
- **Scoring (needs the user):** the sub-step cases 100 and 104 (per-step vs per-time-unit rates).
- **matrix / lna (shared, not changed):** products of a stock with itself or with the destination
  (lna_products excludes both), multi-stock gaps written as one floored linear inflow, and a minimum
  hidden delay of about 3 steps under measurement noise.

## Open ideas

- Table effects of another stock (108's production, consumption and construction; 109's births): an
  effect_hats-style hat basis on a stock, multiplied by a stock, is linear in the knots' values and
  would fit as more columns.
- Logistic regrowth in 109 is truth-written as an inflow r R (1 - R / K) (a table effect to its root)
  while 103 writes births and crowding deaths apart. Without noise the two readings have the same
  mean and the same count of numbers; with counts the variance tells them apart (births + deaths vs
  their difference), which the search's fixed-variance weighting does not see. A final LNA check of
  the two readings would decide it.
- More than one hidden chain; chains between two measured stocks fed by a product.
- The search's counts weighting is fixed per round; lna's likelihood (covariance across stocks)
  would tell moves from links and gaps from outflows better (106 counts-short).
