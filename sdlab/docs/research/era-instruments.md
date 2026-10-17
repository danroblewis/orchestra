# Announced eras as instruments for drains biased by inflow pieces

**Status:** idea (not started)

## Why
The playbook (conflict C3) traces drain bias to inflow pieces that compete with the drain. Its
recommended cure includes instruments: variables that move a level but not the row's residual.

An announced era switch changes one coefficient upstream (a nurse joins, a cook starts) and shifts a
downstream stock's level for reasons unrelated to that stock's own unannounced inflow. So era
indicators x upstream levels, and levels lagged by 2 or more steps, are candidate instruments for the
downstream row.

The matrix method's robust IV on second differences failed because its instruments were weak (the
pipeline inbox drain came out at 29.0). Era-switch instruments are strong where eras exist, and a
first-stage F test says so before they are used.

## How it could be tried
- Strategy `era_iv`. For a row with changing inflow, run 2SLS with instruments [era indicators x
  upstream levels; levels at t-2 to t-5]. Use it only when the first-stage F is above 10.
- If the IV drain differs from the drain fitted with pieces by more than 2 SE, re-measure the pieces
  with the IV drain fixed, and enter the result as a candidate.
- Mechanism test: a -> b, where an announced era switches a's drain (0.2 -> 0.4) and b has an
  unannounced changing outside inflow plus a drain of 0.25. Baseline: b's drain biased by more than
  0.04. IV: within 0.02. Control: no eras, so no strong instrument and no change.
- Targets: era examples whose rows have pieces: sd-restaurant, sd-clinic-doses, sd-ci,
  sd-support-tiers, sd-sawmill, sd-learning-curve, sd-eras long, sd-university, sd-housing.

## Sources
Söderström and Stoica (1983) Instrumental Variable Methods for System Identification, Springer LNCIS
57; Young (2011) Recursive Estimation and Time-Series Analysis, 2nd ed., Springer (refined IV); Staiger
and Stock (1997) Econometrica 65(3):557-586 (weak instruments); literature report
[system identification](literature/system-identification.md) section 5.
