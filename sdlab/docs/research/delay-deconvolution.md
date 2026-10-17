# Hidden stocks by constrained deconvolution and order counting

**Status:** idea (not started)

## Why
The [hidden-stocks](hidden-stocks.md) experiment (delayed copies on a delay grid) found five true hidden
stocks but missed others (kanban defects, supply trucks, support-tiers, manufacturing, saas) and
accepted a false one in sd-population. Five literature traditions treat a hidden stock as a delay whose
kernel can be estimated directly: nonnegative, summing to at most 1 (conservation); its mean is the
residence time, mean²/variance the Erlang order, and only the mean is reliably identified. A Hankel
order count says how many hidden states to look for at all. Playbook M7.

## How it could be tried
- Per group, a long VARX and the singular values of its impulse-response Hankel matrix: the number of
  states beyond the measured stocks is the hidden-stock budget (a lower bound: a positive realisation
  may need more).
- Per candidate pair (from prewhitened residual cross-correlation), NNLS of B's residual on lagged
  copies of A's outflow with a decaying-kernel (TC) penalty and sum <= 1; fit exp / Erlang / pipe to
  the kernel; offer one "delay object" (T, n) with its content by Little's law.
- Acceptance behind the behaviour gate ([behaviour-consistency](behaviour-consistency.md)) and the
  fresh-run grade; the count behind [complexity-budget](complexity-budget.md)'s `max_hidden`.
- Mechanism test: A -> H -> B, Erlang-3, mean 12: kernel mean within 10%, order 2-4; exp delay: order
  about 1; control without a hidden stock: no extra state, no delay object.

## Sources
Goldstein et al. (2009) PNAS 106(51):21825-21829, doi:10.1073/pnas.0902958106; Savic et al. (2007)
J. Pharmacokinet. Pharmacodyn. 34(5):711-726, doi:10.1007/s10928-007-9066-0; Hurtado and Kirosingh
(2019) J. Math. Biol. 79(5):1831-1883; Pillonetto and De Nicolao (2010) Automatica 46(1):81-93; Ho and
Kalman (1966) Regelungstechnik 14:545-548; Van Overschee and De Moor (1994) Automatica 30(1):75-93;
Bauer (2001) Automatica 37(10):1561-1573; Benvenuti and Farina (2004) IEEE TAC 49(5):651-664; Hamilton
(1980) in Randers (ed.), Elements of the System Dynamics Method, 162-181; Little (1961) Oper. Res.
9(3):383-387; Daniels and Nemenman (2015) Nat. Commun. 6:8133.
