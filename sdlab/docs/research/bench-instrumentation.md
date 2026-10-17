# Bench instrumentation: coverage, selection, failure classes, ablation

**Status:** done for I1 (branch `infra/bench-instrumentation`); inflow load, the refitted-truth
ceiling and ablation (I4) not built yet.

## What was built (I1)
- **Every candidate graded** (`tests/bench/candidates.py`): `identify(..., {"candidates": True})`
  lists every variant's flows and judge error (nothing else changes; the page never asks for it).
  The bench grades each like the chosen model and stores per run `candidates` (name, judge error,
  skill@20/@100), `best` (the best-graded candidate: meets the goal, else highest clipped
  skill@20 + skill@100; among those within half a point, the one the judge rates best; with the
  judge's `rank` of it, 1 = picked), `chosen_judge`, `truth_judge`, `truth_better` and `failure`.
  On by default: identical candidates are graded once and the truth's runs are shared, so it adds
  ~2% wall time (1:48 against 1:46 for the full bench); `--no-candidates` skips it.
- **Failure class** per run that misses the goal:
  - *not chosen*: some candidate meets the goal, the judge kept another (selection gap);
  - *not representable*: no candidate meets it, and the judge's own measure (multi-step error from
    ~80 starts at 5/20/100 steps) rates the **true model** at least 5% better than the chosen one: the
    right model would be picked if a generator proposed it (coverage gap);
  - *not supported*: no candidate meets it, and the judge rates the true model no clearly better
    (not 5% below) than the chosen one: on this data the judge cannot prefer the truth, so a new
    generator alone will not help (more data, a better judge, or a prior);
  - *error*: discovery raised.
  The truth is scored with its true numbers, its schedule as outside inflows and its hidden stocks
  started from their true levels. That is a proxy for the playbook's "true structure refitted by
  our own fitter" (no fixed-structure fit mode on the main line yet); it knows more than any fit,
  so it leans towards *not representable*. The 5% margin keeps near-ties (judge noise) out of it.
- **Seeds** (`--seeds K`, `tests/bench/seeds.py`): each example also runs with seeds SEED+2...
  (SEED+1 is the fresh run); discovery reruns on each and is graded there, and the main model is
  graded on each too. Per run "mean ± sd" over seeds, and in the headline the mean skill per seed
  (the headline's own spread) and one run's average spread.
- **Paired tests** (`sdlab/bench_stats.py`): runs paired by example and length, skills clipped at
  -100%, changes under half a point dropped as ties; sign test (binomial) and Wilcoxon signed-rank,
  two-sided. Printed under the headline with `--baseline` (and against the last run);
  `tests/bench/compare.py A B` for two saved runs; the research view's comparison shows them
  (`/api/research/compare/{a}/{b}`).
- **Leakage check**: the bench hands discovery only `page_inputs` (measured stocks' id, name, unit,
  final, group; levels; announced eras: the bench used to pass the whole stock record, including
  `initial` and positions, which discovery did not read). `tests/test_bench_instrumentation.py`
  asserts the bench's call carries nothing else, and runs discovery on sd-eras and sd-saas with every
  truth file, the example's folder and the dataset cache unreadable and the stock ids and names
  replaced by random strings: the same flows and chosen variant, up to renaming.
- **Research view**: runs table columns "best cand. @20", "judge picked best", "failures R / C / S";
  one run shows each run's best-candidate skill, judge rank and class; two runs compared show the
  paired tests.
- `bench --examples sd-saas,sd-eras --lengths default --baseline v2.1` and the full bench show zero
  skill deltas against v2.1 (all 62 runs "same").

## First full run on v2.1 (main line `matrix`, 62 runs, 2026-10-17)

| | runs |
|---|---|
| meet the goal | 12 |
| miss it | 50 |
| - not representable | 44 |
| - not chosen | 1 (sd-recycling default: a candidate at 95.0% / 98.2%, judge rank 9 of 16) |
| - not supported | 5 (sd-supply both lengths, sd-learning-curve default, sd-emergency default, sd-eras long) |
| - error | 0 |

The judge picked the best-graded candidate in **33 of 62** runs. The best candidate's mean skill@20
is 45.4% (chosen: 29.6%) and @100 48.3% (29.3%), but it meets the goal in only 13 runs (chosen: 12).
So selection costs a lot of mean skill (mostly in runs far from the goal: sd-housing long, the best
candidate at 86.1% / 92.3% against -120% chosen; sd-clinic-doses; sd-print-shop), yet only one run
would cross the goal with a perfect judge: the goal is a **coverage** problem. Every failing run has
some candidate, but none is good enough, and in 44 of them the judge would prefer the truth.
The 5 *not supported* runs are where judging on data alone needs help: in sd-supply and
sd-learning-curve default the chosen model has a clearly *lower* judge error than the truth
(0.18 against 0.28; 0.13 against 0.17), so the judge rewards a model that fits this run's draws.

Seeds (6 examples at default length, `--seeds 2`): one run's skill@20 spreads 16 points across
seeds on average (sd-population: -18% ± 80; sd-supply ± 6; sd-orders ± 4; sd-saas ± 0.2), and the
mean over those six moves from 77% to 51% between seeds, while the main model graded on the other
seeds stays within 0.3 points. The run-to-run noise of *discovery* is much larger than the noise of
*grading*: an adopt decision on one seed needs the paired test, and the seeds when a change is small.

## Left for later
- *Inflow load* column; the fresh-run gap is in the table but not as its own column.
- The *refitted* truth ceiling (needs a fixed-structure fit, `refine.py` on `exp/output-error`).
- Ablation `--ablate` (I4); the held-out-judge trap mechanism test.
- Seeds through the paired test (pairing per example on seed means).

## Why
The headline mean skill cannot tell a coverage gain (a better candidate exists) from a selection gain
(the judge picks it) from luck. On v1 the judge picked the best candidate in 31 of 42 runs and an oracle
reached 78.3% against 70.8% ([held-out-judge](held-out-judge.md)): the gap was coverage, but no bench
column shows that. Many adopt/reject decisions on 31 examples also need a noise estimate and a paired
test. Playbook experiments I1 and I4 ([PLAYBOOK](PLAYBOOK.md)).

## How it could be tried (the original plan)
- `identify()` returns every candidate's flows; the bench grades each: **oracle skill** and the
  **judge rank** of the best candidate per run.
- **Failure class** per failing run: *not representable* (no candidate meets the goal, the true
  structure refitted by our own fitter does), *not chosen* (a candidate meets it, the judge chose
  another), *not supported by the data* (the true structure refitted also fails). Needs a
  fixed-structure fit mode (e.g. `refine.py` on `exp/output-error`); the truth is used only in grading.
- **Inflow load**: inflow pieces into stocks the truth does not feed from outside.
- **Fresh-run gap** (fresh-run grading is on the main line): in-sample minus fresh skill per run.
- **Seeds and paired tests**: 2-3 extra seeds per example as a reported column (not the goal);
  Wilcoxon signed-rank over runs against the baseline.
- **Leakage check**: stock ids and names permuted and renamed, rows shuffled: identical skill.
- **Ablation** (I4): every adopted mechanism keeps an `opts` switch; `--ablate` runs leave-one-out on
  the main line; at consolidation an ablation path from the original baseline; the 2x2 for overlapping
  winners.
- Mechanism test: the held-out-judge trap model shows a bad judge rank for the trap and a high inflow
  load; a permuted synthetic model grades identically.

## Sources
Demšar (2006) JMLR 7:1-30; Kapoor and Narayanan (2023) Patterns 4(9):100804, doi:10.1016/j.patter.2023.100804;
Fawcett and Hoos (2016) J. Heuristics 22(4):431-458, doi:10.1007/s10732-014-9275-9; Hooker (1995)
J. Heuristics 1:33-42, doi:10.1007/BF02430364; Rice (1976) Advances in Computers 15:65-118; Lyneis (2000)
SDR 16(1):3-25; literature report [research-process](literature/research-process.md) sections 9-12.
