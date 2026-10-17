# System identification (control engineering and econometrics), read for SD Lab

This is one part of a literature chain. It covers only the system-identification tradition: control
engineering (Ljung, Söderström and Stoica, Schoukens and Pintelon, Billings) and its neighbour in
econometrics (VAR/VECM, instrumental variables, structural breaks, count time series). The tools
survey ([../SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md)) already lists PySINDy,
SysIdentPy, the MATLAB toolbox, Kalman/EM libraries and ruptures as software. This document is about
the *ideas* and how they map onto our pipeline. It does not repeat that survey.

Our problem in this tradition's words: identify a **multivariable, discrete-time, grey-box,
positive (compartmental) state-space model** with partly measured state (hidden stocks), unmeasured
piecewise-constant inputs (outside inflows), announced parameter switches (eras), saturations
(floors at 0, caps), multiplicative nonlinearities (effects), Poisson process noise shared across
the two ends of each flow, operating under its own feedback, judged by k-step-ahead prediction fit
(skill@20, skill@100). The current engine (`sdlab/discovery/matrix.py`) is an **equation-error
(ARX / VARX) estimator with sparse term selection**: each row regresses a stock's change on levels at
t-1 plus a piecewise-constant input, and selection is by BIC.

---

## Summary: what this tradition suggests for us, ranked

1. **Fit with the criterion you are judged by, and do it as multiple shooting.** Equation error
   (one-step least squares) is the maximum-likelihood answer only when the model class is right and
   the noise is white. Ours is never exactly right (hidden stocks, floors, effects), so its bias
   compounds over 20 to 100 steps. The textbook remedy is a prediction-error criterion at the
   horizon of intended use (k-step / simulation error), made tractable by **multiple shooting**
   (short simulated segments, free initial states, continuity penalty). Our `output_error`
   experiment already showed the direction; the literature says to use it for **model selection
   among structures**, not only as a final polish, and to fit H-step segments (Ljung 1999 ch. 7 and
   16; Bock 1983; Ribeiro et al. 2020).
2. **Count hidden stocks from data before searching for where they are.** Fit a long-lag VARX (or
   a subspace method) on the measured stocks; the number of significant Hankel singular values
   beyond the number of measured stocks is the number of hidden states (state order). It is a
   cheap, principled prior for the hidden-stock search, and it says when to stop adding them
   (Ho and Kalman 1966; Van Overschee and De Moor 1994; Jansson 2003; Bauer 2001).
3. **Run residual diagnostics per stock, and let them choose the next structural move.** Whiteness
   of each row's residuals (Ljung-Box), cross-correlation of residuals with every other stock's
   past levels and changes, and with squared levels (Billings-Voon nonlinear tests) say *which row
   is wrong and what it is missing*: lagged correlation means a missing delay (hidden stock),
   correlation with another stock's level means a missing link/effect, correlation with the
   squares means a missing nonlinearity, a step in the running mean means an unannounced input
   change. This is Ljung's identification loop and Kristensen-Madsen's "systematic improvement of
   grey-box models".
4. **Impose the physics as hard constraints: positivity, conservation, stability.** The drain
   matrix of a compartmental system is Metzler with column sums at most zero (discrete time:
   nonnegative entries, column sums at most one). Constrained least squares with those signs, and a
   stability check of the found matrix, removes the runaway models outright (Jacquez 1996; Farina
   and Rinaldi 2000; Lacy and Bernstein 2003; Umenberger et al. 2018).
5. **Identifiability first: check which structures the data can tell apart, and report classes.**
   Structural identifiability of linear compartmental models is a solved question with graph rules
   (Meshkat, Sullivant and Eisenberg 2015; Cobelli and DiStefano 1980). Practical identifiability
   (persistent excitation, informativity: rank and condition number of the regressor matrix,
   profile likelihood) explains most of our "fits about as well" ambiguities and the failures on
   runs that settle to equilibrium. A data-informativity check should gate every structural
   decision (Willems et al. 2005; van Waarde et al. 2020; Raue et al. 2009).
6. **Treat feedback as the main obstacle, and use the only external excitation we have as
   instruments.** All our stocks sit inside loops, and the outside inflows are unmeasured. The
   closed-loop literature says: direct prediction-error methods work if the noise model is right;
   otherwise use instruments that are uncorrelated with the noise (announced era switches, levels
   lagged two or more steps). IV estimates are consistent where least squares is biased by coloured
   residuals (Söderström and Stoica 1983; Forssell and Ljung 1999; Young 2011).
7. **Unannounced input changes are a segmentation problem with a sparsity prior, solved jointly
   with the dynamics.** Sum-of-norms (fused-lasso) segmentation of ARX models and Bai-Perron
   multiple-break tests give the number and dates of input changes, and their penalties are
   calibrated. The known danger, also in our log, is that slow dynamics are collinear with step
   inputs: test that the found breaks are not absorbing a level's slow drift (Ohlsson, Ljung and
   Boyd 2010; Bai and Perron 1998, 2003).
8. **Floors, caps and eras are piecewise-affine (hybrid) identification.** Known switching surfaces
   (stock = 0, stock = cap, era boundaries) make it the easy case: assign each window to a mode,
   fit each mode's affine law with shared parameters where physics says so, or use censored
   (Tobit-style) likelihoods for floored flows (Paoletti et al. 2007; Roll, Bemporad and Ljung
   2004; Lauer and Bloch 2019).
9. **Effects are block-oriented / LPV nonlinearities: identify the linear part first, then the
   static curve.** A stock's level multiplying a flow is a bilinear or linear-parameter-varying
   term; Hammerstein-style alternation (fit rates with the curve fixed, then the curve with rates
   fixed) or FROLS over a small library of products (level × level, level × table basis) finds
   them; validate with the nonlinear correlation tests (Billings 2013; Schoukens and Tiels 2017;
   Tóth 2010).
10. **The noise model matters for counts: a proportional drain with Poisson arrivals is INAR(1).**
    Econometrics of count time series (binomial thinning, INAR/INGARCH) gives consistent
    conditional least squares and exact likelihoods for exactly our "items leave with probability
    k per step" stocks, and says the variance-equals-mean structure is itself identifying
    information (Al-Osh and Alzaid 1987; Weiß 2018). Weighting rows by predicted Poisson variance
    (feasible GLS) is the minimum change.

---

## 1. The prediction-error framework (Ljung)

**Core idea.** A model is a *predictor*: given past data, it predicts the next output. Choose
parameters θ to minimise the size of the prediction errors ε(t, θ) = y(t) − ŷ(t | t−1, θ). With
Gaussian innovations this is maximum likelihood; with the wrong model class it gives the model
whose predictions are closest to the truth in the norm the criterion uses (Ljung 1978, 1999).

```
θ̂ = argmin_θ (1/N) Σ_t ℓ(L(q) ε(t, θ)),     ε(t, θ) = y(t) − ŷ(t | t−k, θ)
```

The key choices are the **predictor horizon k** (one-step = equation error for ARX; k = ∞ is
output/simulation error), the **noise model** (which determines how past errors enter the
predictor), the **prefilter L**, and the **norm ℓ**. A central result: with the true model in the
set, one-step PEM is efficient; when it is not, the limit model minimises a frequency-weighted
misfit whose weighting is set by the input spectrum, the noise model and the prefilter (Ljung 1999,
ch. 8). That is why "fit for intended use" matters (Gevers 2005; Hjalmarsson 2005).

**Model families and how ours map.**

| Family | Equation | Our counterpart |
|---|---|---|
| ARX (equation error) | A(q) y = B(q) u + e | the matrix method: Δx_t = B x_{t−1} + u + e, linear regression |
| ARMAX | A y = B u + C e | ARX plus coloured residuals: what a hidden stock does to a measured row |
| Output error (OE) | y = (B/F) u + e | `output_error` refinement: simulate, then compare |
| Box-Jenkins | y = (B/F) u + (C/D) e | separate dynamics and noise models |
| State space (innovations form) | x_{t+1} = A x + B u + K e, y = C x + e | the full SD model with hidden stocks; K is the Kalman gain |

**What it addresses for us.** Equation error is consistent for our data *only if* every state is
measured, the model class is right and the noise is white. Hidden stocks make the measured rows'
noise coloured (ARMAX), floors and effects make the model class wrong, and windowing changes the
noise. In each case one-step least squares is biased in the direction that helps one-step fit and
hurts 100-step fit. This is the mechanism behind "runaway found models".

**Pipeline step.** Keep least squares as the fast inner engine for scoring thousands of candidate
column sets; re-score the top few structures with a k-step criterion (k = 20 and k = 100, matching
skill@H) using multiple shooting (section 13), and select among structures on that score plus an
order penalty. This is "simulation error in model selection", already listed as an idea in
DISCOVERY-GOAL.md, and the literature supports it as the default when the model class is
approximate (Piroddi and Spinelli 2003; Farina and Piroddi 2012; Shook, Mohtadi and Shah 1991).

**Maturity, implementations.** Fully mature. Python: `statsmodels` (SARIMAX, VARMAX, `MLEModel`
for custom state space), `sippy` (ARX, ARMAX, OE, BJ, subspace; LGPL; PyPI `sippy-unipi`),
SysIdentPy (NARX with free-run simulation error), `scipy.optimize.least_squares` for custom PEM.

**Failure modes.** Output-error and k-step criteria are non-convex and have many local minima,
worse for long horizons and lightly damped or unstable models (Ribeiro et al. 2020). Simulation
error is not a likelihood when there is process noise (our Poisson flows *are* process noise), so
on a correct model it is less efficient than one-step ML. Unstable candidate models make the
simulation blow up: constrain or project to stability first.

---

## 2. Grey-box versus black-box identification

**Core idea.** Black-box: choose a flexible family (ARX order n, NARX, neural net) and let data fix
everything. Grey-box: physics fixes the structure (equations, signs, conservation) and data fixes
the numbers. Bohlin calls the in-between "semi-physical": the modeller proposes physical hypotheses
one at a time and data tests each. Kristensen, Madsen and Jørgensen (2004a, b) formalise grey-box
models as stochastic differential equations estimated by extended-Kalman-filter likelihood, and
give a *systematic improvement* procedure: estimate the model, then estimate each state equation's
process-noise intensity; a large one points at the deficient equation; then model the missing term
nonparametrically against candidate state variables to see what function is missing.

**What it addresses for us.** SD discovery is grey-box structure search: the physics (conservation,
signs, SD rate forms, units) is fixed, the topology and numbers are not. The Kristensen-Madsen loop
is a ready-made answer to "which stock's equation is still wrong and against which variable":
exactly the question our search answers by brute-force trying moves.

**Pipeline step.** After the first structure is found, run a per-stock diagnosis: estimate the
residual (process-noise) variance per row relative to its Poisson expectation (variance ≈ the sum
of the flows' means touching it). Rows whose excess variance is large are deficient. For each, plot
or regress the residual against candidate drivers (other levels, delayed levels, products) with a
smoother (a GAM or binned means); the shape suggests the missing term (linear: link; saturating:
effect; delayed: hidden stock). Only then try search moves on that row.

**Implementations.** CTSM-R (R, `ctsmr`, and its successor `ctsmTMB`) is the reference for
grey-box SDE models. In Python: `statsmodels` `MLEModel`, `dynamax` (JAX, nonlinear and
non-Gaussian SSMs), `pykalman`. The diagnosis step itself is a few dozen lines on our residuals.

**Failure modes.** The diagnosis points at the *row* where the error shows, which may not be the
row where it originates (an unmodelled outflow of A shows as unexplained inflow of B). Use
conservation rows (the per-unit total) to locate it.

---

## 3. Identifiability

### 3.1 Structural identifiability

**Core idea.** A model structure is structurally (globally or locally) identifiable if, with
perfect noise-free data and sufficiently rich inputs, the parameters are uniquely determined by the
input-output map (Bellman and Åström 1970). For linear compartmental models the input-output map is
a transfer matrix C(sI − A)⁻¹B, and identifiability reduces to whether the coefficients of that
map determine the entries of A. Classical results (Cobelli and DiStefano 1980; Godfrey 1983;
Jacquez 1996) and modern graph-theoretic ones (Meshkat, Sullivant and Eisenberg 2015) give rules:
with an input and an output in the same compartment and a strongly connected graph, a model with
at most 2n − 2 flows plus leaks is identifiable for many graph classes; adding a leak to a cycle
can destroy identifiability; *identifiable combinations* (sums, products of rates) are often all
that can be learned. Software: DAISY (Bellu et al. 2007), SIAN (Hong et al. 2019),
StructuralIdentifiability.jl (Julia), STRIKE-GOLDD (MATLAB; Villaverde et al. 2016).

**What it addresses for us.** Our ambiguities are mostly identifiability questions with known
answers:

- **Hidden stock between two measured stocks**: a chain A → H → B with H unmeasured has transfer
  function k_AH k_HB / ((s + k_HB)(s + k_B)) from A's drain to B; swapping the two time constants
  (H's delay and B's own drain) gives the same map unless one end's traffic is measured. Our
  DISCOVERY.md already states this; the compartmental literature proves it and enumerates such
  *indistinguishable* models (Godfrey and Chapman 1990 on "indistinguishability").
- **Move versus link**: a flow A → B at rate k·A and a link (outside → B at k·A, plus A draining to
  outside at k·A) produce the *same mean dynamics*; only conservation rows or the shared-noise
  covariance separate them. That is structural non-identifiability of the mean model, and
  identifiability of the second-moment model: the shared-noise experiment is the right fix.
- **Gap versus proportional plus constant**: identical in linear regression; only signs and
  forms differ.

**Pipeline step.** For every reported structure, compute its *indistinguishable set* under our
model class: enumerate alternatives produced by the known symmetries (swap hidden-delay and drain,
move ↔ link + leak, chain order) and report them as one class rather than searching between them.
For general structures, a cheap local test is the rank of the Jacobian of simulated levels with
respect to parameters at random parameter values (Fisher information rank); a rank deficit means
non-identifiable combinations.

### 3.2 Practical identifiability and persistent excitation

**Core idea.** Even a structurally identifiable model is unidentifiable from data that do not move
enough. An input is *persistently exciting of order n* when its n × n sample autocovariance is
positive definite; for state-space models, data are *informative* for identification when the
stacked matrix [X_−; U_−] of past states and inputs has full row rank (Willems et al. 2005; van
Waarde et al. 2020). Practical identifiability is assessed by the **profile likelihood**: fix one
parameter at a grid of values, re-optimise the rest, and look at how the fit worsens; a flat
profile means the data do not pin it down (Raue et al. 2009; Wieland et al. 2021). Most mechanistic
models are "sloppy": a few stiff parameter combinations, many sloppy ones (Gutenkunst et al. 2007).

**What it addresses for us.** Feedback loops that settle to equilibrium leave levels nearly
constant: the columns "level of A" and "constant" become collinear, and the coefficient of A is
not identified, while k·A* + c is. Short default-length runs are the same problem. This is the
precise statement of "the run did not vary enough". It also explains pieces absorbing dynamics: a
slowly drifting level is nearly collinear with a set of step functions.

**Pipeline step.** (a) Before accepting any coefficient, compute the condition number and the
variance-inflation factor of its column against the others in the row; above a threshold, report
the identifiable combination (the level's coefficient times its mean, plus the constant) instead
of two numbers, and choose the simpler form. (b) For the final model, profile each rate on the
k-step criterion; a flat profile becomes a range in the report ("drain between 0.03 and 0.2 per
step fits about as well"). (c) Report per example how much excitation there was (the singular
values of the centred level matrix); our benchmark-excitation study is this check.

**Failure modes.** Rank tests on noisy data need a noise-aware threshold; profile likelihoods are
expensive (one optimisation per grid point); local (Fisher) analysis misses global ambiguity.

---

## 4. Subspace methods (N4SID, MOESP, CVA) and realisation theory

**Core idea.** Stack past and future data into block Hankel matrices; the projection of future
outputs onto past data has rank equal to the system order n; an SVD gives the order (the gap in
singular values) and an estimate of the state sequence or the extended observability matrix, from
which (A, B, C, D) follow by least squares. No non-convex optimisation; handles MIMO naturally.
Variants differ in weighting: N4SID (Van Overschee and De Moor 1994), MOESP (Verhaegen and
Dewilde 1992), CVA (Larimore 1990). The ancestor is Ho-Kalman realisation from impulse-response
(Markov) parameters, and its noisy version, the eigensystem realisation algorithm (ERA; Juang and
Pappa 1985). Closed-loop-safe variants first fit a high-order ARX model and realise from it
(SSARX, Jansson 2003; PBSID, Chiuso 2007). Order estimation for subspace methods: Bauer (2001).

**What it addresses for us.** *How many hidden stocks are there?* With m measured stocks and order
n̂ > m, there are about n̂ − m hidden states (delays, smoothing stages). Also: a quick linear
baseline model of the whole system, an initial guess for multiple shooting, and a test of whether
the measured stocks already form a state (n̂ ≈ m means no hidden stocks are needed, and any hidden
stock the search proposes is suspect).

**Pipeline step.** Per group of stocks (after our union-find grouping), fit a VARX with p lags
(p chosen by AIC, typically several times the longest plausible delay in windows), treating
announced eras and estimated input pieces as inputs. Form the Hankel matrix of its impulse
responses and take singular values; the count above a noise floor (or chosen by an information
criterion over n) is the state order. Feed n̂ − m as the hidden-stock budget to the search, and the
dominant time constants (eigenvalues of Â) as the candidate delays for hidden stocks, instead of a
fixed 26-value grid.

**Maturity, implementations.** Mature for linear time-invariant systems. Python: `sippy` (N4SID,
MOESP, CVA, PARSIM-K/S/P), `nfoursid` (N4SID with Kalman filter, MIT), `python-control` (Markov
parameters and an ERA function in recent releases), statsmodels VAR for the ARX step. MATLAB's
`n4sid` is the reference.

**Failure modes.** Subspace estimates of A are not constrained to be compartmental, and the state
basis is arbitrary (a similarity transform away from the physical one): they give the order and
the eigenvalues, not the topology. Order estimates are biased low when slow modes are barely
excited (settled loops) and high when there are unmodelled nonlinearities (floors, effects) or
piecewise inputs not given as inputs. Positive realisation of a given transfer function may need a
*higher* order than the minimal one (Benvenuti and Farina 2004), so n̂ − m is a lower bound on the
number of hidden compartments.

---

## 5. Instrumental variables

**Core idea.** Least squares on y = φᵀθ + v is biased when the regressors φ are correlated with
the residual v (coloured noise in an equation-error model, errors in the regressors, feedback).
Instrumental variables replace the normal equations by Σ ζ(t)(y − φᵀθ) = 0, with instruments ζ
correlated with φ but not with v. Classic choices: delayed inputs, or the noise-free output
simulated by a preliminary model (the "auxiliary model" IV). Refined IV (RIV, SRIVC) iterates
prefilters and instruments and reaches the efficiency of ML for Box-Jenkins models (Young 1976;
Young and Jakeman 1980; Söderström and Stoica 1983; Young 2011). SRIVC is the standard for
continuous-time models from sampled data (Garnier and Wang 2008).

**What it addresses for us.** Two biases. (1) A hidden stock left unmodelled puts a delayed copy of
past flows into a measured row's residual: coloured noise correlated with lagged levels, so least
squares biases drains. (2) The "drain bias" in our shared-noise log: inflow pieces and a level's
drain compete for the same variance. Instruments that move the level but not the residual (the
announced era switches, the level two or more windows back, an auxiliary model's simulated level)
estimate the drain consistently.

**Pipeline step.** For a chosen structure, re-estimate each row's coefficients by IV with the
instruments = levels simulated by the current model (auxiliary-model IV), iterate twice. Compare IV
and LS coefficients: a large gap flags a row whose residual is correlated with its regressors,
which is itself a structural diagnostic (a missing delay or a misplaced flow), the Durbin-Wu-Hausman
idea from econometrics.

**Maturity, implementations.** Mature. Python: `linearmodels` (IV2SLS, IVGMM; econometric
convention), `statsmodels` (`IV2SLS` in sandbox), easy to hand-roll. CONTSID (MATLAB) for SRIVC.

**Failure modes.** Weak instruments (barely correlated with the regressor) give huge variance and
bias towards least squares: in settled runs nothing is a strong instrument. Instruments must be
uncorrelated with the noise *including* unmodelled dynamics, which simulated levels from a wrong
model may not be.

---

## 6. Closed-loop identification

**Core idea.** Under feedback, the input is correlated with past noise, so methods that assume
open-loop data (OE, subspace without care, spectral analysis, plain IV with input instruments)
become biased. Forssell and Ljung (1999) classify approaches: **direct** (apply PEM to input and
output as if open-loop; consistent if the noise model is flexible enough to contain the truth),
**indirect** (identify the closed loop from an external reference, then solve for the plant using
a known controller), and **joint input-output** (treat input and output as outputs of a system
driven by the reference; two-stage and projection methods, Van den Hof and Schrama 1993). In every
case, identifiability needs either an **external excitation** (a reference signal) or a
sufficiently complex/nonlinear/switching feedback law (Gevers et al. 2009). Dynamic network
identification extends this to many interconnected modules: which modules are identifiable from
which measured nodes and which excitations (Van den Hof et al. 2013; Gonçalves and Warnick 2008;
Hendrickx, Gevers and Bazanella 2019), and topology detection from measured nodes (Materassi and
Innocenti 2010; Chiuso and Pillonetto 2012 for sparse Bayesian topology).

**What it addresses for us.** An SD model *is* a closed loop: every flow's rate depends on levels it
changes. There is no controller to separate out; the only external signals are the outside inflows
(unmeasured, piecewise constant) and announced era switches (known). Lessons:

- The **direct** approach is what we do (regress on levels). It is consistent only if the noise
  model is right: white residuals per row. Coloured residuals (hidden stocks) break it. This again
  argues for residual whiteness tests as acceptance criteria.
- **Excitation comes from inputs, not from loops.** A loop that settles produces no information.
  Era switches and inflow changes are the experiments; the data informativity depends on how many
  there are and how big.
- The **network identification** results answer "which flows can we identify given which stocks
  are measured?" for our hidden-stock cases: a module (flow) is identifiable when its input node is
  measured and its output node is measured or excited, with conditions on parallel paths
  (Hendrickx et al. 2019). Our "a hidden stock is identifiable when the traffic at one end is
  counted" is a special case.

**Pipeline step.** Treat announced eras as the external reference: (1) use era indicators and their
interactions with levels as instruments (section 5); (2) weight the structure search towards
windows just after era switches and inflow changes, where excitation is rich (or at least report
the share of the run that carries information); (3) when two structures remain, ask which era
switch separates them (section 14).

**Failure modes.** With no external excitation and a linear, time-invariant loop, some structures
are fundamentally unidentifiable; no algorithm fixes that. Nonlinearities (floors, caps) help: a
loop that hits a floor changes its law, which is a natural excitation.

---

## 7. Nonlinear system identification: NARMAX and FROLS structure detection

**Core idea.** NARMAX (Leontaritis and Billings 1985) models y(t) = F(y(t−1..), u(t−1..), e(t−1..))
+ e(t) with F a sum of candidate terms (usually polynomial monomials). The number of candidate
terms explodes, so structure detection is the main problem. **FROLS** (forward regression with
orthogonal least squares; Chen, Billings and Luo 1989; Billings, Chen and Korenberg 1989) adds terms
greedily: orthogonalise each candidate against the selected ones (Gram-Schmidt), compute its
**error reduction ratio** ERR = share of output variance it explains, add the best, stop by an
information criterion or ERR threshold. Then fit a noise model (the MA part) by extended least
squares to unbias the process terms. Validation uses the correlation tests below (Billings and Voon
1986). Weaknesses and fixes: one-step ERR can pick wrong terms when the regressors are correlated
or noise is coloured; *simulation-error* selection (Piroddi and Spinelli 2003), mutual-information
variants (Wei and Billings 2008), bootstrap and Bayesian variants (Baldacchino, Anderson and
Kadirkamanathan 2013), and steady-state or sign constraints for grey-box NARX (Aguirre et al. 2004).
Overparametrised NARMAX models can show spurious dynamics such as instability or chaos even with
small one-step errors (Aguirre and Billings 1995): our runaway models.

**What it addresses for us.** Our stepwise BIC selection is a cousin of FROLS. FROLS adds: an
orthogonalised, order-independent measure of each candidate's contribution; a noise-model step that
removes coloured-noise bias; a mature literature on why one-step selection fails and simulation-
based selection fixes it. Our candidate terms differ (flow columns spanning two rows rather than
per-row monomials), so FROLS must work on *stacked* rows: the candidate is a flow column (−ratio in
the source row, +1 in the target row) and ERR is computed on the stacked, weighted residual.

**Pipeline step.** Already listed as [../frols.md](../frols.md). Concretely: (1) build the stacked
design over all rows of a group (we already do, via normal equations); (2) replace "best move
improving BIC by > 2" with "best ERR among flow columns, orthogonalised against chosen columns",
with BIC stopping; (3) follow it with a simulation-error pruning pass (Piroddi-Spinelli): drop each
term in turn and keep the drop if 20-step simulation error does not worsen.

**Implementations.** SysIdentPy (BSD-3, FROLS, AOLS, MetaMSS, ER, information criteria, free-run
simulation), PySINDy's `FROLS` optimiser. Neither supports cross-row (flow) columns natively; the
algorithm is 50 lines over our cached Gram matrix.

**Failure modes.** Greedy forward selection cannot recover terms that only help in pairs (our
"chains"); ERR depends on the scaling of the rows (our jitter weights); correlated candidates (a
level and its delayed copy) make the choice arbitrary.

---

## 8. Block-oriented models (Hammerstein, Wiener) and LPV models for effects

**Core idea.** Approximate a nonlinear system by connecting linear dynamic blocks and static
nonlinear blocks: Hammerstein (static nonlinearity, then linear dynamics), Wiener (linear dynamics,
then static nonlinearity), and their series combinations (Giri and Bai 2010). Identification
strategies: alternate between the linear block and the nonlinear block (Narendra and Gallman 1966);
over-parametrise the product and recover the factors by SVD (Bai 1998); start from the best linear
approximation, which already reveals the linear blocks' poles (Schoukens and Tiels 2017). Linear
parameter-varying (LPV) models let the coefficients depend on a scheduling variable p(t), A(p) =
A₀ + p A₁ + ..., which covers bilinear systems where a state multiplies another (Tóth 2010).

**What it addresses for us.** An SD *effect* (flow rate = base rate × f(level of C), f a line or a
lookup table) is a quasi-LPV term: the flow's coefficient is scheduled by C's level. If the rate's
other inputs are fixed, it is a Hammerstein-type static nonlinearity on C. Both say: find the
linear structure first, then let one coefficient vary with a candidate scheduler, then shape f.

**Pipeline step.** For each found flow, test effects as follows. (1) Expand the flow's coefficient
in a small basis of a candidate scheduler C: k(C) = k₀ + k₁ C (linear effect) or k₀ Σ w_j B_j(C)
with B_j piecewise-linear hat functions on C's range (a table). The flow column becomes a few
columns (level of A × B_j(C)): still linear in the parameters, so it enters our regression and
pays by BIC. (2) Screen schedulers by the correlation of the flow's residual with level(A) ×
level(C) (the Billings-Voon test, section 12). (3) Refine f by alternating: fix f, fit rates; fix
rates, fit f's table values with monotonicity constraints (an SD lookup is usually monotone).

**Implementations.** No Python package targets this exactly. SysIdentPy can include product
regressors (polynomial degree 2) and so screens bilinear effects. `pwlf` or scikit-learn's
`SplineTransformer` gives the hat basis. MATLAB has `nlhw` (Hammerstein-Wiener).

**Failure modes.** The scheduler must vary enough over the run (an effect of a stock that stays
near its equilibrium is unidentifiable: f is only seen at one point). Product terms are collinear
with the linear terms when the scheduler varies little. The scale of f and of the base rate trade
off (normalise f to 1 at a reference level, as SD does).

---

## 9. Piecewise-affine and hybrid system identification

**Core idea.** A PWA model is a set of affine laws, one per region of the regressor space, plus the
switching rule. Identification must assign data to modes, estimate each mode's parameters, and
estimate the region boundaries. Methods: clustering of local models (Ferrari-Trecate et al. 2003),
bounded-error (Bemporad et al. 2005), mixed-integer programming for global optimality on small
problems (Roll, Bemporad and Ljung 2004), algebraic methods (Vidal et al. 2003), sum-of-norms
regularisation to make parameters piecewise constant over time (Ohlsson and Ljung 2013), and
modern recursive or classification-based algorithms (Breschi, Piga and Bemporad 2016; Bemporad
2023 "PARC"). Tutorials and surveys: Paoletti et al. (2007), Garulli, Paoletti and Vicino (2012),
the book by Lauer and Bloch (2019). Econometrics: threshold autoregression (Tong) and Markov
switching (Hamilton 1989) are the same idea with an unobserved regime.

**What it addresses for us.** Three of our features are hybrid modes with *known or easily
estimated* switching surfaces, the easy case of PWA identification:

- **Floors at 0**: a flow's law is max(0, c + a·A + b·B). On windows where it is floored, the law
  is "zero"; where not, it is affine. Mode assignment: predicted rate < 0, or the source stock at 0.
- **Capacity caps**: outflow ≤ what the stock holds; the mode is "capped" when the demand exceeds
  the content. Same structure.
- **Announced eras**: switching on time with known switch times. Unannounced internal-rate changes:
  switching on time with unknown times (sum-of-norms or Bai-Perron, section 10).

**Pipeline step.** Iteratively reweighted / mode-assigned least squares: (1) fit; (2) mark windows
where a flow would go below zero or above its source's content under the current fit, or where the
source is at 0; (3) refit using only unconstrained windows for that flow's coefficients (or a
censored likelihood, Tobit 1958, which uses the floored windows as "rate ≤ 0" information); (4)
repeat until the mode assignment stops changing. Our [../floors-and-caps.md](../floors-and-caps.md)
experiment is the first instance; the hybrid literature says to alternate assignment and fit, and
to check for local minima by multiple starts.

**Implementations.** `pyparc` (Bemporad's PARC, Python), `scikit-learn` for clustering variants,
statsmodels `MarkovRegression` / `MarkovAutoregression` for unknown regimes, `cvxpy` for
sum-of-norms. The HySI MATLAB toolbox for older methods.

**Failure modes.** With unknown surfaces, PWA identification is NP-hard and sensitive to
initialisation. Few data in a mode give poor estimates of that mode (a stock that hits zero three
times). Mode assignment from a biased initial fit can lock in the bias.

---

## 10. Structural breaks and unknown input changes (econometrics and sysid)

**Core idea.** Detect and date changes in a regression's parameters or intercept. Econometrics:
Chow (1960) test at a known date; Andrews (1993) sup-F at an unknown date; Bai and Perron (1998,
2003) for multiple breaks with dynamic programming and a sequential test or information criterion
for the number. Sysid: segmentation of ARX models with sum-of-norms (group fused lasso) on
parameter differences (Ohlsson, Ljung and Boyd 2010); ℓ1 trend filtering for piecewise-constant or
piecewise-linear signals (Kim et al. 2009). Statistics: PELT (Killick et al. 2012; we already use
it).

**What it addresses for us.** Unannounced outside-inflow changes are breaks in each row's
intercept. The key lesson for us from this literature is **joint estimation**: dating the breaks
from residuals of a dynamics model fitted without them is biased; dating them with the dynamics
fixed absorbs dynamics into the intercept. Bai-Perron estimate the slopes and the breaks jointly,
and give the slopes' asymptotics *given* the breaks. The second lesson is the **penalty**: the
number of breaks should be chosen by a criterion calibrated for break dating (BIC-type with a
penalty growing in log n, or the sequential sup-F tests), not a free tuning constant.

**Pipeline step.** (1) Estimate dynamics and intercept breaks jointly by alternating: given levels'
coefficients, segment the residual intercept (PELT with a Poisson or Gaussian cost and a BIC
penalty); given segments, refit coefficients. (2) Add a guard against pieces absorbing dynamics:
after fitting, regress the piece means on the level means over the same segments; a strong
relation means the pieces are tracking a level (a missing flow), as our `level_for_pieces` already
suspects. (3) Report each break with a confidence interval (Bai 1997 gives them).

**Implementations.** `ruptures`; statsmodels (`breaks_cusumolsresid`, `breaks_hansen`, recursive
residuals via `RecursiveLS` with CUSUM); `cvxpy` for fused lasso; R `strucchange` is the reference
for Bai-Perron.

**Failure modes.** Slow drifts in a level look like many small breaks (and vice versa); breaks near
the ends of the run are poorly dated; joint estimation is non-convex.

---

## 11. Errors-in-variables and noisy regressors

**Core idea.** When the regressors themselves are measured with noise, least squares is biased
towards zero (attenuation). EIV methods (total least squares, Frisch scheme, bias-compensated LS,
IV) correct this (Söderström 2007, 2018; Markovsky and Van Huffel 2007).

**What it addresses for us.** Our *levels* are exact counts, so classical EIV does not apply to
regressors measured at window starts. It does apply whenever we regress on a *derived* noisy
regressor: a delayed copy of a level (a filtered noisy series), an estimated inflow, an estimated
hidden-stock level, a window's *mean* level (which contains part of the same Poisson draws as the
window's change: a simultaneity bias), or when snapshot levels of fast stocks are readings of a
busy-ness that varies within the step (section 8 of DISCOVERY.md: "a level is a noisy reading of
how busy a stock was"). In those cases coefficients are attenuated and links leak to correlated
siblings, which is what the link screener's sibling rules patch by hand.

**Pipeline step.** Use predetermined regressors (levels at the start of the window, as
`matrix.py` does) wherever possible. Where a regressor is a mean over the step or an estimate, use
IV with the lagged level as the instrument, or bias-compensated LS with the regressor-noise
variance estimated from the Poisson structure (variance of a count ≈ its mean). Check: compare the
drain estimated from window-start levels with the one from window-mean levels; a systematic gap
measures the simultaneity bias.

**Failure modes.** EIV corrections need the noise variance ratio; wrong ratios over-correct. The
Frisch scheme gives a set, not a point.

---

## 12. Model validation: residual whiteness, correlation tests, cross-validation

**Core idea.** A model is not validated by its fit but by what it leaves: residuals should be white
and uncorrelated with past inputs (Ljung 1999, ch. 16). Tests: autocorrelation of residuals within
confidence bands ±1.96/√N; Ljung-Box (1978) portmanteau statistic Q = N(N+2) Σ_k r_k² / (N − k);
cross-correlation of residuals with past inputs (a significant correlation at lag k means a missing
dynamic path with that delay). For nonlinear models, Billings and Voon (1986) and Billings and Zhu
(1994) add higher-order tests, e.g. correlations of ε with ε·u, with u² − mean(u²), and of ε² with
u²; significant ones point to missing nonlinear terms. For state-space models, the Kalman
innovations must be white with the predicted covariance (Mehra and Peschon 1971). **Cross-
validation** on time series: hold out contiguous blocks, leave a gap (hv-block, Racine 2000), or
use forward-chaining; for purely autoregressive models with uncorrelated errors, ordinary k-fold is
valid (Bergmeir, Hyndman and Koo 2018). Validation should be on *simulation* (free-run) or k-step
prediction for the intended horizon (Ljung's `compare` with horizon k).

**What it addresses for us.** Our search judges a structure by BIC on fit; our grader judges skill
at 20 and 100 steps. The validation literature says the structure is acceptable only when, in
addition, residuals per row are white, uncorrelated with every stock's past levels, and the
conservation row's residual is white. Each failed test names a defect:

| Failed test on row s | Likely missing structure |
|---|---|
| ε_s autocorrelated at lags 1..L | a hidden stock feeding s (delay), or a mis-specified drain |
| ε_s correlated with past levels of A at lag k | a flow or link from A with a delay of about k |
| ε_s correlated with level(A) × level(C) | an effect of C on a flow from A |
| ε_s correlated with level(s) beyond 0 or near its cap | a floor or cap regime |
| running mean of ε_s steps | an unannounced input change |
| conservation-row residual nonzero | a flow to or from outside (or a hidden stock) |
| residual variance ≫ Poisson expectation | missing structure on that row, or overdispersion |

Our [../held-out-judge.md](../held-out-judge.md) was rejected on benchmark v1. The literature
offers a reason: a single held-out block in a run with few excitation events often contains no
event, so it cannot tell structures apart; hv-block or forward-chaining with several folds, or
cross-validation on *k-step* error, are the standard alternatives.

**Pipeline step.** Add a `diagnose(model, run)` step that computes the table above for every row
and returns ranked suggestions; let the search try those moves first. Accept a structure only if
it passes (or the remaining failures are reported). This is the inner loop of Ljung's procedure
(section 17).

**Implementations.** statsmodels `acorr_ljungbox`, `ccf`; SysIdentPy has residual correlation
tests (`compute_residues_autocorrelation`, `compute_cross_correlation`); simple to write.

**Failure modes.** Many rows × lags × candidates means many tests: control the false-discovery
rate (Benjamini-Hochberg) or use the same √(2 ln m)/√n bar our grouping uses. Whiteness tests have
low power on short runs. Floors, eras and inflow pieces all leave structure in residuals: diagnose
in the order "input changes, floors, links, delays, effects" to avoid blaming the wrong cause.

---

## 13. Multiple shooting and k-step fitting

**Core idea.** Fitting an ODE or a long simulation to data by single shooting (simulate from t₀,
compare everywhere) has a rugged, multimodal objective, and trajectories can diverge for bad
parameters. **Multiple shooting** (Bock 1983; Bock and Plitt 1984; Baake et al. 1992) splits the
horizon into segments, gives each segment its own initial state as a free parameter, simulates
each segment, and adds continuity constraints (or penalties) that the end of segment i equals the
start of segment i+1. The problem is larger but much better conditioned; the estimator is
consistent and the landscape is smoother (Peifer and Timmer 2007; Ribeiro et al. 2020 prove the
smoothing effect for nonlinear sysid). Related: **k-step-ahead prediction error** (Shook, Mohtadi
and Shah 1991; Farina and Piroddi 2012), and the **truncated simulation loss** of SUBNET (Beintema,
Tóth and Schoukens 2021, 2023): an encoder estimates the state at many start times, the model is
simulated T steps from each, and the loss averages the T-step errors. Collocation and profiling
(Varah 1982; Ramsay et al. 2007) are the smooth-data alternatives.

**What it addresses for us.** Skill@H is exactly a multiple-shooting criterion: about 150 start
moments, measured states as initial conditions, H-step simulation. So **the grader's criterion is
already in multiple-shooting form; fit with the same form.** Measured stocks are known initial
states; hidden stocks' initial contents are the free shooting parameters; outside inflows are fixed
as estimated (per our output-error lesson). This replaces 100-step single-shooting refinement
(non-convex, prone to run away) with many short segments.

**Pipeline step.** `refine_by_shooting(structure, run, H)`: segments of length H starting every
H/2 steps; parameters = rates (bounded to compartmental signs) + hidden-stock initial contents per
segment; residuals = simulated minus measured levels, weighted by Poisson variance; solve with
`scipy.optimize.least_squares` (trust-region, Jacobian by finite differences or JAX). Use it (a) to
refine the chosen structure and (b) to re-score the top-N structures from the fast search, picking
the best by shooting error + BIC-style penalty. Start with H = 20; add H = 100 if 20 is stable.

**Implementations.** `scipy.optimize.least_squares`; JAX + `diffrax` or `jaxopt`/`optax` for
gradients (our [../gradient-descent.md](../gradient-descent.md) experiment); CasADi (Python
bindings, LGPL) is the standard tool for multiple shooting with constraints; `deepSI` (Python) has
SUBNET; `pyPESTO` (Python) for profile likelihoods and multi-start.

**Failure modes.** Segment length is a bias-variance knob: short segments behave like one-step
fits, long ones regain the ruggedness. Free hidden initial states per segment can absorb misfit
(too much freedom): penalise their discontinuity or tie them to the model's own prediction.

---

## 14. Optimal input and experiment design

**Core idea.** Choose inputs to maximise information about the parameters (D-optimal: maximise
det of the Fisher information; A-, E-optimal variants) under power or amplitude constraints
(Mehra 1974; Goodwin and Payne 1977; Pronzato 2008). Practical signals: PRBS, multisines with
Schroeder phases (Pintelon and Schoukens 2012). Robust and closed-loop design (Rojas et al. 2007;
Hjalmarsson 2005, 2009): design for the intended use, "least costly" experiments that are just
informative enough (Gevers et al. 2009). For choosing *between* rival structures: T-optimal and
Box-Hill designs maximise the expected divergence between models' predictions (Box and Hill 1967;
Atkinson and Fedorov 1975).

**What it addresses for us.** SD Lab controls the machines in live runs, so it can choose era
switches. When two structures fit the history equally, the best next experiment is the change (a
capacity, a machine) that makes their predictions differ most, relative to Poisson noise.
Identifiability analysis (section 3) tells which parameters are poorly determined; the D-optimal
design tells which change helps most.

**Pipeline step.** For the alternatives that discovery reports ("fits about as well"), simulate
each under a menu of candidate interventions (each available knob up or down by a step) and rank
interventions by the predicted divergence (sum over stocks of squared difference divided by
Poisson variance), discounted by cost. Report the top one as "to tell these apart, try ...".
Actually running it needs the user's sign-off ([../experiment-design.md](../experiment-design.md)).

**Implementations.** No dedicated Python package for sysid input design; the divergence ranking is
simulation only. `pyPESTO`/AMICI and `pyomo.contrib.doe` (Pyomo.DoE) for model-based design of
experiments on ODE/DAE models.

**Failure modes.** Locally optimal designs depend on the unknown parameters (use the ensemble of
alternatives, as above). Interventions on real systems have costs and risks.

---

## 15. Model order selection and regularisation

**Core idea.** Choosing the number of parameters by an information criterion: FPE and AIC
(Akaike 1970, 1974), BIC (Schwarz 1978), MDL (Rissanen 1978), Hannan-Quinn (1979), AICc for small
samples (Hurvich and Tsai 1989); review in Stoica and Selén (2004). AIC targets prediction and
tends to overfit structure; BIC is consistent for the true order when the true model is in the set.
Modern sysid argues for **regularisation instead of order selection**: estimate a high-order model
with a prior that encodes stability and smoothness (kernel-based / Gaussian-process impulse
responses with TC, DC or stable-spline kernels; hyperparameters by marginal likelihood;
Pillonetto and De Nicolao 2010; Chen, Ohlsson and Ljung 2012; Pillonetto et al. 2014; Ljung, Chen
and Mu 2020; Chiuso and Pillonetto 2019).

**What it addresses for us.** (1) We use BIC with hand-set extra prices; the literature gives the
theory for these (they are priors in a MAP score; MDL justifies prices for structural choices like
"to or from outside"). (2) **Hidden-stock delay kernels**: instead of a grid of exp/erlang/pipe
shapes at 26 delays, estimate the *impulse response* from A's drain to B's arrivals as a
regularised FIR with a TC/stable-spline kernel (a nonnegative, decaying, smooth curve), then read
its shape (exp, erlang, pipe) and mean delay from it. This is one convex fit per pair instead of 78.

**Pipeline step.** (a) For a candidate source-target pair, fit B's residual on a long FIR of A's
outflow with a TC kernel prior and nonnegativity; the area is the share that arrives, the centroid
the mean delay, the shape tells the kernel. (b) Keep BIC for the structure search but use AICc or
held-out k-step error when windows are few (default lengths).

**Implementations.** Kernel-based FIR is ridge regression with a specific prior covariance:
a few lines with numpy; MATLAB `impulseest`/`arxRegul` are the references. `sklearn`
GaussianProcessRegressor for the hyperparameters if wanted.

**Failure modes.** Information criteria assume nested, regular models; structural choices
(hidden stock or not) are often non-nested and at a boundary. Long FIRs need long runs.

---

## 16. Positive and compartmental systems

**Core idea.** A system whose states stay nonnegative for nonnegative inputs is positive; in
continuous time its A is Metzler (off-diagonal ≥ 0); compartmental systems add mass balance: column
sums ≤ 0 (each column's outflows do not exceed the compartment's loss) (Jacquez 1996; Farina and
Rinaldi 2000; Haddad, Chellaboina and Hui 2010). Compartmental matrices are always stable
(eigenvalues in the closed left half-plane), and strictly stable if every compartment has a path to
outside. Positive realisation (finding a positive state-space model for a given transfer
function) may require more states than the minimal realisation (Benvenuti and Farina 2004).
Identification with positivity: constrained least squares / PEM, and externally positive system
identification (Grussler, Umenberger and Manchester 2017); stability-constrained identification
(Lacy and Bernstein 2003; Umenberger et al. 2018).

**What it addresses for us.** The discrete-time drain matrix of an SD model with proportional and
linear flows is I + S·K with nonnegative off-diagonal entries (flows into s from j), diagonal
entries ≤ 1, and column sums ≤ 1 (what leaves j cannot exceed j). Every runaway found model
violates this. Links and effects break pure compartmentality (a link creates material), which is
exactly why they need evidence: they are the only structures that can make a loop unstable.

**Pipeline step.** (1) Fit rows with sign constraints (nonnegative least squares on flow columns;
`scipy.optimize.lsq_linear` with bounds, or `nnls`). (2) After fitting, compute the spectral radius
of the found matrix within each era; reject or penalise structures whose radius exceeds 1 unless a
link or effect explains growth and the data show growth (sd-population). (3) Count hidden stocks
needed for a positive realisation of the delays found (section 4).

**Implementations.** `scipy.optimize.lsq_linear`, `nnls`, `cvxpy` for column-sum constraints. No
off-the-shelf compartmental identification package in Python.

**Failure modes.** Constraints active at the solution bias estimates (a drain that should be 0.001
pinned at 0). Growing systems (population) are legitimately unstable.

---

## 17. Econometric tools that fit our structure

- **VAR / VECM and cointegration.** Δx_t = Π x_{t−1} + Γ Δx_{t−1} + μ_t + ε_t is literally our row
  form (Engle and Granger 1987; Johansen 1991). Π = S·K has reduced rank: its rank is at most the
  number of level-driven flows, and conservation puts 1ᵀ in the left null space of S for internal
  moves. Final stocks (never drain) and stocks with no drain are unit roots. **Reduced-rank
  regression** (Johansen's procedure) estimates the number of independent level-driven flows
  before choosing which ones, another order estimate. statsmodels has `VECM` and
  `select_coint_rank`.
- **Spurious regression** (Granger and Newbold 1974). Regressing one trending series on another
  gives "significant" coefficients by chance. Our open idea "links driven by a final, ever-growing
  stock are suspect" ([../output-error.md](../output-error.md)) is exactly this: an I(1) or trending
  regressor against a stationary residual. Remedy: never use an ever-growing stock's level as a
  driver without differencing or a cointegration test; use its *gains* (its inflow) instead.
- **Heteroskedasticity-robust inference and feasible GLS** (White 1980). Poisson noise makes
  variance proportional to the flows: weight each window by the inverse of its predicted variance
  (iterate once), and use sandwich standard errors for coefficient tests.
- **Count time series.** A stock where each item leaves with probability k per step and arrivals are
  Poisson is an **INAR(1)** process, X_t = (1 − k) ∘ X_{t−1} + ε_t, with ∘ binomial thinning
  (McKenzie 1985; Al-Osh and Alzaid 1987); multivariate versions (Latour 1997) cover moves between
  stocks; INGARCH / Poisson autoregression (Ferland, Latour and Oraichi 2006) covers
  level-dependent rates. Conditional least squares is consistent; ML via the convolution of
  binomial and Poisson. The conditional variance, k(1 − k)X_{t−1} + λ, identifies the drain
  independently of the mean (our shared-noise open idea "variance equals mean"). Reference: Weiß
  (2018). Mechanistic count models with Euler-multinomial flows and particle filtering (Bretó et al.
  2009; Ionides, Bretó and King 2006; R `pomp`) are the epidemiology version of the same model.
- **Granger causality and its limits** already covered in the tools survey; the sysid view is that
  Granger tests are a one-step residual cross-correlation test (section 12).

---

## 18. Workflow: how this tradition proceeds with a lot of data and an unknown system

Ljung's "system identification loop" (Ljung 1999, ch. 1 and 16; Schoukens and Ljung 2019 for the
nonlinear road map) is: **prior knowledge → experiment design → data → choose a model set →
choose a criterion → compute the model → validate → if not good enough, revise one of the earlier
choices**. The user-oriented road map for nonlinear systems (Schoukens and Ljung 2019) adds: start
linear, measure how nonlinear the system is, and add nonlinearity only where the linear model's
residuals show it. Translated into the order of decisions for our engine:

1. **Look at the data before modelling.** Plot levels, changes and the per-unit totals. Detect
   saturations (time spent at 0 or at caps), trends (growing final stocks), visible breaks, and how
   fast each stock turns over (lag-1 autocorrelation). Compute **excitation**: singular values of
   the centred level matrix, number and size of era switches and apparent input changes. This
   decides what is identifiable at all and how much complexity the data can pay for.
2. **Preprocess honestly.** Choose the window from the dynamics (shortest time constants), not only
   from the count of windows; remove known flows; mark floored and capped windows; do not
   detrend stocks whose trend is the signal.
3. **Fit the simplest global linear model first** (VARX/ARX on all stocks of a group with
   era-dummies and a constant per stock) to get the **orders**: number of hidden states (Hankel
   singular values / subspace), rank of the level-driven part (reduced-rank regression), dominant
   time constants. This is the "best linear approximation" and the reference to beat.
4. **Estimate unknown inputs jointly with the dynamics** (segmentation with calibrated penalty), and
   check that breaks are not absorbing level dynamics.
5. **Grey-box structure search** with physics as hard constraints (conservation, signs,
   compartmental matrix, units), using the order estimates as budgets. Prefer structured columns
   (flows) over per-row terms. Use a fast equation-error score for the inner loop.
6. **Diagnose residuals row by row** (whiteness, cross-correlation with other stocks' lagged levels,
   with products, with floors, with conservation). Each failure proposes a specific move. Iterate
   steps 5-6. This is where effects, hidden stocks and floors are added: **only where residuals ask
   for them**.
7. **Re-estimate the top structures with the intended-use criterion** (multiple-shooting k-step
   error at H = 20 and 100, Poisson-weighted), with IV or noise-model correction where residuals
   are coloured, and stability enforced.
8. **Validate on held-out excitation events** (blocked CV, forward-chaining), on free-run
   simulation, and on stability. Compare against the linear baseline of step 3: a structured model
   that predicts worse than the black-box VARX is missing something.
9. **Quantify what is not identifiable.** Profile likelihoods for rates; indistinguishable
   structure classes; report them instead of picking arbitrarily.
10. **Design the next experiment** for what remains ambiguous, if the system can be perturbed.

**Diagnostics that reveal structure, as a checklist:**

- per-unit total residual (conservation row): flows to/from outside and hidden stocks;
- Hankel singular values of a long VARX: number of hidden states;
- eigenvalues of the found drain matrix: stability, dominant delays;
- residual autocorrelation per row: missing delays;
- residual cross-correlation with lagged levels of others: missing flows/links and their delays;
- residual correlation with products of levels: effects;
- residual against own level near 0 or cap: floors and caps;
- recursive (rolling-window) coefficient estimates and CUSUM of residuals: unannounced changes;
- residual variance against Poisson expectation: missing structure versus pure noise;
- residual covariance across rows: moves (mirrored), links (independent), co-flows (scaled);
- LS versus IV coefficient gap: residuals correlated with regressors (misplaced structure).

**What the tradition warns against:** selecting structure by one-step fit alone; adding
nonlinearity before the linear part is right; trusting parameters from data without excitation;
using validation data that contain no events; and treating a model that fits well as validated
without residual tests.

---

## 19. Reading list

Core textbooks and surveys
- Ljung, L. (1999). *System Identification: Theory for the User*, 2nd ed. Prentice Hall. ISBN 0-13-656695-2.
- Söderström, T., Stoica, P. (1989). *System Identification*. Prentice Hall. Free PDF: https://user.it.uu.se/~ts/sysidbook.pdf
- Pintelon, R., Schoukens, J. (2012). *System Identification: A Frequency Domain Approach*, 2nd ed. Wiley-IEEE. doi:10.1002/9781118287422
- Ljung, L. (2010). Perspectives on system identification. *Annual Reviews in Control* 34(1):1-12. doi:10.1016/j.arcontrol.2009.12.001
- Schoukens, J., Ljung, L. (2019). Nonlinear system identification: A user-oriented road map. *IEEE Control Systems Magazine* 39(6):28-99. doi:10.1109/MCS.2019.2938121
- Chiuso, A., Pillonetto, G. (2019). System identification: A machine learning perspective. *Annual Review of Control, Robotics, and Autonomous Systems* 2:281-304. doi:10.1146/annurev-control-053018-023744
- Walter, E., Pronzato, L. (1997). *Identification of Parametric Models from Experimental Data*. Springer.
- Åström, K.J., Eykhoff, P. (1971). System identification: a survey. *Automatica* 7(2):123-162. doi:10.1016/0005-1098(71)90059-8

Grey-box
- Bohlin, T. (2006). *Practical Grey-box Process Identification*. Springer. doi:10.1007/1-84628-403-1
- Kristensen, N.R., Madsen, H., Jørgensen, S.B. (2004a). Parameter estimation in stochastic grey-box models. *Automatica* 40(2):225-237. doi:10.1016/j.automatica.2003.10.001
- Kristensen, N.R., Madsen, H., Jørgensen, S.B. (2004b). A method for systematic improvement of stochastic grey-box models. *Computers & Chemical Engineering* 28(8):1431-1449. doi:10.1016/j.compchemeng.2003.10.003

Identifiability and excitation
- Bellman, R., Åström, K.J. (1970). On structural identifiability. *Mathematical Biosciences* 7(3-4):329-339. doi:10.1016/0025-5564(70)90132-X
- Cobelli, C., DiStefano, J.J. (1980). Parameter and structural identifiability concepts and ambiguities. *Am. J. Physiol.* 239(1):R7-R24. doi:10.1152/ajpregu.1980.239.1.R7
- Godfrey, K. (1983). *Compartmental Models and Their Application*. Academic Press.
- Godfrey, K.R., Chapman, M.J. (1990). Identifiability and indistinguishability of linear compartmental models. *Mathematics and Computers in Simulation* 32(3):273-295.
- Meshkat, N., Sullivant, S., Eisenberg, M. (2015). Identifiability results for several classes of linear compartment models. *Bull. Math. Biol.* 77:1620-1651. doi:10.1007/s11538-015-0098-0
- Bellu, G., Saccomani, M.P., Audoly, S., D'Angiò, L. (2007). DAISY: a new software tool to test global identifiability. *Comput. Methods Programs Biomed.* 88(1):52-61. doi:10.1016/j.cmpb.2007.07.002
- Hong, H., Ovchinnikov, A., Pogudin, G., Yap, C. (2019). SIAN: software for structural identifiability analysis of ODE models. *Bioinformatics* 35(16):2873-2874. doi:10.1093/bioinformatics/bty1069
- Villaverde, A.F., Barreiro, A., Papachristodoulou, A. (2016). Structural identifiability of dynamic systems biology models. *PLoS Comput. Biol.* 12(10):e1005153. doi:10.1371/journal.pcbi.1005153
- Raue, A. et al. (2009). Structural and practical identifiability analysis of partially observed dynamical models by exploiting the profile likelihood. *Bioinformatics* 25(15):1923-1929. doi:10.1093/bioinformatics/btp358
- Wieland, F.-G., Hauber, A.L., Rosenblatt, M., Tönsing, C., Timmer, J. (2021). On structural and practical identifiability. *Current Opinion in Systems Biology* 25:60-69. doi:10.1016/j.coisb.2021.03.005
- Gutenkunst, R.N. et al. (2007). Universally sloppy parameter sensitivities in systems biology models. *PLoS Comput. Biol.* 3(10):e189. doi:10.1371/journal.pcbi.0030189
- Willems, J.C., Rapisarda, P., Markovsky, I., De Moor, B. (2005). A note on persistency of excitation. *Systems & Control Letters* 54(4):325-329. doi:10.1016/j.sysconle.2004.09.003
- van Waarde, H.J., Eising, J., Trentelman, H.L., Camlibel, M.K. (2020). Data informativity: a new perspective on data-driven analysis and control. *IEEE TAC* 65(11):4753-4768. doi:10.1109/TAC.2020.2966717

Subspace and realisation
- Ho, B.L., Kalman, R.E. (1966). Effective construction of linear state-variable models from input/output functions. *Regelungstechnik* 14:545-548.
- Juang, J.-N., Pappa, R.S. (1985). An eigensystem realization algorithm for modal parameter identification and model reduction. *J. Guidance, Control, and Dynamics* 8(5):620-627. doi:10.2514/3.20031
- Larimore, W.E. (1990). Canonical variate analysis in identification, filtering and adaptive control. *Proc. 29th IEEE CDC*, 596-604. doi:10.1109/CDC.1990.203665
- Verhaegen, M., Dewilde, P. (1992). Subspace model identification, Part 1. *Int. J. Control* 56(5):1187-1210. doi:10.1080/00207179208934363
- Van Overschee, P., De Moor, B. (1994). N4SID: Subspace algorithms for the identification of combined deterministic-stochastic systems. *Automatica* 30(1):75-93. doi:10.1016/0005-1098(94)90230-5
- Van Overschee, P., De Moor, B. (1996). *Subspace Identification for Linear Systems*. Kluwer. doi:10.1007/978-1-4613-0465-4
- Bauer, D. (2001). Order estimation for subspace methods. *Automatica* 37(10):1561-1573. doi:10.1016/S0005-1098(01)00118-2
- Jansson, M. (2003). Subspace identification and ARX modeling. *Proc. 13th IFAC SYSID*, Rotterdam.
- Qin, S.J. (2006). An overview of subspace identification. *Computers & Chemical Engineering* 30(10-12):1502-1513. doi:10.1016/j.compchemeng.2006.05.045
- Chiuso, A. (2007). The role of vector autoregressive modeling in predictor-based subspace identification. *Automatica* 43(6):1034-1048.
- Armenise, G., Vaccari, M., Bacci di Capaci, R., Pannocchia, G. (2018). An open-source system identification package for multivariable processes (SIPPY). *UKACC 12th Int. Conf. on Control*, 152-157. doi:10.1109/CONTROL.2018.8516791 ; code: https://github.com/CPCLAB-UNIPI/SIPPY

Instrumental variables and closed loop
- Young, P.C. (1976). Some observations on instrumental variable methods of time-series analysis. *Int. J. Control* 23(5):593-612. doi:10.1080/00207177608922186
- Söderström, T., Stoica, P. (1983). *Instrumental Variable Methods for System Identification*. Springer LNCIS 57. doi:10.1007/BFb0009019
- Young, P.C. (2011). *Recursive Estimation and Time-Series Analysis*, 2nd ed. Springer. doi:10.1007/978-3-642-21981-8
- Garnier, H., Wang, L. (eds.) (2008). *Identification of Continuous-time Models from Sampled Data*. Springer.
- Forssell, U., Ljung, L. (1999). Closed-loop identification revisited. *Automatica* 35(7):1215-1241. doi:10.1016/S0005-1098(99)00022-9
- Van den Hof, P.M.J., Schrama, R.J.P. (1993). An indirect method for transfer function estimation from closed loop data. *Automatica* 29(6):1523-1527. doi:10.1016/0005-1098(93)90015-L
- Gevers, M. (2005). Identification for control: from the early achievements to the revival of experiment design. *European J. Control* 11(4-5):335-352. doi:10.3166/ejc.11.335-352
- Gevers, M., Bazanella, A.S., Bombois, X., Mišković, L. (2009). Identification and the information matrix: how to get just sufficiently rich? *IEEE TAC* 54(12):2828-2840. doi:10.1109/TAC.2009.2034199
- Van den Hof, P.M.J., Dankers, A., Heuberger, P.S.C., Bombois, X. (2013). Identification of dynamic models in complex networks with prediction error methods. *Automatica* 49(10):2994-3006. doi:10.1016/j.automatica.2013.07.011
- Gonçalves, J., Warnick, S. (2008). Necessary and sufficient conditions for dynamical structure reconstruction of LTI networks. *IEEE TAC* 53(7):1670-1674. doi:10.1109/TAC.2008.928114
- Materassi, D., Innocenti, G. (2010). Topological identification in networks of dynamical systems. *IEEE TAC* 55(8):1860-1871. doi:10.1109/TAC.2010.2042347
- Chiuso, A., Pillonetto, G. (2012). A Bayesian approach to sparse dynamic network identification. *Automatica* 48(8):1553-1565. doi:10.1016/j.automatica.2012.05.054
- Hendrickx, J.M., Gevers, M., Bazanella, A.S. (2019). Identifiability of dynamical networks with partial node measurements. *IEEE TAC* 64(6):2240-2253. doi:10.1109/TAC.2018.2867336

Nonlinear: NARMAX, FROLS, block-oriented, LPV
- Leontaritis, I.J., Billings, S.A. (1985). Input-output parametric models for non-linear systems, Parts I and II. *Int. J. Control* 41(2):303-344. doi:10.1080/0020718508961129
- Chen, S., Billings, S.A., Luo, W. (1989). Orthogonal least squares methods and their application to non-linear system identification. *Int. J. Control* 50(5):1873-1896. doi:10.1080/00207178908953472
- Billings, S.A., Chen, S., Korenberg, M.J. (1989). Identification of MIMO non-linear systems using a forward-regression orthogonal estimator. *Int. J. Control* 49(6):2157-2189. doi:10.1080/00207178908559767
- Billings, S.A., Voon, W.S.F. (1986). Correlation based model validity tests for non-linear models. *Int. J. Control* 44(1):235-244. doi:10.1080/00207178608933593
- Billings, S.A., Zhu, Q.M. (1994). Nonlinear model validation using correlation tests. *Int. J. Control* 60(6):1107-1120. doi:10.1080/00207179408921513
- Billings, S.A. (2013). *Nonlinear System Identification: NARMAX Methods in the Time, Frequency, and Spatio-Temporal Domains*. Wiley. doi:10.1002/9781118535561
- Aguirre, L.A., Billings, S.A. (1995). Dynamical effects of overparametrization in nonlinear models. *Physica D* 80(1-2):26-40. doi:10.1016/0167-2789(95)90053-5
- Piroddi, L., Spinelli, W. (2003). An identification algorithm for polynomial NARX models based on simulation error minimization. *Int. J. Control* 76(17):1767-1781. doi:10.1080/00207170310001635419
- Aguirre, L.A., Barroso, M.F.S., Saldanha, R.R., Mendes, E.M.A.M. (2004). Imposing steady-state performance on identified nonlinear polynomial models by means of constrained parameter estimation. *IEE Proc. Control Theory Appl.* 151(2):174-179. doi:10.1049/ip-cta:20040102
- Wei, H.L., Billings, S.A. (2008). Model structure selection using an integrated forward orthogonal search algorithm assisted by squared correlation and mutual information. *Int. J. Modelling, Identification and Control* 3(4):341-356. doi:10.1504/IJMIC.2008.020543
- Baldacchino, T., Anderson, S.R., Kadirkamanathan, V. (2013). Computational system identification for Bayesian NARMAX modelling. *Automatica* 49(9):2641-2651. doi:10.1016/j.automatica.2013.05.023
- Farina, M., Piroddi, L. (2012). Identification of polynomial input/output recursive models with simulation error minimisation methods. *Int. J. Systems Science* 43(2):319-333. doi:10.1080/00207721.2010.496057
- Lacerda Junior, W.R., Martins, S.A.M., Nepomuceno, E.G. (2020). SysIdentPy: a Python package for system identification using NARMAX models. *JOSS* 5(54):2384. doi:10.21105/joss.02384
- Narendra, K., Gallman, P. (1966). An iterative method for the identification of nonlinear systems using a Hammerstein model. *IEEE TAC* 11(3):546-550. doi:10.1109/TAC.1966.1098387
- Bai, E.-W. (1998). An optimal two-stage identification algorithm for Hammerstein-Wiener nonlinear systems. *Automatica* 34(3):333-338. doi:10.1016/S0005-1098(97)00198-2
- Giri, F., Bai, E.-W. (eds.) (2010). *Block-oriented Nonlinear System Identification*. Springer LNCIS 404. doi:10.1007/978-1-84996-513-2
- Schoukens, M., Tiels, K. (2017). Identification of block-oriented nonlinear systems starting from linear approximations: a survey. *Automatica* 85:272-292. doi:10.1016/j.automatica.2017.06.044
- Tóth, R. (2010). *Modeling and Identification of Linear Parameter-Varying Systems*. Springer LNCIS 403. doi:10.1007/978-3-642-13812-6
- Schoukens, M., Mattsson, P., Wigren, T., Noël, J.P. (2016). Cascaded tanks benchmark combining soft and hard nonlinearities (two tanks in series with overflow: the closest standard benchmark to a stock chain with a cap). Dataset doi:10.4121/12960104.v1, https://data.4tu.nl/datasets/d4810b78-6cdd-48fe-8950-9bd601e5f47f

Hybrid / piecewise-affine, breaks
- Ferrari-Trecate, G., Muselli, M., Liberati, D., Morari, M. (2003). A clustering technique for the identification of piecewise affine systems. *Automatica* 39(2):205-217. doi:10.1016/S0005-1098(02)00224-8
- Roll, J., Bemporad, A., Ljung, L. (2004). Identification of piecewise affine systems via mixed-integer programming. *Automatica* 40(1):37-50. doi:10.1016/j.automatica.2003.08.006
- Bemporad, A., Garulli, A., Paoletti, S., Vicino, A. (2005). A bounded-error approach to piecewise affine system identification. *IEEE TAC* 50(10):1567-1580. doi:10.1109/TAC.2005.856667
- Paoletti, S., Juloski, A.Lj., Ferrari-Trecate, G., Vidal, R. (2007). Identification of hybrid systems: a tutorial. *European J. Control* 13(2-3):242-260. doi:10.3166/ejc.13.242-260
- Ohlsson, H., Ljung, L., Boyd, S. (2010). Segmentation of ARX-models using sum-of-norms regularization. *Automatica* 46(6):1107-1111. doi:10.1016/j.automatica.2010.03.013
- Ohlsson, H., Ljung, L. (2013). Identification of switched linear regression models using sum-of-norms regularization. *Automatica* 49(4):1045-1050. doi:10.1016/j.automatica.2013.01.031
- Breschi, V., Piga, D., Bemporad, A. (2016). Piecewise affine regression via recursive multiple least squares and multicategory discrimination. *Automatica* 73:155-162. doi:10.1016/j.automatica.2016.07.016
- Bemporad, A. (2023). A piecewise linear regression and classification algorithm with application to learning and model predictive control of hybrid systems. *IEEE TAC* 68(6):3194-3209. doi:10.1109/TAC.2022.3183036
- Lauer, F., Bloch, G. (2019). *Hybrid System Identification*. Springer LNCIS 478. doi:10.1007/978-3-030-00193-3
- Tobin, J. (1958). Estimation of relationships for limited dependent variables. *Econometrica* 26(1):24-36. doi:10.2307/1907382
- Hamilton, J.D. (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica* 57(2):357-384. doi:10.2307/1912559
- Chow, G.C. (1960). Tests of equality between sets of coefficients in two linear regressions. *Econometrica* 28(3):591-605. doi:10.2307/1910133
- Andrews, D.W.K. (1993). Tests for parameter instability and structural change with unknown change point. *Econometrica* 61(4):821-856. doi:10.2307/2951764
- Bai, J., Perron, P. (1998). Estimating and testing linear models with multiple structural changes. *Econometrica* 66(1):47-78. doi:10.2307/2998540
- Bai, J., Perron, P. (2003). Computation and analysis of multiple structural change models. *J. Applied Econometrics* 18(1):1-22. doi:10.1002/jae.659
- Kim, S.-J., Koh, K., Boyd, S., Gorinevsky, D. (2009). ℓ1 trend filtering. *SIAM Review* 51(2):339-360. doi:10.1137/070690274

Errors-in-variables
- Söderström, T. (2007). Errors-in-variables methods in system identification. *Automatica* 43(6):939-958. doi:10.1016/j.automatica.2006.11.025
- Söderström, T. (2018). *Errors-in-Variables Methods in System Identification*. Springer. doi:10.1007/978-3-319-75001-9
- Markovsky, I., Van Huffel, S. (2007). Overview of total least-squares methods. *Signal Processing* 87(10):2283-2302. doi:10.1016/j.sigpro.2007.04.004

Multiple shooting and k-step criteria
- Bock, H.G. (1983). Recent advances in parameter identification techniques for ODE. In *Numerical Treatment of Inverse Problems in Differential and Integral Equations*, Birkhäuser, 95-121. doi:10.1007/978-1-4684-7324-7_7
- Baake, E., Baake, M., Bock, H.G., Briggs, K.M. (1992). Fitting ordinary differential equations to chaotic data. *Physical Review A* 45:5524-5529. doi:10.1103/PhysRevA.45.5524
- Peifer, M., Timmer, J. (2007). Parameter estimation in ordinary differential equations for biochemical processes using the method of multiple shooting. *IET Systems Biology* 1(2):78-88. doi:10.1049/iet-syb:20060067
- Shook, D.S., Mohtadi, C., Shah, S.L. (1991). Identification for long-range predictive control. *IEE Proc. D* 138(1):75-84. doi:10.1049/ip-d.1991.0010
- Ramsay, J.O., Hooker, G., Campbell, D., Cao, J. (2007). Parameter estimation for differential equations: a generalized smoothing approach. *JRSS B* 69(5):741-796. doi:10.1111/j.1467-9868.2007.00610.x
- Ribeiro, A.H., Tiels, K., Umenberger, J., Schön, T.B., Aguirre, L.A. (2020). On the smoothness of nonlinear system identification. *Automatica* 121:109158. doi:10.1016/j.automatica.2020.109158
- Beintema, G.I., Schoukens, M., Tóth, R. (2023). Deep subspace encoders for nonlinear system identification. *Automatica* 156:111210. doi:10.1016/j.automatica.2023.111210

Experiment design
- Mehra, R.K. (1974). Optimal input signals for parameter estimation in dynamic systems: survey and new results. *IEEE TAC* 19(6):753-768. doi:10.1109/TAC.1974.1100701
- Goodwin, G.C., Payne, R.L. (1977). *Dynamic System Identification: Experiment Design and Data Analysis*. Academic Press.
- Box, G.E.P., Hill, W.J. (1967). Discrimination among mechanistic models. *Technometrics* 9(1):57-71. doi:10.1080/00401706.1967.10490441
- Atkinson, A.C., Fedorov, V.V. (1975). The design of experiments for discriminating between two rival models. *Biometrika* 62(1):57-70. doi:10.1093/biomet/62.1.57
- Hjalmarsson, H. (2005). From experiment design to closed-loop control. *Automatica* 41(3):393-438. doi:10.1016/j.automatica.2004.11.021
- Rojas, C.R., Welsh, J.S., Goodwin, G.C., Feuer, A. (2007). Robust optimal experiment design for system identification. *Automatica* 43(6):993-1008. doi:10.1016/j.automatica.2006.12.013
- Pronzato, L. (2008). Optimal experimental design and some related control problems. *Automatica* 44(2):303-325. doi:10.1016/j.automatica.2007.05.016

Order selection, regularisation, validation
- Akaike, H. (1974). A new look at the statistical model identification. *IEEE TAC* 19(6):716-723. doi:10.1109/TAC.1974.1100705
- Schwarz, G. (1978). Estimating the dimension of a model. *Annals of Statistics* 6(2):461-464. doi:10.1214/aos/1176344136
- Rissanen, J. (1978). Modeling by shortest data description. *Automatica* 14(5):465-471. doi:10.1016/0005-1098(78)90005-5
- Hurvich, C.M., Tsai, C.-L. (1989). Regression and time series model selection in small samples. *Biometrika* 76(2):297-307. doi:10.1093/biomet/76.2.297
- Stoica, P., Selén, Y. (2004). Model-order selection: a review of information criterion rules. *IEEE Signal Processing Magazine* 21(4):36-47. doi:10.1109/MSP.2004.1311138
- Pillonetto, G., De Nicolao, G. (2010). A new kernel-based approach for linear system identification. *Automatica* 46(1):81-93. doi:10.1016/j.automatica.2009.10.031
- Chen, T., Ohlsson, H., Ljung, L. (2012). On the estimation of transfer functions, regularizations and Gaussian processes, revisited. *Automatica* 48(8):1525-1535. doi:10.1016/j.automatica.2012.05.026
- Pillonetto, G., Dinuzzo, F., Chen, T., De Nicolao, G., Ljung, L. (2014). Kernel methods in system identification, machine learning and function estimation: a survey. *Automatica* 50(3):657-682. doi:10.1016/j.automatica.2014.01.001
- Ljung, L., Chen, T., Mu, B. (2020). A shift in paradigm for system identification. *Int. J. Control* 93(2):173-180. doi:10.1080/00207179.2019.1578407
- Ljung, G.M., Box, G.E.P. (1978). On a measure of lack of fit in time series models. *Biometrika* 65(2):297-303. doi:10.1093/biomet/65.2.297
- Mehra, R.K., Peschon, J. (1971). An innovations approach to fault detection and diagnosis in dynamic systems. *Automatica* 7(5):637-640. doi:10.1016/0005-1098(71)90028-8
- Racine, J. (2000). Consistent cross-validatory model-selection for dependent data: hv-block cross-validation. *J. Econometrics* 99(1):39-61. doi:10.1016/S0304-4076(00)00030-0
- Bergmeir, C., Hyndman, R.J., Koo, B. (2018). A note on the validity of cross-validation for evaluating autoregressive time series prediction. *Computational Statistics & Data Analysis* 120:70-83. doi:10.1016/j.csda.2017.11.003

Positive and compartmental systems, stable identification
- Jacquez, J.A. (1996). *Compartmental Analysis in Biology and Medicine*, 3rd ed. BioMedware.
- Farina, L., Rinaldi, S. (2000). *Positive Linear Systems: Theory and Applications*. Wiley. doi:10.1002/9781118033029
- Benvenuti, L., Farina, L. (2004). A tutorial on the positive realization problem. *IEEE TAC* 49(5):651-664. doi:10.1109/TAC.2004.826715
- Haddad, W.M., Chellaboina, V., Hui, Q. (2010). *Nonnegative and Compartmental Dynamical Systems*. Princeton University Press.
- Grussler, C., Umenberger, J., Manchester, I.R. (2017). Identification of externally positive systems. *Proc. 56th IEEE CDC*. https://cris.iucc.ac.il/en/publications/identification-of-externally-positive-systems/
- Lacy, S.L., Bernstein, D.S. (2003). Subspace identification with guaranteed stability using constrained optimization. *IEEE TAC* 48(7):1259-1263. doi:10.1109/TAC.2003.814273
- Umenberger, J., Wågberg, J., Manchester, I.R., Schön, T.B. (2018). Maximum likelihood identification of stable linear dynamical systems. *Automatica* 96:280-292. doi:10.1016/j.automatica.2018.06.032

State-space likelihood for counts and nonlinear models
- Shumway, R.H., Stoffer, D.S. (1982). An approach to time series smoothing and forecasting using the EM algorithm. *J. Time Series Analysis* 3(4):253-264. doi:10.1111/j.1467-9892.1982.tb00349.x
- Schön, T.B., Wills, A., Ninness, B. (2011). System identification of nonlinear state-space models. *Automatica* 47(1):39-49. doi:10.1016/j.automatica.2010.10.013
- Kantas, N., Doucet, A., Singh, S.S., Maciejowski, J., Chopin, N. (2015). On particle methods for parameter estimation in state-space models. *Statistical Science* 30(3):328-351. doi:10.1214/14-STS511
- Ionides, E.L., Bretó, C., King, A.A. (2006). Inference for nonlinear dynamical systems. *PNAS* 103(49):18438-18443. doi:10.1073/pnas.0603181103
- Bretó, C., He, D., Ionides, E.L., King, A.A. (2009). Time series analysis via mechanistic models. *Annals of Applied Statistics* 3(1):319-348. doi:10.1214/08-AOAS201

Econometrics
- Granger, C.W.J., Newbold, P. (1974). Spurious regressions in econometrics. *J. Econometrics* 2(2):111-120. doi:10.1016/0304-4076(74)90034-7
- Engle, R.F., Granger, C.W.J. (1987). Co-integration and error correction. *Econometrica* 55(2):251-276. doi:10.2307/1913236
- Johansen, S. (1991). Estimation and hypothesis testing of cointegration vectors in Gaussian vector autoregressive models. *Econometrica* 59(6):1551-1580. doi:10.2307/2938278
- White, H. (1980). A heteroskedasticity-consistent covariance matrix estimator and a direct test for heteroskedasticity. *Econometrica* 48(4):817-838. doi:10.2307/1912934
- Al-Osh, M.A., Alzaid, A.A. (1987). First-order integer-valued autoregressive (INAR(1)) process. *J. Time Series Analysis* 8(3):261-275. doi:10.1111/j.1467-9892.1987.tb00438.x
- Latour, A. (1997). The multivariate GINAR(p) process. *Advances in Applied Probability* 29(1):228-248. doi:10.2307/1427868
- Ferland, R., Latour, A., Oraichi, D. (2006). Integer-valued GARCH process. *J. Time Series Analysis* 27(6):923-942. doi:10.1111/j.1467-9892.2006.00496.x
- Weiß, C.H. (2018). *An Introduction to Discrete-Valued Time Series*. Wiley. doi:10.1002/9781119097013
- Cameron, A.C., Trivedi, P.K. (2013). *Regression Analysis of Count Data*, 2nd ed. Cambridge University Press. doi:10.1017/CBO9781139013567

Python implementations mentioned
- SysIdentPy: https://github.com/wilsonrljr/sysidentpy (BSD-3; NARMAX, FROLS, simulation error, residual tests)
- SIPPY: https://github.com/CPCLAB-UNIPI/SIPPY, PyPI `sippy-unipi` (LGPL; ARX/ARMAX/OE/BJ, N4SID, MOESP, CVA, PARSIM)
- nfoursid: https://github.com/spmvg/nfoursid (N4SID plus Kalman filter)
- python-control: https://github.com/python-control/python-control (Markov parameters, ERA in recent releases)
- statsmodels: VAR, VECM (`select_coint_rank`), SARIMAX/`MLEModel`, `MarkovRegression`, `acorr_ljungbox`, `RecursiveLS` (CUSUM)
- linearmodels: https://github.com/bashtage/linearmodels (IV2SLS, IVGMM)
- pyPESTO: https://github.com/ICB-DCM/pyPESTO (multi-start, profile likelihood)
- CasADi: https://web.casadi.org (multiple shooting with constraints)
- deepSI: https://github.com/GerbenBeintema/deepSI (SUBNET truncated simulation loss)
- PARC (`pyparc`): http://cse.lab.imtlucca.it/~bemporad/parc/ (piecewise-affine regression)
- ruptures, cvxpy, scipy (`least_squares`, `lsq_linear`, `nnls`)

Not verified for this note: exact current version numbers of the packages above (see the tools
survey for the ones it checked); Jansson (2003) and Ho-Kalman (1966) have no DOI; the DOIs of Chiuso (2007) and Godfrey and Chapman (1990) were left out rather than guessed. Citations were written from the literature as known, with three checked by web search (SIPPY, the cascaded-tanks benchmark, and Grussler et al. 2017 in place of an unconfirmed 2016 Umenberger-Manchester paper).
