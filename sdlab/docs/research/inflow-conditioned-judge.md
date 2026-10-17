# Inflow-conditioned held-out judge and era hold-out

**Status:** idea (not started)

## Why
The [held-out-judge](held-out-judge.md) experiment failed because a held-out block must forecast an
outside inflow that changes unannounced, so it measured inflow extrapolation, not dynamics. The
methodology literature explains exactly this pitfall; the SD field proposes eras as natural experiments.
A held-out score that conditions on a coarse inflow asks the bench's question. Low priority: the in-data
judge already picks the best candidate in 31 of 42 v1 runs. Playbook M12.

## How it could be tried
- On a held-out block: freeze the candidate's rate coefficients, re-estimate only one inflow value per
  stock and block, simulate H steps from measured states.
- With announced eras: fit on eras 1..k, predict era k+1 re-estimating only era-specific numbers.
- Measure on I1's judge-rank column ([bench-instrumentation](bench-instrumentation.md)).
- Mechanism test: the held-out-judge trap is ranked worst; constant-inflow candidates are not favoured
  as with the old held-out judge.

## Sources
Dawid (1984) JRSS A 147(2):278-292, doi:10.2307/2981683; Racine (2000) J. Econometrics 99(1):39-61;
Bergmeir, Hyndman and Koo (2018) CSDA 120:70-83, doi:10.1016/j.csda.2017.11.003; Forrester and Senge
(1980) TIMS Studies in the Management Sciences 14; Oreskes, Shrader-Frechette and Belitz (1994) Science
263(5147):641-646.
