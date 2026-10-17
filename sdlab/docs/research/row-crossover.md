# Assembling the model row by row from the candidates

**Status:** idea (not started)

## Why
identify() picks one whole candidate out of 16. Each candidate makes its choices globally: forward or
backward search, changing or constant inflows, trusting receivers or rows, eras or not. Different
stocks need different choices:
- sd-bakery default: the constant-inflows candidate grades 26.6% at skill@20 and the chosen
  changing-inflows candidate -1170%. The orders row should have no pieces; flour's should.
- sd-clinic-doses long: changing-inflow candidates grade -77% to -109%, the chosen one -347%.
- sd-pipeline default: the receiver's row holds the right move (0.32) while the source row, under
  constant inflows, has 0.11.

"Choose the inflow form per stock by behaviour" is an open idea of [change-price](change-price.md).
A greedy row swap reaches combinations no single candidate has, from candidates we already compute.
Wrapper feature selection and algorithm portfolios work the same way. Structure search (running) edits
flows; this recombines whole rows of the existing pool and needs no new generator.

## How it could be tried
- Strategy `row_crossover`: keep every variant's rows (coefficients per configuration, inflow pieces).
- Assemble a model from a choice of row per stock, re-run `conserve` and `read_flows` on the mixture,
  and judge it.
- Start from the judge's pick. Visit stocks in order of their partial-model error (each row simulated
  alone with the others measured; [partial-model-simulation](partial-model-simulation.md)), and try
  every other variant's row for that stock.
- Keep a swap only if the whole-model judge improves by more than a margin (2% relative). Two sweeps.
- Mechanism test: two independent subsystems in one model. One is an inbox whose intake changes every
  30 steps (needs changing inflows). The other is a slowly draining stock with a constant inflow, where
  pieces absorb the drain (needs constant). Baseline: the best whole candidate is right on one
  subsystem only. Strategy: rows from both, and skill@20 above either candidate's. Control: when one
  candidate is right everywhere, no swap.
- Run it behind the piece-proof judge (wave 3): more choices give flexible rows more chances to fool
  the in-data judge.
- Targets: sd-bakery default, sd-clinic-doses long, sd-pipeline default, sd-emergency default,
  sd-learning-curve default.

## Sources
Kohavi and John (1997) Artif. Intell. 97(1-2):273-324 (wrapper selection); Rice (1976) Advances in
Computers 15:65-118; Gomes and Selman (2001) Artif. Intell. 126(1-2):43-62 (portfolios);
[held-out-judge](held-out-judge.md) (oracle 78.3% vs 70.8% on v1); failure analysis in
[IDEAS-WAVE4](IDEAS-WAVE4.md).
