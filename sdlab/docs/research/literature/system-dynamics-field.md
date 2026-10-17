# The System Dynamics field on models from and against data

Literature research, 2026-10-17. One tradition in a chain of reviews: what the System Dynamics (SD)
field itself says about building models from data and testing them against data, and what that
suggests for SD Lab's automatic discovery (`sdlab/discovery/`, described in
[../../DISCOVERY.md](../../DISCOVERY.md), goal in [../../DISCOVERY-GOAL.md](../../DISCOVERY-GOAL.md)).
The tools survey ([../SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md)) already covers
software, Vensim/Stella calibration, Stanify, `readsdr`, sd-ai and generic equation discovery;
this document does not repeat it, and cites those items only where the SD *method* matters.

Citations were checked against publisher, RePEc, MIT DSpace, the System Dynamics Society
proceedings site or the Albany SD archive where marked; a few page ranges are from memory and are
marked "(unchecked)".

---

## Summary (ranked by expected value for our engine)

1. **Use eigenvalues as a model-selection constraint, not just an explanation tool.** The SD
   literature's linear analysis (N. Forrester 1982; Kampmann and Oliva 2008; Güneralp 2006) ties
   each behaviour mode (growth, decay, oscillation) to eigenvalues of the model's linearised
   matrix. Our found models are linear in levels, so their eigenvalues are free to compute. A found
   model whose dominant eigenvalue is positive when no measured stock grows exponentially, or
   complex when nothing oscillates, is wrong before simulation. This is the cheapest direct fix for
   the "runaway found models" in DISCOVERY-GOAL.md.
2. **Partial-model *simulation* tests, row by row (Homer 1983/2012; Oliva 2003).** Drive one
   stock's candidate equation with the *measured* levels of every other stock and simulate only
   that stock over H steps. This sits between our one-step regression and the whole-model judge.
   It localises which row runs away and keeps calibration problems small, which Oliva argues
   prevents structure being forced to fit.
3. **Read structure off behaviour: a behaviour-mode fingerprint per stock (Sterman 2000 ch. 4;
   Richardson and Pugh 1981; Barlas and Kanar 2000; Yücel and Barlas 2011).** Each canonical mode
   has a minimal generating structure: oscillation needs at least two stocks in a negative loop
   (or a delay), S-shapes need a shift in loop dominance (a nonlinear effect), overshoot-and-collapse
   needs an eroding carrying capacity. Classifying each measured stock's mode is cheap and narrows
   the candidate families before the BIC search, and flags where a hidden stock or an effect must
   exist.
4. **Kalman-filter likelihood (Peterson's FIMLOF, 1976/1980; Li, Rahmandad and Sterman 2025) as
   the SD field's own answer to one-step versus simulation error.** It is the principled scorer for
   hidden stocks and shared (co-flow) noise. The tools survey already recommends it; the SD
   literature adds that it was the field's original statistical proposal and that the newest SD
   evidence favours it with process noise.
5. **Formulate rates the SD way: normal rate × product of normalised effects (Sterman 2000 ch.
   13-14; Richardson and Pugh 1981; Hines' "molecules").** An effect is a table f(x/x\*) with
   f(1)=1, monotone and saturating. Searching over that *constrained* family is far smaller and
   better identified than generic symbolic regression. Ríos-Ocampo and Gary (2022) give six
   parametric shapes that can replace tables with 1-2 parameters each.
6. **Use Theil's decomposition of fit error as an automatic diagnostic (Sterman 1984).** Splitting
   each stock's mean-square error into bias (U^M), unequal variation (U^S) and unequal covariation
   (U^C) tells the search what is missing: bias means a missing constant inflow or wrong level;
   unequal variation means a wrong gain or a missing effect; covariation-only error is noise and
   should stop the search.
7. **Run Barlas's direct-structure and extreme-condition tests on every found model (Forrester and
   Senge 1980; Barlas 1996).** Simulate the found model from empty stocks and from ten times the
   observed levels; reject candidates that create negative stocks, drain more than a stock holds,
   or explode. These are automatic, model-agnostic, and catch the failures that history-fitting
   cannot.
8. **Delays: estimate order from mean²/variance (Hamilton 1980; Roy 2000) and report a delay of
   order n as one object, not n hidden stocks.** A third-order delay is three hidden stocks that
   nothing can measure separately; SD practice treats it as one formulation with two parameters
   (average time, order). This removes a large identifiability trap from the hidden-stock search.
9. **Judge long horizons on behaviour-pattern features, not only point error (Barlas 1989, 1996;
   Yücel and Barlas 2011; Sucullu and Yücel 2014).** For oscillating and S-shaped stocks a small
   phase error ruins point skill@100 while period, amplitude and inflection timing are right.
   Pattern features should be a tiebreak and diagnostic (the goal metric itself stays skill@H).
10. **Take the field's critiques as design rules.** Fitting history is not validation (Forrester
    and Senge 1980; Sterman 2000 ch. 21; Oreskes et al. 1994); several structures fit equally well
    (identifiability: report the equivalence class); a coefficient that is statistically weak can
    still be structurally essential (Mass and Senge 1978), so do not drop a loop just because a
    short run cannot see it; and eras are natural experiments, the closest thing our data has to
    out-of-sample structural validation.

Published automatic structure inference inside the SD field remains tiny (Abdelbari and Shafi
2018/2019; a semi-automatic reference-mode tool on GitHub; an ISDC 2026 generative algorithm with
partial success; a 2026 SINDy-inspired paper on causal-loop structure). LLM work in SD
builds models from text, not from data (sections 8 and 9).

---

## 1. The modelling process and reference modes

**Sources.**
- Forrester, J. W. (1961). *Industrial Dynamics*. MIT Press.
- Forrester, J. W. (1980). Information sources for modeling the national economy. *Journal of the
  American Statistical Association* 75(371): 555-566.
- Randers, J. (ed.) (1980). *Elements of the System Dynamics Method*. MIT Press / Productivity
  Press. Its chapters are cited separately below.
- Richardson, G. P. and Pugh, A. L. (1981). *Introduction to System Dynamics Modeling with
  DYNAMO*. MIT Press (reissued by Productivity Press).
- Sterman, J. D. (2000). *Business Dynamics: Systems Thinking and Modeling for a Complex World*.
  Irwin/McGraw-Hill. Chapter 3 (the modelling process), chapter 4 (structure and behaviour),
  chapters 6-7 (stocks and flows), chapters 8-10 (growth, S-shapes), chapter 11 (delays),
  chapters 13-14 (formulating rates, nonlinear relationships), chapter 17 (supply chains and
  oscillation), chapter 21 (testing).
- Lane, D. C. and Smart, C. (1996). Reinterpreting "generic structure": evolution, application and
  limitations of a concept. *System Dynamics Review* 12(2): 87-120 (pages unchecked).

**Core idea.** The SD process runs: articulate the problem; draw *reference modes* (plots of key
variables over time, measured or sketched); state a *dynamic hypothesis* (the feedback structure
believed to generate the reference modes); formulate a simulation model; test it; then use it for
policy. The modelling is iterative. Forrester (1980) argues that numerical time series are the
smallest of three information sources (the others are written material and the "mental database"
of people who run the system), and that *structure* comes mostly from the latter two; numbers are
for checking behaviour and setting parameters.

**What it suggests for an automatic engine.** Two things. First, the SD field never expected to
read structure only from numbers: names, units and operating knowledge supply the skeleton. For us
that is the page's stock names, units, `final` and `group`, plus an LLM prior from names (see
[../llm-priors.md](../llm-priors.md)). Second, the reference mode is a *qualitative* target: the
shape of behaviour matters before its exact values.

**Pipeline step.** A "reference-mode" pass at the start: for each measured stock, record its
behaviour mode (section 2), time scale (time to half-way, period) and whether it is conserved with
some other stock (sum of two stocks steady). This is a feature vector the rest of discovery can
use to choose candidate families and to sanity-check results.

**Failure modes.** Data series that show one mode over the observed window but would show another
over a longer one (an S-curve seen only in its early, exponential-looking part). Outside inputs
that impose their own shape (a step in inflow makes a goal-seeking response that is not internal).

---

## 2. Behaviour modes and the structure-behaviour link

**Sources.**
- Sterman (2000), chapter 4, "Structure and Behavior of Dynamic Systems": the fundamental modes
  (exponential growth, goal seeking, oscillation) and their combinations (S-shaped growth,
  S-shaped growth with overshoot, overshoot and collapse).
- Graham, A. K. (1977). *Principles on the Relationship between Structure and Behavior of Dynamic
  Systems*. PhD thesis, MIT.
- Richardson, G. P. (1995). Loop polarity, loop dominance, and the concept of dominant polarity.
  *System Dynamics Review* 11(1): 67-88.
- Paich, M. (1985). Generic structures. *System Dynamics Review* 1(1): 126-132; Lane and Smart
  (1996) above; Hines, J. (1996) *Molecules of Structure* (Ventana, distributed as a Vensim
  library) and Eberlein, R. and Hines, J. (1996), Molecules for modelers, ISDC proceedings.
- Barlas, Y. and Kanar, K. (2000). Structure-oriented behavior tests in model validation. ISDC
  2000, Bergen.
- `wzh1895/Stock-and-Flow-in-Python` (GitHub): "semi-automatic SD model conceptualization" that
  matches a reference mode to basic behaviour patterns with dynamic time warping and suggests a
  generic structure; cites Barlas and Kanar (2000) and Moxnes' PHAPI framework; last changelog entry
  2019 ([repo](https://github.com/wzh1895/Stock-and-Flow-in-Python)).

**Core idea.** Behaviour is the fingerprint of feedback structure:

| Behaviour of a stock | Minimal structure that produces it | Linear-model signature |
|---|---|---|
| Exponential growth or decline | a dominant positive loop (inflow proportional to the stock itself) | a real positive eigenvalue |
| Goal seeking (exponential approach to a level) | a dominant negative loop: flow ∝ gap between goal and stock, or a drain ∝ stock with a constant inflow | real negative eigenvalue; time constant = 1/|λ| |
| Oscillation | a negative loop containing at least **two** stocks, or a delay (a stock correction acting through a supply line) | complex eigenvalue pair; period 2π/ω |
| S-shaped growth | a positive loop whose dominance shifts to a negative loop as a nonlinear effect (resource limit) bites | not linear: dominance shifts, eigenvalue changes sign over time |
| S-shape with overshoot | as above, with a delay in the negative loop | shifting dominance plus a complex pair |
| Overshoot and collapse | as above, where the limit itself is a stock consumed or eroded by the growth (fishery, soil) | not linear: two coupled nonlinear loops |
| Steady with noise | equilibrium; every loop balanced | all eigenvalues negative and large |

A single first-order stock cannot oscillate; a linear model cannot produce S-shapes; a
second-order linear model can oscillate only if it has a negative loop through both stocks. These
are *necessary* conditions, which is what makes them useful for pruning.

**What it suggests for an automatic engine.** A "behaviour fingerprint" per measured stock, and
rules from it:
- A stock that oscillates (spectral peak or autocorrelation with a negative lobe, after removing
  outside steps) while every candidate model of it is first order means a missing stock: either a
  hidden one (a supply line, a backlog) or a link to another measured stock that closes a negative
  loop. That points the hidden-stock search at the right place.
- An S-shaped stock means a nonlinear effect: offer an effect candidate (the growth flow multiplied
  by a falling function of the stock itself, or of a resource stock).
- Overshoot-and-collapse of stock A together with a decline of stock B means B is a resource
  consumed by A's flows: offer an effect of B on A's growth, and a flow or co-flow draining B.
- Goal seeking toward a level that is not zero means either a constant inflow plus a drain, or a
  gap formulation; which one depends on whether the "goal" moves with other stocks.

Examples in our benchmark that fit these rows: sd-fishery and sd-farm-soil (overshoot, eroding
resource), sd-population and sd-learning-curve (growth and S-shapes), sd-supply and sd-orders
(oscillation from supply lines), sd-housing (goal seeking with a long delay).

**Pipeline step.** Before the search: classify each stock (classifier on detrended, era-segmented
levels: fit growth, first-order approach, logistic, damped sine, and pick by BIC). Output: allowed
and required structure features per stock ("needs a second state", "needs an effect",
"no positive loop"). Use as priors in the score (cheaper columns for the required features, a
penalty for features that contradict the mode), never as hard rules.

**Failure modes.** Outside inputs that change mid-run create apparent modes (a step looks like goal
seeking). Short runs see only part of a mode. Counting noise on small stocks can look like
oscillation. Multiple modes superpose in one stock (growth plus oscillation). The rules are
necessary conditions, not sufficient: they say *something* is missing, not exactly what.

---

## 3. Validation and testing

**Sources.**
- Forrester, J. W. and Senge, P. M. (1980). Tests for building confidence in system dynamics
  models. In Legasto, Forrester and Lyneis (eds.), *System Dynamics*, TIMS Studies in the
  Management Sciences 14: 209-228. North-Holland.
- Barlas, Y. (1989). Multiple tests for validation of system dynamics type of simulation models.
  *European Journal of Operational Research* 42(1): 59-87.
- Barlas, Y. (1996). Formal aspects of model validity and validation in system dynamics. *System
  Dynamics Review* 12(3): 183-210. doi:10.1002/(SICI)1099-1727(199623)12:3<183::AID-SDR103>3.0.CO;2-4.
- Barlas, Y. and Carpenter, S. (1990). Philosophical roots of model validation: two paradigms.
  *System Dynamics Review* 6(2): 148-166.
- Sterman (2000), chapter 21, "Truth and beauty: validation and model testing" (tests:
  boundary adequacy, structure assessment, dimensional consistency, parameter assessment, extreme
  conditions, integration error, behaviour reproduction, behaviour anomaly, family member,
  surprise behaviour, sensitivity analysis, system improvement).
- Sterman, J. D. (1984). Appropriate summary statistics for evaluating the historical fit of
  system dynamics models. *Dynamica* 10(2): 51-66 (MIT working paper D-3393, 1983:
  [Albany archive](https://archives.albany.edu/concern/daos/nk322z25d)).
- Sterman, J. D. (2002). All models are wrong: reflections on becoming a systems scientist.
  *System Dynamics Review* 18(4): 501-531.
- Groesser, S. N. and Schwaninger, M. (2012). Contributions to model validation: hierarchy,
  process, and cessation. *System Dynamics Review* 28(2): 157-181.
- Saysel, A. K. and Barlas, Y. (2006). Model simplification and validation with indirect
  structure validity tests. *System Dynamics Review* 22(3): 241-262.
- Yücel, G. and Barlas, Y. (2011). Automated parameter specification in dynamic feedback models
  based on behavior pattern features. *System Dynamics Review* 27(2): 195-215. doi:10.1002/sdr.457
  ([RePEc](https://ideas.repec.org/a/bla/sysdyn/v27y2011i2p195-215.html)).
- Sucullu, C. and Yücel, G. (2014). Behavior analysis and testing software (BATS). ISDC 2014,
  Delft ([pdf](https://sesdyn.ie.bogazici.edu.tr/projects/bats/files/Can_Sucullu_Gonenc_Yucel_BATS_Paper_ISDC_2014_Delft.pdf)).
- Rahmandad, H. and Sterman, J. D. (2012). Reporting guidelines for simulation-based research in
  social sciences. *System Dynamics Review* 28(4): 396-411. doi:10.1002/sdr.1481.

**Core idea.** Validity in SD is about *structure*, not fit. Barlas (1996) orders the tests:
1. **Direct structure tests** (no simulation): each equation against knowledge of the real
   system; dimensional consistency; parameter values plausible; extreme-condition logic (what does
   the equation say when a stock is 0 or huge?).
2. **Structure-oriented behaviour tests** (simulate, but aimed at structure): extreme-condition
   simulations, behaviour sensitivity, phase relationships, boundary adequacy. Barlas calls these
   the strongest.
3. **Behaviour pattern tests**, last: does the model reproduce the *pattern* of the data
   (trend, period, amplitude, phase lag, autocorrelation)? Barlas (1989) gives a multi-step
   procedure comparing trends, autocorrelation functions, means, variances and phase lags, and
   argues point-by-point fit is the wrong criterion because noise and phase shifts dominate it.

Sterman (1984) gives the standard fit statistics. The mean-square error between simulated and
actual series splits into three Theil shares that sum to 1:
U^M (bias: means differ), U^S (unequal variation: variances differ), U^C (unequal covariation:
the parts move out of step). Large U^M or U^S signal systematic error; error mostly in U^C, with
small total error, is what noise or small phase shifts produce.

**What it suggests for an automatic engine.**
- Direct structure tests are already partly ours (units ratios, `final`, `group`, signs). Add
  **extreme-condition tests as automatic filters**: simulate each finalist from all stocks at 0 and
  from all stocks at 5-10× their observed maximum, with the observed outside inflows; reject or
  penalise models that make any stock negative, drain more than a stock holds in a step, or grow
  without limit where the data shows no growth.
- **Theil shares as the search's diagnostic** (per stock, from the multi-step judge): U^M high →
  try a constant inflow/outflow or an era-specific constant; U^S high → try an effect or a
  different gain; U^C dominant and total error near the noise floor → stop adding structure for
  that stock.
- **Behaviour-pattern tests as tiebreaker** at long horizons, especially for oscillating stocks.
  BATS and Yücel and Barlas (2011) define pattern features (slope sign changes, inflection points,
  period, amplitude ratio) that can be computed automatically.
- **Reporting** (Rahmandad and Sterman 2012): the report should list the found model, the data it
  was fitted to, the fit statistics, and what was tried and rejected. Our "what is left over" and
  "fits about as well" sections are the start of that.

**Pipeline step.** A "validation gate" after search and before the final answer: dimensional and
sign checks (cheap), extreme-condition simulations (cheap), Theil shares per stock (from the judge
runs we already do), eigenvalue check (section 5). Each finalist gets a short test report.

**Failure modes.** Extreme-condition tests need the found equations to be meaningful outside the
observed range; linear forms are not (a linear inflow with a negative coefficient goes negative at
large levels), so the gate should apply floors (as the truth's `desired_rate` does) before
judging. Pattern features are noisy on short runs. Theil shares are descriptive: they say a
mismatch is systematic, not which structure fixes it.

---

## 4. Calibration and estimation

**Sources.**
- Graham, A. K. (1980). Parameter estimation in system dynamics modeling. In Randers (ed.),
  *Elements of the System Dynamics Method*: 143-161. Earlier MIT working paper (1976)
  ([Albany archive](https://archives.albany.edu/concern/daos/3r075b820)).
- Peterson, D. W. (1980). Statistical tools for system dynamics. In Randers (ed.), *Elements of the
  System Dynamics Method*, chapter 11, from p. 224. Earlier version 1976
  ([Albany archive](https://archives.albany.edu/description/catalog/ua435aspace_d4c5d1582913f5de15c87ea6ce76d11c)).
  Peterson's method is FIMLOF: full-information maximum likelihood via optimal (Kalman) filtering.
  His PhD thesis (MIT, 1975) developed it.
- Senge, P. M. (1977). Statistical estimation of feedback models. *Simulation* 28(6): 177-184.
- Mass, N. J. and Senge, P. M. (1978). Alternative tests for the selection of model variables.
  *IEEE Transactions on Systems, Man, and Cybernetics* 8(6): 450-460.
- Eberlein, R. L. (1986). Full feedback parameter estimation. Working paper
  ([Albany archive](https://archives.albany.edu/concern/daos/w0892v89w)).
- Homer, J. B. (1983). Partial-model testing as a validation tool for system dynamics. ISDC 1983
  ([Albany archive](https://archives.albany.edu/concern/daos/2n49tk06b)); republished in *System
  Dynamics Review* 28(3): 281-294, 2012.
- Homer, J. B. (2014). Levels of evidence in system dynamics modeling. *System Dynamics Review*
  30(1-2): 75-80 (pages unchecked).
- Sterman, J. D. (1989). Modeling managerial behavior: misperceptions of feedback in a dynamic
  decision making experiment. *Management Science* 35(3): 321-339
  ([RePEc](https://ideas.repec.org/a/inm/ormnsc/v35y1989i3p321-339.html)). Estimates the
  anchoring-and-adjustment stock-management rule (order = expected loss + α(goal − stock) +
  β·α(goal supply line − supply line)) from subjects' data.
- Oliva, R. (2003). Model calibration as a testing activity. *European Journal of Operational
  Research* 151(3): 552-568. doi:10.1016/S0377-2217(02)00622-7
  ([author page](https://people.tamu.edu/~roliva/research/sd/calibration.html)).
- Dogan, G. (2007). Bootstrapping for confidence interval estimation and hypothesis testing for
  parameters of system dynamics models. *System Dynamics Review* 23(4): 415-436.
- Rahmandad, H., Oliva, R. and Osgood, N. D. (eds.) (2015). *Analytical Methods for Dynamic
  Modelers*. MIT Press. Chapters include Struben, Sterman and Keith, "Parameter estimation
  through maximum likelihood and bootstrapping methods"; Jalali, Rahmandad and Ghoddusi, "Using
  the method of simulated moments for system identification"; Osgood and Liu, "Combining Markov
  chain Monte Carlo approaches and dynamic modeling".
- Hosseinichimeh, N., Rahmandad, H., Jalali, M. S. and Wittenborn, A. K. (2016). Estimating the
  parameters of system dynamics models using indirect inference. *System Dynamics Review* 32(2):
  156-180 ([RePEc](https://ideas.repec.org/a/bla/sysdyn/v32y2016i2p154-178.html),
  [MIT DSpace](https://dspace.mit.edu/handle/1721.1/111143); author order and page range differ
  between records).
- Andrade, J. and Duggan, J. (2021). A Bayesian approach to calibrate system dynamics models
  using Hamiltonian Monte Carlo. *System Dynamics Review* 37(4): 283-309 (title from memory; see
  the tools survey for the RePEc link).
- Li, T. (Tse Yang), Rahmandad, H. and Sterman, J. D. (2025). Improving parameter estimation and
  confidence intervals of SD models. *System Dynamics Review* 41(2): e70004
  ([RePEc](https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html)). Compares least squares,
  Gaussian variants, Poisson, negative binomial and Kalman filtering with process noise.
- ISDC 2023 abstract 1285, "Bringing data into dynamic models: guidelines for advanced estimation
  methods" ([abstract](https://proceedings.systemdynamics.org/2023/abstracts/1285.html)): a
  practical workflow for choosing an estimation method.

**Core ideas, in plain words.**
- **Graham (1980): estimate below the level of aggregation first.** Many parameters can be set from
  data about one equation alone ("how long does a ticket wait", "what fraction leaves per week"),
  before any whole-model fitting. Formulate equations so each parameter means one observable
  thing.
- **Homer (1983): partial-model testing.** Cut the model into pieces; drive each piece with the
  *measured* inputs it would get from the rest of the model; compare its simulated output to the
  measured output. Errors are localised and the fit cannot borrow slack from elsewhere.
- **Oliva (2003): calibration is a test of the structural hypothesis.** Done on small partitions,
  it reveals mis-specified structure: if a partition cannot fit with plausible parameters, the
  structure is wrong. Whole-model calibration after partial calibration is the final check, not
  the estimator. He also argues for keeping parameters with prior information fixed and only
  calibrating what the data can identify.
- **Peterson (1980): FIMLOF.** Treat the model as a state-space system with process noise and
  measurement noise, run a Kalman filter that corrects states with each data point, and maximise
  the likelihood of the one-step prediction errors. This handles unmeasured stocks, noisy and
  missing data, and gives confidence intervals. The classical SD complaint about econometrics
  (Senge 1977) was that single-equation regression on noisy data biases feedback-model
  parameters (errors-in-variables); FIMLOF was the answer.
- **Sterman (1989): decision rules can be estimated directly.** The stock-management rule with a
  supply-line weight is a regression with a few interpretable parameters, estimated by nonlinear
  least squares on its own row. This is a model for estimating SD "molecules" one at a time.
- **Confidence and inference** (Dogan 2007; Struben et al. 2015; Li et al. 2025): bootstrap the
  residuals and refit to get intervals. Least squares gives misleading intervals; count likelihoods
  and filtering with autocorrelated process noise are better.
- **Simulation-based estimation** (method of simulated moments, Jalali et al. 2015; indirect
  inference, Hosseinichimeh et al. 2016): match statistics of simulated and real data (means,
  autocorrelations, auxiliary regression coefficients) instead of point paths. Useful when the
  likelihood is intractable or when the data are panels rather than one long series.
- **Bayesian** (Osgood and Liu 2015; Andrade and Duggan 2021; Stanify): priors on parameters and
  MCMC/HMC; particle filtering for nonlinear models with hidden states.

**What it suggests for an automatic engine.**
- Our pipeline already mirrors Graham-Homer-Oliva: per-stock rows with other stocks' measured
  levels as regressors are partial models, and the multi-step judge is whole-model calibration as
  the test. What is missing is the middle: **partial-model *simulation***. Simulate one stock with
  its candidate equation, feeding every other stock's measured level, for H steps from many
  starts. A row that is fine one step ahead but runs off in partial simulation is wrong (or is
  stable only with a feedback through another stock, which tells us that loop matters).
- **FIMLOF is the scorer for hidden stocks and co-flows** (survey agrees). Once a hidden stock is
  proposed, its level is a filtered state, not a delayed regressor.
- **Sterman 1989 says: estimate the stock-management molecule as a unit.** For an ordering or
  staffing stock whose inflow responds to a gap in another stock and to a supply line, the rule
  `inflow = loss estimate + (goal − stock)/T_s + (goal_SL − supply line)/T_sl` is one candidate
  with three or four parameters, not a set of independent links. sd-supply, sd-orders and
  sd-manufacturing should be checked for this shape.
- **Bootstrap inclusion probabilities** (Dogan; Struben et al.): refit the chosen structure, and
  re-run the search, on block-bootstrapped data; report how often each flow appears. This is the
  SD-native framing of the ensemble idea in [../bayesian-structure.md](../bayesian-structure.md).
- **Simulated moments for long horizons**: matching autocorrelation at lags 1..H and the
  variance of levels is a cheap auxiliary objective aligned with skill@100.

**Pipeline step.** (a) After the one-step BIC search, a partial-simulation check per stock; rows
that fail get their next candidates (another form, an effect, a hidden stock) tried before
whole-model judging. (b) Final parameter refinement by Kalman likelihood (or output error, as in
[../output-error.md](../output-error.md)) with count-aware noise. (c) Block bootstrap for
inclusion probabilities.

**Failure modes.** Partial-model simulation driven by measured levels hides instabilities that
appear only when the loop is closed (two rows each fine with the other's data, unstable together);
it must be followed by whole-model checks. Kalman likelihood with a mis-specified process-noise
size either trusts the data too much (becomes one-step error) or too little (becomes simulation
error). Bootstrap on time series needs block resampling and is costly for structure search.
Errors-in-variables bias (Senge 1977) affects our one-step regression too: noisy measured levels
used as regressors shrink coefficients toward zero, which is one reason drains are biased.

---

## 5. Loop dominance and eigenvalue analysis

**Sources.**
- Forrester, N. B. (1982). *A Dynamic Synthesis of Basic Macroeconomic Theory: Implications for
  Stabilization Policy Analysis*. PhD thesis, MIT (eigenvalue elasticity analysis).
- Richardson (1995), above.
- Ford, D. N. (1999). A behavioral approach to feedback loop dominance analysis. *System Dynamics
  Review* 15(1): 3-36 (loop deactivation).
- Mojtahedzadeh, M., Andersen, D. and Richardson, G. P. (2004). Using Digest to implement the
  pathway participation method for detecting influential system structure. *System Dynamics
  Review* 20(1): 1-20. doi:10.1002/sdr.285.
- Güneralp, B. (2006). Towards coherent loop dominance analysis: progress in eigenvalue elasticity
  analysis. *System Dynamics Review* 22(3): 263-289 (pages unchecked).
- Kampmann, C. E. and Oliva, R. (2008). Structural dominance analysis and theory building in
  system dynamics. *Systems Research and Behavioral Science* 25(4): 505-519
  ([CBS record](https://research.cbs.dk/en/publications/structural-dominance-analysis-and-theory-building-in-system-dynam/)).
- Kampmann, C. E. (2012). Feedback loop gains and system behavior (written 1996). *System Dynamics
  Review* 28(4): 370-395.
- Duggan, J. and Oliva, R. (eds.) (2013). Special issue: methods for identifying structural
  dominance. *System Dynamics Review* 29(1).
- Hayward, J. and Boswell, G. P. (2014). Model behaviour and the concept of loop impact: a
  practical method. *System Dynamics Review* 30(1-2): 29-57.
- Oliva, R. (2016). Structural dominance analysis of large and stochastic models. *System
  Dynamics Review* 32(1): 26-51.
- Naumov, S. and Oliva, R. (2018). Refinements to eigenvalue elasticity analysis: interpretation
  of parameter elasticities. *System Dynamics Review* 34(3): 426-437 (pages unchecked).
- Schoenberg, W., Davidsen, P. and Eberlein, R. (2020). Understanding model behavior using the
  Loops that Matter method. *System Dynamics Review* 36(2): 158-190
  ([arXiv 1908.11434](https://arxiv.org/abs/1908.11434),
  [BORA](https://bora.uib.no/bora-xmlui/handle/11250/2765498)).
- Eberlein, R. L. (1989). Simplification and understanding of models. *System Dynamics Review*
  5(1): 51-68 (model reduction keeping dominant behaviour).

**Core idea.** Behaviour is generated by whichever loops dominate at each moment. Methods:
- **Eigenvalue elasticity** (N. Forrester; Kampmann; Güneralp; Kampmann and Oliva): linearise the
  model; the eigenvalues give the behaviour modes (growth/decay rate, frequency); the elasticity of
  each eigenvalue to each loop gain says which loops create which mode. Exact for linear models.
- **Pathway participation** (Mojtahedzadeh): which causal pathways drive the change in a chosen
  variable's slope and curvature, at each time.
- **Loop deactivation** (Ford 1999): cut a loop and see what changes.
- **Loop impact** (Hayward and Boswell) and **Loops that Matter** (Schoenberg et al.): a score per
  loop per time step, computed from link contributions to stock changes; scales to large models
  and is built into Stella and `pysimlin`.
- **Model reduction** (Eberlein 1989): remove structure that does not affect the dominant modes.

**What it suggests for an automatic engine.** Our found models are, in their core, linear:
Δx = (S·K)x + c + effects. So **the eigenvalues of I + S·K (per era) are free**, and they predict
long-horizon behaviour exactly for the linear part. That gives:
- A **stability/consistency check**: count real positive eigenvalues (runaway growth), complex
  pairs (oscillation, with period), and the slowest time constant. Compare with the behaviour
  fingerprint of the data (section 2). A model with a positive eigenvalue fitted to data that
  shows no sustained growth is wrong, whatever its one-step BIC. This directly targets the
  "Run away" examples (sd-population, sd-services, sd-university).
- A **constraint during estimation**: if the data's fingerprint says "no growth", estimate with
  the spectral radius of the step matrix constrained to < 1 (or penalise it), as in stable
  system-identification methods. A complex pair at the observed period is a positive signal for
  structures that create oscillation.
- **Eigenvalue elasticity to find what to fix**: when a runaway eigenvalue appears, its elasticity
  to each found flow's coefficient names the flow responsible. Remove or re-form that flow first.
- **Loops that Matter for the report** (as in [../loop-dominance.md](../loop-dominance.md)):
  explanation, after the fact.
- **Model reduction** as a parsimony step: drop flows whose removal leaves eigenvalues and
  skill@H essentially unchanged.

**Pipeline step.** Compute eigenvalues for every finalist (and cheaply for every candidate that
reaches the judge). Add an eigenvalue-consistency term to the score; offer "constrained refit" for
models with a runaway mode.

**Failure modes.** Effects, floors and caps make the model nonlinear, so eigenvalues of the linear
part describe behaviour only near an operating point; recompute along the trajectory (as Oliva 2016
and Kampmann and Oliva do) when effects are present. Outside inflows that grow make growth in data
without any positive loop. A genuinely unstable true system (sd-population growth) must be allowed
a positive eigenvalue: the rule is consistency with data, not "always stable".

---

## 6. Formulating nonlinear relationships and table functions

**Sources.**
- Sterman (2000), chapter 13 (formulating rate equations: fractional rate, adjustment to a goal,
  stock management, capacity-limited flows with min/max, first-order control so a stock never goes
  negative) and chapter 14 (formulating nonlinear relationships: table functions; normalise input
  and output; reference point at (1,1); extreme points; shape from the physics of saturation).
- Richardson and Pugh (1981), chapters on formulating rate equations and multiplicative effects.
- Alfeld, L. E. and Graham, A. K. (1976). *Introduction to Urban Dynamics*. Wright-Allen Press
  (multiplier formulations).
- Franco, D. (2007). Fifty years of table functions. ISDC 2007
  ([pdf](https://proceedings.systemdynamics.org/2007/proceed/papers/FRANC270.pdf)).
- Ríos-Ocampo, J. P. and Gary, M. S. (2022). Using analytical equations to represent nonlinear
  relationships in system dynamics. *System Dynamics Review* 38(4): 354-370
  ([Strathprints](https://strathprints.strath.ac.uk/89750)). Six forms (logistic, exponential,
  modified exponential, quadratic, logarithmic, power) with a Python fitting script and Vensim
  macros.
- Kleemann, Dianati and Pedercini (2022). Elasticity formulations: theory and practice in system
  dynamics. ISDC 2022 ([pdf](https://proceedings.systemdynamics.org/2022/papers/P1168.pdf)).
- Eker, S., Slinger, J., van Daalen, E. and Yücel, G. (2014). Sensitivity analysis of graphical
  functions. *System Dynamics Review* 30(3): 186-205 (pages unchecked).
- Ford, D. N. and Sterman, J. D. (1998). Expert knowledge elicitation to improve formal and mental
  models. *System Dynamics Review* 14(4): 309-340 (eliciting table functions from experts).
- Bala, B. K., Arshad, F. M. and Noh, K. M. (2017). *System Dynamics: Modelling and Simulation*,
  chapter 5, "Parameter estimation and sensitivity analysis" (estimating table functions, normal
  fractional rates) ([RePEc](https://ideas.repec.org/h/spr/sptchp/978-981-10-2045-2_5.html)).

**Core idea.** The canonical SD rate is

    flow = normal flow × effect₁(x₁/x₁*) × effect₂(x₂/x₂*) × …

where each effect is a function of a *normalised* input, equal to 1 at the reference point, with
plausible behaviour at the extremes (0 and saturation), and usually monotone. Tables are drawn
from knowledge of the extremes and the slope at the reference point; data then refine them. Flows
out of a stock are written so they cannot exceed what the stock holds (first-order control:
outflow = min(desired, stock/minimum time)). The field has a long-running discussion of when to
replace tables by analytic forms (fewer parameters, smoother, easier to estimate) and of how
sensitive behaviour is to table shape (Eker et al. 2014 find that shape details often matter less
than the end points and the slope near the operating point).

**What it suggests for an automatic engine.** Effects are the part of our benchmark v2 that the
current engine cannot express. The SD formulation gives the right *constrained* search space:
- The effect's input is a level normalised by a reference (its mean or initial level, or a
  measured "capacity" stock): x/x\*. This makes a table's x-axis comparable across examples.
- The output is a multiplier, f(1)=1, monotone, bounded. Fit in log space:
  log(flow) = log(normal flow) + Σ log fᵢ(xᵢ/xᵢ\*), which turns the product into a sum.
- Candidate shapes: Ríos-Ocampo and Gary's six analytic forms (1-2 parameters each), or a
  monotone piecewise-linear table with 3-5 knots fitted by isotonic or constrained least squares.
- Which stock drives the effect: the SD rule of thumb is that limits come from resources and
  capacities (a stock the flow consumes, a stock of workers or machines), and from crowding of the
  stock itself. That is a short candidate list per flow (the flow's own source and target, and any
  stock in the same group), not every stock.
- Capacity-limited flows are `min(desired, capacity)` or the smooth "first-order control"; these
  are the "capacity-limited form" asked for in DISCOVERY.md section 10.

**Pipeline step.** After the linear search: for each found flow whose residual correlates with a
normalised level (its source, target, or same-group stock), fit the multiplicative effect in log
space with each analytic shape and a monotone table; accept by BIC plus partial-simulation skill.
Then refit jointly.

**Failure modes.** An effect fitted on data that covers only part of the input range is
unconstrained outside it (extrapolates wrongly at long horizons); the f(1)=1, monotone and bounded
constraints exist to limit that. Two effects on correlated inputs are not separately identifiable.
Log-space fitting fails when flows hit zero; use a Poisson likelihood or a small offset. A
"linear effect" of a stock on its own outflow is the same as a quadratic drain, so effects and
general rate forms overlap ([../general-equations.md](../general-equations.md)).

---

## 7. Delays and their identification

**Sources.**
- Forrester (1961), chapter 9 and appendix H (material and information delays, exponential delays
  of orders 1, 3 and pipeline).
- Sterman (2000), chapter 11 (material delays: pipeline, first order, third order, nth order;
  information delays / smoothing; the order determines the shape of the response to a pulse; the
  variance of the transit-time distribution is mean²/n).
- Hamilton, M. S. (1980). Estimating lengths and orders of delays in system dynamics models. In
  Randers (ed.), *Elements of the System Dynamics Method*. 1976 MIT working paper with five
  statistical methods and empirical tests
  ([Albany archive](https://archives.albany.edu/concern/daos/dz011772b)).
- Roy, S. and Mohapatra, P. K. J. A method for estimating order of system dynamics delays
  ([Albany archive](https://archives.albany.edu/downloads/br86bm65s)); Roy, S. (2000). Bulk delays
  in system dynamics models. ISDC 2000
  ([pdf](https://proceedings.systemdynamics.org/2000/PDFs/roy311p.pdf)): order = mean²/variance of
  holding time.

**Core idea.** A delay is a stock (or chain of stocks) between an inflow and an outflow. An nth-
order delay with average time T is a chain of n stocks each with time T/n; its outflow's response
to a pulse is an Erlang(n, n/T) distribution. Order 1 responds at once and decays; order 3 has an
S-shaped step response; a pipeline (infinite order) passes the input unchanged after exactly T.
Delay length and order can be estimated from input-output data: the mean and variance of the lag
distribution (distributed-lag regression, impulse response) give T and n = T²/variance.

**What it suggests for an automatic engine.** Our hidden-stock search already offers delayed
copies of levels (exp, Erlang, pipe filters on a grid). The SD literature adds:
- **Moment estimates instead of a grid**: estimate the lag distribution between a source's outflow
  and a target's inflow (by distributed-lag regression on the windowed changes), then set T = mean
  lag and n = mean²/variance, rounded and capped. This replaces grid search and gives the order
  directly.
- **An nth-order delay is one object.** Report "a delay of 6 days, order 3, holding about N" with a
  single hidden content, not three hidden stocks. The internal stocks are unidentifiable from
  levels at the two ends; only the total content (Little's law) and the shape are.
- **Information delays are different from material delays.** A goal or perceived value that
  smooths a measured level (perceived demand, expected loss rate) is a first-order smooth, not a
  conserved hidden stock: nothing flows. In our forms this appears as a flow driven by a smoothed
  level, which is the stock-management rule's "expected loss" (section 4).

**Pipeline step.** In hidden-stock discovery: estimate (T, n) by moments from the lag
distribution; offer one "delay object" candidate per detected lagged pair; distinguish material
(conserved: the hidden content plus the two measured stocks is steady) from information delays
(no conservation) by the conservation residual.

**Failure modes.** Moment estimates are poor when the input varies little (no excitation) or the
run is short relative to T. Mixed delays (some items fast, some slow, as in a lognormal
follow-up) give an order below 1 by the formula; cap and report. Delays inside a feedback loop
are biased by the feedback when estimated by open-loop regression (the classic closed-loop
identification problem); partial-model simulation reduces this.

---

## 8. Data-driven SD and automatic structure inference

**Sources (all that we found inside the SD field).**
- Pruyt, E., Cunningham, S., Kwakkel, J. H. and de Bruijn, J. A. (2014). From data-poor to
  data-rich: system dynamics in the era of big data. ISDC 2014, Delft: 2458-2469
  ([pdf](https://proceedings.systemdynamics.org/2014/proceed/papers/P1390.pdf)). Names "inferring
  model structures from data" as one of three roles for data science in SD; a position paper.
- Abdelbari, H. and Shafi, K. (2018). Learning structures of conceptual models from observed
  dynamics using evolutionary echo state networks. *Journal of Artificial Intelligence and Soft
  Computing Research*; Abdelbari and Shafi (2019). A system dynamics modeling support system based
  on computational intelligence. *Systems* 7(4): 47
  ([doi:10.3390/systems7040047](https://doi.org/10.3390/systems7040047)). Infers CLDs, stock-flow
  diagrams, equations and parameters from stock time series; textbook models.
- `wzh1895/Stock-and-Flow-in-Python` (section 2): reference-mode matching with dynamic time warping
  to suggest generic structures; semi-automatic.
- ISDC 2026 abstract 1226, "From data to model structure: a generative algorithm to develop
  system dynamics models" ([abstract](https://proceedings.systemdynamics.org/2026/abstracts/1226.html)):
  net-flow equations from stock time series; recovers a cooling teacup and predator-prey, partial
  success on a workforce/production/inventory model; argues for human-in-the-loop tools.
- Roman, S., Soloviy, V. and Kubeczko, K. (2026). Exploratory modelling of multi-system
  transformation pathways from real-world data: a SINDy-inspired sparse orthogonal regression
  technique. arXiv 2606.21530 ([abstract](https://arxiv.org/abs/2606.21530)): sparse dependencies
  among European indicators, read as reinforcing and balancing loops; structural, not forecasting.
- Yücel and Barlas (2011): automated parameter search toward a *behaviour pattern* rather than a
  data series.
- Estimation for policy-scale data-rich models: COVID-19 SD models calibrated across many
  countries (e.g. Rahmandad, Xu and Ghaffarzadegan, 2022, Enhancing long-term forecasting:
  learning from COVID-19 models, *PLOS Computational Biology* 18(5): e1010100) show the field's
  current practice: hand-built structure, automated multi-region calibration, forecast skill
  tracked over time.

**Core idea.** The field recognises data-driven structure inference as a goal (Pruyt et al. 2014)
but the published attempts are few, small, and recover *net* flow per stock or causal-loop
diagrams, not conserved moves between stocks with SD rate forms. None reports prediction skill
on a held-out horizon against a known true model the way our benchmark does.

**What it suggests.** Our setting is ahead of the SD literature here; there is nothing to adopt.
Two transferable ideas: reference-mode matching to *generic structures* (section 2) and
pattern-based search objectives (section 3). The COVID work's practice of tracking forecast skill
across successive data releases is the same idea as our skill@H.

**Failure modes noted in these works.** Recovery degrades sharply from 2-3 stock textbook models
to 5+ stock models with delays and nonlinearities (ISDC 2026 abstract); net-flow fits cannot tell
a move from an independent inflow and outflow.

---

## 9. LLMs and SD (brief; the tools survey covers the systems)

- Akhavan, A. and Jalali, M. S. (2024). Generative AI and simulation modeling: how should you
  (not) use large language models like ChatGPT. *System Dynamics Review* 40(3): e1773
  ([RePEc](https://ideas.repec.org/a/bla/sysdyn/v40y2024i3ne1773.html)). Guidelines across the
  modelling process; LLMs support, not replace, the modeller.
- Hosseinichimeh, N., Majumdar, A., Williams, R. and Ghaffarzadegan, N. (2024). From text to map:
  a system dynamics bot for constructing causal loop diagrams. *System Dynamics Review* 40(3):
  e1782.
- Schoenberg, W. et al. (2025). How well can AI build SD models? arXiv 2503.15580 (sd-ai
  evaluation).

**For us.** All build structure from text. The SD-native use in our engine is a prior over flows
and effects from stock names and units (Forrester's "mental database" stand-in), and a narrator of
found models. Akhavan and Jalali's caution applies: the prior must never override the data.

---

## 10. The field's critiques: what fitting can and cannot show

**Sources.** Forrester and Senge (1980); Mass and Senge (1978); Senge (1977); Barlas (1996);
Barlas and Carpenter (1990); Sterman (2000) ch. 21; Sterman (2002); Oliva (2003); Homer (2014);
Oreskes, N., Shrader-Frechette, K. and Belitz, K. (1994). Verification, validation, and
confirmation of numerical models in the earth sciences. *Science* 263(5147): 641-646; Lyneis, J.
M. (2000). System dynamics for market forecasting and structural analysis. *System Dynamics
Review* 16(1): 3-25.

**Core points.**
1. **Fitting history is not validation.** Many structures reproduce one historical path,
   especially if parameters are free; a good fit is necessary, not sufficient (Forrester and
   Senge; Sterman ch. 21; Oreskes et al.).
2. **Over-fitting by structure, not only by parameters.** Adding loops, effects and exogenous
   inputs until history fits gives a model that fails under new conditions. Lyneis (2000) warns
   that a model that fits by exogenous drivers explains nothing.
3. **Statistical significance is not structural importance** (Mass and Senge 1978). A variable
   can be insignificant in a regression because it did not vary in the sample, yet dominate when it
   does vary. Dropping it because the data cannot see it is a mistake for policy use.
4. **Errors-in-variables and simultaneity** bias single-equation estimates in feedback systems
   (Senge 1977; Peterson's FIMLOF was the response).
5. **Identifiability**: parameters and structures that the data cannot distinguish should be set
   from other evidence (Graham 1980; Oliva 2003) or reported as uncertain (Dogan 2007; Li et al.
   2025).
6. **Levels of evidence** (Homer 2014): make explicit which parts of a model rest on data, which on
   expert judgement, which on assumption.

**What they suggest for an automatic engine.**
- Keep the multi-step judge (skill@H) as the referee, but do not treat a fitting structure as
  proven: report alternatives that fit about as well (we do), with bootstrap inclusion
  probabilities.
- **Eras are natural experiments.** A structure fitted on one era that predicts the next era
  after only its announced parameters change is the strongest structural evidence available to us.
  An "era hold-out" test (fit on eras 1..k, predict era k+1 with parameters re-estimated only for
  era-specific flows) is the SD validation idea most directly applicable. (The held-out judge
  experiment rejected random held-out windows, see [../held-out-judge.md](../held-out-judge.md);
  era hold-out is a different, structural test.)
- **Penalise exogenous explanations.** Unannounced input changes that the engine adds to fit
  history are exactly Lyneis' "exogenous drivers"; their price in the score should stay honest
  ([../change-price.md](../change-price.md)).
- **Do not prune by significance alone in short runs** (Mass and Senge): when a flow is weakly
  identified but structurally required (behaviour mode needs it; units and conservation imply
  it), keep it with a prior-informed value, and say so.
- **Report levels of evidence** per flow: measured, fitted with tight interval, fitted loosely,
  assumed by prior.

---

## 11. What an expert SD modeller does with lots of data, and what can be automated

The process below is assembled from Sterman (2000, ch. 3, 21), Richardson and Pugh (1981),
Graham (1980), Homer (1983), Oliva (2003) and Barlas (1996), as an expert would actually run it
when handed many measured series and asked "what system produced this?".

| # | What the expert does | Can it be automated? How, in our pipeline |
|---|---|---|
| 1 | **Look at every series.** Plot levels; note units, magnitudes, time scales, noise, gaps, obvious steps. Identify which series are stocks (accumulate) and which are flows or rates. | Yes. Already given: the page says which are stocks. Add automatic step detection, noise floor per stock (our jitter weights), and per-stock time scales (autocorrelation decay time). |
| 2 | **Look for conservation.** Do some stocks sum to a near-constant, or does one fall when another rises by the same amount (in the right units)? That is the main chain. | Yes. Pairwise and small-group tests on windowed changes: correlation of ΔA with −ΔB×ratio, and steadiness of A + B/ratio. Already partly in our "mirror" screen; make it an explicit prior for moves. |
| 3 | **Draw the boundary.** Decide what is endogenous and what is driven from outside; flag regime changes. | Partly. Outside inflows and announced eras are given; unannounced changes are found by change detection. The boundary judgement (is this driver part of the system?) is where LLM priors from names can help. |
| 4 | **Name the reference mode of each key stock** (growth, goal seeking, oscillation, S-shape, overshoot) and its time constants or period. | Yes. A behaviour classifier (section 2) on detrended, era-segmented series. Output: fingerprint and period/time constants. |
| 5 | **Form a dynamic hypothesis**: which loops would produce these modes, using generic structures (stock management, S-shaped growth with a limit, aging chain, supply line, workforce-inventory). | Partly. Map fingerprints to required structural features (second state, effect, resource stock); offer generic-structure templates (Sterman ch. 17-19 "molecules") as compound candidates scored as one unit. The creative leap (unexpected structure) stays hard. |
| 6 | **Sketch the stock-and-flow skeleton** from operations knowledge (what physically moves where), not from correlations. | Partly: units, `final`, `group`, names (LLM prior), conservation tests from step 2. |
| 7 | **Formulate each rate** with a standard molecule: fractional rate, goal gap, anchoring-and-adjustment, capacity-limited min, normal × effects, delays. Parameters chosen to be observable. | Yes, as a candidate library. Ours has constant, proportional, gap, linear; add stock-management, capacity-limited, multiplicative effects, nth-order delay objects. |
| 8 | **Estimate parameters below the aggregate level** where data allow (a known average delay, a fraction measured directly). | Yes: measured flows (counters) already subtracted; per-row regression is this step. |
| 9 | **Partial-model tests**: drive each subsystem with measured inputs and compare to its measured output. Fix the pieces that fail before closing loops. | Yes. Partial-model *simulation* per row (section 4). Currently missing. |
| 10 | **Calibrate the whole model**, by simulation error or Kalman filtering; examine residuals (Theil shares, autocorrelation, residual vs each level). | Yes. Multi-step judge exists; add Theil shares and residual-vs-level scatter as diagnostics feeding back to step 7 (try an effect where residual correlates with a level). Kalman likelihood as scorer. |
| 11 | **Add structure where error is systematic**: a missing delay where response is too quick; an effect where gain changes with level; a hidden stock where a measured stock oscillates with no second state. | Yes, with rules from steps 4 and 10: each systematic residual pattern maps to a candidate addition. This is the "structure repair" loop. |
| 12 | **Test**: dimensional consistency, extreme conditions, behaviour patterns (period, amplitude), sensitivity of behaviour to uncertain parameters, loop dominance explanation that makes sense. | Yes: the validation gate (section 3) plus eigenvalues (section 5). |
| 13 | **Simplify**: remove structure that does not matter for behaviour (Eberlein 1989; Saysel and Barlas 2006). | Yes: drop-one tests on skill@H and eigenvalues. |
| 14 | **Check against a change**: does the model predict behaviour after a policy or regime change it was not fitted on? | Yes: era hold-out (section 10). |
| 15 | **Report** structure, parameters with intervals, what fits equally well, levels of evidence, and remaining anomalies. | Yes: extend our report with inclusion probabilities, Theil shares, eigenvalues, evidence levels. |

The steps that remain hard to automate are 5 and 6 when the true structure is not in the
candidate library, and the judgement in step 3 of what belongs inside the boundary. Everything
else is a search over a library plus tests, which is what the engine already is.

The expert's key habit, worth copying literally: **when a fit fails, read the *shape* of the
failure to decide the next structural move**, rather than adding parameters blindly. Our current
loop adds columns by BIC; the SD habit is "residual pattern → structure hypothesis → test".
Making that mapping explicit (Theil shares, residual-vs-level, behaviour fingerprint vs model
eigenvalues) is the main thing this tradition offers an automatic engine.

---

## 12. Concrete experiments suggested (for the synthesis)

| Experiment | Section | Target examples (expected) | Cost |
|---|---|---|---|
| Eigenvalue consistency check and constrained refit for runaway modes | 5 | sd-population, sd-services, sd-university, sd-eras | small |
| Partial-model simulation per row before whole-model judging | 4 | runaway and middling examples | small |
| Behaviour fingerprint → structure priors (oscillation needs a second state; S-shape needs an effect) | 2 | sd-supply, sd-orders, sd-fishery, sd-farm-soil, sd-learning-curve | medium |
| Multiplicative effects in log space with SD-constrained shapes | 6 | the five benchmark-v2 effect examples, sd-fishery | medium |
| Stock-management molecule as one candidate | 4, 7 | sd-supply, sd-orders, sd-manufacturing, sd-webshop-stock | medium |
| Delay objects with moment-estimated (T, n) | 7 | sd-hidden-chain, sd-hospital, sd-pipeline | medium |
| Extreme-condition gate and Theil-share diagnostics | 3 | all (robustness) | small |
| Era hold-out as a structural test | 10 | era examples | small |
| Kalman (FIMLOF) scorer with count-aware process noise | 4 | hidden stocks, co-flows | large (overlaps [../state-space.md](../state-space.md)) |

---

## Reading list

Books and chapters
- Forrester, J. W. (1961). *Industrial Dynamics*. MIT Press.
- Richardson, G. P. and Pugh, A. L. (1981). *Introduction to System Dynamics Modeling with DYNAMO*. MIT Press.
- Randers, J. (ed.) (1980). *Elements of the System Dynamics Method*. MIT Press. Esp. Graham (pp. 143-161), Hamilton, Peterson (ch. 11).
- Sterman, J. D. (2000). *Business Dynamics*. Irwin/McGraw-Hill. Chapters 3, 4, 11, 13, 14, 17, 21.
- Rahmandad, H., Oliva, R. and Osgood, N. D. (eds.) (2015). *Analytical Methods for Dynamic Modelers*. MIT Press.
- Forrester, J. W. and Senge, P. M. (1980). Tests for building confidence in system dynamics models. TIMS Studies in the Management Sciences 14: 209-228.
- Graham, A. K. (1977). *Principles on the Relationship between Structure and Behavior of Dynamic Systems*. PhD thesis, MIT.
- Forrester, N. B. (1982). *A Dynamic Synthesis of Basic Macroeconomic Theory*. PhD thesis, MIT.

Validation and fit
- Barlas, Y. (1989). EJOR 42(1): 59-87.
- Barlas, Y. (1996). SDR 12(3): 183-210.
- Sterman, J. D. (1984). Appropriate summary statistics for evaluating the historical fit of SD models. Dynamica 10(2): 51-66.
- Yücel, G. and Barlas, Y. (2011). SDR 27(2): 195-215. doi:10.1002/sdr.457.
- Groesser, S. N. and Schwaninger, M. (2012). SDR 28(2): 157-181.
- Rahmandad, H. and Sterman, J. D. (2012). SDR 28(4): 396-411. doi:10.1002/sdr.1481.
- Homer, J. B. (2014). Levels of evidence in system dynamics modeling. SDR 30(1-2).

Calibration and estimation
- Senge, P. M. (1977). Simulation 28(6): 177-184.
- Mass, N. J. and Senge, P. M. (1978). IEEE Trans. SMC 8(6): 450-460.
- Homer, J. B. (1983/2012). Partial-model testing as a validation tool for system dynamics. SDR 28(3): 281-294.
- Sterman, J. D. (1989). Management Science 35(3): 321-339.
- Oliva, R. (2003). EJOR 151(3): 552-568. doi:10.1016/S0377-2217(02)00622-7.
- Dogan, G. (2007). SDR 23(4): 415-436.
- Hosseinichimeh, N. et al. (2016). SDR 32(2): 156-180.
- Andrade, J. and Duggan, J. (2021). SDR 37(4): 283-309.
- Li, T., Rahmandad, H. and Sterman, J. D. (2025). SDR 41(2): e70004.

Loop dominance
- Richardson, G. P. (1995). SDR 11(1): 67-88.
- Ford, D. N. (1999). SDR 15(1): 3-36.
- Mojtahedzadeh, M., Andersen, D. and Richardson, G. P. (2004). SDR 20(1): 1-20. doi:10.1002/sdr.285.
- Güneralp, B. (2006). SDR 22(3).
- Kampmann, C. E. and Oliva, R. (2008). Systems Research and Behavioral Science 25(4): 505-519.
- Kampmann, C. E. (2012). SDR 28(4): 370-395.
- Hayward, J. and Boswell, G. P. (2014). SDR 30(1-2): 29-57.
- Oliva, R. (2016). SDR 32(1): 26-51.
- Schoenberg, W., Davidsen, P. and Eberlein, R. (2020). SDR 36(2): 158-190.
- Eberlein, R. L. (1989). SDR 5(1): 51-68.

Formulation, nonlinearities, delays
- Franco, D. (2007). Fifty years of table functions. ISDC.
- Ríos-Ocampo, J. P. and Gary, M. S. (2022). SDR 38(4): 354-370.
- Eker, S. et al. (2014). Sensitivity analysis of graphical functions. SDR 30(3).
- Ford, D. N. and Sterman, J. D. (1998). SDR 14(4): 309-340.
- Hamilton, M. S. (1980). Estimating lengths and orders of delays in SD models. In Randers (ed.).
- Roy, S. (2000). Bulk delays in system dynamics models. ISDC.
- Lane, D. C. and Smart, C. (1996). Reinterpreting "generic structure". SDR 12(2).

Data-driven SD, automation, LLMs
- Pruyt, E. et al. (2014). From data-poor to data-rich. ISDC: 2458-2469.
- Abdelbari, H. and Shafi, K. (2019). Systems 7(4): 47. doi:10.3390/systems7040047.
- ISDC 2026 abstract 1226. From data to model structure: a generative algorithm.
- Roman, S., Soloviy, V. and Kubeczko, K. (2026). arXiv 2606.21530.
- Akhavan, A. and Jalali, M. S. (2024). SDR 40(3): e1773.
- Hosseinichimeh, N. et al. (2024). SDR 40(3): e1782.

Critiques
- Oreskes, N., Shrader-Frechette, K. and Belitz, K. (1994). Science 263(5147): 641-646.
- Sterman, J. D. (2002). All models are wrong. SDR 18(4): 501-531.
- Lyneis, J. M. (2000). SDR 16(1): 3-25.
- Barlas, Y. and Carpenter, S. (1990). SDR 6(2): 148-166.
