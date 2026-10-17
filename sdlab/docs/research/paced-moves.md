# Moves paced by a third stock: reading the matrix as stoichiometry times rates

**Status:** idea (not started)

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

## Sources
Hoffmann, Fröhner and Noé (2019) J. Chem. Phys. 150:025101 (Reactive SINDy); Craciun and Pantea (2008)
J. Math. Chem. 44(1):244-259; Szederkényi, Banga and Alonso (2011) BMC Syst. Biol. 5:177; Sterman (2000)
Business Dynamics, ch. 13 (rates paced by resources, gap formulations).
