# Signal analysis and time-series statistics for finding structure

Literature research note, 2026-10-17. One part of a chain: this part covers **signal analysis and
time-series statistics**: how to find the components of a signal, and how to tell which series
are related, in which direction, with what delay. A later note combines all parts.

Context: SD Lab's discovery (see [DISCOVERY.md](../../DISCOVERY.md), [DISCOVERY-GOAL.md](../../DISCOVERY-GOAL.md))
gets measured stock levels at discrete steps, with counting (Poisson) noise, conservation between
stocks, floors at 0 and caps, piecewise-constant unannounced outside inflows, announced eras,
unmeasured (hidden) stocks acting as delays, feedback loops that settle near equilibrium, and
daily/weekly/seasonal schedules. It finds flows by sparse weighted least squares on windowed
changes, plus a PELT step for outside-inflow pieces, a lagged-correlation screen for hidden
stocks and a correlation-based split into groups. Earlier surveys
([SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md), [tools-survey](../tools-survey.md))
covered tools, SINDy, causal discovery and reaction networks; this note does not repeat them.

Citations were taken from the literature as I know it and spot-checked where marked.
DOIs are given where I am confident of them; otherwise a stable URL or the book.

---

## Summary: the ten most useful ideas, ranked

1. **Use the counting noise as a probe signal.** Every flow's amount per step is a random draw
   that leaves its source and arrives at its target. So the cross-covariance of two stocks'
   *prewhitened* per-step change residuals shows the structure directly. A move is a negative
   spike at lag 0. A flow through a hidden stock is a negative bump at positive lags whose shape
   *is* the delay kernel. A link is positive. A co-flow is a lag-0 spike at a fixed ratio. This
   works best exactly where other methods fail: in loops that have settled near equilibrium,
   where only the noise still moves. The formal versions are the prewhitened cross-correlation
   function (Box and Jenkins; Haugh 1976) and the linear inverse model / fluctuation-dissipation
   method (Penland and Sardeshmukh 1995; Ching and Tam 2017).
2. **Estimate a hidden stock's delay by constrained deconvolution, then read its moments.**
   Regress the target's unexplained inflow on lagged copies of the source's outflow with
   nonnegative weights that sum to at most 1 (conservation). The weights are the delay
   distribution h(τ). The mean of h is the hidden stock's residence time, so by Little's law
   rate × mean gives its size. mean²/variance gives the Erlang order: 1 is exponential, large is a
   pipe. Pharmacometrics (transit compartments, Savic et al. 2007) and epidemiology (deconvolving
   deaths into infections, Goldstein et al. 2009) do exactly this.
3. **Treat the daily and weekly schedules as free sinusoidal experiments.** Fit the harmonic at
   1/day to every stock. For a first-order stock with time constant T, the gain is
   1/√(1+(ωT)²) and the phase lag is atan(ωT). So the **phase lag between stocks orders them
   along a chain and measures their time constants**. Phase that keeps growing with frequency, with
   little loss of gain, points to a pipe delay. Cross-spectra and coherence generalise this to
   all frequencies. At low frequency, the group delay (−dφ/dω) equals the mean residence time
   between the two series, whatever the delay's shape.
4. **Group stocks by partial (conditional) dependence, not marginal correlation.** A shared
   schedule or flash sale correlates everything with everything. Partial coherence (Dahlhaus 2000)
   or a graphical lasso on prewhitened residuals (Jung et al. 2015) keeps only direct
   connections. That is a better first split of a 400-stock model than union-find on |r| > 0.3.
5. **Find outside-input changes with methods that expect autocorrelated, locally drifting
   residuals.** Use DeCAFS (Romano et al. 2022), an AR(1)-robust segmentation (Chakar et al.
   2017), or PELT run on a fitted model's *innovations*. Choose the penalty from the whole
   CROPS path (Haynes et al. 2017), not from one BIC price. This addresses the
   [change-price](../change-price.md) finding that internal dynamics masquerade as pieces.
6. **Classify spikes with the time-series outlier taxonomy.** The four textbook outlier types each
   have an SD meaning. An additive outlier is a measurement glitch. An innovational outlier is a
   batch arrival that then propagates. A level shift in the change series is a new inflow rate. A
   level shift in the level series is a one-off pulse. Joint detection with re-estimation (Chen
   and Liu 1993; Tsay 1988) separates them; robust filters (Hampel) are a cheap first pass.
7. **Use the linear-Gaussian state-space model as the reference framework.** The Kalman filter
   and RTS smoother give hidden stock levels and one-step likelihoods. EM (Shumway and Stoffer
   1982) fits the transfer matrix with structural zeros and equality constraints, as MARSS
   does. Auxiliary residuals (Harvey and Koopman 1992) tell breaks from outliers. Intervention
   analysis (Box and Tiao 1975) is the textbook treatment of announced eras.
8. **Count hidden states before searching for them.** The singular values of a block Hankel
   matrix of lagged levels (ERA, subspace identification N4SID, multichannel SSA) estimate the
   minimal state dimension. That dimension minus the number of measured stocks bounds how many
   hidden stages exist. Its linear-recurrence order is the same quantity seen from SSA.
9. **Use the statistics of integrated series.** Stocks are sums of flows. A unit-root test
   (ADF/KPSS) says whether a stock drains or only accumulates. The cointegration rank (Johansen)
   counts the independent accumulators. Conservation shows up as near-exact cointegrating vectors
   (unit totals). Regressing one level on another without this produces spurious relations
   (Granger and Newbold 1974).
10. **For effects and caps, look for coefficients that change with the state.** S-map local
    Jacobians (Deyle et al. 2016) or a time-varying-coefficient Kalman regression give "how
    strongly A drives B right now". Regressing that coefficient on a third stock's level reveals a
    multiplicative effect. Threshold AR models reveal a cap or floor. **Granger tests, transfer
    entropy and convergent cross mapping add little beyond our regression.** They also fail
    under feedback, temporal aggregation, common drivers and near-equilibrium. Use them only as
    framing or a sanity baseline.

---

## How the data looks to a signal analyst

These properties of SD Lab data decide which tools apply.

- **Levels are integrals.** A stock's level is the running sum of its net flow. Its spectrum is
  the net-flow spectrum divided by about ω² (an integrator) for an accumulating stock. A stock
  with a proportional drain fraction k (time constant T = 1/k) gives a "Lorentzian" divided by
  1 + (ωT)². Most coupling analysis should therefore be done on **changes** (first differences)
  or on **model residuals**, not on levels.
- **Counting noise excites the system.** Under Poisson counting, each flow carries noise whose
  variance equals its mean, and the same draw enters both ends of a move. That noise is broadband
  and keeps exciting every loop even at equilibrium. This is unusual: in classical system
  identification the input must be designed to excite the system. Here the noise does it, and
  its known covariance structure (from conservation) is information.
- **Common drivers are everywhere.** Daily/weekly schedules and outside-inflow changes hit many
  stocks at once. Marginal dependence measures will see a dense graph. Conditional measures are
  needed.
- **Feedback is the norm.** Gap-closing flows and links form loops. Frequency-domain transfer
  estimates and Granger tests are biased in closed loop unless an external signal is used.
- **Windows aggregate.** Summing steps into windows smooths noise but aliases fast dynamics and
  creates spurious lag-0 ("instantaneous") dependence. A daily cycle survives only while windows
  are shorter than half a day.
- **Nonlinearity is limited and specific.** Flows are floored at 0 and capped by what a stock
  holds, and "effects" multiply a rate by a function of another level. Between those boundaries,
  most dynamics are linear. Linear methods are the right first tool; a few targeted
  nonlinearity checks cover the rest.

---

## 1. Decomposition: trend, schedule, and the rest

### Classical decomposition, STL, MSTL, X-13ARIMA-SEATS

- **Idea.** Split a series into trend + seasonal + remainder. Classical decomposition uses
  moving averages. STL (Seasonal-Trend decomposition using Loess) iterates loess smoothers and has
  a robust mode that down-weights spikes (Cleveland, Cleveland, McRae and Terpenning 1990). MSTL
  handles several periods at once, such as daily and weekly (Bandara, Hyndman and Bergmeir 2021).
  X-13ARIMA-SEATS is the US Census Bureau's production seasonal adjustment. It includes automatic
  detection of outliers, level shifts and trading-day effects (Findley et al. 1998). TBATS
  (De Livera, Hyndman and Snyder 2011) and Prophet (Taylor and Letham 2018) are model-based
  alternatives.
- **What it reveals here.** Which stocks carry a schedule, with which periods, and how strongly.
  The amplitude and timing of each stock's seasonal component feed directly into the harmonic
  analysis in section 2.3. The trend shows slow drifts that may be unannounced input changes.
- **Pipeline step.** Run MSTL (periods 1 day and 1 week, in steps) on each stock's per-step
  change and on its level. Record the seasonal strength
  F_s = max(0, 1 − Var(R)/Var(S+R)) (Wang, Smith and Hyndman 2006). Record the phase of each
  seasonal component.
- **Caution, specific to us.** **Do not deseasonalise stocks one by one and then look for
  couplings in the remainders.** A schedule that reaches B by flowing from A *is* coupling
  evidence. Removing it separately from each series throws that evidence away. Worse, a
  separate fit can leave distorted residual cycles that create false coupling. Remove only the
  *outside* schedule: the seasonal part of stocks that have an inflow from outside, or a seasonal
  term inside the joint regression. Then let the model propagate it. (The single-step link
  screen's centred moving average in DISCOVERY.md section 8 has this same risk.)
- **Python.** `statsmodels.tsa.seasonal.STL`, `MSTL`, `seasonal_decompose`;
  `statsmodels.tsa.x13.x13_arima_analysis` (needs the Census binary); `prophet`; `tbats`.
- **Maturity.** Very high. Failure modes: end effects, schedule changes at eras, windows longer
  than half a period (aliasing).

### Singular spectrum analysis (SSA) and multichannel SSA

- **Idea.** Embed the series in a trajectory (Hankel) matrix of lagged copies, take its SVD, and
  group the components: trend, oscillation pairs, noise (Broomhead and King 1986; Vautard and
  Ghil 1989; Golyandina, Nekrutkin and Zhigljavsky 2001). Multichannel SSA does the same for many
  series jointly and finds modes they share.
- **What it reveals here.** (a) Oscillation pairs show schedules and loop oscillations (a
  negative-feedback loop with a delay rings at its own period). (b) **The rank of the trajectory
  matrix is the order of the linear recurrence the series obeys.** For a linear stock-flow
  system, that is the state dimension seen from that stock. It is a hint about how many
  first-order stages, measured or hidden, sit behind it (see section 5.3). (c) SSA-based
  change-point detection (Moskvina and Zhigljavsky 2003) flags times when the signal subspace
  changes.
- **Python.** `pyts.decomposition.SingularSpectrumAnalysis`; the `ssa` code in `pymssa`; R
  `Rssa` is the reference implementation.
- **Failure modes.** The window length is a choice. Noise rank inflates the order under Poisson
  noise, so look for a gap in the singular values, not the rank. Components separate only if
  their frequencies differ.

### Empirical mode decomposition (EMD, EEMD)

- **Idea.** Adaptively sift a series into "intrinsic mode functions", from fast to slow (Huang et
  al. 1998). The ensemble variant adds noise to reduce mode mixing (Wu and Huang 2009).
- **What it reveals here.** Little that STL/SSA do not. It is useful only for strongly
  nonstationary oscillations.
- **Python.** `EMD-signal` (`PyEMD`).
- **Verdict.** Low priority. It has no statistical model, suffers mode mixing and end effects,
  and gives poor results under count noise.

---

## 2. Spectral and frequency-domain analysis

### 2.1 Periodograms, Welch, multitaper, Lomb-Scargle

- **Idea.** The periodogram is the squared Fourier transform: power at each frequency. Welch
  (1967) averages periodograms over overlapping segments to reduce variance. Thomson's (1982)
  multitaper uses several orthogonal tapers (Slepian sequences). That gives low-bias, low-variance
  spectra and an F-test for pure lines (strictly periodic components such as a schedule). Lomb
  (1976) and Scargle (1982) handle uneven sampling and gaps (VanderPlas 2018 is a practical
  guide).
- **What it reveals here.**
  - *Lines* at 1/day, 1/week and their harmonics are schedules. Thomson's F-test separates a
    true line from a broadband peak, such as a resonance of a feedback loop.
  - *The shape of the continuum.* A stock fed by white flow noise and drained at rate k has power
    ∝ 1/(k² + ω²): flat below the corner frequency k, falling at −20 dB per decade above it.
    **The corner frequency estimates the drain rate from one series alone.** A steeper rolloff
    (−40, −60 dB/decade) means the noise reaching this stock passed through more first-order
    stages, a hint of hidden stocks upstream. Caveat: each stage adds its own counting noise,
    which flattens the high end, so the slope is only a hint.
  - *A broadband peak* away from zero frequency is a loop that oscillates: negative feedback
    with a delay, as in inventory/ordering loops.
- **Pipeline step.** A multitaper spectrum for each stock's change series, with the F-test for
  lines at schedule frequencies. Fit a rational spectrum (one or two poles) to the continuum to
  get each stock's time constant(s) as a prior for the regression.
- **Python.** `scipy.signal.periodogram`, `welch`; `scipy.signal.windows.dpss` for tapers;
  `nitime` (multitaper, F-test); `spectrum` package; `mne.time_frequency.psd_array_multitaper`;
  `astropy.timeseries.LombScargle`.
- **Failure modes.** Aliasing when the step or window is too long. Spectral leakage from strong
  lines into neighbours (tapers fix this). Nonstationarity across eras: compute spectra per era.

### 2.2 Cross-spectra, coherence, and frequency-domain transfer functions

- **Idea.** For two series x and y, the cross-spectrum S_xy(ω) has a magnitude and a phase. The
  coherence |S_xy|² / (S_xx S_yy) lies between 0 and 1 and is a correlation per frequency. If y
  is x passed through a linear filter H plus independent noise, then H(ω) = S_xy / S_xx (gain and
  phase). The coherence also gives confidence bands for H (Bendat and Piersol 2010, chapters 6
  and 9; Brillinger 1981). Group delay −dφ/dω gives the delay; the generalized cross-correlation
  (Knapp and Carter 1976) and Hannan and Thomson (1973) give delay estimators.
- **What it reveals here.** This is the most direct tool for **hidden stocks between two measured
  ones**:
  - Let x be A's outflow toward the hidden stock: k × level of A, or −(A's unexplained change).
    Let y be B's unexplained inflow. The transfer function of a hidden first-order stock with
    delay T is H = 1/(1 + iωT): the gain falls and the phase lag approaches 90°. An Erlang chain
    of n stages gives 1/(1 + iωT/n)ⁿ: the phase lag approaches n × 90° and the gain falls n
    times faster. A pipe (fixed delay) gives e^(−iωT): unit gain, with the phase falling
    linearly with frequency.
  - **The low-frequency group delay is the mean residence time for any shape**, because it is the
    first moment of the impulse response. Gain falloff versus phase growth then picks the shape.
  - **A co-flow** (an amount that always moves with another at ratio r) shows as coherence near 1
    at every frequency, flat gain r and zero phase.
  - **Low coherence** between two stocks at all frequencies, after removing common drivers
    (section 6.5), is evidence that no direct flow joins them.
- **Pipeline step.** For each candidate pair from the screen, estimate H(ω) by Welch or
  multitaper cross-spectra on prewhitened residuals. Fit the three delay shapes (exp, Erlang n,
  pipe) to the complex H in the band where coherence is significant. Report the mean delay from
  the low-frequency slope of the phase.
- **Python.** `scipy.signal.csd`, `scipy.signal.coherence`; `nitime.analysis.CoherenceAnalyzer`;
  `mne_connectivity.spectral_connectivity_time`.
- **Failure modes.** **Feedback biases H = S_xy/S_xx** when y's noise feeds back into x (Akaike
  1968; Forssell and Ljung 1999). The fix is to use an external signal as an instrument:
  H = S_zy / S_zx with z an outside inflow, the schedule or an era step. The indirect and
  joint input-output methods of closed-loop identification do this formally. Low coherence
  under Poisson noise in small flows needs long runs. Windowing aggregates the series and caps
  the usable band.

### 2.3 Harmonic probing with the schedule

- **Idea.** The narrowband special case of 2.2. When a known periodic input (the daily cycle)
  drives the system, regress each stock on sin and cos at that frequency (and its harmonics) to
  get an amplitude and phase per stock. In a linear system, each first-order stage multiplies the
  amplitude by 1/√(1+(ωT)²) and adds a lag of atan(ωT). That gives T = tan(Δφ)/ω for a single
  stage between two stocks.
- **What it reveals here.** Ordering of stocks along a process (phases increase downstream). Time
  constants of each stage. **A missing stage** (the phase jumps between two measured stocks by
  more than their own drains explain) means a hidden stock. Daily, weekly and seasonal
  harmonics give the transfer function at three frequencies for free. Sterman (2000) discusses
  the phase lag of delays in SD terms, and circadian biology uses phase maps the same way.
- **Pipeline step.** Harmonic regression per stock per era. Build a phase-ordering of stocks.
  Compare the measured phase step between connected stocks with the step their fitted drains
  predict, and flag excess phase as a hidden-delay candidate.
- **Failure modes.** The schedule must enter at a known place (an outside inflow). Floors and
  caps distort amplitudes. Several entry points of the schedule mix phases.

### 2.4 Wavelets and wavelet coherence

- **Idea.** Wavelets give a time-frequency picture: power and phase per scale *and* per time
  (Torrence and Compo 1998). Wavelet coherence localises coupling in time (Grinsted, Moore and
  Jevrejeva 2004). The maximal-overlap discrete wavelet transform (MODWT) gives an additive
  multiresolution decomposition with good statistical theory (Percival and Walden 2000). Wavelet
  shrinkage removes noise (Donoho and Johnstone 1994). For counts, apply it after a
  variance-stabilising transform (Haar-Fisz, Fryzlewicz and Nason 2004).
- **What it reveals here.** When couplings or schedules change at eras or unannounced times: the
  coherence between A and B at the daily scale switches off when a route closes. Sharp wavelet
  detail coefficients localise spikes and level shifts.
- **Python.** `PyWavelets` (`pywt`, includes `swt`/MODWT-like transforms), `pycwt` (wavelet
  coherence with significance tests), `ssqueezepy`.
- **Failure modes.** Cone-of-influence edge effects. Significance needs red-noise surrogates, not
  white. Coherence is high almost anywhere for short series.

---

## 3. Change points and regimes

The outside inflows are piecewise constant with unannounced changes. Eras are announced. Caps and
floors switch the dynamics. SD Lab already uses PELT with a BIC-like price
([change-price](../change-price.md)).

### 3.1 Offline segmentation: PELT, binary segmentation, WBS, SMUCE, CROPS

- **Idea.** Minimise the cost of the segments plus a penalty per change. PELT finds the exact
  optimum in about linear time (Killick, Fearnhead and Eckley 2012). Binary segmentation (Scott
  and Knott 1974) is greedy. Wild binary segmentation (Fryzlewicz 2014) draws random intervals
  and is robust to short segments. SMUCE (Frick, Munk and Sieling 2014) gives confidence
  statements on the number of changes. CROPS (Haynes, Eckley and Fearnhead 2017) gives the
  optimal segmentations for **every penalty in a range** at once: plot the number of changes
  against the penalty and pick the elbow. Bai and Perron (1998, 2003) handle structural breaks
  in regression coefficients, which is the right form for "an era changed a rate". The classic
  CUSUM (Page 1954) is the sequential ancestor.
- **What it reveals here.** Outside-inflow changes as level shifts in a stock's unexplained
  change. Era effects on rates as breaks in regression coefficients.
- **Python.** `ruptures` (PELT, BinSeg, BottomUp, Window, Dynp, kernel costs; Truong, Oudre and
  Vayatis 2020); `changepoint` and `changepoint.np` in R; `skchange` (Python, includes CROPS);
  `stumpy` for matrix-profile regime cues.
- **Failure modes for us.** (1) **Autocorrelated residuals** make every penalty too low, so many
  false changes appear. The residuals of a misspecified drain are autocorrelated: this is the
  sd-pipeline story in [change-price](../change-price.md). (2) A constant penalty assumes a fixed
  number of changes; an inflow that changes at a steady rate violates it (also found there).
  (3) Short segments bias the row's own drain coefficient (within-piece demeaning).

### 3.2 Change points with local fluctuations and autocorrelation

- **Idea.** Model the signal as abrupt changes *plus* a random-walk drift *plus* AR(1) noise, and
  segment by penalised dynamic programming that accounts for both: **DeCAFS** (Romano, Rigaill,
  Runge and Fearnhead 2022, verified). Alternatives: robust change points in the mean of an
  AR(1) process (Chakar, Lebarbier, Lévy-Leduc and Robin 2017); robust costs that resist outliers
  (Fearnhead and Rigaill 2019).
- **What it reveals here.** Unannounced input changes, without letting slow internal dynamics
  (feedback, unmodelled drains) or a spike pass for a change. This is the gap the change-price
  experiment found.
- **Pipeline step.** Replace the cost in the outside-inflow PELT with a DeCAFS-style cost:
  random-walk variance and AR coefficient estimated per stock robustly. Or prewhiten the residual
  with an AR fit before PELT, and use CROPS to select among penalties per stock.
- **Python/R.** `DeCAFS` (R, on R-universe); a cost of this shape is easy to write for
  `ruptures`.

### 3.3 Bayesian online change-point detection (BOCPD)

- **Idea.** Maintain a posterior over the "run length" since the last change. Each new
  observation either extends the run or starts a new one, under a hazard rate (Adams and MacKay
  2007; Fearnhead and Liu 2007 for the exact filtering form).
- **What it reveals here.** The probability of a change at each time, not a single answer. That
  suits reporting uncertainty ("the inflow probably changed around day 12"). It handles Poisson
  observations with a conjugate gamma prior, so **counting noise is modelled exactly**. It is
  also the natural form for [online identification](../online-identification.md).
- **Python.** `bayesian_changepoint_detection` (Kulick), `bocd`; simple to implement in about 50
  lines with a Poisson-gamma model.
- **Failure modes.** Sensitive to the hazard and the prior. The plain model assumes independence
  within segments, so the same autocorrelation caveat applies: run it on innovations.

### 3.4 Hidden Markov models, Markov-switching and switching state-space models

- **Idea.** A hidden discrete state (regime) evolves as a Markov chain, and each regime has its
  own observation model or dynamics (Rabiner 1989). Markov-switching autoregressions put the
  regime on the AR coefficients and mean (Hamilton 1989; Kim 1994). Switching linear dynamical
  systems (Ghahramani and Hinton 2000) and their Bayesian nonparametric version, the sticky
  HDP-HMM/SLDS (Fox, Sudderth, Jordan and Willsky 2011), let the number of regimes be learned.
  Recurrent SLDS make the switching depend on the continuous state (Linderman et al. 2017).
  **That is the exact form of a cap or floor: the dynamics switch when the level crosses a
  threshold.**
- **What it reveals here.** Recurring regimes such as night/day staffing, sprint/no-sprint and
  open/closed. Regime-dependent rates. With rSLDS, the location of a threshold.
- **Python.** `hmmlearn` (including Poisson emissions); `statsmodels.tsa.regime_switching`
  (`MarkovRegression`, `MarkovAutoregression`); `ssm` (Linderman lab, SLDS/rSLDS);
  `dynamax` (JAX: HMMs, LGSSMs, and more).
- **Failure modes.** Label switching. Regimes that the data does not revisit cannot be told apart
  from a one-off change point. Many parameters. For piecewise-constant inputs that never return to
  an earlier level, segmentation (3.1-3.3) is a better fit than an HMM.

### 3.5 Threshold autoregression (caps and floors)

- **Idea.** SETAR/TAR models switch AR coefficients when a lagged value crosses an estimated
  threshold (Tong and Lim 1980). With a censored observation model, a Tobit Kalman filter handles
  floors (Allik et al. 2016).
- **What it reveals here.** A flow that saturates at a capacity, or a stock floored at 0. A
  threshold model estimates the cap and tests "linear vs capped" (Hansen 1997 for the
  inference).
- **Python/R.** R `tsDyn` (SETAR, LSTAR, tests); in Python, a grid search on the threshold with
  least squares is a few lines.

### 3.6 Intervention analysis (announced eras)

- **Idea.** For a change at a *known* time, add a step or pulse dummy passed through a small
  transfer function: a sudden or gradual permanent change, or a decaying pulse (Box and Tiao
  1975).
- **What it reveals here.** How an announced era changed each stock: sudden vs gradual, and the
  time constant of the adjustment. That time constant is the stock's (or loop's) own dynamics, a
  natural experiment. **The response to an era step is the system's step response**, which
  carries the same information as a designed experiment
  ([experiment-design](../experiment-design.md)).
- **Python.** `statsmodels` SARIMAX with exogenous step/pulse regressors.

---

## 4. Robust methods for spikes and outliers

- **Taxonomy with an SD meaning.** The four classical outlier types (Fox 1972; Tsay 1988;
  Chen and Liu 1993):

| Type | Time-series meaning | SD meaning in our data |
|---|---|---|
| Additive outlier (AO) | one observation wrong, dynamics untouched | a measurement glitch; drop or down-weight |
| Innovational outlier (IO) | a shock enters and propagates through the dynamics | a batch arrival (sprint spike, release burst) into a stock, flowing on downstream |
| Level shift (LS) in the change series | a lasting jump in the mean of Δlevel | an outside inflow's rate changed (an unannounced input change) |
| Level shift in the level series = a single spike in Δlevel | a one-off jump | a one-off pulse of material added or removed |
| Temporary change (TC) | a jump decaying geometrically | a pulse into a stock with a proportional drain |

- **Joint estimation.** Chen and Liu (1993) iterate: fit the model, test every time point for each
  type, add the most significant as a dummy, and refit. That avoids the masking where outliers
  distort the model that is supposed to detect them. **This "outliers as dummies inside the
  model" loop is the right shape for our outside-input pieces.** A spike is an innovational
  outlier to be explained by downstream propagation, not a separate piece in each downstream
  stock.
- **Cheap robust filters.** The Hampel filter (median ± k × MAD in a moving window; Hampel 1974)
  for spike flags. Robust scale estimators Qn/Sn (Rousseeuw and Croux 1993). Huber (1964)
  M-estimation, or least absolute deviation, for the regression itself. The robust mode of STL.
- **Counts.** The Anscombe transform 2√(x + 3/8) (Anscombe 1948) makes Poisson variance about
  constant (≈ 1), so Gaussian outlier thresholds become meaningful. The Freeman-Tukey and
  Haar-Fisz transforms play the same role.
- **Python.** `sktime` and `hampel` packages for filters; `statsmodels.robust` (RLM, Huber,
  `mad`, `qn_scale`); `statsmodels` SARIMAX for dummy-based joint estimation (the full Chen-Liu
  loop is R `tsoutliers`; it is easy to port).

---

## 5. State-space models, Kalman filtering, EM and unobserved components

### 5.1 The linear-Gaussian state-space model

- **Idea.** x_{t+1} = A x_t + B u_t + w_t, y_t = C x_t + v_t. The Kalman filter (Kalman 1960)
  gives the one-step predictions and their likelihood. The Rauch-Tung-Striebel smoother (Rauch,
  Tung and Striebel 1965) gives the best estimate of every state using all data. Standard texts:
  Harvey (1989); Durbin and Koopman (2012); Shumway and Stoffer (2017).
- **SD mapping.** x = all stocks, measured and hidden. A = I + the flow matrix: off-diagonals are
  proportional flows, conservation makes the columns of the flow part sum to zero (or lose to
  outside). u = outside inflows and their pieces. w = flow noise. **w's covariance has the
  conservation structure: a move contributes +v to both diagonal entries and −v off-diagonal.**
  v = measurement error, often 0 for exact counts. The Poisson variance can be approximated by
  making the variance of w state-dependent: the linear noise approximation (van Kampen; for
  inference: Komorowski et al. 2009; Fearnhead, Giagos and Sherlock 2014).
- **What it reveals here.** (a) **Hidden stock levels**, from the smoother. (b) A proper
  one-step likelihood to judge candidate structures that accounts for process noise. The current
  judge is least squares on windowed changes, which treats levels as noiseless regressors
  (errors-in-variables bias, part of the "drain bias" noted in
  [shared-noise](../shared-noise.md)). (c) Innovations: the whitened residuals that change-point
  detection (section 3) and coupling analysis (section 6) should run on.
- **Python.** `statsmodels.tsa.statespace` (MLEModel, SARIMAX, UnobservedComponents,
  DynamicFactorMQ with EM); `dynamax` (JAX, LGSSM with EM and SGD, HMMs); `filterpy`;
  `simdkalman`; `pykalman` (has `em()`, but is unmaintained). R `MARSS` (Holmes, Ward and Wills
  2012) is the best reference for **constrained** multivariate state-space fits: fixed zeros,
  shared values and linear constraints in A. That is our flow-matrix structure.

### 5.2 EM for linear dynamical systems

- **Idea.** Alternate between the smoother (E-step: expected states and their covariances) and
  regression (M-step: A, Q, R from those expectations) (Shumway and Stoffer 1982; Ghahramani and
  Hinton 1996). The M-step is a least-squares problem. **Structural zeros and the conservation
  equalities are just linear constraints in it**, so the existing candidate-flow machinery can be
  the M-step. EM with a hidden state between A and B is "fit the hidden-delay flow" done
  jointly with everything else.
- **Pipeline step.** For a chosen structure (with hypothesised hidden stocks), run constrained EM
  to refine rates and estimate hidden levels. Compare structures by the Kalman log-likelihood
  plus BIC. Plan this as the final refinement and judge ([state-space](../state-space.md)).
- **Failure modes.** Local optima: initialise from the regression answer. Slow convergence when
  process noise is small. The Gaussian approximation is poor for small counts (switch to the
  count models of section 8). Identifiability of hidden states needs at least one measured end
  (as DISCOVERY.md already notes; Bellman and Åström 1970 for compartmental identifiability).

### 5.3 How many hidden states? Hankel rank, ERA, subspace identification

- **Idea.** The block Hankel matrix of lagged covariances (or of impulse responses) of a linear
  system has rank equal to its minimal state dimension (Ho and Kalman 1966). The eigensystem
  realization algorithm (Juang and Pappa 1985) and subspace methods such as N4SID (Van Overschee
  and De Moor 1996) estimate that order from the singular values, then estimate A and C. SSA
  (section 1) is the single-series version.
- **What it reveals here.** If the Hankel singular values show a gap after n values, and m stocks
  are measured and not explained as pure integrators, then about n − m first-order stages are
  hidden. An Erlang delay of order k counts as k. **It is a count before the search**, so the
  hidden-stock search knows how many to look for and when to stop. The observability of each
  hidden mode in each measured stock (in C) suggests where it attaches.
- **Python.** `sippy` (N4SID, MOESP, CVA); `pyERA`; a plain SVD of a block Hankel matrix in numpy.
- **Failure modes.** Fast hidden stages (a 2-hour step at hourly steps) have small singular values
  that sink into noise, as DISCOVERY.md already notes for the hospital. Nonlinearity (caps, floors)
  adds spurious order. Piecewise inputs must be removed first, or they add order.

### 5.4 Unobserved-components (structural time-series) models

- **Idea.** Write a series as a sum of interpretable unobserved parts: a local level or local
  linear trend (random walk), seasonals, cycles, regression effects and irregular noise. Estimate
  them by Kalman filter (Harvey 1989; Durbin and Koopman 2012). Bayesian structural time series
  adds spike-and-slab regression (Scott and Varian 2014). **Auxiliary residuals** (smoothed
  disturbances of each component, Harvey and Koopman 1992; de Jong and Penzer 1998) tell an
  outlier in the observation from a break in the level from a break in the slope.
- **What it reveals here.** An outside inflow that changes is a "local level" in the inflow,
  driven by rare large jumps. Model the inflow as a level with a heavy-tailed disturbance, or as a
  level plus auxiliary-residual break tests. The smoothed inflow is then the estimate of the
  unannounced input, **jointly with the stocks' dynamics** instead of in a separate PELT pass.
  That avoids double-counting between pieces and drains.
- **Python.** `statsmodels.tsa.UnobservedComponents` (level, trend, seasonal, cycle,
  autoregressive, exog); `orbit` (Uber); `tfp.sts` (TensorFlow Probability); `pybats` for dynamic
  generalized linear models with Poisson observations (West and Harrison 1997).

---

## 6. Dependence and coupling between series

### 6.1 Lagged cross-correlation and prewhitening

- **Idea.** The cross-correlation function (CCF) between x and y at lags −L..L. Raw CCFs of
  autocorrelated series are meaningless: two independent random walks correlate strongly (Yule
  1926; Granger and Newbold 1974). **Prewhitening** fits an ARMA filter to x, applies the same
  filter to y, and then computes the CCF. That CCF is proportional to the impulse response from x
  to y, and its standard errors are 1/√n under no relation (Box and Jenkins 1970, chapter 11;
  Haugh 1976 for the double-prewhitening independence test).
- **What it reveals here.** This is the workhorse for idea 1 of the summary. On per-step
  residuals of change (after the model so far, or after a per-stock AR fit):
  - lag-0 **negative** CCF: material moves between them in the same step (a move);
  - negative CCF at lags 1..L with a smooth bump: material leaves A and arrives in B later, so a
    hidden stock. The bump's shape is h(τ). Its area relative to Var(A's residual) is the share
    of A's outflow that reaches B;
  - **positive** CCF: a link (B's inflow follows A's level, nothing leaves A) or a common driver;
  - lag-0 positive spike at a steady ratio: a co-flow.
  The existing pre-screen (exp delays at 2, 12, 72 steps correlated with the residual) is a
  coarse, unwhitened version of this. Prewhitening makes the significance threshold honest and
  turns the CCF into the kernel directly.
- **Pipeline step.** Prewhiten each stock's residual with an AR(p) fit (p by BIC). Compute the CCF
  for all candidate pairs at lags 0..L by FFT. Use a threshold of √(2 ln(pairs × lags))/√n, as
  the group split already does. Keep the significant shapes and pass them to deconvolution (7.2).
- **Python.** `statsmodels.tsa.stattools.ccf`; `scipy.signal.correlate`; prewhitening via
  `statsmodels` AutoReg.
- **Failure modes.** Feedback: a reverse path puts mass at negative lags. Look at both sides, and
  treat a two-sided CCF as a loop. Aggregation into windows moves mass to lag 0. Common drivers
  give positive CCFs: remove them or condition on them (6.5).

### 6.2 Linear inverse models and fluctuation-dissipation (structure from equilibrium noise)

- **Idea.** For a stable linear system driven by white noise, the lagged covariance satisfies
  C(τ) = G(τ) C(0) with G(τ) = exp(Mτ). So the drift matrix is M = (1/τ) log(C(τ) C(0)⁻¹). The
  noise covariance follows from the Lyapunov (fluctuation-dissipation) relation
  M C(0) + C(0) Mᵀ + Q = 0 (Penland 1989; Penland and Sardeshmukh 1995, verified). In network
  science the same relation reconstructs directed links from noisy dynamics (Ren, Wang, Li and
  Lai 2010; Ching and Tam 2017, verified; review: Wang, Lai and Grebogi 2016).
- **What it reveals here.** **The whole flow matrix of a system that has settled near
  equilibrium**, from its fluctuations alone. That is the case where the regression has least to
  work with: the levels barely move, but the noise does. Q itself is informative: under
  conservation, each move contributes a negative off-diagonal entry equal to its mean rate (from
  Poisson variance = mean). **Q's sign pattern is a map of moves, and its size estimates their
  rates.** This extends the [shared-noise](../shared-noise.md) idea from lag 0 to the full
  dynamics. The equilibrium version of "variance equals mean" (its open idea) is exactly this
  relation.
- **Pipeline step.** On a stretch flagged as near-equilibrium (no pieces, low trend), compute
  C(0) and C(1) of the level deviations, estimate M and Q, and read candidate flows from the
  significant entries. Use it as a prior or a cross-check for the regression.
- **Failure modes.** Needs stationarity and many steps. Hidden stocks make the measured system
  non-Markov: the log of C(τ)C(0)⁻¹ then depends on τ. **That τ-dependence ("tau test") is
  itself a hidden-state detector** (Penland and Sardeshmukh 1995).

### 6.3 Granger causality and its pitfalls

- **Idea.** x Granger-causes y if past x improves the prediction of y beyond y's own past (Granger
  1969). It can be computed in VAR form, conditionally on other series (Geweke 1984), or in the
  frequency domain (Geweke 1982). The MVGC toolbox (Barnett and Seth 2014) is a careful
  implementation. Shojaie and Fox (2022) review the field.
- **What it adds here.** Very little over what discovery already does. Our stepwise regression of
  each stock's change on lagged levels *is* a conditional Granger analysis, with BIC as the
  test. Its value is the warnings the literature has collected:
  - **Non-stationary levels** give spurious Granger causality. Use differences, or lag-augmented
    VARs (Toda and Yamamoto 1995).
  - **Temporal aggregation and subsampling** (our windows) create spurious instantaneous
    causality and can reverse the apparent direction (Breitung and Swanson 2002; Barnett and Seth
    2017; Gong et al. 2015).
  - **Measurement noise** can reverse the inferred direction (Nalatore, Ding and Rangarajan 2007).
  - **Hidden common drivers** create false links. Latent-variable versions are SVAR-FCI (Malinsky
    and Spirtes 2018) and PCMCI+/LPCMCI (Runge 2020; Gerhardus and Runge 2020; see
    [causal-discovery](../causal-discovery.md)).
  - **Strong deterministic coupling** violates the separability Granger assumes (Sugihara et al.
    2012).
  - Granger answers "is there information flow", not "is there a material flow". **A link and a
    move look the same to it.** Only conservation (the source losing what the target gains)
    separates them.
- **Python.** `statsmodels.tsa.stattools.grangercausalitytests`, `statsmodels` VAR
  `test_causality`; `tigramite` (GPL-3.0) for PCMCI.

### 6.4 Transfer entropy and mutual information

- **Idea.** Transfer entropy (Schreiber 2000) is the model-free version of Granger: the
  conditional mutual information between past x and present y, given past y. For Gaussian
  variables it equals Granger causality up to a factor of 2 (Barnett, Barrett and Seth 2009).
  Mutual information between series detects any dependence, including nonlinear; the k-nearest-
  neighbour estimator is standard (Kraskov, Stögbauer and Grassberger 2004). Delay-scanning
  transfer entropy estimates the coupling delay (Wibral et al. 2013).
- **What it reveals here.** Nonlinear couplings that linear methods miss: in principle, effects
  and caps. Counts are discrete, so plug-in estimators apply directly to small counts.
- **Python.** `IDTxl` (Wollstadt et al. 2019), `JIDT` (Java, with Python bindings), `pyinform`,
  `sklearn.feature_selection.mutual_info_regression`, `npeet`.
- **Verdict.** Low priority. It needs a lot of data, is slow for 400 stocks, gives no sign or
  rate, and has the same aggregation and common-driver problems as Granger. Possibly useful as a
  check for nonlinear residual dependence after the linear model is fitted.

### 6.5 Partial correlation, partial coherence and graphical models for time series

- **Idea.** Two series are directly connected in the *conditional independence graph* if they
  stay dependent after conditioning on all others. For time series this is defined by the
  inverse spectral matrix: **partial coherence** is zero at all frequencies if and only if there
  is no edge (Brillinger 1996; Dahlhaus 2000). High-dimensional versions are the graphical lasso
  on the spectral density (Jung, Hannak and Goertz 2015, verified) and sparse inverse covariance
  of VAR residuals. Partial directed coherence adds direction (Baccalá and Sameshima 2001).
- **What it reveals here.** **The best replacement for the correlation-based grouping in
  DISCOVERY.md section 7.** A schedule shared by 400 services makes marginal correlations dense.
  Partial coherence, or partial correlations of prewhitened residuals, keeps only the edges that
  survive conditioning, and that graph's connected components are the groups. The sign of the
  lag-0 partial correlation of residuals already separates moves (negative) from links/co-flows
  (positive).
- **Pipeline step.** Prewhiten residuals per stock. Compute `GraphicalLassoCV` on residuals at lag
  0 and on the stacked [lag 0, lag 1] vectors. The components of the edge graph are the search
  groups. Use edge signs and lags as priors for move vs link.
- **Python.** `sklearn.covariance.GraphicalLassoCV`; `nitime` partial coherence; `mne_connectivity`
  (PDC, DTF).
- **Failure modes.** Needs n much larger than the group size for good estimates (shrinkage helps).
  Conditioning on a collider (a common effect) can create a false edge. Conservation makes the
  covariance of changes nearly singular when unit totals are included: leave the total rows out.

### 6.6 Takens embedding, convergent cross mapping and empirical dynamic modelling

- **Idea.** Takens' theorem (Takens 1981; Sauer, Yorke and Casdagli 1991; Deyle and Sugihara 2011
  for multivariate embeddings) says that lagged copies of one observable of a deterministic system
  reconstruct its whole state. Convergent cross mapping (CCM; Sugihara et al. 2012) says: if x
  drives y, then y's reconstruction can predict x, increasingly well as the library grows.
  Empirical dynamic modelling (EDM) forecasts with nearest neighbours (simplex; Sugihara and May
  1990) or locally weighted linear maps (S-map; Sugihara 1994). The S-map coefficients are
  local Jacobians: interaction strengths that change with the state (Deyle, May, Munch and
  Sugihara 2016, verified). Ye et al. (2015) add lags to CCM to handle delays.
- **What it reveals here.**
  - Embedding dimension: false nearest neighbours (Kennel, Brown and Abarbanel 1992), or the
    simplex forecast skill against E. This is the nonlinear version of the Hankel order in
    5.3, so another estimate of the number of hidden stages.
  - **S-map Jacobians for effects.** If the local coefficient ∂ΔB/∂A rises and falls with stock
    C's level, then C multiplies the A→B flow: an "effect". This is idea 10 of the summary.
  - CCM itself is a poor fit. It assumes weakly forced, deterministic, nonlinear dynamics. Our
    systems are stochastic, strongly forced by outside inputs and schedules, and nearly linear.
    Strong forcing gives "generalized synchrony", where CCM reports bidirectional causation
    (McCracken and Weigel 2014; Cobey and Baskerville 2016; Baskerville and Cobey 2017), and
    counting noise erodes cross-map skill.
- **Python.** `pyEDM` (Sugihara lab, the reference); `causal-ccm`; `skccm`.
- **Verdict.** Use S-map for effect detection. Skip CCM for structure.

### 6.7 Unit roots, cointegration and error-correction models

- **Idea.** A series is integrated (I(1)) if its changes are stationary but its level is not.
  Tests: augmented Dickey-Fuller (Dickey and Fuller 1979) with a unit-root null; KPSS with a
  stationarity null (Kwiatkowski et al. 1992). Two I(1) series are cointegrated if some linear
  combination is stationary (Engle and Granger 1987). The Johansen (1991) test gives the number r
  of independent cointegrating relations; n − r is the number of independent stochastic trends.
  An error-correction model (ECM) writes the changes as reacting to the deviation from the
  long-run relation.
- **What it reveals here.**
  - **Drain or accumulator?** A stock with a proportional outflow is mean-reverting (stationary
    around a moving input level). A final stock, or a stock with only constant outflows, is a
    unit-root accumulator. ADF and KPSS together classify them, a quick hint for the candidate
    list.
  - **Conservation as cointegration.** In a closed group, the unit total is a cointegrating
    combination with known weights (1, 1, ..., with conversion ratios). **Leftover non-stationarity
    in the total means an unmeasured exchange with outside.** This is the existing "total row"
    evidence, with a formal test.
  - **The Johansen rank counts independent accumulators:** final stocks plus independent
    random-walk outside inputs. A gap-closing flow ("close the gap to a goal") is an
    error-correction term. The ECM's loading coefficients are the gap-adjustment rates.
  - **Spurious regression warning.** Regressing levels on levels without these checks produces
    relations that are not there (Granger and Newbold 1974; Phillips 1986). Discovery regresses
    changes on levels, which is the ECM form and is fine. But any level-on-level screen is not.
- **Python.** `statsmodels.tsa.stattools.adfuller`, `kpss`, `coint`;
  `statsmodels.tsa.vector_ar.vecm` (`coint_johansen`, `VECM`).
- **Failure modes.** Low power in short runs. Breaks (eras, pieces) look like unit roots (Perron
  1989): test per era or with break-aware tests (Zivot and Andrews 1992).

---

## 7. Impulse responses, distributed lags and deconvolution (delays and hidden stocks)

### 7.1 The SD delay family as transfer functions

A hidden stock between measured A and B is a delay with impulse response h(τ):

| SD delay | Discrete h(τ) | Transfer function | Mean | Variance |
|---|---|---|---|---|
| first-order (exp) | geometric: (1/T)(1 − 1/T)^(τ−1) | 1/(1 + iωT) | T | T² (approx.) |
| Erlang order n (n stages, SD "DELAY3" is n = 3) | negative binomial / discretised gamma | 1/(1 + iωT/n)ⁿ | T | T²/n |
| pipeline (fixed) | δ(τ − T) | e^(−iωT) | T | 0 |

So the **order is mean²/variance** of the estimated kernel (the transit-compartment formula;
Sterman 2000, chapter 11 discusses choosing the order of a delay from the observed spread).
Non-integer n is allowed and estimated continuously in pharmacometrics (Savic et al. 2007,
verified; Sun and Jusko 1998).

### 7.2 Estimating h(τ)

- **Distributed-lag regression.** y_t = Σ_τ h_τ x_{t−τ} + e_t. A free finite impulse response
  (FIR) is noisy with many lags, so add structure. Almon (1965) used polynomial lags. Koyck (1954)
  and Jorgenson (1966) used geometric and rational lags (an ARX with one pole is exactly a
  first-order delay). Gamma/Erlang lags are the SD-shaped choice. Laguerre basis functions
  (Wahlberg 1991) represent exponential-like kernels with few coefficients.
- **Regularised kernels.** The stable-spline / TC kernel prior (Pillonetto and De Nicolao 2010;
  survey: Pillonetto et al. 2014) estimates a long impulse response by ridge regression with a
  prior that the response is smooth and decays. Its hyperparameters are fitted by marginal
  likelihood. It is mature in system identification, and it removes the need for a delay grid.
- **Constrained deconvolution (the SD-specific step).** Conservation adds constraints the generic
  methods lack: h ≥ 0, and Σh ≤ 1, with equality if everything that leaves A along this route
  arrives in B. Nonnegative least squares with a sum constraint (`scipy.optimize.nnls` plus a
  penalty, or `cvxpy`) or Richardson-Lucy deconvolution (used by Goldstein et al. 2009, verified,
  to turn deaths into infections) give a physically valid kernel. Then fit exp/Erlang/pipe to it
  and read off mean (residence time), order (mean²/variance) and the hidden size
  (Little's law: average flow × mean).
- **Local projections.** Jordà (2005) regresses y_{t+h} on x_t and controls, separately for each
  horizon h. It is robust to misspecification and gives impulse responses with honest error
  bands. That is useful when the rest of the model is uncertain.
- **What it reveals here.** The delay *and its shape* without a grid of 26 delays × 3 shapes,
  and an honest confidence band (the "range of delays that fit about as well").
- **Where the input signal comes from.** Measured A's outflow toward the hidden stock is k × A
  (the regressor), or its residual (the noise probe of 6.1). B's arrivals are B's unexplained
  change plus B's estimated outflows. **Feedback** from B to A biases the estimate (see 2.2).
  Instruments: lagged outside inputs, era steps.
- **Python.** `statsmodels` OLS/ARDL (`statsmodels.tsa.ardl.ARDL` with distributed lags);
  `scipy.optimize.nnls`; `cvxpy`; stable-spline kernels are not packaged in Python, but they are
  about 30 lines of numpy (the MATLAB System Identification Toolbox has `impulseest` with them).
- **Failure modes.** Two delays in a row (the hidden one and B's own drain) can be swapped
  without changing the input-output relation unless one end's flow is counted (already noted in
  DISCOVERY.md). Pipe delays longer than the run length, and slow, smooth inputs, give poorly
  conditioned problems.

---

## 8. Count time series

- **INAR: the stock-and-flow model in statistical form.** The integer-valued autoregression
  X_t = α ∘ X_{t−1} + ε_t uses binomial thinning ∘: each of the X_{t−1} items survives with
  probability α. ε_t is a count of new arrivals (McKenzie 1985; Al-Osh and Alzaid 1987). **That is
  exactly a stock with a proportional drain 1 − α and an outside inflow, under counting noise.**
  Multivariate INAR with thinning between components (Latour 1997; Pedeli and Karlis 2013) is a
  stochastic compartment model: items leave one stock and enter another with given
  probabilities. The likelihood is exact and known, so these models give the right noise model
  for small counts where the Gaussian approximation fails. Weiß (2018) is the textbook.
- **Poisson autoregression (INGARCH).** The intensity λ_t = d + a λ_{t−1} + b X_{t−1}
  (Ferland, Latour and Oraichi 2006; Fokianos, Rahbek and Tjøstheim 2009), with covariates in
  `tscount` (Liboschik, Fokianos and Fried 2017). GLARMA (Davis, Dunsmuir and Streett 2003) is the
  observation-driven GLM version. Dynamic GLMs (West and Harrison 1997) are the parameter-driven
  version with Poisson observations.
- **Hawkes processes.** Self- and mutually-exciting point processes (Hawkes 1971): an event in A
  raises the rate in B according to a kernel. The kernel is a link's or hidden delay's impulse
  response, and the excitation matrix is a directed graph. This matters for fine-grained event
  data (individual arrivals), less for levels.
- **What they reveal here.** Correct weights and likelihoods (variance = mean). Thinning
  probabilities = drain fractions. **Dispersion checks:** a Fano factor (variance/mean of the
  per-step change) above 1 means batching (spikes, sprints) or an unmodelled input. Below 1 means
  regular, scheduled flows. Either tells you the noise model, and see
  [count-likelihoods](../count-likelihoods.md).
- **Python.** `statsmodels` GLM/`Poisson`/`NegativeBinomial` with lagged regressors (INGARCH by
  hand); `pybats` (Poisson DGLMs); `tick` (Hawkes); `PyMC`/`NumPyro` for INAR likelihoods.
  `tscount` is R.
- **Failure modes.** Multivariate INAR likelihoods are expensive (convolutions). Use conditional
  least squares or the Gaussian (linear noise) approximation for large counts and exact
  likelihoods only for small stocks.

---

## 9. Exploratory checklist for a large multi-series dataset

What an expert would compute first, in order, before any search. Each item states what it
suggests about the structure. All of it is cheap: per-series or pairwise FFT work.

**Per series**

1. **Plot everything on one page**: small multiples of levels and per-step changes, with eras
   marked. Look for steps, ramps, spikes, flat floors, ceilings, and stocks that never decrease
   (final stocks).
2. **Basic shape statistics per stock**: min (does it sit at 0, a floor?), max (a cap?), share of
   steps at the min/max, share of steps where it decreases (never decreases = final or
   accumulator).
3. **Dispersion of per-step changes**: variance/mean (Fano factor) of the change. About 1:
   Poisson-like independent flows. Much more than 1: batches or input changes. Variance much
   larger than the mean of the absolute change: an aggregated large throughput.
4. **Robust spike scan** (Hampel filter on changes, after the Anscombe transform) and a count of
   spikes per stock. Cluster spike times across stocks: simultaneous spikes are a shared batch,
   spikes later downstream show the route.
5. **Autocorrelation of levels**: lag-1 autocorrelation ≈ 1 − drain fraction for a stock with
   white inflow. Hence a first estimate of each stock's time constant. An ACF that stays near 1
   suggests an accumulator or a slow loop.
6. **Unit-root/stationarity pair (ADF + KPSS) per stock and per era**: drained vs accumulating.
7. **Multitaper spectrum of changes**: schedule lines (F-test at 1/day, 1/week and harmonics),
   corner frequency (drain rate), rolloff slope (stages upstream), broadband peaks (oscillating
   loops).
8. **MSTL decomposition**: seasonal strength and seasonal phase per stock. The trend shows
   unannounced input changes.
9. **Change-point scan with a penalty path** (CROPS or BOCPD) on prewhitened changes. How many
   changes per stock as a function of the penalty: an elbow means real pieces; a smooth curve
   means misfit dynamics posing as pieces.

**Across series**

10. **Conservation totals per unit**: the sum of all stocks of a unit and its trend. Constant:
    closed. Drifting: exchange with outside. Steps: unmeasured pulses. Test the total for a unit
    root.
11. **Phase map of the daily harmonic**: amplitude and phase of each stock at 1/day, sorted by
    phase. That gives the probable order of stocks along the process. Excess phase between
    neighbours suggests hidden stages.
12. **Lag-0 correlation matrix of per-step change residuals** (prewhitened), split by sign:
    negative = mirror (a move), positive = shared driver, link or co-flow. Then its **partial**
    version (graphical lasso). Then cluster the partial graph into groups.
13. **Prewhitened CCF for every candidate pair at lags 0..L** (FFT, one pass): the lag of the
    extreme, its sign and its width. A negative bump at lag > 0 is a hidden delay candidate;
    two-sided mass is a loop.
14. **Coherence and phase for the top pairs**: flat gain and zero phase = co-flow; phase growing
    linearly = pipe delay; phase bending to 90°·n = n-stage delay. The low-frequency slope = mean
    delay.
15. **Lagged covariances near equilibrium (LIM)**: on quiet stretches, M = log(C(1)C(0)⁻¹) and Q
    from the Lyapunov relation. Read negative Q entries as moves. Check whether M depends on the
    lag (the "tau test"): if so, hidden stocks.
16. **Hankel singular values of the stacked change residuals**: a gap after n means n states.
    Compare n with the measured stocks to count hidden stages.
17. **Era responses**: for each announced era, the response of every stock to the step (sudden or
    gradual, with which time constant). These are free step-response experiments.
18. **Cointegration rank (Johansen) within each group**: the number of independent accumulators,
    and the long-run relations (gaps being closed).
19. **Nonlinearity probes**: scatter each flow's estimated amount against its source level (a
    bend = cap or effect), and S-map θ-scan per stock (forecast skill rising with θ > 0 means
    state-dependent dynamics). Check whether local coefficients correlate with a third stock's
    level (an effect).
20. **Write hypotheses down as a candidate list with priors** (moves, links, hidden delays with
    mean/order, pieces, effects) and hand it to the structure search as seeds. Do not feed it
    the final answer.

---

## 10. Concrete pipeline proposals (in order of expected value)

1. **Prewhitened residual CCF + constrained deconvolution** for hidden stocks (6.1 + 7.2).
   It replaces the exp-at-2/12/72 pre-screen and the 26-delay grid with a kernel estimate. Its
   moments give delay, order and size. Mechanism test: hidden-chain and hospital lab.
2. **Partial-correlation grouping** (6.5) in place of |r| < −0.3 union-find, for the 400-stock
   case and for schedules shared by everything. Mechanism test: the shop and the fleet.
3. **Autocorrelation-aware change points** (3.2, CROPS) for outside-input pieces, run on
   innovations of the current model and re-estimated jointly (Chen-Liu loop, section 4).
   Mechanism test: sd-pipeline, sd-support-tiers, sd-population.
4. **Harmonic phase map** (2.3) as a prior for ordering and hidden-stage detection where
   schedules exist.
5. **LIM / Lyapunov noise covariance** (6.2) for loops that have settled: sd-orders, sd-supply,
   sd-population.
6. **Kalman likelihood and constrained EM** (5.1-5.2) as the final judge and hidden-level
   estimator, after the structure search.
7. **S-map or TVP-Kalman coefficients regressed on candidate modulators** (6.6) to propose
   effects for the benchmark-v2 effect examples.
8. **Hankel order count** (5.3) to bound the number of hidden stocks searched.

---

## 11. Reading list

Grouped by section. ★ marks the ones to read first.

**Textbooks and surveys**
- ★ Box, G.E.P., Jenkins, G.M., Reinsel, G.C. and Ljung, G.M. (2015). *Time Series Analysis:
  Forecasting and Control*, 5th ed. Wiley. (Prewhitening, transfer-function models, intervention
  analysis. First edition 1970.)
- ★ Shumway, R.H. and Stoffer, D.S. (2017). *Time Series Analysis and Its Applications*, 4th ed.
  Springer. https://doi.org/10.1007/978-3-319-52452-8
- ★ Durbin, J. and Koopman, S.J. (2012). *Time Series Analysis by State Space Methods*, 2nd ed.
  Oxford University Press.
- Harvey, A.C. (1989). *Forecasting, Structural Time Series Models and the Kalman Filter*.
  Cambridge University Press.
- Brillinger, D.R. (1981). *Time Series: Data Analysis and Theory*. Holden-Day (SIAM reprint 2001).
- Bendat, J.S. and Piersol, A.G. (2010). *Random Data: Analysis and Measurement Procedures*, 4th
  ed. Wiley. (Coherence, frequency-response estimation, errors.)
- Percival, D.B. and Walden, A.T. (1993). *Spectral Analysis for Physical Applications*. Cambridge
  University Press.
- Percival, D.B. and Walden, A.T. (2000). *Wavelet Methods for Time Series Analysis*. Cambridge
  University Press.
- ★ Ljung, L. (1999). *System Identification: Theory for the User*, 2nd ed. Prentice Hall.
- Hyndman, R.J. and Athanasopoulos, G. (2021). *Forecasting: Principles and Practice*, 3rd ed.
  OTexts. https://otexts.com/fpp3/
- Weiß, C.H. (2018). *An Introduction to Discrete-Valued Time Series*. Wiley.
  https://doi.org/10.1002/9781119097013
- Sterman, J.D. (2000). *Business Dynamics*. McGraw-Hill. (Chapter 11: delays, their order and
  phase lag.)
- West, M. and Harrison, J. (1997). *Bayesian Forecasting and Dynamic Models*, 2nd ed. Springer.
- Wang, W.-X., Lai, Y.-C. and Grebogi, C. (2016). Data based identification and prediction of
  nonlinear and complex dynamical systems. *Physics Reports* 644, 1-76.
  https://doi.org/10.1016/j.physrep.2016.06.004
- Shojaie, A. and Fox, E.B. (2022). Granger causality: a review and recent advances. *Annual
  Review of Statistics and Its Application* 9, 289-319.
  https://doi.org/10.1146/annurev-statistics-040120-010930

**Decomposition**
- ★ Cleveland, R.B., Cleveland, W.S., McRae, J.E. and Terpenning, I. (1990). STL: a
  seasonal-trend decomposition procedure based on loess. *Journal of Official Statistics* 6(1),
  3-73.
- Bandara, K., Hyndman, R.J. and Bergmeir, C. (2021). MSTL: a seasonal-trend decomposition
  algorithm for time series with multiple seasonal patterns. arXiv:2107.13462.
- Findley, D.F., Monsell, B.C., Bell, W.R., Otto, M.C. and Chen, B.-C. (1998). New capabilities
  and methods of the X-12-ARIMA seasonal-adjustment program. *Journal of Business and Economic
  Statistics* 16(2), 127-152. https://doi.org/10.1080/07350015.1998.10524743
- De Livera, A.M., Hyndman, R.J. and Snyder, R.D. (2011). Forecasting time series with complex
  seasonal patterns using exponential smoothing. *JASA* 106(496), 1513-1527.
  https://doi.org/10.1198/jasa.2011.tm09771
- Taylor, S.J. and Letham, B. (2018). Forecasting at scale. *The American Statistician* 72(1),
  37-45. https://doi.org/10.1080/00031305.2017.1380080
- Wang, X., Smith, K. and Hyndman, R.J. (2006). Characteristic-based clustering for time series
  data. *Data Mining and Knowledge Discovery* 13(3), 335-364.
  https://doi.org/10.1007/s10618-005-0039-x
- Broomhead, D.S. and King, G.P. (1986). Extracting qualitative dynamics from experimental data.
  *Physica D* 20(2-3), 217-236. https://doi.org/10.1016/0167-2789(86)90031-X
- Vautard, R. and Ghil, M. (1989). Singular spectrum analysis in nonlinear dynamics, with
  applications to paleoclimatic time series. *Physica D* 35(3), 395-424.
  https://doi.org/10.1016/0167-2789(89)90077-8
- Golyandina, N., Nekrutkin, V. and Zhigljavsky, A. (2001). *Analysis of Time Series Structure:
  SSA and Related Techniques*. Chapman and Hall/CRC.
- Moskvina, V. and Zhigljavsky, A. (2003). An algorithm based on singular spectrum analysis for
  change-point detection. *Communications in Statistics - Simulation and Computation* 32(2),
  319-352. https://doi.org/10.1081/SAC-120017494
- Huang, N.E. et al. (1998). The empirical mode decomposition and the Hilbert spectrum for
  nonlinear and non-stationary time series analysis. *Proc. R. Soc. Lond. A* 454, 903-995.
  https://doi.org/10.1098/rspa.1998.0193
- Wu, Z. and Huang, N.E. (2009). Ensemble empirical mode decomposition. *Advances in Adaptive
  Data Analysis* 1(1), 1-41. https://doi.org/10.1142/S1793536909000047

**Spectra, coherence, wavelets**
- Welch, P.D. (1967). The use of fast Fourier transform for the estimation of power spectra.
  *IEEE Trans. Audio and Electroacoustics* 15(2), 70-73. https://doi.org/10.1109/TAU.1967.1161901
- ★ Thomson, D.J. (1982). Spectrum estimation and harmonic analysis. *Proceedings of the IEEE*
  70(9), 1055-1096. https://doi.org/10.1109/PROC.1982.12433
- Lomb, N.R. (1976). Least-squares frequency analysis of unequally spaced data. *Astrophysics and
  Space Science* 39, 447-462. https://doi.org/10.1007/BF00648343
- Scargle, J.D. (1982). Studies in astronomical time series analysis II. *Astrophysical Journal*
  263, 835-853. https://doi.org/10.1086/160554
- VanderPlas, J.T. (2018). Understanding the Lomb-Scargle periodogram. *ApJS* 236, 16.
  https://doi.org/10.3847/1538-4365/aab766
- Hannan, E.J. and Thomson, P.J. (1973). Estimating group delay. *Biometrika* 60(2), 241-253.
  https://doi.org/10.1093/biomet/60.2.241
- Knapp, C. and Carter, G. (1976). The generalized correlation method for estimation of time
  delay. *IEEE Trans. ASSP* 24(4), 320-327. https://doi.org/10.1109/TASSP.1976.1162830
- Akaike, H. (1968). On the use of a linear model for the identification of feedback systems.
  *Annals of the Institute of Statistical Mathematics* 20, 425-439.
  https://doi.org/10.1007/BF02911655
- ★ Forssell, U. and Ljung, L. (1999). Closed-loop identification revisited. *Automatica* 35(7),
  1215-1241. https://doi.org/10.1016/S0005-1098(99)00022-9
- Torrence, C. and Compo, G.P. (1998). A practical guide to wavelet analysis. *Bulletin of the AMS*
  79(1), 61-78. https://doi.org/10.1175/1520-0477(1998)079<0061:APGTWA>2.0.CO;2
- Grinsted, A., Moore, J.C. and Jevrejeva, S. (2004). Application of the cross wavelet transform
  and wavelet coherence to geophysical time series. *Nonlinear Processes in Geophysics* 11,
  561-566. https://doi.org/10.5194/npg-11-561-2004
- Donoho, D.L. and Johnstone, I.M. (1994). Ideal spatial adaptation by wavelet shrinkage.
  *Biometrika* 81(3), 425-455. https://doi.org/10.1093/biomet/81.3.425
- Fryzlewicz, P. and Nason, G.P. (2004). A Haar-Fisz algorithm for Poisson intensity estimation.
  *Journal of Computational and Graphical Statistics* 13(3), 621-638.
  https://doi.org/10.1198/106186004X2697

**Change points and regimes**
- ★ Killick, R., Fearnhead, P. and Eckley, I.A. (2012). Optimal detection of changepoints with a
  linear computational cost. *JASA* 107(500), 1590-1598.
  https://doi.org/10.1080/01621459.2012.737745
- ★ Haynes, K., Eckley, I.A. and Fearnhead, P. (2017). Computationally efficient changepoint
  detection for a range of penalties. *JCGS* 26(1), 134-143.
  https://doi.org/10.1080/10618600.2015.1116445 (verified)
- ★ Romano, G., Rigaill, G., Runge, V. and Fearnhead, P. (2022). Detecting abrupt changes in the
  presence of local fluctuations and autocorrelated noise. *JASA* 117(540), 2147-2162.
  https://doi.org/10.1080/01621459.2021.1909598 (verified; arXiv:2005.01379)
- Chakar, S., Lebarbier, E., Lévy-Leduc, C. and Robin, S. (2017). A robust approach for estimating
  change-points in the mean of an AR(1) process. *Bernoulli* 23(2), 1408-1447.
  https://doi.org/10.3150/15-BEJ782
- Fearnhead, P. and Rigaill, G. (2019). Changepoint detection in the presence of outliers.
  *JASA* 114(525), 169-183. https://doi.org/10.1080/01621459.2017.1385466
- Fryzlewicz, P. (2014). Wild binary segmentation for multiple change-point detection. *Annals of
  Statistics* 42(6), 2243-2281. https://doi.org/10.1214/14-AOS1245
- Frick, K., Munk, A. and Sieling, H. (2014). Multiscale change point inference. *JRSS B* 76(3),
  495-580. https://doi.org/10.1111/rssb.12047
- Scott, A.J. and Knott, M. (1974). A cluster analysis method for grouping means in the analysis
  of variance. *Biometrics* 30(3), 507-512. https://doi.org/10.2307/2529204
- Page, E.S. (1954). Continuous inspection schemes. *Biometrika* 41(1/2), 100-115.
  https://doi.org/10.1093/biomet/41.1-2.100
- Bai, J. and Perron, P. (1998). Estimating and testing linear models with multiple structural
  changes. *Econometrica* 66(1), 47-78. https://doi.org/10.2307/2998540
- Bai, J. and Perron, P. (2003). Computation and analysis of multiple structural change models.
  *Journal of Applied Econometrics* 18(1), 1-22. https://doi.org/10.1002/jae.659
- ★ Adams, R.P. and MacKay, D.J.C. (2007). Bayesian online changepoint detection.
  arXiv:0710.3742.
- Fearnhead, P. and Liu, Z. (2007). On-line inference for multiple changepoint problems. *JRSS B*
  69(4), 589-605. https://doi.org/10.1111/j.1467-9868.2007.00601.x
- Truong, C., Oudre, L. and Vayatis, N. (2020). Selective review of offline change point detection
  methods. *Signal Processing* 167, 107299. https://doi.org/10.1016/j.sigpro.2019.107299
  (the `ruptures` paper)
- Rabiner, L.R. (1989). A tutorial on hidden Markov models and selected applications in speech
  recognition. *Proceedings of the IEEE* 77(2), 257-286. https://doi.org/10.1109/5.18626
- Hamilton, J.D. (1989). A new approach to the economic analysis of nonstationary time series and
  the business cycle. *Econometrica* 57(2), 357-384. https://doi.org/10.2307/1912559
- Kim, C.-J. (1994). Dynamic linear models with Markov-switching. *Journal of Econometrics* 60,
  1-22. https://doi.org/10.1016/0304-4076(94)90036-1
- Ghahramani, Z. and Hinton, G.E. (2000). Variational learning for switching state-space models.
  *Neural Computation* 12(4), 831-864. https://doi.org/10.1162/089976600300015619
- Fox, E.B., Sudderth, E.B., Jordan, M.I. and Willsky, A.S. (2011). Bayesian nonparametric
  inference of switching dynamic linear models. *IEEE Trans. Signal Processing* 59(4), 1569-1585.
  https://doi.org/10.1109/TSP.2010.2102756
- Linderman, S.W., Johnson, M.J., Miller, A.C., Adams, R.P., Blei, D.M. and Paninski, L. (2017).
  Bayesian learning and inference in recurrent switching linear dynamical systems. *AISTATS*,
  PMLR 54, 914-922.
- Tong, H. and Lim, K.S. (1980). Threshold autoregression, limit cycles and cyclical data. *JRSS
  B* 42(3), 245-292.
- Hansen, B.E. (1997). Inference in TAR models. *Studies in Nonlinear Dynamics and Econometrics*
  2(1).
- Allik, B., Miller, C., Piovoso, M.J. and Zurakowski, R. (2016). The Tobit Kalman filter: an
  estimator for censored measurements. *IEEE Trans. Control Systems Technology* 24(1), 365-371.
  https://doi.org/10.1109/TCST.2015.2432155
- ★ Box, G.E.P. and Tiao, G.C. (1975). Intervention analysis with applications to economic and
  environmental problems. *JASA* 70(349), 70-79. https://doi.org/10.1080/01621459.1975.10480264

**Outliers and robustness**
- Fox, A.J. (1972). Outliers in time series. *JRSS B* 34(3), 350-363.
- Tsay, R.S. (1988). Outliers, level shifts, and variance changes in time series. *Journal of
  Forecasting* 7(1), 1-20. https://doi.org/10.1002/for.3980070102
- ★ Chen, C. and Liu, L.-M. (1993). Joint estimation of model parameters and outlier effects in
  time series. *JASA* 88(421), 284-297. https://doi.org/10.1080/01621459.1993.10594321
- Hampel, F.R. (1974). The influence curve and its role in robust estimation. *JASA* 69(346),
  383-393. https://doi.org/10.1080/01621459.1974.10482962
- Huber, P.J. (1964). Robust estimation of a location parameter. *Annals of Mathematical
  Statistics* 35(1), 73-101. https://doi.org/10.1214/aoms/1177703732
- Rousseeuw, P.J. and Croux, C. (1993). Alternatives to the median absolute deviation. *JASA*
  88(424), 1273-1283. https://doi.org/10.1080/01621459.1993.10476408
- Anscombe, F.J. (1948). The transformation of Poisson, binomial and negative-binomial data.
  *Biometrika* 35(3/4), 246-254. https://doi.org/10.1093/biomet/35.3-4.246

**State space, EM, subspace identification**
- Kalman, R.E. (1960). A new approach to linear filtering and prediction problems. *Journal of
  Basic Engineering* 82(1), 35-45. https://doi.org/10.1115/1.3662552
- Rauch, H.E., Tung, F. and Striebel, C.T. (1965). Maximum likelihood estimates of linear dynamic
  systems. *AIAA Journal* 3(8), 1445-1450. https://doi.org/10.2514/3.3166
- ★ Shumway, R.H. and Stoffer, D.S. (1982). An approach to time series smoothing and forecasting
  using the EM algorithm. *Journal of Time Series Analysis* 3(4), 253-264.
  https://doi.org/10.1111/j.1467-9892.1982.tb00349.x
- Ghahramani, Z. and Hinton, G.E. (1996). Parameter estimation for linear dynamical systems.
  Technical Report CRG-TR-96-2, University of Toronto.
- ★ Holmes, E.E., Ward, E.J. and Wills, K. (2012). MARSS: multivariate autoregressive state-space
  models for analyzing time-series data. *The R Journal* 4(1), 11-19.
  https://doi.org/10.32614/RJ-2012-002
- Harvey, A.C. and Koopman, S.J. (1992). Diagnostic checking of unobserved-components time series
  models. *Journal of Business and Economic Statistics* 10(4), 377-389.
  https://doi.org/10.1080/07350015.1992.10509913
- de Jong, P. and Penzer, J. (1998). Diagnosing shocks in time series. *JASA* 93(442), 796-806.
  https://doi.org/10.1080/01621459.1998.10473731
- Scott, S.L. and Varian, H.R. (2014). Predicting the present with Bayesian structural time
  series. *International Journal of Mathematical Modelling and Numerical Optimisation* 5(1/2),
  4-23. https://doi.org/10.1504/IJMMNO.2014.059942
- Ho, B.L. and Kalman, R.E. (1966). Effective construction of linear state-variable models from
  input/output functions. *Regelungstechnik* 14(12), 545-548.
- Juang, J.-N. and Pappa, R.S. (1985). An eigensystem realization algorithm for modal parameter
  identification and model reduction. *Journal of Guidance, Control, and Dynamics* 8(5), 620-627.
  https://doi.org/10.2514/3.20031
- Van Overschee, P. and De Moor, B. (1996). *Subspace Identification for Linear Systems*. Kluwer.
  https://doi.org/10.1007/978-1-4613-0465-4
- Bellman, R. and Åström, K.J. (1970). On structural identifiability. *Mathematical Biosciences*
  7(3-4), 329-339. https://doi.org/10.1016/0025-5564(70)90132-X
- Komorowski, M., Finkenstädt, B., Harper, C.V. and Rand, D.A. (2009). Bayesian inference of
  biochemical kinetic parameters using the linear noise approximation. *BMC Bioinformatics* 10,
  343. https://doi.org/10.1186/1471-2105-10-343
- Fearnhead, P., Giagos, V. and Sherlock, C. (2014). Inference for reaction networks using the
  linear noise approximation. *Biometrics* 70(2), 457-466. https://doi.org/10.1111/biom.12152

**Coupling and dependence**
- Haugh, L.D. (1976). Checking the independence of two covariance-stationary time series: a
  univariate residual cross-correlation approach. *JASA* 71(354), 378-385.
  https://doi.org/10.1080/01621459.1976.10480353
- Yule, G.U. (1926). Why do we sometimes get nonsense-correlations between time-series? *JRSS*
  89(1), 1-63. https://doi.org/10.2307/2341482
- ★ Granger, C.W.J. and Newbold, P. (1974). Spurious regressions in econometrics. *Journal of
  Econometrics* 2(2), 111-120. https://doi.org/10.1016/0304-4076(74)90034-7
- ★ Penland, C. and Sardeshmukh, P.D. (1995). The optimal growth of tropical sea surface
  temperature anomalies. *Journal of Climate* 8(8), 1999-2024.
  https://doi.org/10.1175/1520-0442(1995)008<1999:TOGOTS>2.0.CO;2 (verified)
- Penland, C. (1989). Random forcing and forecasting using principal oscillation pattern analysis.
  *Monthly Weather Review* 117(10), 2165-2185.
  https://doi.org/10.1175/1520-0493(1989)117<2165:RFAFUP>2.0.CO;2
- ★ Ching, E.S.C. and Tam, H.C. (2017). Reconstructing links in directed networks from noisy
  dynamics. *Physical Review E* 95, 010301(R). https://doi.org/10.1103/PhysRevE.95.010301
  (verified)
- Ren, J., Wang, W.-X., Li, B. and Lai, Y.-C. (2010). Noise bridges dynamical correlation and
  topology in coupled oscillator networks. *Physical Review Letters* 104, 058701.
  https://doi.org/10.1103/PhysRevLett.104.058701
- Granger, C.W.J. (1969). Investigating causal relations by econometric models and cross-spectral
  methods. *Econometrica* 37(3), 424-438. https://doi.org/10.2307/1912791
- Geweke, J. (1982). Measurement of linear dependence and feedback between multiple time series.
  *JASA* 77(378), 304-313. https://doi.org/10.1080/01621459.1982.10477803
- Geweke, J.F. (1984). Measures of conditional linear dependence and feedback between time
  series. *JASA* 79(388), 907-915. https://doi.org/10.1080/01621459.1984.10477110
- Barnett, L. and Seth, A.K. (2014). The MVGC multivariate Granger causality toolbox. *Journal of
  Neuroscience Methods* 223, 50-68. https://doi.org/10.1016/j.jneumeth.2013.10.018
- Barnett, L. and Seth, A.K. (2017). Detectability of Granger causality for subsampled
  continuous-time neurophysiological processes. *Journal of Neuroscience Methods* 275, 93-121.
  https://doi.org/10.1016/j.jneumeth.2016.10.016
- Toda, H.Y. and Yamamoto, T. (1995). Statistical inference in vector autoregressions with
  possibly integrated processes. *Journal of Econometrics* 66(1-2), 225-250.
  https://doi.org/10.1016/0304-4076(94)01616-8
- Breitung, J. and Swanson, N.R. (2002). Temporal aggregation and spurious instantaneous causality
  in multiple time series models. *Journal of Time Series Analysis* 23(6), 651-665.
  https://doi.org/10.1111/1467-9892.00284
- Gong, M., Zhang, K., Schölkopf, B., Tao, D. and Geiger, P. (2015). Discovering temporal causal
  relations from subsampled data. *ICML*, PMLR 37, 1898-1906.
- Nalatore, H., Ding, M. and Rangarajan, G. (2007). Mitigating the effects of measurement noise on
  Granger causality. *Physical Review E* 75, 031123. https://doi.org/10.1103/PhysRevE.75.031123
- Malinsky, D. and Spirtes, P. (2018). Causal structure learning from multivariate time series in
  settings with unmeasured confounding. *KDD Workshop on Causal Discovery*, PMLR 92, 23-47.
- Runge, J. (2020). Discovering contemporaneous and lagged causal relations in autocorrelated
  nonlinear time series datasets. *UAI*, PMLR 124, 1388-1397. (PCMCI+)
- Gerhardus, A. and Runge, J. (2020). High-recall causal discovery for autocorrelated time series
  with latent confounders. *NeurIPS* 33. (LPCMCI)
- Schreiber, T. (2000). Measuring information transfer. *Physical Review Letters* 85(2), 461-464.
  https://doi.org/10.1103/PhysRevLett.85.461
- Barnett, L., Barrett, A.B. and Seth, A.K. (2009). Granger causality and transfer entropy are
  equivalent for Gaussian variables. *Physical Review Letters* 103, 238701.
  https://doi.org/10.1103/PhysRevLett.103.238701
- Kraskov, A., Stögbauer, H. and Grassberger, P. (2004). Estimating mutual information. *Physical
  Review E* 69, 066138. https://doi.org/10.1103/PhysRevE.69.066138
- Wibral, M. et al. (2013). Measuring information-transfer delays. *PLoS ONE* 8(2), e55809.
  https://doi.org/10.1371/journal.pone.0055809
- Wollstadt, P. et al. (2019). IDTxl: the Information Dynamics Toolkit xl. *JOSS* 4(34), 1081.
  https://doi.org/10.21105/joss.01081
- Brillinger, D.R. (1996). Remarks concerning graphical models for time series and point
  processes. *Revista de Econometria* 16(1), 1-23.
- ★ Dahlhaus, R. (2000). Graphical interaction models for multivariate time series. *Metrika*
  51(2), 157-172. https://doi.org/10.1007/s001840000055
- ★ Jung, A., Hannak, G. and Goertz, N. (2015). Graphical LASSO based model selection for time
  series. *IEEE Signal Processing Letters* 22(10), 1781-1785.
  https://doi.org/10.1109/LSP.2015.2425434 (verified; arXiv:1410.1184)
- Baccalá, L.A. and Sameshima, K. (2001). Partial directed coherence: a new concept in neural
  structure determination. *Biological Cybernetics* 84(6), 463-474.
  https://doi.org/10.1007/PL00007990
- Takens, F. (1981). Detecting strange attractors in turbulence. In *Dynamical Systems and
  Turbulence*, Lecture Notes in Mathematics 898, 366-381. https://doi.org/10.1007/BFb0091924
- Sauer, T., Yorke, J.A. and Casdagli, M. (1991). Embedology. *Journal of Statistical Physics*
  65, 579-616. https://doi.org/10.1007/BF01053745
- Kennel, M.B., Brown, R. and Abarbanel, H.D.I. (1992). Determining embedding dimension for
  phase-space reconstruction using a geometrical construction. *Physical Review A* 45, 3403.
  https://doi.org/10.1103/PhysRevA.45.3403
- Deyle, E.R. and Sugihara, G. (2011). Generalized theorems for nonlinear state space
  reconstruction. *PLoS ONE* 6(3), e18295. https://doi.org/10.1371/journal.pone.0018295
- Sugihara, G. and May, R.M. (1990). Nonlinear forecasting as a way of distinguishing chaos from
  measurement error in time series. *Nature* 344, 734-741. https://doi.org/10.1038/344734a0
- Sugihara, G. (1994). Nonlinear forecasting for the classification of natural time series.
  *Phil. Trans. R. Soc. A* 348, 477-495. https://doi.org/10.1098/rsta.1994.0106
- ★ Sugihara, G., May, R., Ye, H., Hsieh, C., Deyle, E., Fogarty, M. and Munch, S. (2012).
  Detecting causality in complex ecosystems. *Science* 338(6106), 496-500.
  https://doi.org/10.1126/science.1227079
- ★ Deyle, E.R., May, R.M., Munch, S.B. and Sugihara, G. (2016). Tracking and forecasting
  ecosystem interactions in real time. *Proc. R. Soc. B* 283, 20152258.
  https://doi.org/10.1098/rspb.2015.2258 (verified)
- Ye, H., Deyle, E.R., Gilarranz, L.J. and Sugihara, G. (2015). Distinguishing time-delayed causal
  interactions using convergent cross mapping. *Scientific Reports* 5, 14750.
  https://doi.org/10.1038/srep14750
- McCracken, J.M. and Weigel, R.S. (2014). Convergent cross-mapping and pairwise asymmetric
  inference. *Physical Review E* 90, 062903. https://doi.org/10.1103/PhysRevE.90.062903
- Cobey, S. and Baskerville, E.B. (2016). Limits to causal inference with state-space
  reconstruction for infectious disease. *PLoS ONE* 11(12), e0169050.
  https://doi.org/10.1371/journal.pone.0169050
- Baskerville, E.B. and Cobey, S. (2017). Does influenza drive absolute humidity? *PNAS*
  114(12), E2270-E2271. https://doi.org/10.1073/pnas.1616664114

**Integrated series and cointegration**
- Dickey, D.A. and Fuller, W.A. (1979). Distribution of the estimators for autoregressive time
  series with a unit root. *JASA* 74(366), 427-431. https://doi.org/10.1080/01621459.1979.10482531
- Kwiatkowski, D., Phillips, P.C.B., Schmidt, P. and Shin, Y. (1992). Testing the null hypothesis
  of stationarity against the alternative of a unit root. *Journal of Econometrics* 54, 159-178.
  https://doi.org/10.1016/0304-4076(92)90104-Y
- ★ Engle, R.F. and Granger, C.W.J. (1987). Co-integration and error correction: representation,
  estimation, and testing. *Econometrica* 55(2), 251-276. https://doi.org/10.2307/1913236
- Johansen, S. (1991). Estimation and hypothesis testing of cointegration vectors in Gaussian
  vector autoregressive models. *Econometrica* 59(6), 1551-1580. https://doi.org/10.2307/2938278
- Phillips, P.C.B. (1986). Understanding spurious regressions in econometrics. *Journal of
  Econometrics* 33(3), 311-340. https://doi.org/10.1016/0304-4076(86)90001-1
- Perron, P. (1989). The great crash, the oil price shock, and the unit root hypothesis.
  *Econometrica* 57(6), 1361-1401. https://doi.org/10.2307/1913712
- Zivot, E. and Andrews, D.W.K. (1992). Further evidence on the great crash, the oil-price shock,
  and the unit-root hypothesis. *Journal of Business and Economic Statistics* 10(3), 251-270.
  https://doi.org/10.1080/07350015.1992.10509904

**Delays, distributed lags, deconvolution**
- Almon, S. (1965). The distributed lag between capital appropriations and expenditures.
  *Econometrica* 33(1), 178-196. https://doi.org/10.2307/1911894
- Koyck, L.M. (1954). *Distributed Lags and Investment Analysis*. North-Holland.
- Jorgenson, D.W. (1966). Rational distributed lag functions. *Econometrica* 34(1), 135-149.
  https://doi.org/10.2307/1909858
- Wahlberg, B. (1991). System identification using Laguerre models. *IEEE Trans. Automatic
  Control* 36(5), 551-562. https://doi.org/10.1109/9.76361
- ★ Pillonetto, G. and De Nicolao, G. (2010). A new kernel-based approach for linear system
  identification. *Automatica* 46(1), 81-93. https://doi.org/10.1016/j.automatica.2009.10.031
- Pillonetto, G., Dinuzzo, F., Chen, T., De Nicolao, G. and Ljung, L. (2014). Kernel methods in
  system identification, machine learning and function estimation: a survey. *Automatica* 50(3),
  657-682. https://doi.org/10.1016/j.automatica.2014.01.001
- Jordà, Ò. (2005). Estimation and inference of impulse responses by local projections. *American
  Economic Review* 95(1), 161-182. https://doi.org/10.1257/0002828053828518
- ★ Savic, R.M., Jonker, D.M., Kerbusch, T. and Karlsson, M.O. (2007). Implementation of a transit
  compartment model for describing drug absorption in pharmacokinetic studies. *Journal of
  Pharmacokinetics and Pharmacodynamics* 34(5), 711-726.
  https://doi.org/10.1007/s10928-007-9066-0 (verified)
- Sun, Y.-N. and Jusko, W.J. (1998). Transit compartments versus gamma distribution function to
  model signal transduction processes in pharmacodynamics. *Journal of Pharmaceutical Sciences*
  87(6), 732-737. https://doi.org/10.1021/js970414z
- ★ Goldstein, E., Dushoff, J., Ma, J., Plotkin, J.B., Earn, D.J.D. and Lipsitch, M. (2009).
  Reconstructing influenza incidence by deconvolution of daily mortality time series. *PNAS*
  106(51), 21825-21829. https://doi.org/10.1073/pnas.0902958106 (verified)

**Count time series**
- McKenzie, E. (1985). Some simple models for discrete variate time series. *Water Resources
  Bulletin* 21(4), 645-650. https://doi.org/10.1111/j.1752-1688.1985.tb05379.x
- ★ Al-Osh, M.A. and Alzaid, A.A. (1987). First-order integer-valued autoregressive (INAR(1))
  process. *Journal of Time Series Analysis* 8(3), 261-275.
  https://doi.org/10.1111/j.1467-9892.1987.tb00438.x
- Latour, A. (1997). The multivariate GINAR(p) process. *Advances in Applied Probability* 29(1),
  228-248. https://doi.org/10.2307/1427868
- Pedeli, X. and Karlis, D. (2013). Some properties of multivariate INAR(1) processes.
  *Computational Statistics and Data Analysis* 67, 213-225.
  https://doi.org/10.1016/j.csda.2013.05.019
- Ferland, R., Latour, A. and Oraichi, D. (2006). Integer-valued GARCH process. *Journal of Time
  Series Analysis* 27(6), 923-942. https://doi.org/10.1111/j.1467-9892.2006.00496.x
- Fokianos, K., Rahbek, A. and Tjøstheim, D. (2009). Poisson autoregression. *JASA* 104(488),
  1430-1439. https://doi.org/10.1198/jasa.2009.tm08270
- Liboschik, T., Fokianos, K. and Fried, R. (2017). tscount: an R package for analysis of count
  time series following generalized linear models. *Journal of Statistical Software* 82(5).
  https://doi.org/10.18637/jss.v082.i05
- Davis, R.A., Dunsmuir, W.T.M. and Streett, S.B. (2003). Observation-driven models for Poisson
  counts. *Biometrika* 90(4), 777-790. https://doi.org/10.1093/biomet/90.4.777
- Hawkes, A.G. (1971). Spectra of some self-exciting and mutually exciting point processes.
  *Biometrika* 58(1), 83-90. https://doi.org/10.1093/biomet/58.1.83

Spot-check sources for entries marked "verified":
[DeCAFS arXiv](https://arxiv.org/pdf/2005.01379), [DeCAFS JASA (RePEc)](https://ideas.repec.org/a/taf/jnlasa/v117y2022i540p2147-2162.html),
[Deyle et al. 2016 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4721089),
[Ching and Tam 2017](https://link.aps.org/doi/10.1103/PhysRevE.95.010301),
[Goldstein et al. 2009 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2796142),
[Savic et al. 2007 (citation via PAGE)](https://www.page-meeting.org/Abstracts/the-transit-compartment-model-the-truth-behind-n/),
[Jung et al. 2015 (arXiv)](https://arxiv.org/pdf/1410.1184),
[Haynes et al. 2017 (Lancaster)](https://eprints.lancs.ac.uk/id/eprint/72270),
[Penland and Sardeshmukh 1995 (NOAA PSL)](https://psl.noaa.gov/psd1/pubs/1995/details/penland_01abs.html).
