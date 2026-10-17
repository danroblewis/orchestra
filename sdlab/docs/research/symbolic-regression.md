# Symbolic regression for rate equations and effect curves

**Status:** running (wave 2, benchmark v2)

## Hypothesis
After the linear fit, a symbolic search over what is left (rate term x f(level of C), f from a
grammar: products, ratios, powers, exp, log, saturating forms, clamps) finds effects; a found f becomes
an SD Lab effect (a table sampled from f, or linear). Constrained SD grammar vs unconstrained SR
(gplearn; PySR if Julia installs cleanly).

Branch `exp/symbolic-regression`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
