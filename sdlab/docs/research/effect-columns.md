# Effects as basis-expanded flow columns in the regression

**Status:** idea (not started)

## Why
An SD effect (flow = base rate x f(level of C / normal)) is a flow coefficient scheduled by a stock.
Expanded as columns level(A) x h_j(C) (a linear term, or 3-5 hat functions over C's range) it stays
linear in the parameters, so the existing stepwise BIC can choose it as a group. Discovery never
proposes an effect on benchmark v2, and the effect examples are read as links (v2.1 skill@20:
sd-sawmill -261%/-207%, sd-learning-curve default -72%, sd-emergency 5%/-47%). Five literature
traditions converge on this form. Playbook M5.

## How it could be tried
- After the first pass, for each found flow out of A (or a link driven by A), candidate schedulers
  C = A, B and same-group stocks whose product column correlates with the row's residual
  (Billings-Voon screen); add the group, accept by BIC and the judge.
- Constrain to SD shapes: f(normal) = 1, monotone, bounded; snap to SD Lab's linear-clamp or table
  effect. Try the four placements (stimulate or inhibit; inflow or outflow).
- Mechanism test: A -> B at 0.2 x A x clamp(C/100, 0, 1.5), C driven through its range by a schedule:
  table within 10% at the knots, skill@20 > 0.9; controls: no effect, and C nearly constant (f seen at
  one point only), get no group.
- Read the symbolic-regression and PySINDy results first (they touch effects).

## Sources
Schoukens and Tiels (2017) Automatica 85:272-292, doi:10.1016/j.automatica.2017.06.044; Billings and
Voon (1986) Int. J. Control 44(1):235-244; Ríos-Ocampo and Gary (2022) SDR 38(4):354-370,
doi:10.1002/sdr.1718; Dayneka, Garg and Jusko (1993) J. Pharmacokinet. Biopharm. 21(4):457-478,
doi:10.1007/BF01061691; Rackauckas et al. (2020) arXiv:2001.04385; Sterman (2000) Business Dynamics,
McGraw-Hill, ch. 13-14.
