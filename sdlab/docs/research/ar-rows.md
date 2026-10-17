# Rows fitted with their own noise model (AR residuals)

**Status:** idea (not started)

## Why
Unmodelled hidden stocks and smoothed inputs leave autocorrelated residuals in a row. In a closed loop,
least squares is then biased, because the lagged level correlates with past noise. In closed-loop
identification, direct prediction-error methods are consistent only when the noise model is right.

Feasible GLS with an AR(p) noise model (Cochrane-Orcutt), or an ARMAX row, removes this part of the
drain bias. It does not change how changes are detected ([inflow-innovations](inflow-innovations.md))
or how rows are weighted ([count-likelihoods](count-likelihoods.md)). The fitted AR coefficient is also
a diagnostic: a large one flags a hidden stock or delay for [mass-balance-hidden](mass-balance-hidden.md)
or [delay-deconvolution](delay-deconvolution.md).

## How it could be tried
- An option `ar_rows` in a strategy. After each pass, fit AR(p) (p by BIC, at most 3) to the row's
  residual within pieces.
- Filter y, the level columns and the piece indicators with the AR filter, refit the coefficients, and
  iterate twice.
- Report each row's AR coefficients.
- Mechanism test: a -> h -> b with h hidden (0.2 and 0.1) and b draining 0.25. The baseline biases b's
  drain; with AR rows it comes within 0.02. Control: a model with no hidden stocks has AR near 0 and is
  unchanged.
- Targets: receiver rows of the hidden-stock examples (sd-cloud-credits, sd-sawmill, sd-kanban,
  sd-learning-curve), and sd-services (biased frontend drain).

## Sources
Cochrane and Orcutt (1949) JASA 44(245):32-61; Forssell and Ljung (1999) Automatica 35(7):1215-1241;
Söderström and Stoica (1989) System Identification, Prentice Hall; Ljung (1999) System Identification,
2nd ed., ch. 7.
