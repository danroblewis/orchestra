# Independent systems under a common cause

**Status:** ladder done (strategy at commit 19de233); benchmark v2.1 and 100 generated models in progress  
**Strategy:** `common_cause` (`sdlab/sdlab/discovery/strategies/common_cause/`), tests in
`tests/test_ladder_common_cause.py`  
**Verdict:** pending the bench; on the ladder, the best strategy on the independent and identical rungs (028-038: 43 of 44 pass) with no case lost against earned_pieces' committed version

Real systems mix unrelated stocks. The independent rungs (028-033) and the identical-numbers rungs
(034-038) ask discovery to recover each part and invent nothing between them. `common_cause` is
`earned_pieces` (vendored at its commit 559c670, counting likelihood by default) with three additions:

1. **exact.py**: noise-free fits floored at float precision, and exchanges along exact ties;
2. **exact.tiebreak**: among exact fits, the plainest row (own level, no cross term);
3. **places.py**: shared change places, so a common cause is not read as a cross-link; and honest
   pieces for every changing row.

## Why every strategy failed 032 without noise

032 is three independent chains of three, all stocks from 0, constant inflows. Chain 2's last stock
drains at 0.2 (`C2 -> outside = 0.2 C2`) and chain 3's first stock leaves at 0.2 (`A3 -> B3 = 0.2 A3`):
**the two chains share an eigenvalue (0.8 per step)**. On one run from rest with constant inflows,
each stock's level is a constant plus a sum of the system's modes; a mode shared by two chains
makes `A3 = 30 (1 - 0.8^t)` an exact linear combination of chain 2's levels:

    A3 = 0.5 A2 + 0.2143 B2 - 0.0714 C2 + const        (exact; smallest singular value 5e-8 of the largest)

So the 9 levels and the constant span only 9 dimensions, not 10, and every row that reads any of
A2, B2, C2, A3 has a one-parameter family of exact fits. The truth is the sparsest member
(`dC2 = 0.15 B2 - 0.2 C2`: eliminating either of its terms adds two others). The noisy variants pass
because counting noise excites all ten directions.

Where the shared fit goes wrong (`sdlab/discovery/regression.py`, `matrix.py`, `changes.py`):

- **BIC on rounding error.** `stepwise` scores `T log(rss / T)`, with rss floored only at an absolute
  `1e-12`. On exact data, once a row fits, rss is numerical junk (1e-20 of the signal, or the
  1e-9 ridge in `fit_subset`), and any column that shaves the junk gains hundreds against a price
  of `log T`. Forward stepwise on C2's row takes A3 first (the most correlated single column), then
  A2, C2, B2 and four junk columns: `C3, A3 0.42, C1, B3, C2 -0.17, A2 -0.21, B2 0.057, A1`.
- **Greedy path.** Even with a floor, forward selection stops at an exact but non-sparsest set
  (`A3 0.7, A2 -0.35, C2 -0.15`): reaching `{B2, C2}` needs an exchange (add B2 at no gain, then
  drop A3 and A2), which `stepwise` never tries (it adds only for a gain, drops one at a time).
- **PELT on zero-variance residuals.** `pelt` prices a change by the noise variance estimated from
  successive differences of the residual, ~1e-28 on exact data, so the ridge's tiny systematic bias
  is cut into pieces (A3's exact row `dA3 = 6 - 0.2 A3` got 11 pieces).

The same three faults fail 034, 035 and 038 without noise (identical stocks are exactly collinear;
in 035 each gap to 100 decays by the same 20%, so A, B, C and the constant span two dimensions), with
one more: among equally sparse exact sets the drop order (first column first) picks the first stock
(`B -> outside = 0.2 A`), not the row's own.

### Proposed shared fix (not made: shared modules)

Minimal reproduction: `tests/test_ladder_common_cause.py::test_exact_collinearity_reproduction`
(C2's row of 032 none-long: shared `stepwise` returns 8 columns with A3; floored with exchanges it
returns `[B2, C2]`).

1. `regression.fit_subset`: floor rss at the data's precision, relative to a scale passed in by the
   caller (here `1e-8 x T x` the mean square of all stocks' changes; `earned_pieces`' working copy
   has a resolution-based floor, `T q^2 / 6` for data rounded to q, which is the same idea).
2. `regression.stepwise`: when the fit is at the floor, try exchanges (swap a chosen column for an
   unchosen one, then drop what the fit does not need) and keep the plainest exact set, keyed by
   (number of columns, number of other stocks' levels, their distance in the page order, how many
   are listed after the row's stock). Needs the row's own column index as an argument.
3. `changes.pelt`: floor the noise variance at the same scale (`max(dv / 2(n-1), floor)`).

Each is a no-op with noise (the floor is far below any counting noise). In `common_cause` the three
are applied by temporarily rebinding the shared functions for the duration of one `identify` call
(`exact.floored`; each ladder or bench item runs alone in its own process), and the tie-break runs
on every row after reselection (`exact.tiebreak`).

## 033: a common cause read as a cross-link

033 is two unrelated chains whose outside inflows step at the same moments (20/12 -> 35/21 -> 10/6,
every 80 steps). A1 follows its inflow within two steps (it drains at 0.5), so `0.3 x A1` tracks A2's
inflow everywhere except for a step or two after each change. Priced row by row, BIC takes the
link: on counts-long A2's row with a link from A1 and a constant scores 6856, with its true pieces
(a value and a place per change, 25 changes) 6900. The link is wrong but cheap.

The fix is in what a change costs. A change place already earned by another stock's row is known:
the second stock pays only for its value there. With the places priced as values the truth scores
6710 and wins by 146 (counts-short: 993 vs 1018).

`places.offer`, after earned_pieces' reselection:

- **witnesses**: the rows whose fit has pieces; their residuals with the other witnesses' levels left
  out (suspected stand-ins). With no row in pieces (every changing stock read as a link), every row
  whose pieces beside its own level alone pay at the textbook price.
- each row is offered pieces at the places the **other** witnesses show jointly (`joint_pelt`: one
  partition shared by several standardised series, a change costing (1 + rows) log T), each priced
  as a value, with its levels chosen afresh by backward elimination from every level it may read,
  places it does not need pruned (then the constant, if it does not pay). It is taken if its BIC is
  lower than the row's own (own changes priced as a value and a place); a row losing its pieces must
  have white residuals.
- while rows take shared pieces, the places are found again from them (their residuals with each
  other's levels left out) and offered again (up to 3 rounds). The joint places are what removes the
  link: the first round's places, from A1 alone, are off by a step or several where A1's draws hid
  the change, and A2 keeps A1's level for the steps the places miss.
- a row that keeps its own pieces is first offered those pieces found again beside its levels at the
  textbook price (`honest`), since the matrix's cheap pieces over-cut and co-adapt with the drain.

A cross-link survives only if it explains something the shared pieces do not; a row that does not
change with the others pays a value per place for nothing and keeps its own form. Places are never
credited from the row itself (a single stock with a stepping inflow pays full price, as before).

The reselection's whiteness test runs at 0.1% instead of 1% (`ALPHA`): with one test per row and
candidate, 1% rejected true rows (034 counts-long C: p = 0.009 for the right row).

## Ladder results

Letters: none-short, none-long, counts-short, counts-long. (earned_pieces' column is its uncommitted
working copy at the time of the run.)

| case | common_cause | earned_pieces | held_out | lna | matrix |
|---|---|---|---|---|---|
| 028-two-independent-stocks | PPPP | PPPP | PPPP | PPPP | PPFF |
| 029-two-chains-of-two | PPPP | PPPP | PPPP | PPPP | PPFF |
| 030-two-chains-of-three | PPPP | PPPP | PPPP | PPPP | PPFF |
| 031-three-chains-of-two | PPPP | PPPP | PPPP | PPPP | PPFP |
| **032-three-chains-of-three** | **PPPP** | FFPP | FFPP | FFPP | FFFP |
| **033-independent-chains-shared-driver** | **PPPP** | PPFF | PPFF | PPFF | PPFF |
| **034-identical-twins** | **PPPP** | FFPF | FFPP | FFPP | FFFF |
| **035-identical-twins-different-starts** | **PPPP** | FFPP | FFPP | FFPP | FFFF |
| 036-same-inflow-different-drains | PPPP | PPPP | PPPP | PPPP | PPFF |
| 037-identical-twins-own-steps | PPPF | PPPF | PPFF | PPPP | PPFF |
| **038-identical-twin-chains** | **PPPP** | FFPP | FFPP | FFPP | FFFP |
| random independent cases 042, 043 (16 cases) | 61 P, 2 E, 1 F | 55 P, 1 E, 8 F | 58 P, 3 E, 3 F | 64 P | 33 P |
| whole ladder (472 items) | **309 P**, 117 E, 46 F | 290 P, 120 E, 62 F | 280 P, 118 E, 74 F | **340 P**, 74 E, 58 F | 203 P, 85 E, 184 F |

Per tag (pass + equivalent): independent 137 of 140 (earned_pieces 119, held_out 120, lna 125,
matrix 69); identical 19 of 20 (12, 12, 14, 5); common-cause 4 of 4 (2 for every other).

Against earned_pieces, no case is lost except three random goal-gap cases (047 #2, #3, #7 counts-long:
E -> F). They fail with every addition of common_cause switched off as well (`shared_places`,
`tiebreak`, `exact`: False), so they come from the earned_pieces version vendored here (HEAD), not
from this strategy; earned_pieces' newer working copy gets them equivalent. Cases fixed against
earned_pieces: 032 none x2, 033 counts x2, 034 none x2 and counts-long, 035 none x2, 038 none x2,
019 counts-short, 043 #2/#6/#7/#8 none, 031 none-short.

lna leads the whole ladder (link cases pass outright where the matrix family is equivalent); on the
independent and identical rungs common_cause is ahead (lna fails 032, 033, 034, 035, 038 noise-free
or noisy).

Robustness on other seeds (10 seeds each, counts-short / counts-long passes): 033 9 / 9 (earned_pieces
8 / 0, matrix 1 / 0); 029 8 / 9; 031 9 / 9; 034 10 / 9; 038 10 / 9; 020 9 / 10; 037 3 / 5
(earned_pieces 1 / 1, lna 8 / 3).

## Bench results

In progress (examples bench v2.1 and `--generated 100`, started on commit 19de233).

## What does not work yet

- **037 counts** (identical stocks, each inflow stepping at its own times) and **027 counts-long**:
  a drain biased with the pieces (037: 0.24-0.29 against 0.2). In 027 long even the true change
  places lose by BIC to a constant inflow and a drain of 0.015: one-step regression cannot see the
  drain; the behaviour judge should, but every candidate makes the same choice.
- **033 counts-short, one seed in ten**: a mild Ljung-Box rejection (p = 0.001) keeps the matrix's
  pieces on B1 beside a split move/link.
- Discovery time is about twice earned_pieces' (joint scans for 8 candidates).

## Open ideas

- **Counting-noise covariance** as a second test of cross-links: a real move's draw is shared step by
  step (cov(e_A1, e_A2) = -rate), a common cause's is not. Not needed for 033 (no move between the
  chains survives the shared places) but it would separate a real move from a link in 038 counts and
  in the link cases where the matrix family is only equivalent.
- **Lags at the change places**: a stock fed through a move responds one step after its source; one
  driven by the same cause responds at the same step. The witnesses could be filtered by this.
- **Shared places in the matrix's own row fit** (instead of after it): the fine pieces would be found
  jointly across rows from the start.
- The exact-tie key uses the page order (nearer, then earlier stocks) only to break ties the data
  cannot (038 none: B1 fits A1 and A2 equally). A conservation-aware key (prefer the source whose
  own row loses what the receiver gains) would not need the order.
