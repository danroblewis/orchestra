# Judge noise: tied candidates told apart by simplicity

**Status:** idea (not started)

## Why
The judge's errors are often within its own sampling noise, while the tied candidates' grades differ
widely:
- sd-emergency default: the chosen candidate scores 0.396 and grades 5% at skill@20; the per-era
  candidates score 0.401 and grade 73-75%;
- sd-clinic-doses long: 0.526 grades -347%, 0.530 grades -109%, 0.536 grades -77%;
- sd-kanban default: 0.412 grades 61%, 0.416 grades 65%.

The judge averages about 80 starts, and a block bootstrap over those starts gives its standard error.
Breiman's one-standard-error rule picks the simplest model within one SE of the best, the standard guard
against chance wins. This is not a new judge (the piece-proof judge is running). It is a rule for which
candidate to take when the judge cannot separate them.

## How it could be tried
- Strategy `judge_ties`. `simulate.behaviour_error` also returns each start's error; the SE comes from
  a moving-block bootstrap over starts (blocks of 5).
- Candidates within 1 SE of the best form the tie set. Within it, pick fewest inflow pieces, then
  fewest flows, then fewest era columns.
- Variant: re-judge the tie set with 160 starts.
- Gate the pick with the behaviour gate: constant-inflow candidates have the fewest pieces and can run
  away.
- Mechanism test: on the held-out-judge trap, the trap edges out the true candidate by less than 1 SE,
  and the strategy picks the true one. Control: when the true candidate is clearly better (more than
  3 SE), the pick does not change.
- Targets: sd-emergency default, sd-clinic-doses long, sd-kanban default, sd-webshop-stock.

## Sources
Breiman, Friedman, Olshen and Stone (1984) Classification and Regression Trees, Wadsworth (one-SE
rule); Hastie, Tibshirani and Friedman (2009) The Elements of Statistical Learning, 2nd ed., section
7.10; Künsch (1989) Ann. Stat. 17(3):1217-1241 (block bootstrap); Meinshausen and Bühlmann (2010) JRSS B
72(4):417-473.
