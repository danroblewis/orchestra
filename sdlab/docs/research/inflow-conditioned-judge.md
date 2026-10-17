# Inflow-conditioned held-out judge and era hold-out

**Status:** done (wave 3, benchmark v2.1): piece-proof judges; the era hold-out not tried  
**Verdict:** reject as a main-line judge (every variant but one picks worse than the main line's on its
own candidates); keep `judges.py` as a block for strategies whose candidates add structure

## Why
The [held-out-judge](held-out-judge.md) experiment failed because a held-out block must forecast an
outside inflow that changes unannounced, so it measured inflow extrapolation, not dynamics. The
in-data judge has the opposite weakness, seen in [hidden-stocks](hidden-stocks.md),
[symbolic-regression](symbolic-regression.md), [pysindy](pysindy.md) and [floors-and-caps](floors-and-caps.md):
each candidate is run with its OWN outside-inflow pieces, so pieces that imitate missing structure
(an effect, a hidden stock, a misread flow) make a wrong candidate look right. The grader asks a
different question: the candidate's dynamics, fed the truth's outside inflows. Playbook M12.

## What was done
Branch `exp/piece-proof-judge` (from `550a8f0`), worktree `.claude/worktrees/agent-a97340735bd8f007c`.
`sdlab/discovery/judges.py`: `score(cands, stocks, run, judge)` / `choose(...)` for any candidate loop;
every judge takes the pieces out of the candidate's hands in a different way (only the data is used):

| judge | the outside inflow each candidate is run with | hypothesis item |
|---|---|---|
| own | its own pieces (the main line) | |
| common | per stock and step, the median over all candidates of their net outside inflow | (a) |
| anchor | the pieces of the candidate `own` ranks first, for everyone | (a) |
| mean | its own pieces at their mean | (b) |
| refit | dynamics frozen, inflow re-measured over the run in coarse pieces (>= n/50 steps) | (c) |
| window | dynamics frozen, per judged window one inflow number per stock per 25 steps, least squares on the window | (c) |
| split | its pieces' values re-measured on every other step (same draws cannot be reused) | (d) |
| own x (1 + c x load) | own error times the variance its pieces carry relative to the stocks' step changes | (d) |
| a+b, geometric means, max, ranks | combinations | |

Strategy `piece_proof` = the main line's 16 candidates chosen by `judges.choose` (default "common";
`opts["judge"]` picks another). Variants other than the default were measured on the same candidates
and the bench's own grader offline (every candidate of every run graded once; each judge's pick read
off); the offline numbers for "common" match the bench run exactly.

## Mechanism tests (`tests/test_strategy_piece_proof.py`)
Candidates: three main-line variants plus the true structure with an outside inflow measured from the
data (pieces of >= 5 steps with its dynamics frozen).
| model | own picks | common | window | mean |
|---|---|---|---|---|
| births misread as a move, paid back by adults' pieces (234/step vs 80/160) | the trap (0.0135 vs truth 0.0154), graded 66% vs 100% | **truth** (0.018 vs 0.26) | truth (by 0.0001) | constant inflows |
| signups that really change, bug spikes | truth | **truth** | a wrong one (tie) | truth |
| a -> b at k a table(c), imitated by 30-40 pieces | truth (by 0.02) | a wrong one: the median carries the imitation | **truth** (0.18 vs 2.5+) | truth |
| signups, main-line candidates only (no truth) | receivers (68%) | trust rows (-758%) | | |

The common inflow catches a candidate whose pieces are far from everyone else's, and keeps changing
inflows; it fails whenever the right candidate is a minority (the median then carries the majority's
imitation) or when the candidates' inflows are not comparable (constant-inflow and changing-inflow
rows absorb different things). The window judge separates the effect case strongly but ties elsewhere:
a per-window inflow absorbs most of what goes wrong over 5 or 20 steps.

## Results (baseline v2.1: 29.6% / 29.3%, fresh 28.9% / 29.7%, 12 of 62 meet the goal)
| judge | skill@20 | skill@100 | fresh @20 / @100 | goal | pick changed | better / worse by > 2 points @20 |
|---|---|---|---|---|---|---|
| own (main line) | 29.6% | 29.3% | 28.9% / 29.7% | 12 | - | - |
| **common (bench run)** | **12.5%** | **17.1%** | 11.0% / 17.4% | 11 | 46 of 62 | 8 / 21 |
| anchor | 29.9% | 29.5% | 29.2% / 29.9% | 12 | 12 (4 graded differently) | 1 / 0 |
| mean | -15.4% | -24.9% | -15.5% / -24.4% | 3 | 44 | 3 / 29 |
| refit | 8.3% | 3.3% | 8.3% / 3.5% | 8 | 38 | |
| window | -0.4% | -2.6% | -0.9% / -2.6% | 8 | 47 | 3 / 23 |
| split | 19.5% | 30.8% | 18.8% / 31.2% | 10 | 29 | |
| own + mean | 17.7% | 13.2% | 17.5% / 14.0% | 9 | 26 | 5 / 13 |
| own + common | 16.6% | 17.7% | 14.7% / 18.1% | 11 | 43 | 7 / 14 |
| own + window | 18.9% | 16.9% | 18.2% / 17.0% | 12 | 21 | 4 / 8 |
| geometric mean of own and mean | 28.1% | 24.1% | 27.9% / 24.7% | 12 | 17 | 4 / 6 |
| own x (1 + 0.1 load) | 24.4% | 24.2% | 24.3% / 24.9% | 12 | 14 | 3 / 5 |
| best-graded candidate (oracle) | 45.5% | 47.1% | 45.4% / 47.2% | 13 | 39 | 21 / 0 |

Common, run as the bench: up sd-emergency default (+70), sd-learning-curve default (+132),
sd-fishery long (+57), sd-brewery long (+16), sd-restaurant default; down sd-bakery long (+19% ->
-852%), sd-eras long, sd-housing (both), sd-population (both), sd-restaurant long, sd-moderation long,
sd-support-tiers long, sd-university default, sd-manufacturing default, sd-learning-curve long.
Mean drops every example whose inflow really changes (hidden-chain, saas, services, reservoirs to
-100%). Run time: the common, mean and anchor judges cost about what `own` does (50-100 s of the
bench's CPU), window about 3x, refit about 5x (PELT per stock per candidate). Matrix unchanged (sd-saas,
sd-eras, sd-pipeline default: zero deltas against v2.1).

## Lessons
- On the main line's own candidates the in-data judge is hard to beat: the candidates differ mostly
  in the inflow's form (constant or changing) and in conservation, and "own" is the only judge that
  sees each candidate's dynamics with the inflow those dynamics were estimated with. Swapping in any
  other inflow pairs dynamics with an inflow they did not absorb, and the error that follows ranks
  candidates by robustness to the wrong inflow, not by being right.
- A candidate-independent inflow is only as good as the candidates it comes from. The median is
  right when the wrong candidate is the outlier (the births trap) and wrong when the right candidate
  is (a found effect or hidden stock): exactly the case the other strategies need.
- Refitting inflows per window, or per candidate over the run, is fair (same budget for all) but
  mostly blind: a free inflow, even a coarse one, absorbs the misfit over the horizons we judge.
- The judge ceiling is real (oracle +16 points) but no data-only judge here reaches any of it except
  "anchor" (+0.3, one run).

## Open ideas
- Judge structural additions, not whole candidates: compare a candidate with its addition and
  without, both fed the inflow of the one WITHOUT it (the addition must remove pieces, not move them):
  the effect and hidden-stock cases pass this by construction; it is what "anchor" does when the
  base candidate wins `own`.
- A window judge with error over the window's later part only (fit the coarse inflow on the first
  half of each window, score the second): breaks the ties seen here.
- The era hold-out (fit on eras 1..k, predict era k+1) is still untried.
- Combine per candidate type: "own" between inflow forms, "window" or "anchor" for an added effect or
  hidden stock (the symbolic and hidden-stock strategies' acceptance step).

## Sources
Dawid (1984) JRSS A 147(2):278-292, doi:10.2307/2981683; Racine (2000) J. Econometrics 99(1):39-61;
Bergmeir, Hyndman and Koo (2018) CSDA 120:70-83, doi:10.1016/j.csda.2017.11.003; Forrester and Senge
(1980) TIMS Studies in the Management Sciences 14; Oreskes, Shrader-Frechette and Belitz (1994) Science
263(5147):641-646; Kirchner (2009) WRR 45(2):W02429 (an inferred input absorbs misspecification).
