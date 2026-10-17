# Partial-model simulation per row

**Status:** idea (not started)

## Why
The SD field's calibration practice tests each piece of a model by driving it with the measured values
of everything else and simulating it alone (partial-model testing); a piece that cannot fit with
plausible numbers has the wrong structure. Our rows are fitted one step ahead and judged only as a
whole model, so a row that runs off is found only in aggregate. Playbook M8.

## How it could be tried
- For each row of each candidate, simulate that stock H steps from ~80 starts with the other stocks'
  measured levels and its own inflow pieces fed in; a row failing the partial test gets its
  alternatives (other variants' rows, or the bounded refit of
  [behaviour-consistency](behaviour-consistency.md)) before the whole-model judge.
- The partial test is a flag, not a verdict: a row stable only inside its loop is decided by the
  whole-model judge.
- Mechanism test: a trap row (positive own-coefficient plus constant inflow) fails, the true row
  passes; control: a correct row in a loop stable only when closed is not rejected.

## Sources
Homer (2012) SDR 28(3):281-294, doi:10.1002/sdr.1478 (the 1983 paper); Oliva (2003) EJOR 151(3):552-568,
doi:10.1016/S0377-2217(02)00622-7; Graham (1980) in Randers (ed.), Elements of the System Dynamics
Method, 143-161.
