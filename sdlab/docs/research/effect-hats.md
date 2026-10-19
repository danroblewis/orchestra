# Effects as tent columns, fitted jointly (strategy `effect_hats`)

**Status:** done (ladder rungs 017-018; benchmark v2.1 and 100 generated models)  
**Verdict:** BENCH_VERDICT

## Question
The ladder's effect rungs failed for every strategy: 017-linear-effect (A -> B at 0.3 x A x C/50)
passed only without noise (`symbolic`, `symbolic_anchor`: only none-short; `sindy`: both noise-free),
and 018-table-effect (the same move times a table of C with a kink at 50) failed in every variant for
every strategy. Why, and can a strategy pass both, with counting noise too, without breaking 001-016?

## Why the existing strategies failed (`sdlab-ladder show 017|018 --strategy symbolic`)
None of it is the ladder's effect matching (but see "The scorer" below for the counting variants).

- **matrix** has no effects: it reads A x f(C) as links from C (C -> B, A -> outside reading C) and
  tens of outside-inflow pieces into A and B (018 none-long: 12 parts wrong or spurious).
- **symbolic, 017 none-long: the right curve, read back as the wrong flows.** A x C/50 is the
  product A x C, the same column whichever stock is called the base. The screen picked base C,
  curve lin(A); `effects.translate` pairs a drain and a link into a move only when the drain leaves
  the base stock, so the found model is A -> outside = 0.33 x C x lin(A) plus outside -> B = 0.33 x C
  x lin(A): the same amounts as the truth (behaviour exact), but keys (flow, A, -, C) and (flow, -, B,
  C) with effects of A, all wrong or spurious.
- **symbolic, 018: the curve is not in the grammar.** The table bends at 50 (slope 0.016 below,
  0.008 above). No grammar shape fits it within the noise-free 2% (a straight line is 8% off at the
  kink), so in none-short the judge keeps matrix (whose inflow pieces imitate the effect); in
  none-long the curve is taken, but the rows disagree on its number (each row is fitted alone, and
  each takes a different share of the misfit through its other columns): A -> B 0.038, A -> outside
  0.30, outside -> B 0.11, all with the effect.
- **symbolic, counts:** the screen finds nothing on 300 steps; on 2000 steps the judge keeps matrix.
- **sindy** has products A x C in its library (so 017 noise-free passes) but no kinked curves (018)
  and its sparse fits do not survive counting noise.

## What was done
Strategy package `sdlab/sdlab/discovery/strategies/effect_hats/` (no shared module changed):

- `basis.py`: a curve of C as tents (hat functions) over K knots; the tents sum to 1, so base x f(C) is
  linear in the K table values and an SD Lab table effect is exactly what is fitted (flat beyond the
  end knots, as `effect_value`).
- `screen.py`: every (base: a stock or 1, C) as a group of K tent columns, projected on what the rows
  leave after their levels (and pelt pieces); a pair that clearly explains one or two rows is a
  candidate. Both readings of a product (A x f(C), C x f(A)) are kept; the price decides.
- `search.py`: for every way the flow can run (between the two rows, out of or into one, or out of
  its base stock into a row), the tent weights are fitted **jointly in both rows** (one shared group,
  with the flow's signs), knot count 2-8 by BIC, every placement compared on the same rows. The curve
  (normalised to 1 at C's mean level) becomes a virtual stock offered to the matrix method in those
  rows; `translate.py` reads it back (a drain and a link on the curve become a move; a leftover drain
  of a third stock on the same curve becomes the move's co-flow, `uses`).
- `joint.py`: every number of the model refitted at once in a stacked least squares across all rows
  (each flow's columns enter every row it touches with its sign; an effect flow's columns are its
  tents; a co-flow's `per` re-read from the used stock's row in alternation), rows weighted by their
  own noise; then flows dropped one at a time while the joint one-step BIC falls.
- `pieces.py`: outside inflow pieces pooled into a few values and re-cut (Viterbi, a change costing
  2 log T in the row's noise; the number of values by BIC, each extra value priced 2 log T more), and
  the steps within 2 of a change left out of the fit (`guard`). Why: see "Inflow pieces bias drains".
- Acceptance: the curve must explain both halves of the data; the model must price better than the
  base with its inflows re-cut the same way (BIC, pooled values counted once) and behave within 1.1x
  of it on the judge; the lowest price wins, a flow whose rate is not its source's level paying
  2 log T. With no effect accepted, the base with re-cut inflows is returned when it prices better
  (`seg_base`).

Tests: `tests/test_ladder_effect_hats.py` (tents equal a table effect; the joint refit recovers a
table effect exactly; a pooled inflow is re-cut at its true changes with an unbiased drain; 017 and
018 none-short pass; no effect is added to a chain). New ladder case
`027-stepping-inflow-drain`: the C row of 017/018 alone.

## Inflow pieces bias drains under counting noise
The rungs' C stock has an inflow that steps 3 <-> 7 every 100 steps (unannounced) and a drain of
0.1. Even fitted with the true structure, the drain comes out fast:

| C row fitted with | drain k (true 0.1), Monte Carlo of 40 runs of 2000 steps |
|---|---|
| true change times, one inflow value per window | 0.108 (Nickell-type short-panel bias) |
| true change times, two pooled values | 0.101-0.104 |
| PELT pieces (as the matrix cuts them) | 0.122 |
| pooled values, change times re-cut freely | 0.118 (3 values chosen), 0.113 (2) |
| ... and the 2 steps either side of each change left out | 0.106 |

A change placed one step late moves k by about 10% (the jump in the inflow lands in the wrong
piece). On the ladder the matrix reads 027's drain as 0.144 (2000 steps) and 0.376 (300 steps).

## Results: ladder (letters: none-short, none-long, counts-short, counts-long)
LADDER_TABLE

## Results: benchmark v2.1 (31 examples x 2 lengths)
BENCH_TABLE

## Results: 100 generated models
GEN_TABLE

## The scorer
1. **No standard-error allowance for the linear parts of a case with effects.** `oracle.py` is
   disabled for the whole case when any true flow has an effect (`Oracle.ok` needs `linear_system`
   of every flow), so C's inflow and drain in 017/018, which are linear and untouched by the effect,
   must be within 10% with no allowance for what the data can say. Fitting the truth's own structure
   by least squares (true effect shape, true change times, per-window inflow) fails 017 counts-short
   (every part 11-23% off), 017 counts-long (C inflow 15%), 018 counts-short (C parts 52% / 31%) and
   018 counts-long (C parts 38% / 20%). Proposed: build the oracle per row, for every row that no
   effect or hidden flow touches (or with the effect's true multiplier as a known column).
2. `sdlab-ladder show` crashes on a stored spurious effect part (`cli.py` line 178: an effect part's
   size is `math.inf`, stored as `null`, formatted with `:.3g`).
3. Equivalent effect readings are scored by key: k x C x lin(A) for a move A -> B is the same function
   as k x A x lin(C) but is keyed (flow, A, B, C) with an effect of A, so it fails. Fair as a test of
   SD's usual form (rate = source x effect), worth knowing.

## Open ideas
OPEN_IDEAS
