# combined_lean: change places at a modified-BIC price and weak flows dropped

**Status:** done on the ladder. The tests ran at e0bc5f5. Two fixes followed: in eda02dd the gate also skips a dispersion below -5, and in 781c56c a dropped flow must also keep the multi-step error with the inflow pieces averaged. A replay of the tests with the fixed code gives the same status changes. The realistic runs ran at 781c56c. Examples bench: not run.
**Strategy:** `sdlab/discovery/strategies/combined_lean/` (commit e0bc5f5), tests
`tests/test_ladder_combined_lean.py`; offline replay `tests/study_combined_r2.py lean`.
**Verdict:** adopt the change-place price and the flow pass, gated, into combined (round 2). Strict goes from 618 to 649 of 936 paired test cells (66.0% -> 69.3%), passes from 679 to 682, and noisy cells from 26 to 32 passes. 3 cells drop from pass to equivalent: 008, 046#8 and 082 counts-short, where a true weak link is dropped.

## Question

55 of combined's 61 passes that fail the strict tier fail it for extra parts. Typical cases: one or
two inflow change places the data barely earn (039#4: an inflow of 39.1 then 42.9; 040#6: a blip of
48.8 in 33.4), a weak extra flow (042#8: A2 -> out reading B2 at 0.045), a self-reinforcing inflow
next to pieces (053#5). Can a pass after the choice take these out without losing passes?

## What it does (`prune.py`)

1. **Gate.** (two-sided on dispersion since eda02dd) The pass runs only where the chosen model fits the data to their noise. With counts,
   the dispersion and Ljung-Box tests of combined_misfit (`fitcheck.py`) must both be at z ≤ 5. A
   complexity price means something only when the model is right. On the realistic runs, where no
   model is, the ungated pass changed 35 of 62 runs and cost skill (mean skill@20 over them 26.4% ->
   20.9%, `tests/study_combined_r2.py lean OUT --real`). Models with unmeasured stocks are left alone
   (their numbers are not refitted here).
2. **Change places.** Each pieced outside inflow is re-segmented on its own change places. The
   residual of its stock, with the flow's inflow added back, is split by dynamic programming over
   subsets of those places, weighted by the model's one-step variance. The cost per change is
   `cp` x log T with cp = 1.5: the modified BIC (Zhang and Siegmund 2007) charges about 3/2 log n per
   change point, where combined charges log T (a place and a value). The numbers are refitted
   (combined's refit) and the result kept if the stricter score falls.
3. **Flows.** Backward elimination: a flow goes when removing it and refitting costs less likelihood
   than `fp` x 0.5 log T per number it wrote (fp = 1, BIC). The drops are kept only if the stricter
   score falls and the in-data multi-step error stays within 1.1x, both with the model's own inflow
   pieces and, since 781c56c, with the pieces at their mean. The own pieces alone let sd-population lose
   a needed flow: in-data error 0.0080 -> 0.0091, but 0.32 -> 0.70 with the pieces averaged, and skill@20
   59% -> -729%. This is capped at 30 s.

Score: NLL + 0.5 log T x numbers + (cp - 1) log T x change places (+ (fp - 1) 0.5 log T x numbers).

Tried and switched off: merging a constant inflow and a link into one `c + k x` flow (054's true form;
`merge_inflows`). The grader replaces only constant found inflows with the truth's, so a merged flow
into a stock the truth feeds counts its `c` twice (on the replay, skill@20 of -4 to -68 on 009, 010,
046, 055).

## Results

From the store (`sdlab-ladder sync --strategies combined_misfit,combined_lean,combined_r2 --cases 0,1,sd- --jobs 3`,
2026-10-18 22:53 to 2026-10-19 ~03:15 PDT; then `sdlab-ladder strict ... --cases 0,1`; the realistic runs
again at 781c56c), compared on the 936 test cells every strategy ran. combined's rows are its stored ones
(ded5e80/130d21b, stale); see combined_misfit.md for that caveat.

| 936 test cells | pass | equivalent | strict |
|---|---|---|---|
| combined (stored) | 679 | 101 | 618 (66.0%) |
| lna | 579 | 123 | 432 (46.2%) |
| **combined_lean** | **682** | **103** | **649 (69.3%)** |
| of which noise-free and counts (826) | 650 (combined 653) | 99 | 622 (combined 599) |
| of which noisy: meas, gaps, weekly, lag, outliers, bias (110) | 32 (combined 26) | 4 | 27 (combined 19) |

- Changed status against combined: 5 fail -> pass and 1 equivalent -> pass, all in noisy cells (080 bias-short
  and meas-short, 083 bias-short, 084 bias-long and meas-short, 088#3 meas-long; 080 bias-short is one of the 14
  cells the analysis labels achievable that no strategy passed). 3 pass -> equivalent (008, 046#8 and 082
  counts-short).
- Over the whole ladder (`sdlab-ladder strict`, every cell run, all strict verdicts known): 924 cells, 73.8% pass,
  70.2% strict. The passes failing strict fell from combined's 63 (57 for extra parts) to 33 (20 for extra parts).
- **Realistic** (62 runs, 781c56c): mean skill@20 39.4%, against 40.6% for the stored combined (-3.8 paired; 3 better,
  5 worse, p = 0.20). Its first version (e0bc5f5, one-sided gate, no averaged check) gave 32.9%, mostly from
  sd-population. The gate keeps it off most realistic runs. The gap to stored combined is mostly combined's
  own run-to-run differences (see combined_misfit.md).

## The declared boundary (2026-10-20)

Outside flows are a modelling decision the case makes, not something discovery may invent (the user's
approval, CLAUDE.md invariant 2; docs/research/declared-boundary.md). This strategy carries its own copy of
`matrix/boundary.py` at 723f72c (`combined_lean/boundary.py`; HIDDEN_PRICE 0, CLAIM_PRICE 2) and uses it:

- **lna's atoms** (the search lna, gap_prior, lna_pulses, lna_stack and its levels and products stages share,
  `_vendored/lna/`): an atom with an outside end (in, grow, link, gap, out, drain) is offered only on a
  declared side and kind (`atom_rule`: one that reads a measured input is "measured", any other
  "estimate"); the candidate set is filtered before the noise check and every later fit holds an atom off
  the boundary at 0 (swaps and stages cannot bring one back). A stock with no declared outflow therefore
  has no drain: what it loses is moves.
- The other specialists' copies (censored, effect_hats, common_cause, hidden_transit, periodic_inflows)
  start from the main line's matrix method (the pinned shared library, which they cannot change) and are
  kept inside the boundary by the guard on their models below.
- **Every candidate before the judge:** where a boundary is declared, each candidate model passes the guard
  (`inside_candidates`: a flow outside it becomes its best-priced alternative, a move into a stock of its
  unit, a link made a move, or nothing), with one refit budget for all candidates (GUARD_FITS 150 refits,
  and at most 30 s or half what the caller's timer leaves; past it the offending flows are dropped
  unrefitted, never kept). Identical candidates are guarded once.
- **The judge:** with no boundary declared, each outside flow is a boundary claim and adds CLAIM_PRICE x log T
  (on the -2 log L scale, so half that on the judge's negative log-likelihood) to the candidate's BIC.
- **The answer:** the guard and the anti-correlated pair moves once more (declared), or the moves and the
  priced claims (not declared), bounded the same way; `boundary` and `boundary_claims` in the result.

Results: in progress (paired pool runs on Kubernetes 300-305 and 40 Tests cells; see below when reported).
