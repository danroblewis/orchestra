# Behaviour-mode fingerprints as structure priors

**Status:** idea (not started)

## Why
In SD, behaviour is the fingerprint of structure: oscillation needs a negative loop through at least two
stocks (or a delay), S-shaped growth needs a nonlinear effect, overshoot-and-collapse needs an eroding
resource. Classifying each measured stock's mode is cheap and says where a second state or an effect
must exist. One tradition only (the SD field), hence a low rank. Playbook M13.

## How it could be tried
- Per stock and era: fit growth, first-order approach, logistic and damped-oscillation shapes to
  detrended levels, choose by BIC.
- Required features become cheaper columns ("oscillates" -> second state or closing loop; "S-shape" ->
  effect); contradicted features a penalty; never hard rules.
- Mechanism test: a supply-line oscillation where the prior moves the search to the second-state
  candidate; control: a first-order stock gets no prior.
- Targets: sd-supply, sd-orders, sd-fishery, sd-farm-soil, sd-learning-curve.

## Sources
Sterman (2000) Business Dynamics, McGraw-Hill, ch. 4; Kampmann and Oliva (2008) Syst. Res. Behav. Sci.
25(4):505-519; Yücel and Barlas (2011) SDR 27(2):195-215, doi:10.1002/sdr.457; Barlas (1989) EJOR
42(1):59-87.
