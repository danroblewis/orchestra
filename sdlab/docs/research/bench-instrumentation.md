# Bench instrumentation: coverage, selection, failure classes, ablation

**Status:** idea (not started)

## Why
The headline mean skill cannot tell a coverage gain (a better candidate exists) from a selection gain
(the judge picks it) from luck. On v1 the judge picked the best candidate in 31 of 42 runs and an oracle
reached 78.3% against 70.8% ([held-out-judge](held-out-judge.md)): the gap was coverage, but no bench
column shows that. Many adopt/reject decisions on 31 examples also need a noise estimate and a paired
test. Playbook experiments I1 and I4 ([PLAYBOOK](PLAYBOOK.md)).

## How it could be tried
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
