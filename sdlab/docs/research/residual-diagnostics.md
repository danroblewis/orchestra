# A diagnose-and-expand loop driven by residual signatures

**Status:** idea (not started)

## Why
The headroom is in models no candidate represents. System identification, the SD field, time-series
analysis and the methodology literature all say the same: criticise a fitted model row by row, and let
the shape of what is left name the missing structure. Today humans do this between experiments.
Playbook M3, with I3 (the battery measured as a tool).

## How it could be tried
- `diagnose(row)` returns typed proposals: autocorrelated residuals -> hidden stock / delay; residual
  following another stock's lagged level -> link or delayed flow; following level(A) x level(C) ->
  effect; one-sided near zero -> floor or cap; CUSUM break -> input change or era-specific number;
  two rows mirroring at lag 0 -> move or co-flow; variance far above the Poisson expectation -> missing
  structure (at or below it: stop); Theil bias / unequal variation in the multi-step error -> constant
  term / gain or effect.
- Try proposals one at a time in the order inputs, floors, links, delays, effects; accept by penalised
  multi-step improvement; stop when clean or nothing pays.
- I3: on the 31 examples and generated models, score each diagnostic's precision and recall for the
  component the found model lacks (the truth used to evaluate the tool, not the engine).
- Mechanism test: three synthetic models each missing one component (hidden stock, effect, floor): the
  right proposal ranks first and is added; control: a correct model gets no proposal.

## Sources
Ljung (1999) System Identification, 2nd ed., Prentice Hall; Ljung and Box (1978) Biometrika
65(2):297-303; Billings and Voon (1986) Int. J. Control 44(1):235-244; Kristensen, Madsen and Jørgensen
(2004) Comput. Chem. Eng. 28(8):1431-1449, doi:10.1016/j.compchemeng.2003.10.003; Box (1980) JRSS A
143(4):383-430; Gelman et al. (2020) Bayesian Workflow, arXiv:2011.01808; Sterman (1984) Dynamica
10(2):51-66; Schoukens and Ljung (2019) IEEE Control Systems Magazine 39(6):28-99.
