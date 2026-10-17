# Unannounced eras: recurring regimes found in the data, then fitted as eras

**Status:** done (wave 4, benchmark v2.1)  
**Verdict:** adopt as an option, but behind the behaviour gate or piece-proof judge (+11.4 / +11.5 points
mean skill, 12 -> 17 runs meeting the goal, the same on fresh runs; the judge can be fooled by a regime
that stands in for an outside inflow)

## Why
In 14 of the 31 truths, an internal flow's equation changes without being announced. Examples:
- sd-moderation: posting per creator switches between 0.1 and 0.03 every 10-14 steps (day and night);
- sd-fishery: the launch gap's goal switches between 36 and 0 with the season;
- sd-bakery and sd-print-shop: the restock time switches 10 -> 60 -> 10 -> 40 and 5 -> 30;
- also sd-farm-soil (restore), sd-saas (churn), sd-university, sd-manufacturing, sd-orders, sd-supply,
  sd-ci and sd-brewery.

The main line can absorb such a change only in an outside inflow's pieces. Pieces take the constant
part of the change, never the coefficient part (a gap's -1/time, a link's k). This idea finds regimes in
the *coefficients* and hands them to the existing per-configuration columns
([regime-models](regime-models.md) proposed switching models for the outside inflow instead).

## What was done
Branch `exp/latent-eras` (from `3197240`), worktree `.claude/worktrees/agent-a2925152de5202a4f`; commit
in the log entry below.

- `sdlab/discovery/regimes.py` (new): per stock row, a K-regime Markov-switching regression of the
  row's change on the constant and every level the row may use (Hamilton filter and Kim smoother in
  numba, EM; Student-t noise with 4 degrees of freedom so a one-off spike does not need a regime; one
  variance per row; a little stickiness). K = 2 or 3. Starts: the pooled residual split by quantiles,
  and the PELT pieces of what the found row (and a row on its own level only) leaves unexplained,
  grouped by value with 1-D k-means. A path is kept only if
  1. every regime recurs (at least 3 spells),
  2. it beats no regimes in BIC with every switch priced as a parameter (log T each), and
  3. it changes a level's number: per-regime numbers beat a constant per regime with shared numbers
     by more than log T, **with the row's own inflow pieces taken out** (so a per-regime number cannot
     stand in for a change in the outside inflow).
  Rows whose switches coincide (70% within one step) share one path, fitted jointly. At most 2
  processes.
- Strategy `latent_eras`: runs the main line, finds the processes, then for each process alone and
  for both together reruns the 8 "numbers per era" variants with the regimes merged into the announced
  eras (each step's configuration is announced era x regime); the judge picks, and a candidate with
  regimes must beat the main line's judge error by 10% (`judge_margin`).
- `matrix.py` option `era_levels` (default "chosen", the current behaviour): "allowed" lets every
  level the row may use take a number per configuration, not only those chosen without eras. The
  strategy uses "allowed".

Options (all in `opts`): `era_levels`, `coefficient_regimes`, `coef_within_pieces`, `judge_margin`,
`max_regimes`, `min_spells`, `max_processes`, `share`, `nu`, `shared_variance`, `detect_on`.

## Mechanism test (`tests/test_strategy_latent_eras.py`)
The brief's model (creators feed screening by a link switching 0.1 / 0.03) does not separate the two
methods: within a 12-step spell creators barely move, so the switch is a change in the queue's inflow,
which the main line replays as pieces (kept by the grader, since the queue is not fed a constant) and
behaves (skill@20 99.8%); the strategy is as good (test kept as a control). The smallest model where
the main line fails is a switching **move**:

a fed 100 a step -> b at 0.5 or 0.1, switching every 12 steps unannounced; b drains 0.2; 2000 steps.

| | matrix | latent_eras |
|---|---|---|
| a -> b | one move 0.349 (+ spurious links) | 0.4975 / 0.1003 by regime |
| regimes | - | 1 process, K = 2, shared by rows a and b, all 166 switches within one step |
| skill@20 | -207% | 100% |

Controls: an outside inflow that switches 200 / 80 (recurring) gets no regime; a model that never
changes gets no regime.

## Results (baseline v2.1: 29.6% / 29.3%, 12 of 62; fresh runs 28.9% / 29.7%, 12)
| attempt | skill@20 | skill@100 | goal | fresh @20 / @100 / goal | run time (summed) |
|---|---|---|---|---|---|
| v2.1 | 29.6% | 29.3% | 12 | 28.9% / 29.7% / 12 | 586 s |
| 1: regimes on the found row's columns, Gaussian, per-regime variance (targets only) | - | - | - | - | - |
| 2: every allowed level, switch-priced BIC, each process alone and together | 33.0% (+3.4) | 33.6% (+4.3) | 15 | 32.1% / 34.1% / 15 | 2004 s |
| **3: + Student-t noise, PELT-piece starts, coefficient test within pieces, judge margin 10%** | **41.1% (+11.4)** | **40.9% (+11.5)** | **17** | **40.1% / 41.3% / 16** | 1968 s |

Run time is about 3.4x the main line (the main line runs in full, then 8 variants per process set);
the machine was shared during both runs.

Every run moving more than 2 points (attempt 3, in-sample @20 / @100, fresh @20 / @100, regimes used):

| run | v2.1 | latent_eras | fresh | regimes from rows |
|---|---|---|---|---|
| sd-bakery default | -1170% / -10328% | 95% / 96% | 94% / 96% | flour + shelf |
| sd-bakery long | 19% / -1650% | 99% / 99% | 98% / 99% | shelf |
| sd-ci long | 88% / 91% | 91% / 96% | 90% / 96% | todo |
| sd-clinic-doses default | -602% / -864% | -55% / -161% | -61% / -163% | doses |
| sd-clinic-doses long | -347% / -208% | -1226% / -5344% | -1222% / -5234% | doses + (vaccinated, waiting) |
| sd-kanban default | 61% / 63% | 86% / 84% | 85% / 85% | capacity, backlog |
| sd-kanban long | 57% / 60% | 79% / 88% | 79% / 88% | capacity, backlog |
| sd-population long | 50% / 92% | 19% / -10% | 18% / -10% | adults |
| sd-print-shop default | -529% / -2305% | 60% / 75% | 61% / 76% | toner + mono_queue |
| sd-print-shop long | -158% / -196% | 66% / 79% | 66% / 79% | toner |
| sd-support-tiers default | -548% / -1574% | -552% / -1568% | -588% / -1603% | new_tickets |
| sd-university default | 75% / 88% | 98% / 99% | 98% / 99% | year1, rooms, admitted |
| sd-university long | 76% / 94% | 96% / 97% | 95% / 97% | rooms, year1, admitted |

Newly meeting the goal: sd-bakery (both), sd-university (both), sd-ci long. Fresh-run skill tracks
in-sample skill everywhere (the fresh run shares the schedule, so this is expected and is not the
guard; recurrence and the coefficient test are).

What attempt 2 -> 3 fixed: sd-population default (a control whose only change is the outside migration)
fell from 68% to -1110% in attempt 2: a regime in the adults row stood in for the migration pieces and
the judge preferred it by a tie-sized margin (0.0107 vs 0.0137). The coefficient test within pieces and
the 10% judge margin removed it; they also turned bakery default 45% -> 95% and print-shop -167% -> 60%
(fewer, cleaner regimes).

`matrix` unchanged: zero deltas on `--examples sd-saas,sd-eras,sd-pipeline --lengths default
--baseline v2.1`.

Diagnosis only (not part of the strategy): the ceiling with the truth's own unannounced coefficient
changes handed in as eras (main-line `identify` with those labels): bakery default 78%, print-shop
default -1% (@100 53%), university 98%, kanban 86%, brewery 82%, moderation -357% (judge error 3.2 ->
0.27, but creators' inflow and drain are confounded, and the grader feeds the true inflow).

## Verdict
**Adopt as an option, combined with the behaviour gate or piece-proof judge** (needs a combination).
The gain is large and holds on fresh runs, but the mechanism adds flexibility the current judge can be
fooled by:
- **sd-population long** (50% -> 19%, @100 92% -> -10%): the adults row's regimes follow the migration
  schedule. Within pieces their coefficient gain is small (89 vs an existence gain of 7212, 1.2%) but
  above the threshold; with them the judge error falls 0.49 -> 0.054, because the per-regime numbers
  reproduce the outside inflow on the data, while the grader feeds the true migration as well. A
  gain-ratio threshold does not separate it from print-shop's useful regimes (ratios 5-6%).
- **sd-clinic-doses long** (-347% -> -1226%, clipped to -100% in the mean either way): the doses row's
  regimes switch 1998 times in 7000 steps (flicker, not eras).
A judge that runs the found model with the true outside inflows replaced (as the grader does), or a
gate against runaway behaviour, should catch both. Everything is behind options so it can be combined.

## Open ideas
- Combine with the piece-proof judge / behaviour gate (above), then lower the judge margin.
- sd-moderation: the day/night regime is found exactly only with K = 3 and a regime per variance (the
  news spikes need their own regime; Student-t alone does not reach it from these starts), and it is a
  constant-only regime (creators barely move), so the coefficient test rejects it; even with the
  truth's labels the creators row's inflow/drain confounding keeps it below 0.
- sd-fishery: the season regime is found jointly in fuel, at_sea and in_port (20 switches, exact), but
  no candidate with it beats the main line; fishery fails elsewhere (changing-inflow variants explode).
- A minimum mean spell length or a switch-rate prior would remove flickering paths (clinic-doses).
- With periodic-inflows: the phase of a periodic profile could label day/night regimes directly.
- Run time: detect on a subset of rows (those whose residual pieces cluster), or rerun only the
  variants the main line's judge ranked best.

## Sources
Hamilton (1989) Econometrica 57(2):357-384; Kim (1994) J. Econometrics 60(1-2):1-22; Dureau,
Kalogeropoulos and Baguelin (2013) Biostatistics 14(3):541-555; Deyle et al. (2016) Proc. R. Soc. B
283:20152258; Mangan et al. (2019) Proc. R. Soc. A 475:20180534 (hybrid-SINDy); Ohlsson, Ljung and Boyd
(2010) Automatica 46(6):1107-1111.
