# Drains measured where nothing flows in (recession analysis)

**Status:** done (wave 4, benchmark v2)  
**Verdict:** needs a combination. The generalised fit gains +10.5 / +15.2 points, on fresh runs too, but
moves runs both ways through the judge. The brief's strict "no inflow at all" version gains +1.0 / +1.4 and
harms nothing.

## Why
In the one-step fit a drain and an unannounced outside inflow are confounded, and pieces bias the
drain. Within-piece demeaning biases it by about (1 + a)/(m - 1)
([change-price](change-price.md)). On sd-pipeline default, under constant inflows, the inbox drains
0.11 against a true 0.3, and skill@100 is -178%.

Many truths have stretches with no inflow at all:
- sd-restaurant: doors close, and arrivals are 0.3 a minute in the mornings;
- sd-farm-soil: no growth for 23 of every 52 weeks;
- sd-clinic-doses: six days in seven without a delivery;
- also sd-emergency at night, sd-kanban sprint days 2-14, and sd-fishery's closed season.

On those stretches a stock's level decays freely, and its drain can be read off the recession curve
with no inflow model at all. Hydrology does this backwards (Kirchner 2009): identify the
storage-discharge law from recessions, then invert it to recover the unmeasured input. Here that
means fixing the drain first, then estimating the inflow with the drain fixed, which cannot bias the
drain.

## How it could be tried
- Strategy `recession`. From the first pass, mark candidate quiet steps per row: steps whose local
  inflow estimate (piece value) sits at the bottom of its distribution and is not distinguishable from
  0, or runs of at least m consecutive falls.
- Fit the row's level coefficients on quiet steps only, with no inflow term. If there are enough quiet
  steps (at least 5 x the number of coefficients) and the quiet fit differs from the full fit by more
  than 2 SE, keep the quiet coefficients.
- Then estimate the pieces on all steps with those coefficients fixed. Never refit the levels on the
  reported pieces: the change-price spiral needs that refit.
- Enter the result as a candidate.
- Mechanism test: an inbox whose intake alternates on and off (9 per step for 20 steps, then 0 for
  20, with unannounced variation) drains 0.3 to working, and working drains 0.2; 600 steps. Baseline:
  inbox drain off by more than 0.05. Strategy: within 0.02, skill@100 at least 0.9. Control: an intake
  that never stops (always above 3) gives no quiet steps and the matrix result.
- Targets: sd-pipeline default @100, sd-restaurant @100, sd-farm-soil @100, sd-clinic-doses, sd-kanban,
  sd-fishery, sd-emergency.

## What was done
Branch `exp/recession-drains` (worktree `.claude/worktrees/agent-aeb915aed5fd422f0`); the commit is the one
that adds this section. Building block `sdlab/discovery/recession.py` (`quiet_steps`, `recession_row`,
`apply`, usable on any `identify_one` result). Strategy `sdlab/discovery/strategies/recession.py`: every
main-line candidate is entered as it is and, where some row changes, entered again with the recession rows
("..., recession drains"). The judge picks among all of them.

For each row with an outside inflow (not final, and not already set by conservation):
1. Quiet steps: what the row's levels leave unexplained is cut by PELT into fine pieces (at least 2 steps).
   A piece is quiet when its value is within 2 standard errors of the 10% weighted quantile of piece values
   (the noise is measured within pieces). Each quiet stretch loses its first and last step (`recession_trim`).
2. The row's levels (its own drain always) plus one constant are fitted on the quiet steps. The constant is
   dropped when it is within 2 SE of 0, and then there is no inflow term at all. Steps 1 and 2 repeat until
   the quiet steps settle.
3. The quiet fit is kept only when:
   - there are at least max(20, 5 x (columns + 1)) quiet steps, and fewer than 90% of all steps;
   - the own drain's SE is at most 0.25 x its value (`recession_precision`): a level sitting at an
     equilibrium while the inflow is quiet cannot be told from the inflow's quiet level;
   - some number differs from the row's own by more than 2 SE.
4. The inflow is then measured on all steps with those numbers fixed, in pieces of at least
   `recession_piece` = 2 steps. The levels are never refitted on the pieces.

Options: the strategy's `DEFAULTS` set two, `recession_piece` 2 and `recession_trim` 1, and the
`SDLAB_RECESSION` environment variable (JSON) overrides them for ablations. The rest are off by default:
- `recession_zero_only`: the brief's strict version; only fits whose quiet constant is 0 are kept.
- `recession_split_only`: with announced eras, only the per-era candidates get recession rows.
- `recession_replace`: the recession candidate replaces its parent instead of joining it.
- also `recession_constant`, `recession_precision`, `recession_width` and `recession_share`.

**The brief's mechanism test does not fail the main line.** With 20-step on/off stretches (9, 6 or 12, then
0), `matrix` gets the inbox drain at 0.285-0.316 and skill@20 99.9%, whether or not the receiver is measured.
The change scan places 20-step pieces exactly. The main line fails when the stretches are shorter than its
5-step minimum piece.

**Mechanism test** (`tests/test_strategy_recession.py`): bursts of 3 steps (15, 10 or 20, unannounced), then
12 quiet steps; the inbox drains 0.1 into working, working drains 0.2; 600 steps.

| | seed 1 | seed 2 |
|---|---|---|
| `matrix`: inbox own drain | 0.364 | 0.334 |
| `matrix`: spurious "inbox drains faster when working is high" | 0.57 | 0.74 |
| `matrix`: skill@20 | -46% | -41% |
| `recession`: inbox drain | 0.105 | 0.104 |
| `recession`: skill@20 / @100 | 99.0% / 98.6% | 99.8% / 99.8% |

Control: 20-step stretches at 9, 6 or 12, then 4, where the main line is right at 0.3; the result is unchanged.
With pieces at the usual 5-step minimum the recession rows are still found (drain 0.105), but the judge
prefers the main line's biased drain, whose coarse pieces replay the bursts better. The test passes only
with `recession_piece` 2 (or `recession_replace`).

## Results
Bench vs `v2.1`: 62 runs, each clipped at -100% in the means. v2.1 itself: skill@20 29.6%, @100 29.3%, 12
runs meet the goal; on fresh runs 28.9% / 29.7%, 12.

| attempt | skill@20 | skill@100 | fresh @20 / @100 | goal (fresh) | CPU s |
|---|---|---|---|---|---|
| quiet fit with a constant, pieces at the 5-step minimum, no trim, no precision test | 37.3% | 45.2% | 35.9% / 45.4% | 13 (12) | 578 |
| + precision 0.25, trim 1 | 38.3% | 43.7% | 37.6% / 44.1% | 16 (14) | 975 |
| **+ pieces of 2 (adopted defaults; the mechanism test passes)** | **40.1%** | **44.5%** | **39.6% / 44.9%** | **16 (14)** | 987 |
| + zero only + split-era only (the brief's strict version) | 30.6% | 30.7% | 29.8% / 31.0% | 13 (13) | 736 |
| + split-era only | 35.8% | 37.2% | 35.0% / 37.4% | 15 (14) | 1067 |
| + precision 0.1 | 38.5% | 43.1% | 38.0% / 43.6% | 13 (13) | 1107 |

CPU s is run time summed over runs, on a heavily loaded machine (load around 150); the baseline took 586 s.

Adopted defaults: every run that moved by more than 2 points. Fresh runs are within a few points of these.

| run | skill@20 | skill@100 | change @20 / @100 |
|---|---|---|---|
| brewery default | 94.0% | 98.3% | +17.7 / +6.9 |
| brewery long | 89.1% | 96.6% | +22.8 / +8.4 |
| ci default | 93.2% | 96.9% | +4.4 / +1.5 |
| clinic-doses default | -5.2% | 56.6% | +94.8 / +156.6 |
| clinic-doses long | -76.3% | 28.9% | +23.7 / +128.9 |
| cloud-credits long | -909% | -71.0% | -83.5 / -125.4 |
| eras default | 57.9% | 81.6% | -38.6 / -16.4 |
| eras long | 53.2% | 78.1% | +3.7 / +3.8 |
| ev-fleet default | 0.7% | 25.0% | -31.3 / -22.8 |
| fishery default | 96.9% | 95.2% | +94.1 / +195.2 |
| fishery long | -19.0% | -55.7% | -0.5 / +44.3 |
| hospital default | 95.2% | 95.7% | -1.9 / -3.3 |
| hospital long | 96.1% | 94.7% | +3.9 / +8.4 |
| housing long | 97.2% | 98.4% | +197 / +198 |
| learning-curve default | 82.1% | 96.5% | +154 / +134 |
| learning-curve long | 69.7% | 92.3% | +25.0 / +43.4 |
| manufacturing default | 90.9% | 91.7% | +26.1 / +14.0 |
| orders long | 83.1% | 94.0% | -2.8 / -0.1 |
| print-shop long | 40.4% | 69.0% | +140 / +169 |
| recycling default | 63.2% | 90.0% | -8.6 / -5.8 |
| recycling long | 98.6% | 99.6% | +5.3 / +3.2 |
| sawmill default | -167% | 2.3% | 0 / +74.4 |
| sawmill long | -184% | -51.7% | 0 / -46.6 |
| services default | 52.8% | 84.6% | +45.6 / +12.5 |
| services long | 38.8% | 79.9% | +3.7 / +1.8 |
| webshop-stock default | 13.1% | 8.1% | -47.7 / -46.9 |

What it found:
- **The gain is not where the brief looked.** Under the strict version, none of the brief's targets with
  truly quiet stretches moves (restaurant waiting, farm-soil field, kanban capacity). The strict version
  moves only brewery, eras long, fishery long, learning-curve default and sawmill default, all of them up
  (+1.0 / +1.4). sd-pipeline default has no quiet steps (its intake never goes below 3) and does not move
  in any version.
- **The large gains come from the generalisation**: a row's levels fitted on the steps where its outside
  inflow sits at its lowest level, with one constant for that level, instead of demeaning within every
  short piece. This removes the within-piece bias for rows whose "inflow" is a slowly varying base plus
  bursts: clinic-doses vaccinations, housing, print-shop, learning-curve, fishery, services.
- **Why it also loses runs:**
  - Choosing steps by a low residual selects on the noise, and on nonlinear effects that the row's
    "inflow" stands in for. That biases the numbers: webshop-stock default (picking runs through a shelf
    effect) and cloud-credits long. A tighter precision test (0.1) removes both losses, but also the gains
    on clinic-doses default and fishery default.
  - With announced eras, a candidate with shared numbers has pieces standing in for the eras' changes, so
    its quiet steps come from one era. In sd-eras default, middle's raw coefficient goes from 0.51 to 0.28,
    its first era's value. The split-era guard fixes eras but loses more elsewhere (housing long,
    learning-curve).
- **Judge flexibility.** The recession candidate uses the same piece machinery as the main line, but with a
  2-step minimum its re-measured inflow is finer than the main line's 5-step pieces. So part of a recession
  candidate's win in the judge can be replay of history. On this bench the gains are not replay: fresh-run
  skill moves with in-sample skill (+10.0 / +15.2 fresh vs +10.5 / +15.2 in-sample). Still, the current
  judge can be fooled this way, so combine it with the piece-proof judge.

## Verdict
Needs a combination. The generalised quiet fit is the largest single gain on this bench: +10.5 @20,
+15.2 @100 and 4 more runs meeting the goal, about the same on fresh runs. But it moves 26 runs by more than
2 points, and 7 of them go down: eras default, webshop default, cloud-credits long, ev-fleet default,
sawmill long @100, recycling default and hospital default. The judge decides between a row's biased fit and
its quiet fit; no test of the mechanism does. Adopt it behind the piece-proof judge and the
behaviour-consistency gate, then measure again. The strict brief version is safe but small.

## Open ideas
- Pick quiet steps by something other than the residual itself, to avoid selecting on the noise: for
  example, a level falling for m steps in a row, or an inflow profile from periodic-inflows.
- Per-era quiet fits: in a split-era candidate, choose quiet steps within each configuration.
- Recession for co-flow rows (clinic-doses doses: deliveries one day in seven; see starved-coflows).
- Run the quiet fit before conservation, so conservation compares the receivers with an unbiased drain.

## Sources
Kirchner (2009) WRR 45(2):W02429; Brutsaert and Nieber (1977) WRR 13(3):637-643 (recession analysis);
literature report [compartmental analogues](literature/compartmental-analogues.md), summary item 8;
[change-price](change-price.md) open ideas (estimate the levels beside cheap pieces and never refit them).

## The declared boundary (2026-10-20)

Outside flows only where the case declares them (docs/research/declared-boundary.md; CLAUDE.md invariant
2). `recession/boundary.py` is a copy of `matrix/boundary.py` at 723f72c (HIDDEN_PRICE 0). Each main-line
candidate is refitted inside the boundary (`earned.refit`: an outside term only where an estimated one may
be, a measured input only where a measured one may be, sources with no estimated outflow tied), so
recession drains are only tried on rows the boundary lets have an outside inflow; every candidate (with and
without recession drains) is guarded before the judge. The answer: guard and anti-correlated pairs made
moves (declared), or each outside flow priced as a boundary claim at 2 log T (not declared). The copy's one
change: `alternatives()` never pairs an inflow into B with B's own outflow (the reference's self-move).

Results: in progress (paired before/after on Kubernetes 300-305 and 40 stored Tests cells, CPU pool).
