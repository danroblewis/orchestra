# Moves paced by a third stock: reading the matrix as stoichiometry times rates

**Status:** done (wave 4, benchmark v2.1)  
**Verdict:** paced moves: reject as they stand; gap inflows: needs a combination (behaviour gate, piece-proof judge)

## Why
In 9 truths a move's rate reads another stock, and in more of them an inflow has a negative term:
- support-tiers: tier2 -> resolved at 0.5 x agents;
- moderation: flagged -> published, removed and appeals at 0.75, 0.6 and 0.15 x moderators;
- fishery: adults -> landed at 4 x at_sea;
- ev-fleet: dispatch, and plug, a gap on the *destination*;
- also housing (contract, buy), restaurant (seat), supply (ship) and university (admit);
- webshop: reorder into on_order is a gap on shelf.

`flows.read_flows` can only make a move proportional to its source. A negative cross term becomes
"X drains faster when C is high" (an outflow to outside), and the matching positive term in the
receiver becomes a link. On v2.1 runs:
- sd-moderation: "flagged drains faster when moderators is high 1.387" and "None -> removed, link from
  moderators 0.676";
- sd-support-tiers: "tier2 drains faster when tier2_agents is high 0.436";
- sd-webshop-stock: "on_order drains faster when shelf is high 0.187".

This reading behaves differently from the truth whenever the source empties: the link keeps filling the
receiver. It also differs when a floor binds: an outflow is capped by its source, while an inflow's sum
is floored at 0. And the two halves are estimated separately, as two numbers with no conservation.
Reaction-network inference writes the change matrix as stoichiometry x rate laws; our rows are exactly
that product. This is the concrete version of the [reaction-networks](reaction-networks.md) stub.

## How it could be tried
- Strategy `paced_moves`, reading module `discovery/stoich.py`; `flows.py` on the main line is
  unchanged.
- Per driver column C, match a negative entry in one row with a positive entry of the same unit in
  another row (|k_A + k_B| within 2 SE). Form a move A -> B whose rate is a linear form over every
  matched column, a constant included, so that goal-gap moves are covered.
- Negative cross terms together with a positive outside constant become one linear inflow (a gap on
  another stock), not an outflow.
- Refit the matched rows jointly, with the shared coefficient as an equality constraint.
- Put both readings, current and paced, before the judge. [shared-noise](shared-noise.md) can confirm a
  move by cov(dA, dB) = -k x C.
- Mechanism test: tier2 (inflow 10) -> resolved at 0.5 x agents, with agents varying 10-30 and tier2
  running low at times. Baseline: outflow plus link. Strategy: one move, k within 0.03, parts +1, and
  skill@20 at least baseline + 0.1 on runs where tier2 empties. A gap variant: on_order inflow
  max(0, 110 - 0.2 x shelf) with shelf above 550 a third of the time. Control: a real outflow of A
  paced by C, plus a link from C into B with a different coefficient, is not merged.
- Targets: sd-support-tiers, sd-moderation, sd-fishery, sd-ev-fleet, sd-housing, sd-restaurant,
  sd-supply, sd-university, sd-webshop-stock, sd-manufacturing.

## What was done
Branch `exp/paced-moves`, commit `1474672` (worktree `.claude/worktrees/agent-a2ba0a67314fb21fb`).
Strategy `paced_moves` (`sdlab/discovery/strategies/paced_moves.py`), reading module
`sdlab/discovery/stoich.py`; `matrix.identify_one` gains `keep_fit` (off by default; `matrix` gives zero
deltas on sd-saas, sd-eras, sd-pipeline default). For every main-line candidate (`identify.VARIANTS`):
- **match**: a negative entry in A for driver C and positive entries for C in same-unit rows B1..B3;
  each row refitted on the steps where A held at least twice what the move takes, with and without
  A's own columns (where A ran low, the cut-off move looks like a drain of A in both rows); matched if
  the numbers sum to zero within 2 SE;
- **joint refit**: the matched rows' refitted numbers projected so that the entries sum to zero (GLS,
  rows independent), the rows' inflow pieces re-measured on the same steps;
- **readings**: paced (one linear move A -> B, with A's own proportional move folded in), destination
  (also a reverse "move" B -> A folded in as -k x B), then gap inflows offered one (stock, driver) pair
  at a time on the best reading, each kept if it lowers the judged error by 10%
  (`gap_margin`); a gap inflow is `byTime` linear rates `c(piece) - k x C`, floored at 0.
- Options: `paced_readings`, `match_z`, `match_room`, `paced_discount` (default 0), `gap_margin`.

## Mechanism test
`tests/test_strategy_paced_moves.py` (4 tests, all pass, ~7 s):
| case | `matrix` | `paced_moves` |
|---|---|---|
| tier2 (7 a step, bursts of 18) -> resolved at 0.5 x agents (agents ~20, fast turnover); tier2 low ~40% of steps | tier2 drains 0.24 x agents + a link 0.31 into resolved (seeds 1-8: 0.20-0.31; a drain of tier2 0.10 imitates the cut-off); skill@20 0.51 | one move tier2 -> resolved 0.465 x agents (seeds 1-8: 0.37-0.53; within 0.05, not the brief's 0.03); skill@20 0.94 (seeds 1-8: mean 0.65 -> 0.84, 5 up, 2 down, 1 unmatched) |
| gap: on_order inflow max(0, 110 - 0.2 x shelf), shelf above 550 28% of steps | "on_order drains faster when shelf is high" 0.21 + constant inflow; skill@20 -117% | one inflow c - 0.206 x shelf; skill@20 98%, @100 95% |
| control: tier2 drains 0.5 x agents to outside, link 0.25 x agents into resolved | - | not merged; identical to `matrix` |
Parts are unchanged on the tier test (the main line already finds a small tier2 -> resolved move).
Before the masked refit, the two halves never matched on this model (0.37 vs 0.50 on another design);
before the masked re-measure, the judge rated every paced reading worse (the cut-off steps inflated
tier2's inflow pieces).

## Results (baseline v2.1: 29.6% / 29.3%, fresh 28.9% / 29.7%, 12 of 62 meet the goal, CPU 586 s)
| attempt | skill@20 | skill@100 | fresh @20 / @100 | goal | CPU |
|---|---|---|---|---|---|
| v1: SE match on raw rows, all gaps of a stock at once, margin 0.1 | 32.9% | 34.4% | 31.9% / 34.5% | 14 | 1010 s |
| v2: masked refit without the source's drain, masked re-measure, paced discount 0.15 | 31.6% | 31.2% | 31.1% / 31.2% | 14 | 958 s |
| v3: discount 0 | 32.7% | 34.0% | 31.7% / 34.1% | 14 | 1287 s |
| v4: gap inflows per (stock, driver) pair (default) | 34.0% | 32.7% | 33.0% / 32.9% | 14 | 1137 s |
| v4 ablation: gap inflows only | **34.9%** | **34.8%** | **34.0% / 35.0%** | 14 | 902 s |

Runs moving by more than 2 points (v4, skill@20, in-sample / fresh):
| run | v2.1 | v4 | reading |
|---|---|---|---|
| sd-services default | 7% / 18% | 94% / 95% (meets goal) | gap inflow tokens<api (truth: a co-flow) |
| sd-services long | 35% / 38% | 96% / 96% (meets goal) | tokens<api |
| sd-fishery default | 3% / -4% (@100 -102%) | 46% / 41% (@100 30%) | landed<in_port |
| sd-moderation long | -99% / -94% | 12% / 9% | screening<flagged |
| sd-ev-fleet long | 18% / -3% | 23% / 1% | queue<ready |
| sd-moderation default | -67% / -74% | -372% / -411% (@100 -172% -> -58%) | screening<published (rescues a runaway candidate in-sample) |
| sd-recycling default | 72% / 72% | 66% / 66% | paced |
The ablation also lifts sd-fishery long -19% -> 35% (at_sea<fuel) and avoids recycling's drop.
v1 (gaps of a stock read together) also lifted sd-ev-fleet default 32% -> 43% (queue with four drivers).

## Verdict
- **Paced moves**: the mechanism works on the synthetic model once the cut-off steps are handled, but
  on the examples the rows rarely match (moderation's 1.39 x moderators against 0.68 in removed and
  nothing in published or appeals; support-tiers' resolved row absorbs agents into pieces), and where
  they match the judge seldom prefers them; net cost on the bench (v4 vs ablation: -0.9 / -2.1).
  Reject as they stand.
- **Gap inflows**: +5.3 / +5.5 points (fresh +5.1 / +5.3), two runs newly meet the goal. Mostly as
  stand-ins: services' tokens and fishery's landed are not gaps in the truth, but an inflow that stops
  behaves better than an outflow that drains. Same number of free numbers as the reading it replaces,
  but **the judge can be fooled**: per-variant, a gap reading can rescue a runaway candidate in-sample
  (moderation default: a variant at -30 graded becomes -3.7 and wins the judge over the main line's
  -0.67). Needs a combination with the behaviour-consistency gate / piece-proof judge before adopting;
  usable as an option (`paced_readings=("gaps",)`).

## Open ideas
- Match the receivers' side when a row absorbed the driver into pieces (fixed +k in the receiver,
  pieces re-found, BIC within log T: the conservation test extended to cross columns).
- Several receivers with partial matches (moderation: one source, three receivers paced by the same
  stock) need a joint fit over the unit group, not pairwise SE tests.
- Shared-noise covariance (cov(dA, dB) = -move variance) as a second match test.
- Gap inflows as co-flow stand-ins: try them beside starved-coflows (`uses`), which is the true form
  for services and the co-flow examples.
- Judge ties: paced readings differ from the usual one only where sources empty; the judge's
  in-sample differences there are a few percent (a held-out or inflow-conditioned judge may see it).

## Sources
Hoffmann, Fröhner and Noé (2019) J. Chem. Phys. 150:025101 (Reactive SINDy); Craciun and Pantea (2008)
J. Math. Chem. 44(1):244-259; Szederkényi, Banga and Alonso (2011) BMC Syst. Biol. 5:177; Sterman (2000)
Business Dynamics, ch. 13 (rates paced by resources, gap formulations).
