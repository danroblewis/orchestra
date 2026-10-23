# Independent systems under a common cause

**Status:** stopped (ladder at commit 19de233; speed fix 0419efe; confound guard in the commit that adds this line). Bench not completed: stopped twice under machine load (see Bench results); generated models not run  
**Strategy:** `common_cause` (`sdlab/sdlab/discovery/strategies/common_cause/`), tests in
`tests/test_ladder_common_cause.py`  
**Verdict:** needs work before adoption: slow (realistic ladder runs mostly time out), and on the 31 example runs that finished it behaves worse than earned_pieces. On the ladder, the best strategy on the independent and identical rungs (028-038: 43 of 44 pass) with no case lost against earned_pieces' committed version

Real systems mix unrelated stocks. The independent rungs (028-033) and the identical-numbers rungs
(034-038) ask discovery to recover each part and invent nothing between them. `common_cause` is
`earned_pieces` (vendored at its commit 559c670, counting likelihood by default) with three additions:

1. **exact.py**: noise-free fits floored at float precision, and exchanges along exact ties;
2. **exact.tiebreak**: among exact fits, the plainest row (own level, no cross term);
3. **places.py**: shared change places, so a common cause is not read as a cross-link; and honest
   pieces for every changing row.

The floored fit, stepwise and PELT are passed explicitly to private copies of the shared matrix and stepwise (`_vendored/`, from 19fd8f8), so the shared modules are never patched at runtime (queue 2h; found flows byte-identical to before on 028-038 and 20 other cells).

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

### Kubernetes 300-311 (2026-10-22, port-common_cause)

kalman_lna's row and controller passes were copied in at 7c3fb13 (`krows.py`, `derived.py`, `delayed.py`,
`subsets.py`, `tracker.py`), with common_cause's own fixes. Details are in docs/research/fixes/port-common_cause.md.
At 5bb4c2b:
- **308-311 (none-short, none-long, counts-short, counts-long):** 11 of 16 pass (job 405), against 0 before. Every
  achievable cell passes. The 5 fails are 309 counts-short and the 310/311 counts variants, all data-limited.
- **300-307:** 32 of 32 still pass (job 406).
- **Non-kubernetes ladder:** no pass lost (job 407, 1164 cells), and 38 cells gained. Some realistic counts cells that
  failed before now time out.
- **034/035 noise-free:** these fail because of c7cade0 (boundary.py), not the port. They are still open.

## Bench results

**Not completed.** The examples bench (`tests/bench/evaluate.py --strategy common_cause --baseline v2.1
--jobs 3`) was run twice and stopped both times (exit 144) while the machine's load was 100-500:
first on 19de233 (single examples took hours: sd-ci long 26,600 s, sd-farm-soil long 11,800 s), then
on 0419efe (`--label "common_cause 0419efe"`, stopped by the coordinator at 07:28 on 2026-10-19 after
47 of 62 runs; no result file is written for a partial run). `--generated 100` was not run.

Partial, from the second run's log (0419efe), paired on the 31 runs that match earned_pieces'
`earned_pieces v5 counting` run (the version vendored here): mean skill@20 **25.6%** against
earned_pieces' 34.3% (matrix reference 38.4% on the same runs); 6 runs better by more than 2 points,
11 worse; parts right 174 against 171 (matrix 166) of 292. Large losses: sd-fishery long (-77 at
skill@20), sd-bakery long (-7.2), sd-housing long (-4.6), sd-eras long (0.17 against 0.99), sd-orders
long, sd-ev-fleet. Gains: sd-cloud-credits long, sd-emergency (both lengths), sd-clinic-doses long,
sd-learning-curve long.

Diagnosis so far: switching the shared places off (`shared_places: false`) gives back earned_pieces'
behaviour on sd-ev-fleet default (0.51 against -0.31) and sd-fishery default (0.40 against -0.32):
in a real model nearly every row has pieces, so every row is a witness and the cheap shared pieces
replace real structure. A guard was added after the bench (`places.confound`): a shared candidate
may read no stock the row did not read, and must drop at least one witness's level (the common-cause
pattern) or re-cut a row that already had pieces. With it: sd-ev-fleet default 0.58, sd-fishery
default 0.13 (still below 0.40); 028-038 unchanged except 033 (PPPP) and 037 (PPPF) as before. The
whole ladder and the bench were not re-run on it.

Speed: discovery is about 3x earned_pieces' (sd-clinic-doses long 99 s against 31 s), most of it in
the vendored joint decision's PELT calls on many-piece rows; 0419efe made the joint PELT prune and
the place pruning merge neighbours (a single sd-clinic-doses variant 29 s -> 9 s). On the current
ladder (1228 items, many realistic cases) the run on 19de233 recorded 12 timeouts and 4 errors; the
realistic runs mostly time out.

## What does not work yet

- **037 counts** (identical stocks, each inflow stepping at its own times) and **027 counts-long**:
  a drain biased with the pieces (037: 0.24-0.29 against 0.2). In 027 long even the true change
  places lose by BIC to a constant inflow and a drain of 0.015: one-step regression cannot see the
  drain; the behaviour judge should, but every candidate makes the same choice.
- **033 counts-short, one seed in ten**: a mild Ljung-Box rejection (p = 0.001) keeps the matrix's
  pieces on B1 beside a split move/link.
- Speed (above), and the examples' losses: the shared places should be offered only to rows in an
  independent subsystem, or judged by behaviour (run each candidate with and without them).

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

## The declared boundary (2026-10-20)

common_cause keeps outside flows to where the case declares them (docs/research/declared-boundary.md;
`common_cause/boundary.py` is a copy of `matrix/boundary.py` at 723f72c, HIDDEN_PRICE 0, with `kept_sides`
and `GUARD_FITS`, as in odefit's copy):

- rows reselected inside it (`rows.reselect(pieces_ok, exclude)`, as matrix's: an outside term only on
  an `estimate` side, inputs only on a `measured` side, other-unit levels only on an `estimate` side);
- shared change places offered only to rows that may have an outside term (`places.offer(pieces_ok)`);
- sources with no estimated outflow tied from the start (`joint.decide(forced)`);
- the judge sees every candidate guarded, and the chosen candidate's own model is kept for the
  measurement-error refit (eiv.py: the guard's one-step least squares numbers cost the 303 meas-long
  pass otherwise); the answer goes through `boundary.apply`.

With no boundary declared, outside flows are boundary claims: on 038 none-long (identical twin chains,
noise-free) the claim price makes `B1 -> outside` the move `B1 -> B2` (identical levels fit it exactly),
so the noise-free collinearity tests (tests/test_ladder_common_cause.py) now announce the case's
boundary as the ladder does; declared, 038 passes.
