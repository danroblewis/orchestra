# Floors and caps as censoring, offered only where the data reach them

**Status:** idea (not started)

## Why
The [floors-and-caps](floors-and-caps.md) experiment showed hinges work in isolation but imitate
unannounced seasons on the bench (sd-manufacturing and sd-fishery losses). Hybrid-system identification,
inventory theory (sales capped by stock are censored demand) and hydrology (thresholds are visible only
when they bind) suggest: censor steps where a floor or cap binds, and offer a threshold term only for
stocks whose observed range actually reaches it. Playbook M9.

## How it could be tried
- Steps where a source emptied: drop them from its outflows' fit, or treat them as censored (Tobit:
  "rate >= what it held").
- Offer a hinge for stock X only if X spends at least a few percent of steps beyond the threshold the
  row's linear fit implies; never on a row with inflow pieces unless the pieces fail the
  pieces-track-levels guard of [inflow-innovations](inflow-innovations.md).
- Diagnose in the order inputs, floors, links, delays, effects.
- Mechanism tests: the floors test (max(0, 0.2a - 30), shut half the time) recovered; control: a
  seasonal inflow with no floor gets no hinge.

## Sources
Tobin (1958) Econometrica 26(1):24-36, doi:10.2307/1907382; Paoletti et al. (2007) Eur. J. Control
13(2-3):242-260; Lariviere and Porteus (1999) Manage. Sci. 45(3):346-363, doi:10.1287/mnsc.45.3.346;
Jakeman and Hornberger (1993) WRR 29(8):2637-2649; Sterman (2000) Business Dynamics, ch. 13.
