# Closed subsystems: totals that never change

**Status:** idea (not started)

## Why
In sd-fishery the boats in port and at sea always add up to 40, exactly. In sd-ev-fleet the measured
vans add up to 40 minus the hidden returning ones. Such invariants make the levels collinear with the
constant. The one-step regression is then singular: the stepwise search picks any of the equivalent
columns, and the reading produces outside flows that cancel. On sd-fishery default it finds
"None -> in_port 3.873" and "at_sea -> None 3.873", "None -> adults, link from in_port 3.346" for a
catch that is paced by at_sea, and "landed drains faster when in_port is high 2.79".

An exact invariant is free structural information. Nothing crosses the subsystem's boundary, and every
expression inside it has an equivalent in the other members' levels, so the representation should be
chosen by a declared preference, not by rounding.

## How it could be tried
- Strategy `invariants`. Find exact linear invariants among same-unit measured stocks (the null space
  of their step changes, by SVD per unit). Near-invariants with a hidden member come from Johansen
  cointegration.
- For a closed group: no outside inflow or outflow on its members, and one member's level removed from
  every row's allowed columns.
- After fitting, rewrite terms on the removed level through the invariant (A = total - B) into the
  preferred form: the flow's source level first, then its destination's.
- Mechanism test: in_port <-> at_sea (launch 0.3 x in_port, return 0.25 x at_sea), with adults ->
  landed at 4 x at_sea and adults having an inflow and a drain. Baseline: cancelling outside flows or a
  link from in_port. Strategy: none of those, catch read on at_sea, parts +2, skill at least the
  baseline's. Control: a group whose total changes (an outside inflow) gets no invariant.
- Targets: sd-fishery, sd-ev-fleet, and closed loops in generated models.

## Sources
Johansen (1988) J. Econ. Dyn. Control 12(2-3):231-254; Godfrey and Chapman (1990) Math. Comput. Simul.
32(3):273-295; literature report [signals and time series](literature/signals-and-time-series.md)
summary item 9 (conservation as cointegrating vectors); [identifiability](identifiability.md).
