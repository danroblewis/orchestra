# The process of discovering a model from data: how an engine should reason, and how we should run the research

Literature review, one part of a chain (a later document synthesises all parts). Scope: the
*methodology* of model discovery, not any single fitting technique: the Box-Jenkins cycle and its
descendants, residual diagnostics, model discrimination, the Bayesian workflow, equifinality,
abduction and computational scientific discovery, automated science, experiment design,
search-and-verify, benchmark hygiene, ablation, and combining partial methods. Each section gives
the idea in plain words, a concrete step for the **engine**, a concrete practice for the
**programme** (our team), and the failure modes. Citations are real; venues and DOIs/URLs are given
where known.

Context assumed: [../../DISCOVERY-GOAL.md](../../DISCOVERY-GOAL.md),
[../../DISCOVERY-LOOP.md](../../DISCOVERY-LOOP.md), [../README.md](../README.md), and in particular
the held-out-judge result ([../held-out-judge.md](../held-out-judge.md)): the in-sample judge already
picks the best available candidate in 31 of 42 runs, and an oracle picker reaches only 78%, so the
headroom is in **models no candidate represents**, not in picking.

---

## Summary (ranked by expected value to SD Lab)

1. **Make the engine an explicit identify-estimate-criticise loop, not a pipeline.** Box & Jenkins
   (1970) and Box (1980) split modelling into *tentative identification -> efficient estimation ->
   diagnostic criticism -> back to identification*; Gelman et al.'s Bayesian workflow (2020) is the
   modern form. Our engine fits once and picks; it should instead fit, compute structured residual
   diagnostics per stock, and let each failing diagnostic *propose a specific structural expansion*
   (hidden stock, era split, floor, co-flow, effect curve), then refit. This attacks exactly the
   "models no candidate represents" gap.
2. **Residuals are a structure detector; build a diagnostic-to-hypothesis table.** Autocorrelated
   one-step residuals -> missing state (hidden stock / delay); residuals correlated with a lagged
   level of another stock -> missing link or delayed copy; residuals correlated with squares or
   products of levels -> nonlinearity/effect (Billings & Voon 1986; Ramsey 1969 RESET); a break in
   cumulative residuals -> unannounced regime (Brown, Durbin & Evans 1975 CUSUM; Bai & Perron 1998);
   one-sided residuals near zero stock -> floor/cap; cross-stock residual correlation -> shared
   flow/co-flow. Each pattern names its fix. This is the single most actionable import.
3. **Judge by the question asked: simulation (multi-step) predictive performance, conditioned on
   the inflows, i.e. a prequential score.** Dawid's prequential principle (1984) and the
   output-error tradition in system identification (Ljung 1999) say: assess a dynamical model by
   its forecasts, issued sequentially. Our grader is skill@H given true inflows; the engine's
   internal judge should mirror it (multi-step error with inflows re-estimated, never one-step fit
   alone), which also explains why naive held-out CV failed (it confounded dynamics with forecasting
   the unannounced inflow).
4. **Generate broadly, verify strictly (generate-and-test with a hard verifier).** FunSearch
   (Romera-Paredes et al. 2024), AlphaCode (Li et al. 2022) and BACON/IPM-style discovery systems all
   win by producing many candidates cheaply and filtering with a strict, cheap-to-run evaluator. Our
   verifier exists (simulate and score); the generator is narrow. Spend effort widening the
   candidate set, and keep the verifier strict, unchanged and separate from generation.
5. **Benchmark overfitting is the main threat to our programme; add a procedurally generated,
   held-out family of systems now.** 31 fixed examples, ~30-second bench runs, and dozens of
   adopt/reject decisions is the textbook setting for adaptive overfitting (Dwork et al. 2015;
   Recht et al. 2019). Freeze a sealed test set of generated models (different seeds, and whole
   held-out *motif families*) that is scored only at adoption time, and report generalisation gaps
   (Cobbe et al. 2020, Procgen).
6. **Run research as strong inference with multiple working hypotheses, organised as a
   programme with a hard core.** Chamberlin (1890) and Platt (1964): name rival explanations of a
   failure, design the experiment that kills one. Lakatos (1970): keep a protected core (the
   matrix/conservation method) and a belt of auxiliary mechanisms, each added only if it predicts
   *new* successes. Our "one hypothesis, one mechanism test, one bench run" loop is already this;
   add a failure taxonomy so experiments are chosen by what they would discriminate.
7. **Treat equifinality as data: keep a set of acceptable models, not one.** Beven (2006),
   Breiman's Rashomon effect (2001), and Burnham & Anderson's multi-model inference (2002) all say
   that many structures fit equally well. Since skill is behavioural, structurally different but
   behaviourally equivalent models are fine, but the engine should *know* when the data cannot
   distinguish two candidates (profile likelihood, Raue et al. 2009; sloppiness, Gutenkunst et al.
   2007) and then prefer the simpler, report the ambiguity, or ask for excitation.
8. **Ablate and attribute, don't accumulate.** Hooker (1995) and Fawcett & Hoos (2016): controlled
   experiments on heuristics, and ablation paths between the baseline and a combined configuration,
   show which few components carry the gain. Every adopted mechanism should keep an off-switch, and
   each wave should re-run a leave-one-component-out ablation on the current main line.
9. **Combine partial methods by a portfolio plus a per-instance selector, with stacking for
   predictions.** Rice (1976) algorithm selection; Gomes & Selman (2001) portfolios; Xu et al. (2008)
   SATzilla; Yao et al. (2018) stacking. Our "candidates + in-data judge" is already a portfolio with
   a selector; formalise it: each strategy is a candidate generator, the judge is the selector, and
   features of the data (excitation, era count, residual signatures) can route effort.
10. **Design the data you learn from where you can (sequential experiment design), and know when to
   stop.** Box & Hill (1967) model discrimination; Chaloner & Verdinelli (1995); Rainforth et al.
   (2024). For the engine: when two surviving structures disagree, compute the input/perturbation
   that maximises their predicted divergence (needs the live-run sign-off in
   [../experiment-design.md](../experiment-design.md)). Stopping rule: stop expanding when residual
   diagnostics are white *and* the expected skill gain of the next expansion is below its
   penalised cost.

---

## 1. The Box-Jenkins cycle and its descendants

**Core idea.** Box & Jenkins (1970) proposed that time-series modelling is an iterative loop:
(i) *identification*: look at the data (autocorrelation, partial autocorrelation) to propose a
tentative model class and order; (ii) *estimation*: fit that model efficiently; (iii) *diagnostic
checking*: test whether the residuals are white noise (Ljung-Box portmanteau test, Ljung & Box 1978)
and whether over-fitted extensions are needed; if not, return to (i) with what the diagnostics showed.
Box (1976, "Science and statistics") generalised this into the iterative interplay of deduction and
induction in all science; Box (1980) separated *criticism* (checking a model against data with
predictive checks) from *estimation* (inference within a model). Descendants:

- **System identification** (Ljung 1999; Söderström & Stoica 1989): the same loop for dynamical
  models with inputs: choose a model structure set, choose a criterion (prediction error vs output
  error/simulation error), estimate, validate (residual whiteness, residual-input
  independence, cross-validation on fresh data). Ljung frames the user's real choices as *data,
  model set, criterion*.
- **NARMAX / FROLS** (Billings 2013): structure selection by forward orthogonal regression, followed
  by correlation-based validity tests (Billings & Voon 1986) that loop back to structure.
- **General-to-specific econometrics** (Hendry; Castle, Doornik & Hendry 2011, Autometrics): start
  from a general unrestricted model, simplify by multi-path search, and require every retained model
  to pass a battery of misspecification tests (autocorrelation, heteroscedasticity, normality,
  RESET, parameter constancy). *Encompassing* (Mizon & Richard 1986): a good model explains why
  rivals got the results they did.
- **SD's own validation tradition** (Forrester & Senge 1980; Barlas 1996; Sterman 2000 ch. 21;
  Oliva 2003): structure tests, behaviour tests, extreme-condition tests, and Oliva's "model
  calibration as a testing strategy": partial calibration of sub-models, each a falsifiable test
  of the structure, rather than a single global fit.

**For the engine.** Make the loop explicit: `identify -> estimate -> criticise -> expand -> re-estimate`,
per stock row and then jointly. Concretely: after the current matrix fit, run a diagnostic battery
(section 2) on every stock's one-step and multi-step residuals; each failed test produces a
*named* structural proposal; refit only that row with the proposal; accept it if the penalised
multi-step criterion improves; repeat until no test fails or no proposal helps. Oliva-style partial
calibration fits our rows: test each row's structure alone (feeding other stocks' measured levels)
before the joint simulation.

**For the programme.** The same loop at team level: identification = reading every bench row and
residual plot of the failing examples; estimation = an experiment; diagnostic checking = the
mechanism test plus reading every row of the bench result. Never skip identification: an
experiment begins with a residual pattern on named examples, not with a technique.

**Failure modes.** Looping forever on noise (every finite sample "fails" some test at some
significance; use a fixed battery, fixed thresholds, and a penalised criterion). Diagnostics for
one-step errors miss multi-step instability (our runaway models: one-step residuals can look
white while the simulated loop diverges). Identification tools built for linear stationary series
(ACF/PACF) mislead on regime-switching, floored, nonlinear SD data.

## 2. Residual diagnostics as a structure-finding tool

**Core idea.** If the model is right, residuals are unpredictable noise. Any structure left in them
is a pointer to what is missing, and its *shape* names the missing piece. Classical tests:
portmanteau whiteness (Box & Pierce 1970; Ljung & Box 1978), Durbin-Watson (1950), residual-input
cross-correlation (Ljung 1999 ch. 16), nonlinearity tests (Ramsey 1969 RESET; Tsay 1986; BDS,
Brock et al. 1996; Billings & Voon 1986's higher-order correlations like corr(e, e*u) and
corr(e^2, u^2)), parameter constancy and structural-break tests (Chow 1960; Brown, Durbin & Evans
1975 recursive residuals and CUSUM; Bai & Perron 1998 multiple breaks), and posterior predictive
checks with targeted test statistics (Gelman, Meng & Stern 1996).

**A diagnostic-to-hypothesis table for SD.** (This is the concrete import; each row is a candidate
experiment.)

| residual signature (per stock row) | likely missing structure | proposal to try |
|---|---|---|
| one-step residuals autocorrelated (Ljung-Box fails), smooth wandering | a missing state: hidden stock, material delay, information delay | regress residual on delayed/smoothed copies of other stocks' levels (exp, Erlang-k, pipeline); a chosen copy implies a hidden stock ([../hidden-stocks.md](../hidden-stocks.md)) |
| residual correlates with lagged level of stock j (not in the row) | missing link j -> i, possibly delayed | add term; scan lag; choose by multi-step error |
| residual correlates with x_j^2, x_i*x_j, or saturates at extremes | nonlinear rate / effect curve / product co-flow | add product or table-effect term (RESET-like augmented regression) |
| residual one-signed when a stock is near zero, or rate goes negative in fit | floor at zero / outflow capped by contents | floored or min(.) rate form ([../floors-and-caps.md](../floors-and-caps.md)) |
| CUSUM of residuals breaks at a point; coefficients unstable across windows | unannounced regime change, or an inflow step | Bai-Perron break search; per-era coefficients or a new inflow piece ([../regime-models.md](../regime-models.md)) |
| residuals of two stocks strongly negatively correlated at lag 0 | a flow between them mis-estimated (conservation) | move or link term; joint fit with the conservation constraint |
| residuals of several stocks positively correlated | shared driver / co-flow (`uses`) | co-flow term; shared-noise model ([../shared-noise.md](../shared-noise.md)) |
| residual variance grows with level | counting (Poisson-like) noise, not misspecified mean | count likelihood / weights, *not* new structure ([../count-likelihoods.md](../count-likelihoods.md)) |
| one-step white but multi-step diverges | unstable loop gain; bias from errors-in-variables | stability constraint; output-error refinement ([../output-error.md](../output-error.md)) |
| periodic structure in residual spectrum | missing oscillatory input (day/night, sprints) or a second-order delay loop | periodic input component or delay chain |

The row about variance is a warning: some residual structure is about the *noise model*, not the
*dynamics*; confusing the two makes the engine add spurious structure.

**For the engine.** Implement the battery as a function `diagnose(row, residuals, levels, eras)`
returning ranked, typed proposals with a statistic and a p-value or effect size. The expansion step
of section 1 consumes these proposals in order. Record the diagnostic output in the trace so a
human can see why a structure was added.

**For the programme.** Before an experiment, show the residual signature that motivates it on the
named examples (DISCOVERY-LOOP step 2 already asks for "look at residuals"); after it, show the
signature is gone. Score the table itself: on the benchmark, with the truth known, measure how often
each diagnostic's proposal matches the missing truth component (precision/recall of the
diagnostics). That is a cheap, truth-using study that is legal because it evaluates the tool, not the
engine's output.

**Failure modes.** Multiple testing (many stocks x many tests: control false discovery, e.g.
Benjamini & Hochberg 1995, or use effect sizes with a fixed threshold). Residuals of a mis-specified
*upstream* row contaminate downstream rows (fix in topological order, or fit jointly). Unannounced
inflow changes look like breaks everywhere. Short default-length runs give low power.

## 3. Model discrimination and selection

**Core idea.** Choose among candidate structures by a criterion that trades fit against complexity
and that targets the use of the model.

- **Information criteria.** AIC (Akaike 1974) estimates expected out-of-sample predictive
  (Kullback-Leibler) loss; BIC (Schwarz 1978) approximates the log marginal likelihood and is
  consistent for the true model when it is in the set; AICc for small samples (Hurvich & Tsai 1989).
  MDL (Rissanen 1978; Grünwald 2007) codes model plus data. For dynamical models selected by search,
  the effective number of parameters is larger than the count, because of selection.
- **Bayes factors** (Kass & Raftery 1995): ratio of marginal likelihoods; sensitive to priors on
  parameters, which is a problem when priors are vague. For ODE models, ABC-SMC model selection
  (Toni et al. 2009) and reviews by Kirk, Thorne & Stumpf (2013).
- **Cross-validation for time series and its pitfalls.** Standard k-fold assumes exchangeability;
  with dependent data it leaks. Remedies: blocked/hv-block CV (Racine 2000), rolling-origin
  evaluation (Tashman 2000), leave-future-out (Bürkner, Gabry & Vehtari 2020), and structured CV
  guidance (Roberts et al. 2017). Bergmeir, Hyndman & Koo (2018) show ordinary k-fold *is* valid for
  purely autoregressive models with uncorrelated errors, i.e. when the model conditions on the
  past correctly, which is the one-step setting, not the free-simulation setting. Arlot & Celisse
  (2010) survey CV theory. Our own result ([../held-out-judge.md](../held-out-judge.md)) is a
  textbook pitfall: the held-out block required forecasting an exogenous inflow that changes
  without announcement, so the criterion measured inflow extrapolation, not dynamics.
- **Prequential / predictive evaluation** (Dawid 1984; Dawid & Vovk 1999): evaluate a model by the
  sequence of one-step-ahead (or H-step) forecasts it would have issued, each from data before it.
  Proper scoring rules (Gneiting & Raftery 2007) for probabilistic forecasts. Prequential evaluation
  needs no held-out split and matches how SD models are used.
- **Multi-model inference** (Burnham & Anderson 2002): rank by AIC differences, convert to Akaike
  weights, average predictions over the confidence set of models rather than trusting the winner;
  insist on a small, thought-through candidate set. Bayesian model averaging (Hoeting et al. 1999);
  stacking of predictive distributions (Yao, Vehtari, Simpson & Gelman 2018), which is better than
  BMA when no candidate is true (M-open).
- **Model discrimination by design** (Box & Hill 1967; Atkinson & Fedorov 1975 T-optimality): if
  two models fit equally, collect data where they disagree most (section 8).

**For the engine.** (a) The judge should score *dynamics given inflows*: on a held-out block, freeze
rate coefficients, re-estimate only a coarse outside inflow (the open idea in the held-out-judge
document), then simulate H steps; that is a prequential, inflow-conditioned score matching skill@H.
(b) Use an AICc/BIC-like penalty on structural terms *in the multi-step criterion*, with the count
including terms the search considered (or calibrate the penalty empirically on generated models).
(c) Keep the top-k candidates with weights and stack their simulated trajectories when they disagree
little; report disagreement when they disagree a lot.

**For the programme.** Calibrate the internal judge against the grader: for every run, log the
judge's rank of the candidate the grader likes best (the "31 of 42" number). A change to the judge
is evaluated on that rank metric, separately from changes to generation. Never tune the penalty on
the 31 examples; tune it on generated models.

**Failure modes.** Information criteria assume the likelihood is right (with counting noise and
autocorrelated errors it is not, so penalties are mis-scaled). Bayes factors swing with vague priors.
CV on dependent data leaks; CV on regime-switching data measures extrapolation. Model averaging
over structurally different SD models can average away a feedback loop that matters (average
trajectories, not coefficients). Selection after search inflates apparent fit (Freedman's paradox,
1983).

## 4. The Bayesian workflow

**Core idea.** Gelman, Vehtari, Simpson et al. (2020, "Bayesian Workflow", arXiv:2011.01808) treat
modelling as a structured iteration over a *network* of models: choose an initial model; check the
priors by simulating from them (prior predictive checks); validate the computation (fake-data
simulation: fit to data simulated from known parameters and check recovery; simulation-based
calibration, Talts et al. 2018, arXiv:1804.06788, Modrák et al. 2023); fit; check the posterior
against data (posterior predictive checks, Gelman, Meng & Stern 1996; Gabry et al. 2019 on
visualisation); expand or modify the model where checks fail; compare models (LOO, Vehtari, Gelman
& Gabry 2017; LFO for time series); and keep the whole path, because the sequence of models is
itself informative. Earlier statements: Box (1980), Gelman & Shalizi (2013, "Philosophy and the
practice of Bayesian statistics", BJMSP) which explicitly frames it as hypothetico-deductive model
checking rather than pure induction. Betancourt's "Towards a principled Bayesian workflow" (2018)
case study is a compact practical version.

**For the engine.**
- *Prior predictive check of the candidate generator*: simulate from candidate structures with
  plausible coefficient ranges and confirm the generator can produce trajectories that look like
  the data (if no candidate can produce the observed oscillation, a structure family is missing;
  detect that *before* fitting).
- *Fake-data check on every run*: after discovery, simulate the found model with the estimated
  noise and inflows, re-run discovery on that synthetic data, and check it finds itself (a
  self-consistency check, cheap and truth-free). If discovery cannot recover its own answer, the
  answer is not identified from this much data.
- *Posterior predictive checks with targeted statistics*: per stock, compare statistics the
  grader cares about (H-step change distribution, peak timing, oscillation period, time near zero)
  between observed data and replications from the found model.
- *Model expansion as the default response* to a failed check, guided by section 2's table.

**For the programme.** `tests/synth.py` is exactly fake-data simulation; extend it to SBC-style
calibration: draw many random models from a generator, run discovery, and histogram where the true
coefficients fall in the engine's uncertainty (if the engine reports any) or the distribution of
skill. This turns "mechanism test on one tiny model" into "mechanism works across a prior".

**Failure modes.** Workflow is expensive (many refits); keep the per-run version light. Posterior
predictive checks are conservative (data used twice), so they miss misfit; use held-out or
targeted statistics. "Forking paths" (Gelman & Loken 2013): a workflow followed by a human on one
dataset adapts to its noise; an automatic engine is safer because its workflow is fixed in code,
but the *team's* workflow over the benchmark is exactly a garden of forking paths (section 9).

## 5. Equifinality and model-structure uncertainty

**Core idea.** Many different structures and parameter sets reproduce the observed data equally
well. Hydrology names this *equifinality* (Beven & Binley 1992, GLUE; Beven 2006, "A manifesto for
the equifinality thesis", J. Hydrology 320:18-36): accept a set of "behavioural" models rather than
one optimum. Statistics calls it the *Rashomon effect* (Breiman 2001, "Statistical modeling: the two
cultures"; Semenova, Rudin & Parr 2022 on the Rashomon set). Systems biology calls the parameter
version *sloppiness* (Gutenkunst et al. 2007, PLoS Comput Biol 3:e189) and studies *structural* and
*practical identifiability* (Bellman & Åström 1970; Raue et al. 2009 profile likelihood,
Bioinformatics 25:1923). SD literature: Sterman (2000) on the difference between fit and structural
validity; Oliva (2003).

**What it means for us.** Our grader already embraces equifinality: two models with the same
behaviour score the same. But behaviour on the observed inputs is not behaviour under the grader's
150 restarts at different states; structures that agree on the observed trajectory can diverge from
other initial states (e.g. a hidden stock vs a delayed link with the same impulse response but
different response to a perturbed state). So:

**For the engine.** Keep the *behavioural set* (all candidates within a tolerance of the best
penalised score), then test members against each other by simulating from *perturbed initial
states* within the observed range. If they agree, pick the simplest; if they disagree, the data
cannot decide: prefer the one favoured by priors (conservation, units, SD conventions), report
the ambiguity, and (in live runs) propose the excitation that would decide. A profile-likelihood
scan over each structural coefficient flags terms that are not practically identifiable; drop
or fix them.

**For the programme.** Classify every failing run as *(a) truth not in the candidate set*, *(b)
truth in the set but not chosen*, or *(c) truth not identifiable from this data* (truth and the
found model agree on the data but diverge at graded restarts). These need different research:
(a) generation, (b) judging, (c) priors or data. The [../identifiability.md](../identifiability.md)
topic should produce this classification as a standard bench column, and
[../benchmark-excitation.md](../benchmark-excitation.md) already found sd-population is not
excited: treat (c) runs as benchmark findings, not engine failures.

**Failure modes.** A behavioural threshold is arbitrary (GLUE was criticised for incoherent
likelihoods: Mantovan & Todini 2006; Stedinger et al. 2008). Reporting ambiguity can become an
excuse for not improving. Large behavioural sets explode cost.

## 6. Abduction, hypothesis generation, and computational scientific discovery

**Core idea.** Peirce distinguished *abduction* (inference to a hypothesis that would, if true,
make the surprising observation a matter of course) from deduction and induction (Peirce, Collected
Papers 5.189; Hanson 1958, *Patterns of Discovery*). Abduction is how structure is *proposed*;
induction is how it is *tested*. Simon (1973, "Does scientific discovery have a logic?", Phil. Sci.
40:471) argued discovery is heuristic search through a space of hypotheses, and with Langley,
Bradshaw & Zytkow (1987, *Scientific Discovery: Computational Explorations of the Creative
Processes*, MIT Press) built BACON, which rediscovered physical laws by data-driven heuristics
(find invariants, define new terms from ratios/products, recurse). Klahr & Dunbar (1988, Cognitive
Science 12:1) model discovery as *dual-space search*: a hypothesis space and an experiment space,
each guiding search in the other.

The closest ancestor of SD Lab is **inductive process modeling** (Langley et al. 2002, ICML;
Bridewell, Langley, Todorovski & Džeroski 2008, "Inductive process modeling", Machine Learning
71:1-32, doi:10.1007/s10994-007-5042-6; Džeroski & Todorovski eds. 2007, *Computational Discovery
of Scientific Knowledge*, LNAI 4660): models are sets of *processes* (like SD flows) instantiated
from a library of *generic process templates* (e.g. "exponential loss", "predation"), with typed
entities; search enumerates combinations of instantiated processes subject to constraints, fits
parameters by simulation, and ranks by error. Follow-ups: learned constraints on process
combinations (Todorovski, Bridewell & Langley 2011), and HPM, heuristic process discovery that
grows models one process at a time guided by residual fit (Langley & Arvay 2017, AAAI). Related
equation discovery: LAGRANGE/LAGRAMGE (Todorovski & Džeroski 1997) with grammar-constrained ODE
search; Schmidt & Lipson (2009, Science 324:81) symbolic regression of conserved quantities; SINDy
(Brunton, Proctor & Kutz 2016, PNAS). Recently, LLM-guided equation discovery (LLM-SR, Shojaee et al.
2025, ICLR) uses language priors as the abductive generator.

**For the engine.** Adopt the IPM structure explicitly: a *library of SD generic processes*
(constant inflow, first-order drain, transfer proportional to source, goal-seeking gap, delayed
transfer/hidden stock, co-flow, effect multiplier, floor/cap), each with typed slots (which stocks,
signs, units); abduction = "which instantiated process, if added, would explain this residual
signature?" (section 2 gives the mapping); induction = fit and test. Use constraints (conservation,
units, sign conventions) to prune the combinatorial space before fitting. This is a cleaner
framing of what `matrix` already does, and makes adding a new process type a library change rather
than a new strategy.

**For the programme.** The process library *is* our hypothesis language; most "models no
candidate represents" failures are missing library entries or missing combination rules. Keep a
list: for every failing run, which truth process is not expressible in the library? That list is
the generation roadmap.

**Failure modes.** Combinatorial explosion (IPM's main problem: needs beam search, constraints, or
incremental growth). Template libraries encode the designer's assumptions; truths outside them are
invisible (and a library tuned to our 31 examples overfits them). Heuristic growth is greedy and
can lock in an early wrong process (needs backtracking or beam).

## 7. Automated science and closed-loop discovery

**Core idea.** Close the loop: the system generates hypotheses, designs experiments, runs them,
and updates. King et al. (2004, Nature 427:247, "Functional genomic hypothesis generation and
experimentation by a robot scientist") used abductive logic programming plus active choice of
cheap, informative experiments and matched human performance at lower cost; Adam (King et al. 2009,
Science 324:85, "The automation of science") autonomously identified yeast gene functions; Eve
(Williams et al. 2015, J. R. Soc. Interface 12:20141289) used active learning for drug screening.
Kitano (2021, npj Syst Biol Appl) frames a "Nobel Turing challenge". Self-driving labs in chemistry
and materials (Coley, Eyke & Jensen 2020, Angew. Chem.; Szymanski et al. 2023, Nature, A-Lab) use
Bayesian optimisation over experiments. LLM-era "AI scientist" systems (Lu et al. 2024, "The AI
Scientist", arXiv:2408.06292; Gottweis et al. 2025, "Towards an AI co-scientist", arXiv:2502.18864)
automate ideation, coding, experiments and write-up; the reliable ones keep a hard automatic
evaluator in the loop (FunSearch, Romera-Paredes et al. 2024, Nature 625:468; AlphaEvolve,
Novikov et al. 2025, arXiv:2506.13131), and the critiques of the unconstrained ones (e.g. evaluation
of The AI Scientist's outputs finding fabricated or shallow results) show why. Active learning
survey: Settles (2009, UW-Madison CS TR 1648).

**For the engine.** Two loops. Inner: the identify-criticise-expand loop on given data (sections
1-2). Outer (live runs, with sign-off): choose interventions that best discriminate surviving
hypotheses (section 8). The Robot Scientist lesson is that *hypotheses must be executable*: every
hypothesis is a simulatable model, so its prediction for any experiment is computable.

**For the programme.** Our experiment loop (agents in worktrees, strategy + mechanism test + bench)
is a closed-loop research system. Lessons from the automated-science literature: the evaluator
must be fixed and outside the agents' reach (we have this: frozen simulations, fingerprinted);
record negative results (we do); hypothesis generation by agents should be *grounded in a failure
analysis*, not free ideation; and a human or synthesis step should periodically consolidate,
because automated systems accumulate local wins without understanding.

**Failure modes.** Goodharting the evaluator; agents reporting plausible narratives the data do
not support; cost spent on uninformative experiments; ideation diversity collapse (all agents try
similar ideas).

## 8. Sequential experiment design

**Core idea.** Choose the next measurement or perturbation to maximise expected information about
what you are unsure of. Classical optimal design (Fisher 1935; Kiefer 1959; Atkinson, Donev & Tobias
2007); Bayesian design (Lindley 1956; Chaloner & Verdinelli 1995, Stat. Sci. 10:273; Ryan et al.
2016, Int. Stat. Rev.; Rainforth, Foster, Ivanova & Bickford Smith 2024, "Modern Bayesian
experimental design", Stat. Sci. 39:100); *model-discrimination* design (Box & Hill 1967,
Technometrics 9:57: choose the experiment maximising expected divergence between rival models'
predictions; Atkinson & Fedorov 1975 T-optimality); input design for dynamic system identification
(Mehra 1974, IEEE TAC 19:753; Ljung 1999 ch. 13: persistence of excitation); adaptive/amortised
design (Foster et al. 2021, "Deep adaptive design", ICML); in systems biology (Kreutz & Timmer 2009,
FEBS J. 276:923).

**For the engine.** (a) Offline, the analogue of design is *data selection*: identify which time
windows are informative for which coefficient (high excitation, far from equilibrium) and weight
them; flag coefficients estimated only from settled windows as unidentified. (b) Live runs: for the
behavioural set, compute the perturbation of the controllable inputs (a pulse into a stock, a step
in an inflow) that maximises divergence between surviving models' predictions, subject to a cost
and safety budget; ask the user before acting.

**For the programme.** Apply design to our own experiments: choose the next experiment that best
discriminates between rival explanations of the current failures (strong inference, section 13),
not the one that seems most promising. Also: the benchmark is a designed experiment; ensure
generated benchmark models are *excited* (the benchmark-excitation study) so failures are about the
engine, not about data that cannot contain the answer.

**Failure modes.** Optimal designs depend on the (unknown) model; locally optimal designs from a
wrong model are poor (use Bayesian/robust designs over the behavioural set). Perturbing a live
system has real costs.

## 9. Search and verify

**Core idea.** Separate a broad, cheap, possibly unreliable *generator* from a strict, reliable
*verifier*. Generate-and-test is the oldest AI search scheme (Newell & Simon 1972, *Human Problem
Solving*). Modern results show its power when the verifier is good: AlphaCode (Li et al. 2022,
Science 378:1092) samples very many programs and filters by tests; FunSearch (Romera-Paredes et al.
2024) evolves programs scored by an exact evaluator; trained verifiers improve math solving (Cobbe et
al. 2021, arXiv:2110.14168); "best-of-n with a verifier" scaling. In equation discovery, symbolic
regression benchmarks (La Cava et al. 2021, SRBench, NeurIPS Datasets & Benchmarks) find that
methods combining broad search with careful constant fitting and simplicity pressure recover exact
forms most often.

**For the engine.** Our verifier (simulate, multi-step error with penalties, plus the diagnostic
battery) is strong and cheap. The generator should be as broad as compute allows: every strategy
(matrix, SINDy, symbolic regression, delayed-copy regressors, structure search, LLM priors) is a
*candidate source* feeding one shared verifier. Generation can be sloppy; verification must be
uniform. Two-stage verification: a cheap filter (one-step fit, stability, conservation, signs),
then the expensive one (multi-step simulation, perturbed-state agreement).

**For the programme.** Measure generator and verifier separately, always: (i) *coverage*: does any
candidate reach high grader skill? (oracle-pick skill); (ii) *selection*: does the verifier pick it?
(judge rank of the oracle candidate). The held-out-judge study measured this once (oracle 78% vs
picked 70.8% on v1); make both columns standard in the bench output.

**Failure modes.** Verifier exploitation: a broad generator finds candidates that score well on the
verifier but not on the grader (e.g. inflow pieces absorbing dynamics). The verifier needs
complexity penalties and structural plausibility checks to resist its own generator. Cost scales
with breadth.

## 10. Benchmark design and avoiding overfitting a benchmark

**Core idea.** Repeatedly evaluating on a fixed test set and keeping what scores better overfits
the test set even without looking at it (adaptive data analysis: Dwork et al. 2015, "The reusable
holdout", Science 349:636; Blum & Hardt 2015, "The Ladder", ICML). Recht et al. (2019, "Do ImageNet
classifiers generalize to ImageNet?", ICML) built a fresh test set and saw accuracy drops (though
rankings largely held). Remedies: procedurally generated benchmarks with train/test splits over
seeds or level families (Cobbe et al. 2020, "Leveraging procedural generation to benchmark
reinforcement learning", ICML: generalisation gap shrinks only with many training levels); held-out
*families* not just held-out instances; synthetic-to-real gaps (symbolic regression: SRBench's
Feynman and Strogatz sets; ODEBench, d'Ascoli et al. 2024, ODEFormer, ICLR); leakage audits
(Kapoor & Narayanan 2023, Patterns 4:100804); variance-aware comparisons (Bouthillier et al. 2021,
MLSys; Demšar 2006, JMLR 7:1, for comparisons over many datasets; Benavoli et al. 2017, JMLR 18).
Warnings about weak baselines and unreported tuning: Melis, Dyer & Blunsom (2018, ICLR); Henderson
et al. (2018, AAAI, "Deep RL that matters"); Lipton & Steinhardt (2019, "Troubling trends in machine
learning scholarship", ACM Queue 17(1)); Sculley et al. (2018, ICLR workshop, "Winner's curse?").

**For SD Lab specifically.** We have 31 hand-built examples, a 30-second bench, and many agents
making many adopt/reject decisions per day: that is a high adaptive-reuse regime. The goal is "every
example meets the threshold", which rewards fixes to individual examples (each a degree of
freedom). Risk: an engine that passes the 62 runs and fails on the next SD model a user brings.

**For the programme (concrete).**
1. Build the procedural generator ([../procedural-generator.md](../procedural-generator.md)) with
   *motif families* (chains, goal-seeking, co-flows, effects, delays, eras, floors) and composition
   rules. Split: a *development* pool (any seed, used freely), a *validation* pool (scored on every
   bench run), and a *sealed test* pool (fixed seeds plus one or two whole motif families never
   used in development), scored only when adopting into main and logged once.
2. Report the *generalisation gap*: skill on the 31 examples minus skill on the generated
   validation pool. A change that raises the 31 and lowers the pool is overfitting.
3. Report variance: the bench has noise in the data; run more seeds per example (or report
   per-example confidence intervals) and use a paired test (Wilcoxon signed-rank over examples,
   Demšar 2006) for adopt decisions, not "the headline went up".
4. Leakage audit: discovery must not read truth files, names-to-structure maps, or example ids
   (the goal already forbids it); add an automated check (e.g. run discovery on examples with stock
   ids and names permuted/renamed and require identical skill).
5. Freeze the evaluation code per wave; grader fixes are versioned and re-baselined.

**Failure modes.** Generated models can be unrealistic (too easy, too uniform); keep the
hand-built set as the "realism" check and the generated sets as the "generality" check. Sealed sets
leak if consulted often; rotate them.

## 11. Ablation methodology

**Core idea.** Remove or switch off one component at a time and measure the change, to attribute
performance to parts. Hooker (1995, "Testing heuristics: we have it all wrong", J. Heuristics 1:33)
argued for controlled experiments on *why* heuristics work rather than competitive horse races;
McGeoch (2012, *A Guide to Experimental Algorithmics*, CUP) and Johnson (2002, "A theoretician's
guide to the experimental analysis of algorithms") give the methodology. Fawcett & Hoos (2016,
"Analysing differences between algorithm configurations through ablation", J. Heuristics
22:431-458) build an *ablation path* from a source configuration to a target, greedily flipping the
parameter that most changes performance at each step; most of the gain usually comes from a few
changes; Biedenkapp et al. (2017, AAAI) speed it up with surrogates. Functional ANOVA of
hyperparameter importance (Hutter, Hoos & Leyton-Brown 2014, ICML) attributes performance to
components and their interactions. In deep learning, Meyes et al. (2019, arXiv:1901.08644).

**For the engine.** Every mechanism adopted into `matrix` keeps an `opts` switch. The engine can
then also run "ablated variants" as additional candidates (a cheap portfolio, section 12).

**For the programme.** (a) At the end of each wave, run a leave-one-out ablation of the main line
(each adopted mechanism off alone) and a Fawcett-Hoos ablation path from the original baseline to
the main line; mechanisms that contribute nothing are removed. (b) Interactions: when two winners
overlap, measure the 2x2 (neither, A, B, both) rather than adopting sequentially. (c) Per-example
attribution: for each example, which mechanism made it pass. This is the "know why something
works" record the DISCOVERY-LOOP document asks for.

**Failure modes.** Ablations of interacting components mislead (removing A hurts only because B was
tuned with A present). Ablation on the same benchmark used for adoption inherits its overfitting;
ablate on the generated validation pool too.

## 12. Combining many partial methods: ensembles, portfolios, algorithm selection, meta-learning

**Core idea.** No single method is best on all instances (Wolpert & Macready 1997, No Free Lunch,
IEEE TEC 1:67). Combine them:

- **Ensembles** average predictions: bagging (Breiman 1996, ML 24:123), stacking (Wolpert 1992,
  Neural Networks 5:241; for Bayesian predictive distributions Yao et al. 2018, Bayesian Analysis
  13:917), bootstrap ensembles of SINDy models (Fasel et al. 2022, Proc. R. Soc. A 478:20210904,
  E-SINDy).
- **Portfolios** run several algorithms and take the best/first result (Huberman, Lukose & Hogg
  1997, Science 275:51; Gomes & Selman 2001, AI 126:43).
- **Algorithm selection** picks one algorithm per instance from instance features (Rice 1976,
  Advances in Computers 15:65; SATzilla, Xu, Hutter, Hoos & Leyton-Brown 2008, JAIR 32:565; survey
  Kerschke, Hoos, Neumann & Trautmann 2019, Evol. Comput. 27:3).
- **Meta-learning** learns which method works on which kind of data from past runs (Brazdil et al.
  2009/2022, *Metalearning*, Springer; Vanschoren 2018 survey, arXiv:1810.03548). Amortised inference
  (Cranmer, Brehmer & Louppe 2020, PNAS 117:30055) is the extreme: learn the whole data-to-model map
  from simulations.

**For the engine.** Our setting is unusual and favourable: we have a *verifier that applies to
every instance* (simulation fit), so the best combination is a **portfolio with a shared
verifier**, not a learned selector: run all candidate generators, pool candidates, verify. A
selector is needed only for *compute allocation* when the pool is too expensive (route effort by
features: number of stocks, era count, excitation, residual signatures). Combine *per stock row*
where rows are separable (different generators may win different rows), then verify the assembled
model jointly. Stacking of trajectories for prediction only when structures behave alike.

**For the programme.** This is how to avoid a "haphazard amalgamation of tricks": every method is
a candidate generator with a fixed interface (`identify` returning candidates with provenance);
the verifier is one shared component; combination is the portfolio. A new method is valuable iff it
increases *oracle coverage* (it produces the best candidate on some runs no other generator
covers) without degrading selection. Track a coverage matrix: run x generator -> best skill. Its
column of unique wins is each method's contribution (a set-cover view of the portfolio).

**Failure modes.** Pooling more candidates gives the verifier more chances to be fooled (section 9);
cost grows linearly; learned selectors trained on 31 examples overfit (use the generated pool).

## 13. How research itself should be organised (philosophy of method, applied)

- **Multiple working hypotheses** (Chamberlin 1890, Science 15:92; reprinted Science 148:754, 1965):
  hold several rival explanations at once to avoid falling in love with one.
- **Strong inference** (Platt 1964, Science 146:347): devise alternative hypotheses; devise a
  crucial experiment whose outcomes exclude some; run it cleanly; recycle. Fast progress fields do
  this systematically.
- **Research programmes** (Lakatos 1970, in Lakatos & Musgrave eds., *Criticism and the Growth of
  Knowledge*, CUP): a hard core protected by a belt of auxiliary hypotheses; a programme is
  *progressive* if its modifications predict new facts, *degenerating* if they only patch known
  anomalies. Directly applicable: a mechanism that fixes only the example it was designed for is a
  degenerating move; one that also fixes generated models it never saw is progressive.
- **Severe testing** (Mayo 2018, *Statistical Inference as Severe Testing*, CUP): a claim is
  warranted only if it passed a test that would probably have failed were it false: hence mechanism
  tests on synthetic truth where the baseline demonstrably fails.
- **Garden of forking paths / researcher degrees of freedom** (Gelman & Loken 2013; Simmons, Nelson
  & Simonsohn 2011, Psych. Sci. 22:1359): flexible analysis yields false positives; pre-registration
  (Nosek et al. 2018, PNAS 115:2600) fixes the analysis before seeing results.
- **Machine learning that matters** (Wagstaff 2012, ICML): benchmark wins disconnected from the
  real use are hollow; keep the real use (users' SD data) in view.

---

## The ideal end-to-end discovery procedure (engine)

For a dataset of many measured stocks over time, with announced eras, possibly short, noisy,
counted, with unannounced inflow changes.

**0. Contract.** Inputs: levels, units, groups, eras. Output: a set of behaviourally acceptable
models with weights, one recommended model, per-term confidence, and a list of undecided questions.

**1. Look before fitting (identification).**
- Per stock: noise level and type (variance vs level, integer-ness -> counting noise), trend,
  breaks (CUSUM / Bai-Perron on first differences), periodicity, time near zero, saturation.
- Across stocks: conservation candidates (sums that stay constant or change smoothly), lead-lag
  cross-correlations of differences, groups that move together (shared driver), excitation per
  window (where is the system far from equilibrium?).
- Era handling: announced eras define candidate breakpoints; unannounced breaks are flagged as
  hypotheses, not facts.

**2. Generate hypotheses broadly (abduction).**
- Base model: the current matrix method (linear rows with conservation, per-era columns).
- Library of SD processes (section 6) instantiated where the step-1 statistics suggest them
  (conservation -> moves; lead-lag -> links or delays; joint movement -> co-flows; one-sided near
  zero -> floors).
- Other generators as candidate sources: sparse regression with SD-shaped libraries (SINDy),
  symbolic regression for effect curves, delayed-copy regressors, structure search, LLM priors from
  names and units (as *priors on which processes to try first*, never as evidence).
- Prune with hard constraints before fitting: units, conservation, non-negativity, sign rules.

**3. Estimate.** Per row first (fast, regression on measured levels, count-aware weights), then a
joint multi-step (output-error) refinement of the shortlisted models with constraints and stability
enforced. Fit outside inflows as piecewise with a complexity price.

**4. Criticise (diagnostic checking).** For each shortlisted model, run the residual battery of
section 2 on one-step and multi-step residuals; run targeted predictive checks (H-step change
distributions, peaks, periods); run the self-consistency check (re-discover from data simulated by
the found model). Each failure yields a typed proposal.

**5. Expand and repeat.** Apply proposals in order of diagnostic strength, one at a time, refit,
accept if the penalised inflow-conditioned multi-step score improves by more than a calibrated
margin. Beam of width k over proposals to avoid greedy lock-in.

**6. Discriminate among survivors.** Behavioural set = within tolerance of the best. Simulate
members from perturbed states (as the grader does); cluster by behaviour. Within a cluster, pick
the simplest (fewest processes, then fewest hidden stocks). Across clusters, if the data cannot
decide, use priors and report; in a live run, propose the input that best separates the clusters.

**7. Stop.** Stop expanding when (a) all diagnostics pass at the fixed thresholds, or (b) no
proposal improves the penalised score, or (c) the compute budget is spent. Stop the overall run
when the behavioural set is a single behaviour cluster (or the remaining ambiguity is reported).

**8. Report.** Recommended model, alternatives with weights, which terms are poorly identified,
which diagnostics still fail and what they suggest (so a human can add what the library lacks), and
the trace of the loop.

## The ideal research programme (team)

**Principles.** One hard core (the identify-estimate-criticise-expand loop with a shared verifier),
everything else a pluggable generator, diagnostic, or prior with an off-switch. Progress is measured
on three axes, always reported separately: *coverage* (oracle-pick skill), *selection* (judge picks
the oracle candidate), *generalisation* (gap between hand-built and generated sets).

**Phase 0: instrumentation (before more mechanisms).**
1. Bench output gains columns: oracle-pick skill, judge rank of oracle candidate, failure class
   (not representable / not chosen / not identifiable), per-example confidence interval.
2. The procedural generator with motif families and a sealed test split (section 10).
3. The diagnostic battery as a standalone tool, scored for how often each diagnostic correctly
   names the missing truth component on generated models (a legal, truth-using study of a tool).
4. A leakage check (permuted names and ids give the same skill).

**Phase 1: failure taxonomy.** Run the main line on the 31 examples and a few hundred generated
models; classify every failing run; for "not representable" runs, list the missing process type.
This list, sorted by how many runs it affects, *is* the experiment queue. Each experiment states
which failure class and which runs it targets and predicts which rows will change (a strong-inference
style prediction recorded before the run).

**Phase 2: waves of isolated experiments** (the existing DISCOVERY-LOOP), with three additions:
- adopt only with a paired test over examples *and* no significant loss on the generated validation
  pool;
- a mechanism must be progressive in Lakatos's sense: it must help some generated models it was not
  designed on;
- record per-example attribution (which mechanism made which run pass).

**Phase 3: consolidation every few waves.** Leave-one-out ablation and an ablation path on the
main line; remove mechanisms that contribute nothing; refactor generators into the process
library; re-baseline; score the sealed test set once and log it.

**Phase 4: closing the loop.** When the inner loop is solid, add experiment design for live runs
(with the user's sign-off) and the self-consistency/fake-data checks as default engine steps.

**How to know why something works.** A claim "mechanism M fixes failure F" needs: (i) a synthetic
model where F occurs, M fixes it, and the baseline does not (mechanism test, already required);
(ii) the residual signature of F present before and gone after on the named examples; (iii) a gain
on generated models containing F and no gain (and no loss) on models without F (a specificity
check); (iv) a positive leave-M-out ablation on the current main line. Without (iii) and (iv), the
result is a benchmark coincidence.

**Avoiding haphazard amalgamation.** No mechanism enters main except as one of: a library process,
a diagnostic, a generator, a constraint/prior, or a verifier change, each behind a fixed interface.
A mechanism that does not fit any of these is a sign the hard core needs redesign, which is its own
explicit experiment, not a side effect.

---

## Reading list

Core, read first:
- Box, G.E.P. & Jenkins, G.M. (1970). *Time Series Analysis: Forecasting and Control*. Holden-Day (5th ed. with Reinsel & Ljung, Wiley 2015).
- Box, G.E.P. (1980). Sampling and Bayes' inference in scientific modelling and robustness. *J. R. Stat. Soc. A* 143(4):383-430. doi:10.2307/2982063
- Gelman, A., Vehtari, A., Simpson, D., et al. (2020). Bayesian Workflow. arXiv:2011.01808. https://arxiv.org/abs/2011.01808
- Ljung, L. (1999). *System Identification: Theory for the User*, 2nd ed. Prentice Hall.
- Burnham, K.P. & Anderson, D.R. (2002). *Model Selection and Multimodel Inference*, 2nd ed. Springer. doi:10.1007/b97636
- Bridewell, W., Langley, P., Todorovski, L. & Džeroski, S. (2008). Inductive process modeling. *Machine Learning* 71:1-32. doi:10.1007/s10994-007-5042-6
- Beven, K. (2006). A manifesto for the equifinality thesis. *J. Hydrology* 320:18-36. doi:10.1016/j.jhydrol.2005.07.007
- Platt, J.R. (1964). Strong inference. *Science* 146:347-353. doi:10.1126/science.146.3642.347
- Fawcett, C. & Hoos, H.H. (2016). Analysing differences between algorithm configurations through ablation. *J. Heuristics* 22(4):431-458. preprint https://www.cs.ubc.ca/labs/beta/Projects/Ablation/papers/FawcettHoos-joh2016-ablationAnalysis.pdf
- Cobbe, K., Hesse, C., Hilton, J. & Schulman, J. (2020). Leveraging procedural generation to benchmark reinforcement learning. *ICML*. arXiv:1912.01588

Residual diagnostics and structural change:
- Ljung, G.M. & Box, G.E.P. (1978). On a measure of lack of fit in time series models. *Biometrika* 65(2):297-303.
- Billings, S.A. & Voon, W.S.F. (1986). Correlation based model validity tests for non-linear models. *Int. J. Control* 44(1):235-244.
- Billings, S.A. (2013). *Nonlinear System Identification: NARMAX Methods in the Time, Frequency, and Spatio-Temporal Domains*. Wiley.
- Ramsey, J.B. (1969). Tests for specification errors in classical linear least-squares regression analysis. *J. R. Stat. Soc. B* 31(2):350-371.
- Tsay, R.S. (1986). Nonlinearity tests for time series. *Biometrika* 73(2):461-466.
- Brock, W.A., Dechert, W.D., Scheinkman, J.A. & LeBaron, B. (1996). A test for independence based on the correlation dimension. *Econometric Reviews* 15(3):197-235.
- Brown, R.L., Durbin, J. & Evans, J.M. (1975). Techniques for testing the constancy of regression relationships over time. *J. R. Stat. Soc. B* 37(2):149-192.
- Bai, J. & Perron, P. (1998). Estimating and testing linear models with multiple structural changes. *Econometrica* 66(1):47-78.
- Castle, J.L., Doornik, J.A. & Hendry, D.F. (2011). Evaluating automatic model selection. *J. Time Series Econometrics* 3(1).
- Mizon, G.E. & Richard, J.-F. (1986). The encompassing principle and its application to testing non-nested hypotheses. *Econometrica* 54(3):657-678.

Model selection, CV, prequential, averaging:
- Akaike, H. (1974). A new look at the statistical model identification. *IEEE TAC* 19(6):716-723.
- Schwarz, G. (1978). Estimating the dimension of a model. *Ann. Stat.* 6(2):461-464.
- Rissanen, J. (1978). Modeling by shortest data description. *Automatica* 14:465-471; Grünwald, P. (2007). *The Minimum Description Length Principle*. MIT Press.
- Kass, R.E. & Raftery, A.E. (1995). Bayes factors. *JASA* 90(430):773-795.
- Dawid, A.P. (1984). Statistical theory: the prequential approach. *J. R. Stat. Soc. A* 147(2):278-292.
- Gneiting, T. & Raftery, A.E. (2007). Strictly proper scoring rules, prediction, and estimation. *JASA* 102(477):359-378.
- Racine, J. (2000). Consistent cross-validatory model-selection for dependent data: hv-block cross-validation. *J. Econometrics* 99:39-61.
- Tashman, L.J. (2000). Out-of-sample tests of forecasting accuracy: an analysis and review. *Int. J. Forecasting* 16:437-450.
- Bergmeir, C., Hyndman, R.J. & Koo, B. (2018). A note on the validity of cross-validation for evaluating autoregressive time series prediction. *Comput. Stat. Data Anal.* 120:70-83. doi:10.1016/j.csda.2017.11.003
- Bürkner, P.-C., Gabry, J. & Vehtari, A. (2020). Approximate leave-future-out cross-validation for Bayesian time series models. *J. Stat. Comput. Simul.* 90(14):2499-2523. doi:10.1080/00949655.2020.1783262 ; arXiv:1902.06281
- Roberts, D.R. et al. (2017). Cross-validation strategies for data with temporal, spatial, hierarchical, or phylogenetic structure. *Ecography* 40:913-929.
- Arlot, S. & Celisse, A. (2010). A survey of cross-validation procedures for model selection. *Statistics Surveys* 4:40-79.
- Vehtari, A., Gelman, A. & Gabry, J. (2017). Practical Bayesian model evaluation using leave-one-out cross-validation and WAIC. *Stat. Comput.* 27:1413-1432.
- Hoeting, J.A., Madigan, D., Raftery, A.E. & Volinsky, C.T. (1999). Bayesian model averaging: a tutorial. *Stat. Sci.* 14(4):382-417.
- Yao, Y., Vehtari, A., Simpson, D. & Gelman, A. (2018). Using stacking to average Bayesian predictive distributions. *Bayesian Analysis* 13(3):917-1007.
- Toni, T., Welch, D., Strelkowa, N., Ipsen, A. & Stumpf, M.P.H. (2009). Approximate Bayesian computation scheme for parameter inference and model selection in dynamical systems. *J. R. Soc. Interface* 6:187-202.
- Kirk, P., Thorne, T. & Stumpf, M.P.H. (2013). Model selection in systems and synthetic biology. *Curr. Opin. Biotechnol.* 24:767-774.
- Freedman, D.A. (1983). A note on screening regression equations. *Am. Stat.* 37(2):152-155.

Bayesian workflow and checking:
- Talts, S., Betancourt, M., Simpson, D., Vehtari, A. & Gelman, A. (2018). Validating Bayesian inference algorithms with simulation-based calibration. arXiv:1804.06788
- Gelman, A., Meng, X.-L. & Stern, H. (1996). Posterior predictive assessment of model fitness via realized discrepancies. *Statistica Sinica* 6:733-807.
- Gelman, A. & Shalizi, C.R. (2013). Philosophy and the practice of Bayesian statistics. *Br. J. Math. Stat. Psychol.* 66:8-38.
- Gabry, J., Simpson, D., Vehtari, A., Betancourt, M. & Gelman, A. (2019). Visualization in Bayesian workflow. *J. R. Stat. Soc. A* 182(2):389-402.
- Gelman, A. & Loken, E. (2013). The garden of forking paths. Working paper, Columbia University.

Equifinality and identifiability:
- Beven, K. & Binley, A. (1992). The future of distributed models: model calibration and uncertainty prediction. *Hydrological Processes* 6:279-298.
- Breiman, L. (2001). Statistical modeling: the two cultures. *Stat. Sci.* 16(3):199-231.
- Semenova, L., Rudin, C. & Parr, R. (2022). On the existence of simpler machine learning models. *FAccT* (Rashomon ratio).
- Gutenkunst, R.N. et al. (2007). Universally sloppy parameter sensitivities in systems biology models. *PLoS Comput. Biol.* 3(10):e189.
- Raue, A. et al. (2009). Structural and practical identifiability analysis of partially observed dynamical models by exploiting the profile likelihood. *Bioinformatics* 25(15):1923-1929.

System dynamics validation:
- Forrester, J.W. & Senge, P.M. (1980). Tests for building confidence in system dynamics models. *TIMS Studies in the Management Sciences* 14:209-228.
- Barlas, Y. (1996). Formal aspects of model validity and validation in system dynamics. *System Dynamics Review* 12(3):183-210.
- Oliva, R. (2003). Model calibration as a testing strategy for system dynamics models. *Eur. J. Oper. Res.* 151(3):552-568.
- Sterman, J.D. (2000). *Business Dynamics*. McGraw-Hill, ch. 21.

Discovery, abduction, automated science:
- Peirce, C.S. *Collected Papers*, vol. 5 (1934), esp. 5.189; Hanson, N.R. (1958). *Patterns of Discovery*. CUP.
- Simon, H.A. (1973). Does scientific discovery have a logic? *Phil. Sci.* 40(4):471-480.
- Langley, P., Simon, H.A., Bradshaw, G.L. & Zytkow, J.M. (1987). *Scientific Discovery: Computational Explorations of the Creative Processes*. MIT Press.
- Klahr, D. & Dunbar, K. (1988). Dual space search during scientific reasoning. *Cognitive Science* 12:1-48.
- Džeroski, S. & Todorovski, L. (eds.) (2007). *Computational Discovery of Scientific Knowledge*. Springer LNAI 4660.
- Todorovski, L. & Džeroski, S. (1997). Declarative bias in equation discovery. *ICML*.
- Langley, P. & Arvay, A. (2017). Flexible model induction through heuristic process discovery. *AAAI*.
- Schmidt, M. & Lipson, H. (2009). Distilling free-form natural laws from experimental data. *Science* 324:81-85.
- Brunton, S.L., Proctor, J.L. & Kutz, J.N. (2016). Discovering governing equations from data by sparse identification of nonlinear dynamical systems. *PNAS* 113(15):3932-3937.
- King, R.D. et al. (2004). Functional genomic hypothesis generation and experimentation by a robot scientist. *Nature* 427:247-252. doi:10.1038/nature02236
- King, R.D. et al. (2009). The automation of science. *Science* 324:85-89. doi:10.1126/science.1165620
- Williams, K. et al. (2015). Cheaper faster drug development validated by the repositioning of drugs against neglected tropical diseases. *J. R. Soc. Interface* 12:20141289.
- Kitano, H. (2021). Nobel Turing Challenge: creating the engine for scientific discovery. *npj Syst. Biol. Appl.* 7:29.
- Lu, C. et al. (2024). The AI Scientist: towards fully automated open-ended scientific discovery. arXiv:2408.06292
- Gottweis, J. et al. (2025). Towards an AI co-scientist. arXiv:2502.18864
- Romera-Paredes, B. et al. (2024). Mathematical discoveries from program search with large language models. *Nature* 625:468-475.
- Novikov, A. et al. (2025). AlphaEvolve: a coding agent for scientific and algorithmic discovery. arXiv:2506.13131
- Shojaee, P. et al. (2025). LLM-SR: scientific equation discovery via programming with large language models. *ICLR*.
- Settles, B. (2009). Active learning literature survey. UW-Madison CS Tech. Rep. 1648.

Experiment design:
- Box, G.E.P. & Hill, W.J. (1967). Discrimination among mechanistic models. *Technometrics* 9(1):57-71.
- Atkinson, A.C. & Fedorov, V.V. (1975). The design of experiments for discriminating between two rival models. *Biometrika* 62(1):57-70.
- Chaloner, K. & Verdinelli, I. (1995). Bayesian experimental design: a review. *Stat. Sci.* 10(3):273-304.
- Rainforth, T., Foster, A., Ivanova, D.R. & Bickford Smith, F. (2024). Modern Bayesian experimental design. *Stat. Sci.* 39(1):100-114.
- Foster, A., Ivanova, D.R., Malik, I. & Rainforth, T. (2021). Deep adaptive design. *ICML*.
- Mehra, R.K. (1974). Optimal input signals for parameter estimation in dynamic systems: survey and new results. *IEEE TAC* 19(6):753-768.
- Kreutz, C. & Timmer, J. (2009). Systems biology: experimental design. *FEBS J.* 276:923-942.

Search, verification, benchmarks, ablation, combination:
- Newell, A. & Simon, H.A. (1972). *Human Problem Solving*. Prentice-Hall.
- Li, Y. et al. (2022). Competition-level code generation with AlphaCode. *Science* 378:1092-1097.
- Cobbe, K. et al. (2021). Training verifiers to solve math word problems. arXiv:2110.14168
- La Cava, W. et al. (2021). Contemporary symbolic regression methods and their relative performance. *NeurIPS Datasets & Benchmarks*. arXiv:2107.14351
- d'Ascoli, S., Becker, S., Mathis, A., Schwaller, P. & Kilbertus, N. (2024). ODEFormer: symbolic regression of dynamical systems with transformers. *ICLR* (ODEBench).
- Dwork, C. et al. (2015). The reusable holdout: preserving validity in adaptive data analysis. *Science* 349:636-638.
- Blum, A. & Hardt, M. (2015). The Ladder: a reliable leaderboard for machine learning competitions. *ICML*.
- Recht, B., Roelofs, R., Schmidt, L. & Shankar, V. (2019). Do ImageNet classifiers generalize to ImageNet? *ICML*.
- Kapoor, S. & Narayanan, A. (2023). Leakage and the reproducibility crisis in machine-learning-based science. *Patterns* 4(9):100804.
- Demšar, J. (2006). Statistical comparisons of classifiers over multiple data sets. *JMLR* 7:1-30.
- Benavoli, A., Corani, G., Demšar, J. & Zaffalon, M. (2017). Time for a change: a tutorial for comparing multiple classifiers through Bayesian analysis. *JMLR* 18(77):1-36.
- Bouthillier, X. et al. (2021). Accounting for variance in machine learning benchmarks. *MLSys*.
- Melis, G., Dyer, C. & Blunsom, P. (2018). On the state of the art of evaluation in neural language models. *ICLR*.
- Henderson, P. et al. (2018). Deep reinforcement learning that matters. *AAAI*.
- Lipton, Z.C. & Steinhardt, J. (2019). Troubling trends in machine learning scholarship. *ACM Queue* 17(1).
- Hooker, J.N. (1995). Testing heuristics: we have it all wrong. *J. Heuristics* 1:33-42.
- McGeoch, C.C. (2012). *A Guide to Experimental Algorithmics*. CUP.
- Hutter, F., Hoos, H. & Leyton-Brown, K. (2014). An efficient approach for assessing hyperparameter importance. *ICML*.
- Biedenkapp, A., Lindauer, M., Eggensperger, K., Hutter, F., Fawcett, C. & Hoos, H. (2017). Efficient parameter importance analysis via ablation with surrogates. *AAAI*.
- Wolpert, D.H. & Macready, W.G. (1997). No free lunch theorems for optimization. *IEEE TEC* 1(1):67-82.
- Wolpert, D.H. (1992). Stacked generalization. *Neural Networks* 5:241-259; Breiman, L. (1996). Bagging predictors. *Machine Learning* 24:123-140.
- Fasel, U., Kutz, J.N., Brunton, B.W. & Brunton, S.L. (2022). Ensemble-SINDy. *Proc. R. Soc. A* 478:20210904.
- Rice, J.R. (1976). The algorithm selection problem. *Advances in Computers* 15:65-118.
- Huberman, B.A., Lukose, R.M. & Hogg, T. (1997). An economics approach to hard computational problems. *Science* 275:51-54.
- Gomes, C.P. & Selman, B. (2001). Algorithm portfolios. *Artificial Intelligence* 126:43-62.
- Xu, L., Hutter, F., Hoos, H.H. & Leyton-Brown, K. (2008). SATzilla: portfolio-based algorithm selection for SAT. *JAIR* 32:565-606.
- Kerschke, P., Hoos, H.H., Neumann, F. & Trautmann, H. (2019). Automated algorithm selection: survey and perspectives. *Evol. Comput.* 27(1):3-45.
- Cranmer, K., Brehmer, J. & Louppe, G. (2020). The frontier of simulation-based inference. *PNAS* 117(48):30055-30062.

Philosophy of method:
- Chamberlin, T.C. (1890). The method of multiple working hypotheses. *Science* 15:92-96.
- Lakatos, I. (1970). Falsification and the methodology of scientific research programmes. In Lakatos & Musgrave (eds.), *Criticism and the Growth of Knowledge*. CUP.
- Mayo, D.G. (2018). *Statistical Inference as Severe Testing*. CUP.
- Simmons, J.P., Nelson, L.D. & Simonsohn, U. (2011). False-positive psychology. *Psych. Sci.* 22(11):1359-1366.
- Nosek, B.A., Ebersole, C.R., DeHaven, A.C. & Mellor, D.T. (2018). The preregistration revolution. *PNAS* 115(11):2600-2606.
- Wagstaff, K.L. (2012). Machine learning that matters. *ICML*.
- Box, G.E.P. (1976). Science and statistics. *JASA* 71(356):791-799.

*Note on citations:* bibliographic details were taken from memory of the literature and spot-checked
online for the less familiar ones (Fawcett & Hoos 2016; Bürkner, Gabry & Vehtari 2020; Bridewell et
al. 2008). Page ranges for a few book chapters and workshop papers should be checked before anyone
quotes them.
