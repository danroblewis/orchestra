# Do no harm: falling back to persistence where the model is known to be worse

**Status:** idea (not started)

## Why
In some runs every candidate predicts the measured data worse than assuming nothing changes (judge
error above 1): sd-moderation (3.2 default, 6.6 long) and sd-fishery default (1.4). The model chosen is
known to be bad on the data before it is graded, and it grades -67% to -99% at skill@20. A model whose
offending rows are silenced cannot do worse than 0 on those stocks. "Silenced" means: no own-row terms
except moves whose other end is reliable, or every rate in the row scaled by lambda in [0, 1] chosen
by the judge.

This is shrinkage towards the null forecast, which forecasting has long used when a model is
misspecified. It is a stopgap with honest reporting ("these stocks are not explained"), not a
mechanism that makes runs meet the goal. It differs from [behaviour-consistency](behaviour-consistency.md),
which rejects runaway *candidates* before judging: this edits the chosen model after judging, per
stock, against the persistence baseline.

## How it could be tried
- Strategy `fallback`. After the judge, if the best error is above 1, or some stock's own error is,
  run the partial-model test per stock ([partial-model-simulation](partial-model-simulation.md)).
- For each failing stock, either remove its row's non-conserving terms, or scale the row by lambda
  chosen on a grid by the judge. Re-judge, and keep the change if the judge improves.
- Report the silenced stocks in the result, so the page can say what is not explained.
- Mechanism test: a model with an unrepresentable row (a link coefficient that switches day and night,
  unannounced). Baseline: judge above 1 and that stock's skill below 0. Strategy: judge at most 1 and
  that stock's skill at least 0. Control: a correct model is unchanged.
- Targets: sd-moderation, sd-fishery default, sd-restaurant @100.

## Sources
Bates and Granger (1969) Oper. Res. Q. 20(4):451-468 (combining forecasts); Box (1976) JASA
71(356):791-799; Homer (2012) SDR 28(3):281-294 (partial-model testing).
