# Injections as instruments for rows confounded by unannounced inflows

**Status:** idea (not started)

## Why
In causal terms, an unannounced outside inflow that lasts many steps is a latent confounder. It
raises a stock's level, which is a regressor in the row, and it is also part of the row's
unexplained change. So the one-step fit of the drain is biased: the "drain biased by inflow pieces"
problem (playbook conflict C3, [change-price](change-price.md), [recession-drains](recession-drains.md)).
On sd-pipeline default the inbox drains 0.11 against a true 0.3.

The cure for confounding is an instrument: a variable that moves the regressor but is independent of
the confounder. [era-instruments](era-instruments.md) proposes era switches. Announced injections are
better instruments. Their timing and amount are chosen by us at random, so they are independent of
every unannounced inflow by construction (Stock and Watson 2018's external instruments). They are
strong where they are big against the counting noise. And they touch no structural equation, so the
exclusion restriction holds once the known injection is subtracted from the change, as `matrix.py`
already does.

The main line currently uses injections only as known changes (`prev + inj`, `dy - inj`). Least
squares then mixes the clean variation the injections create with the confounded variation. 2SLS uses
only the clean part. Anchor regression (Rothenhäusler et al. 2021) gives a tunable middle ground.

## How it could be tried
- Needs the bench option `--probes K` (see [injection-response-judge](injection-response-judge.md)).
- Strategy `injection_iv`. For each row with pieces or a constant inflow:
  - Instruments: the injection amounts into the row's own stock and into the stocks feeding it, at
    lags 1..k (k = 5), plus the row's own injection response, i.e. the amount decayed by the current
    drain estimate.
  - First stage: regress each chosen level on the instruments. Use IV only if the first-stage F is
    above 10.
  - Second stage: 2SLS of the row's change on the chosen levels and the piece indicators. Variant:
    anchor regression with γ in {1, 5, 25}, chosen by the behaviour judge.
  - If the IV drain differs from the least-squares drain by more than 2 SE, re-measure the pieces
    with the IV drain fixed, and enter the result as a candidate.
- Mechanism test (`tests/test_strategy_injection_iv.py`): a -> b at 0.2; b drains at 0.3; b also
  has an unannounced outside inflow that changes every 20-60 steps as a random walk of levels.
  1000 steps, counting noise, 10 probes into b and 10 into a.
  - Baseline (main line with injections subtracted): b's drain off by more than 0.05.
  - IV: b's drain within 0.02.
  - Controls: no probes gives a first-stage F below 10, so the result is identical to the main line;
    a constant inflow leaves IV and least squares within 1 SE.
- Bench: `--probes 8`; targets are rows with pieces (sd-pipeline, sd-orders, sd-supply, sd-housing,
  sd-restaurant, sd-clinic-doses). Report the drain error per row from the instrumentation, as well as
  skill.

## Sources
- Literature report [causal inference](literature/causal-inference.md), sections 1.2, 1.6, 3.4 and 5 (idea 2).
- Stock, Watson (2018). Identification and estimation of dynamic causal effects in macroeconomics using external instruments. Economic Journal 128(610):917-948. doi:10.1111/ecoj.12593
- Rothenhäusler, Meinshausen, Bühlmann, Peters (2021). Anchor regression: heterogeneous data meet causality. JRSS B 83(2):215-246. doi:10.1111/rssb.12398
- Pearl (2009). Causality, 2nd ed. Cambridge University Press (confounding, instruments).
- Söderström, Stoica (1983). Instrumental Variable Methods for System Identification. Springer LNCIS 57 (via [era-instruments](era-instruments.md)).
