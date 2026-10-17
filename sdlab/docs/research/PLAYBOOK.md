# Playbook: discerning a system dynamics model from data

Synthesis of the literature chain (2026-10-17). It turns six literature reviews, the tools survey and
our own experiments into one procedure, maps it onto `sdlab/discovery/`, and ranks the experiments
to run next.

Inputs:
- the six reviews in [literature/](literature/): [system identification](literature/system-identification.md) (SI),
  [equation discovery](literature/equation-discovery.md) (ED), [signals and time series](literature/signals-and-time-series.md) (ST),
  [the System Dynamics field](literature/system-dynamics-field.md) (SD), [compartmental analogues](literature/compartmental-analogues.md) (CA),
  [research process](literature/research-process.md) (RP); the [tools survey](SD-TOOLS-AND-DISCOVERY.md) (TS);
- our state: [DISCOVERY-GOAL.md](../DISCOVERY-GOAL.md), [DISCOVERY-LOOP.md](../DISCOVERY-LOOP.md),
  [DISCOVERY-EXPERIMENTS.md](../DISCOVERY-EXPERIMENTS.md), and the topic documents in [README.md](README.md);
- the code: `sdlab/discovery/` (matrix method), `sdlab/sdtruth.py` (how data is made), `tests/bench/grade.py`.

**Citations.** 130 sources that the recommendations below rest on were checked by web search
(Crossref, publisher pages, arXiv, PMLR, the SD Society and Albany archives): **118 verified as cited,
11 verified with corrections, 1 not found** in the form cited (Peterson 1980 as a chapter; the 1976 MIT
paper of the same title was found and is cited instead). The table is in [Appendix A](#appendix-a-citations-checked).
A claim in the six reviews that rests only on a source *not* in that table is not used here as
evidence.

**Experiment ids** used below: `I1`-`I5` are infrastructure (measurement), `M1`-`M15` are mechanisms.
The ranked plan is in section 4.

---

## 1. Summary: the procedure the research supports

The six traditions, which grew up apart, describe almost the same procedure. In plain words:

1. **Look before fitting.** Compute cheap statistics per stock and across stocks before any search:
   how much each stock moves (excitation), whether it sits at zero or at a ceiling, whether it only
   accumulates, how noisy its steps are compared with counting noise (variance against mean), whether
   the per-unit totals stay constant, and how stocks' step changes co-vary (a move makes two stocks'
   changes mirror each other; a shared outside driver makes them move together). These decide what the
   data can identify at all. (SI section 18; ST section 9; SD section 11; RP section 1.)
2. **Count before searching, and take the analyst's budget.** Estimate how much structure the data can
   carry: how many state variables beyond the measured stocks (hidden stocks), how many independent
   level-driven flows, how many genuine outside-input changes. Combine that with what the analyst can
   say up front ("no more than 10 stocks worth talking about", "demand changes a few times a season,
   not daily"): a stated complexity budget is a legitimate prior. Use the smaller of the two as the
   budget and as a stopping point. (SI sections 4 and 15; ST section 5.3; CA section 6 on a parameter
   budget per series; [complexity-budget](complexity-budget.md).)
3. **Generate hypotheses broadly, from a library of SD processes.** A model is a sum of processes
   (move, inflow, outflow, link, co-flow, delay, goal gap, effect multiplier), each with a few rate
   forms. Physics (conservation, units, signs, nothing leaves an empty stock) prunes the space before
   anything is fitted. Every method (regression, sparse regression, symbolic search, structure search)
   is a *generator* of candidates. (ED section 1.3; RP sections 6 and 9; CA section 6.)
4. **Fit fast, with the right noise model.** One-step regression of each stock's change on the
   levels at the start of the step is unbiased for our data (levels are exact integer counts); weight
   it by counting noise (variance equals the mean of the flows touching the stock) and use the
   covariance between stocks' changes as evidence of which flows join them. Estimate outside-input
   changes jointly with the dynamics, with a price that does not let them absorb internal behaviour.
   Treat steps where a floor or a cap binds as censored. (ED section 4.9; CA sections 3, 4, 8; SI
   sections 9-10; ST section 3.)
5. **Criticise each fitted model, row by row, and let the shape of the failure name the next
   structural move.** Autocorrelated residuals: a missing delay or hidden stock. Residuals that follow
   another stock's lagged level: a missing link or delayed flow. Residuals that follow a product of
   levels: an effect. One-sided residuals near zero: a floor or cap. A step in cumulative residuals:
   an unannounced change. Too much variance for counting noise: something missing; variance that
   grows with level: the noise model, not new structure. Add one proposal at a time and keep it only if
   the model's behaviour improves by more than its price. (SI sections 2, 12; RP section 2; SD
   section 11.)
6. **Select on the question asked.** Judge candidates by multi-step simulation from many starts,
   at several horizons, with outside inflows held as estimated, after their rates have been refitted by
   that criterion (multiple shooting). Before that, reject candidates whose behaviour the data rule
   out: a loop that grows where nothing grows, a stock driven negative, a run-off under extreme
   starting levels. (SI sections 1, 13, 16; ED summary 2 and 5; SD sections 3, 5; CA section 2.)
7. **Discriminate among the survivors honestly.** Several structures often predict the same data
   (a move vs an outflow plus a linked inflow; two waits in either order; series vs parallel hidden
   paths). Enumerate those equivalents, check whether they still agree from perturbed starting states,
   and choose by a declared preference (fewest outside flows, fewest hidden stocks), not by a tiny
   score gap. Bootstrap the data to see which flows keep appearing. (CA section 1, 4; SI section 3; RP
   section 5; ED section 4.5.)
8. **Stop** when the diagnostics are clean at fixed thresholds, or no proposal improves the
   penalised behaviour score, or the remaining ambiguity is one the data cannot settle. (RP
   "ideal procedure", step 7.)
9. **Report** the recommended model, the alternatives that fit about as well, which numbers the data
   pin down and which they do not, what each structural choice rests on, and which diagnostics still
   fail (so a human can add what the library lacks). (SD section 10; RP step 8; CA section 9.)

And for the research programme running this: **instrument before adding mechanisms** (measure
coverage, selection and generalisation separately), **test on generated systems the engine was not
tuned on**, **one hypothesis per experiment with a control that should not move**, and **keep an off
switch on everything** so the main line stays a set of parts whose contribution is known (RP sections
9-13).

What this changes for us, in one sentence: our engine already fits fast, conserves and judges by
behaviour; what it lacks is (a) a criticise-and-expand loop that proposes structure the candidates
cannot express (effects, co-flows, delays), (b) a behaviour-consistency gate against runaway models,
(c) use of the second moments of counting noise, and (d) measurement that separates "no candidate was
right" from "the judge chose wrong" from "the data cannot tell".

---

## 2. Where the traditions agree, where they disagree, and what our experiments already say

### 2.1 Convergences (independent traditions recommending the same thing)

| # | Recommendation | Traditions | Our evidence |
|---|---|---|---|
| 1 | **Judge (and select) by the intended-use criterion: multi-step simulation, several horizons** | SI, ED, CA, RP, SD (5) | Strongly confirmed. Choosing candidates by behaviour on the data took v1 from 15.5% to 58.2% mean skill@20; judging at 20 steps only picked loops that mimicked an outside input (graded -62000%); 5/20/100 fixed it (DISCOVERY-EXPERIMENTS). [output-error](output-error.md): +2.7 / +3.8 as a final step. |
| 2 | **Residual diagnostics propose the next structural move** | SI, RP, SD, ST, ED (5) | Not tried. Every structural failure in the log was found by a human reading residuals; the engine has no such loop. |
| 3 | **Use the second moments of counting noise** (a move's draw is seen at both ends; covariance of changes = minus the flow) | ED, ST, CA, SI (4) | Partly confirmed. [shared-noise](shared-noise.md): parts +3.5, 14 relationships gained, skill neutral; the correct reading of sd-services' links exposed a biased drain that the wrong reading had hidden. The mechanism works; it needs the drain-bias fix (M4). |
| 4 | **Physics as hard constraints, including positivity and behaviour consistency** (no loop that grows where nothing grows) | SI, ED, SD, RP (4) | Indirectly confirmed: conservation and units rules are what made the matrix method work (DISCOVERY-EXPERIMENTS, "the matrix method"); the worst runs are still runaways (v2: sd-bakery default -1170%, sd-print-shop, sd-clinic-doses, sd-support-tiers default). Caveat from our data: some truths are legitimately unstable in their linear part (sd-manufacturing 1.047, held by floors; [benchmark-excitation](benchmark-excitation.md)). |
| 5 | **Hidden stocks are delays: count them first, estimate the delay kernel, expect only the mean delay to be well identified** | SI, ST, SD, CA, ED (5) | Confirmed in part ([hidden-stocks](hidden-stocks.md), delayed copies on a grid, v1): five true hidden stocks found, 18 -> 20 runs meeting the goal, but one false hidden stock (sd-population default 68% -> 7%), accepted by an in-sample judge. Needs a count before the search and a gate the in-sample fit cannot fool (M7, M1, M15). |
| 6 | **Unannounced input changes absorb internal dynamics unless estimated jointly and priced honestly; check that a structural fix removes them** | SI, ST, CA, SD, RP (5) | Confirmed repeatedly: sd-population long read births as a move paid back by 151 inflow pieces (graded -7701%); level-for-pieces kept; [change-price](change-price.md): the textbook price fails because the intake changes at a steady rate and missed changes bias the drain (a spiral). [output-error](output-error.md): re-estimating inflows per candidate lost (66.6%). |
| 7 | **Effects are a flow coefficient that varies with a scheduler stock: expand it in a small basis that stays linear in the parameters, screen by correlation with products** | SI, ED, SD, CA, ST (5) | Gap confirmed: on benchmark v2 discovery never proposes an effect; the five effect examples are read as links (sd-sawmill -331%/-276% skill@20). |
| 8 | **Equifinality: report classes of equivalent structures, prefer the simplest, do not let score noise decide** | CA, SI, RP, SD, ED (5) | Consistent: [held-out-judge](held-out-judge.md) found the judge picks the best candidate in 31 of 42 runs and an oracle reaches only 78%; sd-population is not excited enough to decide ([benchmark-excitation](benchmark-excitation.md)). |
| 9 | **Benchmark hygiene: many generated systems, held-out families, no per-system tuning** | ED, RP, CA (3) | Risk present: 31 hand-built examples, ~30 s bench, many adopt/reject decisions per day. |
| 10 | **Bootstrap / ensemble inclusion probabilities** | ED, SD, CA, RP (4) | Not tried ([bayesian-structure](bayesian-structure.md)). |
| 11 | **A declarative process library (grammar of SD processes)** | ED, RP, SD, CA (4) | Our forms are hard-coded in `matrix.py`/`flows.py`; co-flows and effects have no path in. |
| 12 | **Floors and caps are censoring / hybrid modes, not noise** | SI, ED, CA, SD (4) | Partly confirmed ([floors-and-caps](floors-and-caps.md)): caps by EM a small net gain; hinges work in isolation but imitate unannounced seasons on the bench. |
| 13 | **Shortlist with the fast fit, refit the shortlist by simulation, multi-start** | ED, CA, SI (3) | Mixed: refinement of the chosen model helps (+2.7); refining the best 3 candidates was rejected ([output-error](output-error.md)). See conflict C4. |
| 14 | **Bound complexity explicitly: a fixed number of change points, a model order, a parameter budget per measured series, structure added one unit at a time** | SI (order selection, Bai-Perron's m breaks), ST (segment neighbourhood vs PELT), CA (Jakeman and Hornberger: 4-6 parameters per series; automatic tools drift to over-complex models), ED (Daniels and Nemenman: one hidden variable at a time), SD (Lyneis: a model that fits by exogenous drivers explains nothing) (5) | Our flexibility failures are all over-spending: 151 inflow pieces where the truth is a constant (sd-population), pieces into internal stocks (sd-support-tiers), a false hidden stock (hidden-stocks). The change-price experiment showed no single price per change suits every example, which is what a budget (a count, not a price) sidesteps. |

### 2.2 Conflicts and how our data settles them

- **C1. Kalman / state-space likelihood as the first thing to build** (TS ranks it 1; SD section 4
  calls it the field's own answer) **vs** our evidence that selection is not the bottleneck. With every
  measured stock observed exactly, the Kalman one-step likelihood of a model without hidden stocks *is*
  the one-step conditional likelihood, i.e. a weighted regression with covariance S·diag(q)·Sᵀ (ED
  section 4.9; CA section 4). **Resolution:** take the noise model now, as count-aware weights and
  covariance evidence (M4); keep filtering for candidates with hidden stocks (M14, after M7).
- **C2. Weak-form / integral fitting** (TS ranks it 5) **vs** ED section 4.4 (weak forms help under
  measurement noise; ours is process noise on exact counts) and our own log ("single steps, no
  windows": 5-step windows biased working->review 0.08 instead of 0.2). **Resolution:** do not pursue
  for the benchmark; revisit only if real user data with measurement error arrives.
- **C3. Errors-in-variables as the cause of drain bias** (SD sections 4 and 10, after Senge 1977; ST
  section 5.1) **vs** ED's opening section and SI section 11: our regressors are levels at the start of
  the step, exact integers, so classical errors-in-variables does not apply. **Resolution:** the drain
  bias we see comes from inflow pieces competing with the drain (change-price, conservation re-measure
  bug) and from coloured residuals left by unmodelled hidden stocks. Fix it by joint estimation (M6),
  by second-moment estimates (M4), or by instruments that move the level but not the residual (era
  switches; SI section 5), not by EIV corrections.
- **C4. Select structure by simulation error** (SI, ED, CA: the fitting method changes which structure
  wins, Čerepnalkoski et al. 2012) **vs** our output-error result (refining the best 3 candidates was
  rejected; "numbers cannot fix structure"). **Resolution:** both hold. Simulation-error selection
  matters when the right structure is among the candidates; on v1 it mostly was not (oracle 78%).
  Coverage first (M3, M4, M5, M7); output-error stays a final stage (M2) and is re-tested as a selector
  once coverage rises.
- **C5. Held-out validation** (SI section 12, RP section 3, CA section 2 recommend it) **vs** our
  rejected [held-out-judge](held-out-judge.md) (-4.8%). **Resolution:** RP section 3 and SI section 12
  explain the failure: a held-out block must forecast an unannounced input, so it measured inflow
  extrapolation, not dynamics. An inflow-conditioned held-out score (freeze coefficients, re-estimate a
  coarse inflow) or an era hold-out (SD section 10) asks the bench's question. Low priority (M12)
  because the in-data judge already picks well.
- **C6. Impose stability** (ED section 4.6, SI section 16) **vs** SD section 5 ("consistency with the
  data, not always stable") and our truths (population growth; sd-manufacturing's linear part is
  unstable and held by floors). **Resolution:** gate on simulated behaviour with floors and caps from
  observed and extreme starting states, use eigenvalues only to locate the responsible coefficient
  (M1).
- **C7. Calibrated BIC-type price for input changes** (SI section 10) **vs** our change-price result
  (2 x log n fails). **Resolution:** ST section 3 gives the reason (residuals of a misspecified drain
  are autocorrelated, which makes any fixed penalty wrong; a fixed count of changes is assumed while the
  intake changes at a steady rate). Detect changes on innovations, choose the penalty per stock from
  the penalty path, and tie the minimum piece length to the row's time constant (M6).
- **C8. "Our simulator is exactly binomial thinning / Euler-multinomial"** (CA section 3, SI
  section 17) **vs** the code: `sdtruth.py` draws each flow Poisson around its rate, then, if a stock's
  outflows want more than it holds, scales them down to what it holds (floored to integers). Poisson
  mean-variance holds except on capped steps; binomial thinning is close only for small drains.
  **Resolution:** use Poisson / linear-noise weights, and treat capped steps as censored (M4, M9).
- **C9. Hinge (piecewise) terms for floors** (SI section 9) **vs** our floors experiment (hinges
  imitate unannounced seasons; flipping a hinge's side swung sd-manufacturing from 72.8% to -354%).
  **Resolution:** offer a floor or cap only for stocks whose observed range reaches the implied
  threshold (CA section 6, hydrology: thresholds are visible only when they bind), and diagnose in the
  order inputs, floors, links, delays, effects (SI section 12) (M9).
- **C11. Accept added structure by in-sample fit** (implicit in stepwise BIC and in our judge) **vs**
  CA section 2 (automatic search drifts to over-complex models), RP section 9 (a broad generator fools
  its own verifier) and our hidden-stocks result (a false hidden stock in sd-population accepted
  in-sample). **Resolution:** additions that add flexibility (hidden stocks, pieces, hinges, effects)
  must pass a test in-sample fits cannot game: the fresh-run grade as a bench column, the behaviour
  gate (M1), and a stated budget (M15).
- **C10. CCM, Granger, transfer entropy for structure** (mentioned in TS and ST) **vs** ST section 6
  and CA section 5: in strongly coupled, strongly forced, closed-loop systems they report the wrong
  direction or nothing beyond our regression. **Resolution:** do not use (section 6).

---

## 3. The procedure mapped onto our pipeline

What `sdlab/discovery/` does now (read from the code), what the research recommends instead or in
addition, and the evidence. Experiment ids refer to section 4.

| Stage | What we do now | What the research recommends | Evidence | Experiment |
|---|---|---|---|---|
| 0. Data | Levels at every step (exact integers), announced eras, units, `final`, `group`. Each flow in the truth is a Poisson draw around its rate, from levels at the start of the step; outflows of a stock that cannot cover them are scaled to what it holds (`sdtruth.py`). | Keep single steps and start-of-step levels (no smoothing, no windows). Mark steps where a stock emptied (its outflows were capped) and stocks that never decrease. | ED opening section; our "single steps" result; King et al. 2015 (fit increments, never cumulative levels). | M9 |
| 1. Look first | Nothing explicit (the change scan and the judge implicitly see some of it). | A per-stock and cross-stock profile: excitation (singular values of centred levels; time far from equilibrium), time at 0 / at max, Fano factor of changes, per-unit totals, lag-0 covariance of changes (sign and size), behaviour mode. | SI section 18; ST section 9; SD sections 2 and 11; RP section 1. | I1 (excitation column), M4, M13 |
| 2. Count and budget | Nothing (complexity is limited only by per-term BIC prices). | State order from Hankel singular values of a long VARX per group (hidden-state budget); number of genuine changes from a penalty path; an analyst-stated budget (max stocks incl. hidden, max flows, max changes per outside inflow or a minimum time between them) enforced by keeping the best model within it (e.g. optimal partitioning with a fixed number of segments). | Ho and Kalman 1966; Van Overschee and De Moor 1994; Bauer 2001; Haynes et al. 2017; Killick et al. 2012 (segment neighbourhood); Bai and Perron 1998; Jakeman and Hornberger 1993. | M7, M6, M15 |
| 3. Rows (generation) | Per stock, stepwise BIC over all allowed levels (forward, or backward when few), `add_gain` log T, drop by 2. | Same fast engine, plus: count-aware weights; candidate columns from a process library (effect bases, delay objects, co-flow `uses`), tried where diagnostics point; inclusion stability over bootstrap resamples. | Langley and Arvay 2015 (regression first is right); Bridewell et al. 2008; Fasel et al. 2022; Meinshausen and Bühlmann 2010. | M3, M4, M5, M7, M10 |
| 4. Outside inflow | PELT on the row's residual, cost = sum of squares, price 0.5 then 1 x log n x variance from successive differences; fine pieces first; a level in place of pieces; inflow form chosen with levels fixed; pieces only for stocks with an inflow. | Change detection on innovations (prewhitened), penalty chosen per stock from the CROPS path, minimum piece length tied to the row's time constant, joint alternation with the dynamics, a guard that flags pieces tracking another level, a check that a structural addition removes pieces. | Bai and Perron 1998; Romano et al. 2022; Haynes et al. 2017; Chen and Liu 1993; Kirchner 2009; Lyneis 2000; our change-price (min length 10: 73.2% vs 70.8%). | M6 |
| 5. Eras | Per-configuration columns for the levels a row uses, joining the stepwise search before the change scan. | Keep (structure shared, numbers per era where they pay, as in group-sparse SINDy and MDSINE). Add eras as instruments and as natural experiments for validation. | Our eras result (+8 points on v1); Mangan et al. 2019; SD section 10. | M12 |
| 6. Conservation and reading flows | Rows reconciled afterwards: a drain set to what same-unit receivers take if BIC allows (or within 30% for changing rows); gains in other units are links; negative cross terms read as "drains faster when A is high". | Use the covariance of changes to decide move vs link vs co-flow (a move is a negative covariance equal to its rate; a link has none; a co-flow mirrors at ratio `per`); estimate drains from second moments where inflow pieces bias the mean fit. | Vardi 1996; Fearnhead et al. 2014; Martinelli et al. 2022 (ratio consistency); Craciun and Pantea 2008 (move vs out+in identical in the mean); our shared-noise. | M4 |
| 7. Candidates | 16 variants (forward/backward x changing/constant inflows x trust receivers/rows x per-era numbers). | Treat every strategy as a generator into one shared pool; add generators by coverage (unique oracle wins), not by headline. | Rice 1976; Romera-Paredes et al. 2024; RP section 12. | I1 |
| 8. Judge | Multi-step error on the data from ~80 starts at 5, 20, 100 steps, the candidate's own estimated inflows feeding it. | Keep. Add a behaviour-consistency gate first (eigenvalues of the per-era step matrix compared with the data's growth; free runs from extreme states with floors and caps). Report the judge's rank of the best candidate. | Aguirre and Billings 1995; Umenberger et al. 2018; Kampmann and Oliva 2008; Barlas 1996; Forrester and Senge 1980. | M1, I1 |
| 9. Refine | None on the main line ([output-error](output-error.md) not adopted). | Multiple-shooting H-step refit of rates, inflows fixed, multi-start; partial-model simulation per row (each row driven by measured levels of the others) to localise a failing row. | Bock 1983; Ribeiro et al. 2020; Homer 2012; Oliva 2003; our output-error. | M2, M8 |
| 10. Criticise and expand | None (humans do it between experiments). | A per-row diagnostic battery that returns typed proposals; one proposal at a time; accept by penalised multi-step improvement; stop when clean. | Ljung and Box 1978; Billings and Voon 1986; Kristensen et al. 2004; Sterman 1984 (Theil shares); Box 1980. | M3, I3 |
| 11. Discriminate and report | "Fits about as well" list in the result. | Equivalence rewrites with a declared tie-break; boundary reduction (a delay going to zero, an effect slope going to zero gives the simpler model); bootstrap inclusion; levels of evidence per flow. | Godfrey and Chapman 1990; Davidson et al. 2017; Szederkényi et al. 2011; Transtrum and Qiu 2014; Raue et al. 2009; Dogan 2007. | M10, M11, I5 |

---

## 4. Ranked experiment plan

Ordered by expected value and dependency. Infrastructure comes first because every later adopt
decision is only as good as the measurement (RP "Phase 0"; Dwork et al. 2015; Cobbe et al. 2020).
Mechanisms M1, M4 and M5 can start in parallel with I2: their mechanism tests are synthetic and do not
need the generator.

### 4.0 The order

| Rank | Id | Experiment | Kind | Topic document |
|---|---|---|---|---|
| 1 | I1 | Bench instrumentation: oracle skill, judge rank, failure class, inflow load, seeds and paired tests, leakage check, off switches | infrastructure | [bench-instrumentation](bench-instrumentation.md) (new) |
| 2 | I2 | Procedural generator with held-out motif families and a sealed test pool | infrastructure | [procedural-generator](procedural-generator.md) |
| 3 | M1 | Behaviour-consistency gate: growth/eigenvalue consistency and extreme-condition runs, with a located, constrained refit | mechanism | [behaviour-consistency](behaviour-consistency.md) (new) |
| 4 | M4 | Count-aware weights and second moments: co-flows, moves vs links, drains from covariance | mechanism | [count-likelihoods](count-likelihoods.md) (with [shared-noise](shared-noise.md)) |
| 5 | M5 | Effects as basis-expanded flow columns in the regression | mechanism | [effect-columns](effect-columns.md) (new) |
| 6 | M3 + I3 | Diagnose-and-expand loop, with the diagnostic battery scored as a tool | mechanism + infrastructure | [residual-diagnostics](residual-diagnostics.md) (new) |
| 7 | M6 | Outside-input changes on innovations: penalty path, time-constant piece length, pieces-track-levels guard | mechanism | [inflow-innovations](inflow-innovations.md) (new) |
| 8 | M15 | A complexity budget: analyst-stated limits on stocks, flows and input changes, generic or swept on the bench | mechanism | [complexity-budget](complexity-budget.md) |
| 9 | M2 | Output-error / multiple-shooting refit as the final stage on v2 | mechanism | [output-error](output-error.md) |
| 10 | M7 | Hidden stocks by constrained deconvolution and order counting (delay objects), with the hidden-stocks branch's acceptance behind M1 | mechanism | [delay-deconvolution](delay-deconvolution.md) (new) |
| 11 | M8 | Partial-model simulation per row | mechanism | [partial-model-simulation](partial-model-simulation.md) (new) |
| 12 | M9 | Floors and caps as censoring, offered only where the data reach them | mechanism | [censored-floors](censored-floors.md) (new) |
| 13 | M10 | Bootstrap inclusion probabilities and a bagged candidate | mechanism | [bayesian-structure](bayesian-structure.md) |
| 14 | I5 + M11 | Identifiability: self-consistency check, equivalence rewrites, boundary reduction | infrastructure + mechanism | [identifiability](identifiability.md) |
| 15 | M12 | Inflow-conditioned held-out judge and era hold-out | mechanism | [inflow-conditioned-judge](inflow-conditioned-judge.md) (new) |
| 16 | M13 | Behaviour-mode fingerprints as priors | mechanism | [behaviour-fingerprints](behaviour-fingerprints.md) (new) |
| 17 | M14 | Kalman / EM refinement of hidden-stock candidates | mechanism | [state-space](state-space.md) |
| - | I4 | Ablation and consolidation at the end of each wave | infrastructure (rule) | [bench-instrumentation](bench-instrumentation.md) (new) |
| - | - | Process library refactor (consolidation, not a bench mechanism) | architecture | [process-library](process-library.md) (new) |

Running experiments (gradient descent, numerical optimisation, PySINDy, structure search, symbolic
regression) are not re-ranked here; when they report, measure them with I1's columns,
and the coverage view in I1 decides whether each joins the candidate pool. M5 and M7 should read the
symbolic-regression and PySINDy results before starting (they overlap); M7 builds on the finished
hidden-stocks experiment.

### 4.1 Infrastructure (measurement)

**I1. Bench instrumentation.** *Hypothesis:* the headline mean skill cannot tell a coverage gain from a
selection gain from luck; per-run columns can. *Change* (`tests/bench/evaluate.py`, `grade.py`, and
`identify()` returning every candidate's flows):
- **oracle skill** (best graded candidate) and **judge rank** of that candidate, per run (generalises
  the held-out-judge study's 31-of-42 count);
- **failure class** per failing run: *not representable* (no candidate meets the goal, but the true
  structure with numbers fitted by our own fitter does), *not chosen* (a candidate meets it, the judge
  picked another), *not supported by the data* (the true structure refitted by our fitter also fails).
  The "truth-structure ceiling" needs a fixed-structure fit mode (the rate refit in
  `exp/output-error`'s `refine.py` is one); it uses the truth only in grading, which the goal allows;
- **inflow load**: inflow pieces into stocks the truth does not feed from outside (exogenous
  explanation of internal dynamics; Lyneis 2000; King et al. 2015);
- **fresh-run gap** (now on the main line: each found model is also graded on another run with other
  random draws): report in-sample minus fresh skill per run; a gap means the model replays its own
  run's draws (inflow pieces into stocks the truth does not feed, hidden stocks that fit noise);
- **seeds**: the same examples run on 2-3 extra seeds as a reported column (not the goal), to estimate
  run-to-run noise; **paired test** (Wilcoxon signed-rank over runs; Demšar 2006) against the baseline;
- **leakage check**: stock ids and names permuted and renamed, row order shuffled, skill must be
  identical (Kapoor and Narayanan 2023);
- **off switches**: every adopted mechanism keeps an `opts` flag; `--ablate` runs leave-one-out (I4).
*Mechanism test:* on the held-out-judge trap model (births read as a move, paid back by inflow pieces),
the bench reports the trap's judge rank and a high inflow load; a permuted copy of a synthetic model
gives identical skill. *Targets:* all runs. *Expected effect:* none on skill; it decides what to work
on (on v1: the oracle reached 78.3% vs 70.8% chosen, so coverage was the bigger gap). *Dependencies:*
none. *Cost:* small to medium.

**I2. Procedural generator with a sealed split.** *Hypothesis:* mechanisms tuned on 31 examples do
not generalise; a generated pool reveals it. *Change:* a generator of SD models from motif families
(chains, loops, goal gaps, hidden delays of order 1-3, co-flows, effects, floors/caps, announced eras,
unannounced input changes, schedules), sized and checked for boundedness and excitation (the checks in
[benchmark-excitation](benchmark-excitation.md)); three pools: development (any seed), validation
(scored on every bench run, reported as a generalisation gap against the 31), sealed test (fixed seeds
plus one or two whole motif families never used in development, scored only at adoption, logged once).
*Mechanism test:* generated models pass the excitation checks; the main line's skill on the pool by
motif family is reported; a motif family held out is never sampled in development. *Targets:* all.
*Expected effect:* none on skill; protects every adopt decision and calibrates penalties
(Cobbe et al. 2020; Dwork et al. 2015; Recht et al. 2019; La Cava et al. 2021; Kaptanoglu et al. 2023 on
per-system tuning). *Dependencies:* none (uses `sdtruth.py` unchanged through `tests/synth.py`).
*Cost:* medium to high.

**I3. The diagnostic battery as a measured tool** (first step of M3). *Hypothesis:* each diagnostic in
the table of M3 names the missing truth component more often than chance. *Change:* a standalone
`diagnose(model, run)`; on the 31 examples and generated models, with the truth known, score each
diagnostic's precision and recall for the component the found model lacks (a legal truth-using study
of a tool, RP section 2). *Cost:* small once M3's battery exists. *Dependencies:* I2 for volume.

**I4. Ablation and consolidation** (a rule, run at the end of each wave). Leave-one-out ablation of
every adopted mechanism on the 31 and the validation pool, an ablation path from the original baseline
to the main line (Fawcett and Hoos 2016), and the 2x2 for winners that overlap. Mechanisms that
contribute nothing are removed (Hooker 1995).

**I5. Identifiability checks.** *Change:* (a) a self-consistency check per run: simulate the found
model with its own estimated inflows and counting noise, rediscover from that data, and grade the
rediscovered model against the found one (Gelman et al. 2020; Talts et al. 2018); a model discovery
cannot recover from its own data is not supported by this much data; (b) the excitation column from
[benchmark-excitation](benchmark-excitation.md) in every bench run. Feeds I1's "not supported" class.
*Cost:* small.

### 4.2 Mechanisms

Each entry: hypothesis, concrete change, mechanism test (smallest synthetic model via
`tests/synth.py`, with a control that must not change), targets on benchmark v2, expected effect,
dependencies, cost. **Baseline: "v2.1"** (main line after the simulator and grader were fixed to share
an emptied stock's level among its outflows as the engine does, with fresh-run grading): **12 of 62
runs meet the goal, mean skill@20 29.6% (fresh runs 28.9%)**. Per-run numbers below are v2.1 skill@20
(default / long) unless marked @100. Compare with `--baseline v2.1`.

**M1. Behaviour-consistency gate.** *Hypothesis:* many failing candidates contain a loop whose growth
the data rule out (a positive own-coefficient chosen together with a constant inflow, a link that
feeds back on its source); simulating each candidate from observed and extreme starting states, with
floors and caps, and comparing its growth with the data's, rejects them before the judge; the
eigenvalue of the per-era step matrix I + B and its sensitivity name the coefficient to refit with a
bound. *Change:* in `identify()`, before judging: (1) free runs of H = 100-500 steps from the observed
states, from all stocks at 0 and at 5-10x their observed maximum, with the candidate's own inflows;
reject or penalise a candidate whose stocks leave a generous multiple of the observed range when the
data show no comparable growth; (2) for a rejected candidate, compute the dominant eigenvalue's
sensitivity to each row's coefficients, refit that row with the offending coefficient bounded (scipy
`lsq_linear`) and re-enter it as a new candidate. *Mechanism test:* a stock with constant inflow 10 and
drain 0.1 at equilibrium on a short run, where the one-step fit admits a positive own-coefficient plus a
large constant (a trap candidate is planted if the baseline does not produce it); the gate rejects the
trap and the refit recovers 0.1 within 0.02. Controls: a growing population (births 0.02 x adults) keeps
its positive eigenvalue; a floored unstable linear part (like sd-manufacturing) is not rejected,
because the test runs with floors. *Targets:* sd-bakery default (-1170%),
sd-clinic-doses (-602%/-347%), sd-cloud-credits default (-859%), sd-print-shop (-529%/-158%),
sd-support-tiers default (-548%), sd-housing long (-120%), sd-moderation (-67%/-99%), sd-fishery @100
(-102%/-141%), sd-pipeline default @100 (-178%), sd-restaurant @100 (-14%/-75%); and as an acceptance
gate for added structure (the hidden-stocks branch's false hidden stock in sd-population). *Expected effect:* turns large negative tails
into the next-best candidate's skill; with clipping at -100% in the mean, +5 to +15 points of mean
skill@20 is plausible, few runs newly meeting the goal (those need M4/M5). *Dependencies:* none. *Cost:*
small. *Sources:* Aguirre and Billings 1995; Umenberger et al. 2018; Lacy and Bernstein 2003; Kaptanoglu
et al. 2021; Kampmann and Oliva 2008; N. Forrester 1982; Barlas 1996; Forrester and Senge 1980.

**M4. Count-aware weights and second moments.** *Hypothesis:* each flow's per-step amount is one
Poisson draw seen at both of its ends, so (a) a row's residual variance is the sum of the means of the
flows touching it (weights), (b) the covariance of two stocks' changes is minus the moves between them
(plus co-flow terms at ratio `per`), independent of inflow pieces; using (b) to read moves, links and
co-flows, and to estimate the drain where the mean fit is biased by pieces, fixes what the
shared-noise experiment lacked. *Change:* start from `exp/shared-noise` (`d104d53`): (1) feasible GLS
in `regression.py` with weights 1 / (sum of the row's fitted flow means), one iteration; (2) move
rates from the residual covariance, `Cov(dA, dB) = -k_AB * mean(A)`, on steps where neither stock is
capped, used as the drain when the row has changing inflow (instead of the 30% rule in `conserve`);
(3) a co-flow `uses` when C's residual mirrors A's outflow at a steady ratio (Martinelli et al.'s
ratio consistency). *Mechanism tests:* (i) the sd-services pattern on a synthetic fan-out (frontend
calls an API by links, drains by moves): baseline drain biased (as 0.893 vs 0.80 on sd-services), the
strategy within 0.03; (ii) a co-flow A -> B uses 0.5 of C: `per` within 0.05 and C's row read as
`uses`, not "drains faster when A is high"; (iii) control with no shared draws: no `uses`, no change.
*Targets:* the co-flow examples (sd-bakery, sd-print-shop, sd-clinic-doses, sd-cloud-credits,
sd-brewery) and the 15 examples with added co-flows; sd-services (7%/35%). *Expected effect:* largest
single coverage gain available: four of the five co-flow examples are below 0 on v2.1. *Dependencies:* the
shared-noise branch. *Cost:* medium. *Sources:* Fearnhead, Giagos and Sherlock 2014; Vardi 1996;
Callaham et al. 2021; Al-Osh and Alzaid 1987; Bretó et al. 2009; Martinelli et al. 2022; Craciun and
Pantea 2008; Li, Rahmandad and Sterman 2025 (count likelihoods in SD calibration).

**M5. Effects as basis-expanded flow columns.** *Hypothesis:* an SD effect (flow = base rate x f(level
of C / normal)) is a flow coefficient scheduled by C; expanding it as columns level(A) x h_j(C) (h a
linear term, or 3-5 hat functions on C's observed range) keeps the row linear in the parameters, so
the existing stepwise BIC can choose it as a group; snapping f to SD Lab's linear-clamp or table effect
gives an expressible model. *Change:* after the first pass, for each found flow out of A (or into B
from outside driven by A), candidate schedulers C = A, B and stocks of the same group whose product
column correlates with the row's residual (Billings-Voon screen); add the group of columns, accept by
BIC and by the judge; monotone, f(normal) = 1, bounded (Sterman 2000 ch. 14). *Mechanism test:* A -> B
at 0.2 x A x clamp(C/100, 0, 1.5) with C driven through its range by a schedule: baseline reads a
link (skill below 0.5); strategy recovers the table within 10% at the knots, skill@20 > 0.9. Controls:
no effect (no group accepted); C nearly constant (no group accepted: f is seen at one point only).
*Targets:* sd-sawmill (-261%/-207%), sd-learning-curve default (-72%), sd-webshop-stock
(61%/64%), sd-emergency (5%/-47%), sd-farm-soil @100 (50%/78%), sd-fishery. *Expected effect:*
coverage for the five effect examples. *Dependencies:* read the symbolic-regression and PySINDy
results first (both touch effects); M3's screen. *Cost:* medium. *Sources:* Tóth 2010 (LPV, via SI);
Schoukens and Tiels 2017; Billings and Voon 1986; Ríos-Ocampo and Gary 2022; Dayneka, Garg and Jusko
1993 (four placements: stimulate or inhibit, inflow or outflow); Rackauckas et al. 2020 (learn a free
multiplier, then distil); Sterman 2000.

**M3. Diagnose-and-expand loop** (with I3). *Hypothesis:* the headroom is in models no candidate
represents; a per-row residual battery names the missing component, and adding one named proposal at a
time reaches structures the fixed variants cannot. *Change:* `diagnose(row)` returns typed proposals
from this table (SI section 12, RP section 2, SD section 3):

| Residual signature (per row) | Proposal |
|---|---|
| autocorrelated (Ljung-Box), smooth wandering | hidden stock / delay (M7) |
| correlates with another stock's lagged level | link or delayed flow from it |
| correlates with level(A) x level(C) | effect of C on A's flow (M5) |
| one-sided when a stock is near 0 or the fitted rate < 0 | floor / cap (M9) |
| CUSUM break | input change or era-specific number (M6) |
| two rows' residuals mirror at lag 0 | move or co-flow (M4) |
| variance far above the Poisson expectation | missing structure; at or below it: stop |
| bias in the multi-step error (Theil U^M) / unequal variation (U^S) | constant term / gain or effect |

Proposals are tried in the order inputs, floors, links, delays, effects; each accepted only if the
penalised multi-step score improves; stop when the battery is clean or nothing pays. *Mechanism test:*
three synthetic models, each missing one component (a hidden stock A -> H -> B; an effect; a floor):
the battery ranks the right proposal first, the loop adds it, skill@20 rises above 0.9; control: the
correct model gets no proposal. *Targets:* every "not representable" run in I1. *Expected effect:*
the main route to coverage; its size depends on M4, M5, M7 and M9 supplying the proposals.
*Dependencies:* I1 (failure classes), I3 (scored battery), generators M5/M7/M9. *Cost:* medium to
large. *Sources:* Ljung 1999; Ljung and Box 1978; Billings and Voon 1986; Kristensen, Madsen and
Jørgensen 2004; Box 1980; Gelman et al. 2020; Sterman 1984; Schoukens and Ljung 2019 (linear first,
nonlinearity only where residuals ask).

**M6. Outside-input changes on innovations.** *Hypothesis:* pieces absorb dynamics because PELT runs
on residuals that are autocorrelated when the drain is wrong, with one fixed price; detecting changes
on prewhitened residuals, choosing each stock's price from the penalty path, and setting the minimum
piece length from the row's time constant stops the drain/pieces spiral. *Change* in `changes.py` and
the pass loop of `matrix.py`: (1) fit AR(1) to the row's residual, run PELT on the innovations (or a
DeCAFS-style cost); (2) CROPS over a penalty range, take the elbow per stock; (3) minimum piece length
= max(5, c / own drain) (short pieces bias the own coefficient by about (1 + a)/(m - 1), change-price
open ideas); (4) after the fit, regress piece means on every other level's means over the same
segments; a strong relation proposes that level as a column (generalising level-for-pieces). *Mechanism
tests:* the change-price chain (intake changes every 30 steps): the inbox keeps its real changes, the
downstream stock gets none; a row with a misspecified drain and AR residuals: plain PELT adds pieces,
the strategy does not. Control: a genuine steady-rate intake (sd-pipeline-like) keeps its pieces.
*Targets:* sd-pipeline default (@100 -178%), sd-support-tiers, sd-kanban, sd-restaurant, sd-emergency,
sd-population (inflow load). *Expected effect:* +2-3 points on the affected runs (min piece length 10
alone gave 73.2% vs 70.8% on v1). *Dependencies:* I1's inflow-load column. *Cost:* medium. *Sources:*
Romano et al. 2022; Haynes, Eckley and Fearnhead 2017; Killick et al. 2012; Bai and Perron 1998;
Ohlsson, Ljung and Boyd 2010; Chen and Liu 1993; Kirchner 2009; Kavetski et al. 2006; Dehning et al.
2020 (change points priced and limited).

**M15. A complexity budget.** *Hypothesis:* our worst overfitting is flexibility the data cannot pin
down (inflow pieces that replay a run's draws, hidden stocks or flows added because they fit); a budget
the analyst states (max stocks including hidden ones, max flows, max changes per outside inflow or a
minimum time between changes) is a prior that removes it, and because it is a *count*, not a price, it
avoids the change-price experiment's finding that no single price per change suits every example.
*Where it sits in the procedure:* step 2 ("count and budget"): the budget caps what generation may
propose and what selection may keep; selection keeps the best model within the budget. *Change:* opts
on `identify()` (`max_hidden`, `max_flows`, `max_changes` per inflow or `min_change_gap`); under
`max_changes = m`, optimal partitioning with exactly m+1 segments at most (the segment-neighbourhood
form of the change scan; PELT is its penalised form) and the best m chosen by the usual criterion within
the cap; under `max_hidden`/`max_flows`, the stepwise search and the hidden-stock proposals stop at the
cap, keeping the best-scoring set. *Bench rule:* budgets must be generic (e.g. hidden stocks <= measured
stocks; at most one change per N steps with N a fixed fraction of the run; flows <= 3 x measured
stocks) or swept over a grid with the whole sweep reported; never read from the true model or set per
example. *Mechanism test:* a stock with a constant inflow and counting noise on a short run, where the
uncapped scan finds chance pieces (the change-price test found two in a 4-piece series at the low
price): with `max_changes` = 3 the true pieces are kept and no chance pieces appear; control: an intake
with 6 real changes and a budget of 8 is unchanged. *Targets:* sd-population (151 pieces on v1; the
false hidden stock on the hidden-stocks branch), sd-support-tiers (pieces into internal stocks),
sd-pipeline default, sd-kanban; and the fresh-run gap (I1) everywhere. *Expected effect:* closes
in-sample vs fresh-run gaps; skill gain where pieces replay draws; the sweep shows whether results
are robust to the budget (if they move a lot with N, the budget is doing tuning, not prior work).
*Dependencies:* I1 (fresh-run gap, inflow load); combine with M6 (M6 changes how changes are found,
M15 how many may be kept). *Cost:* small. *Sources:* Killick, Fearnhead and Eckley 2012 (segment
neighbourhood vs PELT); Bai and Perron 1998 (m breaks, chosen by criterion or sequential tests);
Jakeman and Hornberger 1993 (rainfall-runoff data support about 4-6 parameters); Chen et al. 2024 and
Duvnjak et al. 2024 (automatic search drifts to over-complex models); Daniels and Nemenman 2015 (add
hidden variables one at a time, in a fixed order); Lyneis 2000 (fit by exogenous drivers explains
nothing); Dehning et al. 2020 (a small number of change points with priors on them). Topic:
[complexity-budget](complexity-budget.md).

**M2. Output-error refit as the final stage, on v2.** *Hypothesis:* the v1 result (+2.7/+3.8) holds
on v2 once structure improves; multiple shooting (H-step segments from measured states, inflows fixed)
keeps the refit stable. *Change:* port `exp/output-error`'s `refine.py` to the v2 main line as an
`opts` stage after the judge; segments of 20 steps from every 10th step, multi-start (3 starts), rates
bounded to their signs. *Mechanism test:* the existing one (rates off by +50%/-40% come back within
0.03); control: a correct model is unchanged within 0.01. *Targets:* long-horizon runs (sd-fishery
long, sd-restaurant long @100, sd-farm-soil @100, sd-kanban). *Expected effect:* +2-4 points of
skill@100. *Dependencies:* none; re-run after M1/M4/M5. *Cost:* small (code exists), +40% run time.
*Sources:* Bock 1983; Ribeiro et al. 2020; Piroddi and Spinelli 2003; Farina and Piroddi 2012;
Čerepnalkoski et al. 2012.

**M7. Hidden stocks by constrained deconvolution and order counting.** *Hypothesis:* the delay
between a source's outflow and a target's unexplained inflow can be estimated directly as a
nonnegative kernel (sum at most 1); its mean is the hidden stock's residence time, mean²/variance its
Erlang order, and a Hankel order count bounds how many hidden stocks to look for, replacing the
26-delay grid. *Change:* per candidate pair from the residual cross-correlation (prewhitened, M3), NNLS
of B's residual on lagged copies of A's outflow with a decaying-kernel penalty (TC kernel); one "delay
object" (T, n) per accepted pair; a VARX-Hankel order per group as the budget; the hidden content by
Little's law. *Mechanism test:* A -> H -> B with H unmeasured, Erlang-3, mean 12: kernel mean within
10%, order 2-4; exponential delay: order about 1; control without a hidden stock: order count adds
nothing, no delay object. *Targets:* the hidden stocks the grid did not find ([hidden-stocks](hidden-stocks.md), v1: sd-kanban
defects, sd-supply trucks, sd-support-tiers, sd-manufacturing, sd-saas lapsed), and the false one it
found (sd-population: the order count should say there is no extra state). *Expected effect:* parts,
kanban and supply skill; fewer false hidden stocks. *Dependencies:* the hidden-stocks branch
(`exp/hidden-delays`, done: five true hidden stocks, 18 -> 20 runs meeting the goal on v1, one false
hidden stock) as the comparison and as the acceptance code; its acceptance goes behind M1 and the
fresh-run grade, and its count behind M15's `max_hidden`. *Cost:* medium.
*Sources:* Goldstein et al. 2009; Savic et al. 2007; Hurtado and Kirosingh 2019; Pillonetto and De
Nicolao 2010; Ho and Kalman 1966; Van Overschee and De Moor 1994; Bauer 2001; Jansson 2003; Hamilton
1980; Little 1961; Benvenuti and Farina 2004 (a positive realisation may need more stocks than the
order); Daniels and Nemenman 2015 (one hidden variable at a time).

**M8. Partial-model simulation per row.** *Hypothesis:* a row whose one-step fit is fine but which
runs off when simulated alone, fed the other stocks' measured levels, is wrong; testing rows this way
localises failures the whole-model judge only sees in aggregate. *Change:* for each row of each
candidate, simulate that stock H steps from ~80 starts with the others' measured levels and its own
inflow pieces; a row failing the partial test gets its alternative forms (the other variants' rows, or
M1's bounded refit) before the whole-model judge. *Mechanism test:* the M1 trap row fails the partial
test while the true row passes; control: a correct row in a loop that is stable only when closed is
not rejected (the partial test is a flag, the whole-model judge decides). *Targets:* runaway runs (with
M1). *Cost:* small. *Sources:* Homer 2012; Oliva 2003; Graham 1980.

**M9. Floors and caps as censoring, where the data reach them.** *Hypothesis:* the floors experiment's
hinges failed by imitating seasons; offering a floor or cap only where the observed range reaches the
implied threshold, and censoring capped steps (an emptied stock tells only "rate >= what it held"),
keeps the isolated gains without the bench losses. *Change* (on `exp/floors`): drop or Tobit-censor
steps where a source emptied from its outflows' fit; offer a hinge for stock X only if X spends at
least a few percent of steps beyond the threshold the row's linear fit implies; never offer a hinge on
a row that has inflow pieces unless the pieces fail M6's guard. *Mechanism tests:* the floors test
(max(0, 0.2a - 30), shut half the time) recovered; control: a seasonal inflow with no floor gets no
hinge. *Targets:* sd-moderation, sd-orders long, sd-supply, sd-manufacturing (control-like), sd-fishery
long (control). *Expected effect:* the isolated gains of the floors experiment (sd-moderation long
49%/-32% -> 83%/75%) without its losses. *Cost:* small to medium. *Sources:* Tobin 1958; Paoletti et
al. 2007; Lariviere and Porteus 1999; Jakeman and Hornberger 1993 (thresholds visible only when they
bind); Sterman 2000 (first-order control).

**M10. Bootstrap inclusion.** Block-bootstrap the steps (blocks of consecutive steps), rerun each
row's stepwise selection, keep flows selected in at least 60-80% of resamples, median coefficients;
the bagged model enters the candidate pool, and inclusion probabilities go in the report. *Mechanism
test:* two collinear source stocks where one-shot selection flips between seeds and bagging picks the
right one in at least 80% of seeds; control: a well-separated model is unchanged. *Targets:* parts
stability between default and long; sd-university, sd-services. *Cost:* medium (compute x B).
*Sources:* Fasel et al. 2022; Meinshausen and Bühlmann 2010; Dogan 2007.

**M11 (with I5). Equivalence rewrites and boundary reduction.** Enumerate output-preserving rewrites of
the chosen structure (move <-> outflow plus linked inflow; hidden series <-> parallel; delay order),
refit each, keep those within tolerance of the best score that also agree from perturbed starts, and
choose by fewest outside flows then fewest hidden stocks; if a delay's or an effect's parameter can go
to its limit (zero delay, zero slope) within tolerance, take the simpler model. *Mechanism test:*
population births (link vs move) on a short, settled run: both rewrites reported, the declared
preference applied; on a long, excited run the covariance (M4) decides. *Cost:* medium. *Sources:*
Godfrey and Chapman 1990; Davidson et al. 2017; Szederkényi, Banga and Alonso 2011; Craciun and Pantea
2008; Transtrum and Qiu 2014; Raue et al. 2009; Gutenkunst et al. 2007; Meshkat, Sullivant and Eisenberg
2015.

**M12. Inflow-conditioned held-out judge and era hold-out.** Score a candidate on a held-out block
with its rate coefficients frozen and only a coarse outside inflow (one value per block) re-estimated
there; with announced eras, fit on eras 1..k and predict era k+1 re-estimating only era-specific
numbers. *Mechanism test:* the held-out-judge trap is ranked worst, and the old held-out judge's
preference for constant-inflow candidates does not recur. *Targets:* judge rank (I1); era examples.
*Expected effect:* small (the judge already picks the best candidate in 31 of 42 v1 runs). *Cost:*
small to medium. *Sources:* Dawid 1984; Racine 2000; Bergmeir, Hyndman and Koo 2018; Oreskes et al.
1994; Forrester and Senge 1980.

**M13. Behaviour-mode fingerprints as priors.** Classify each measured stock's mode (growth,
goal-seeking, oscillation, S-shape, overshoot-and-collapse) per era; required features become cheaper
columns ("oscillates" -> a second state or a closing loop; "S-shape" -> an effect), contradicted ones a
penalty; never hard rules. *Mechanism test:* a supply-line oscillation (two-stock negative loop with a
delay) where the fingerprint moves the search to the second-state candidate; control: a first-order
stock gets no prior. *Targets:* sd-supply, sd-orders, sd-fishery, sd-farm-soil, sd-learning-curve.
*Cost:* medium. One tradition only (SD), hence the rank. *Sources:* Sterman 2000 ch. 4; Kampmann and
Oliva 2008; Yücel and Barlas 2011; Barlas 1989.

**M14. Kalman / EM refinement of hidden-stock candidates.** After M7 proposes a delay object, fit it as
a state (Kalman smoother; EM with structural zeros and conservation as linear constraints in the
M-step) rather than as a filtered regressor; compare by one-step likelihood plus penalty. *Cost:*
large. *Dependencies:* M7. *Sources:* Shumway and Stoffer 1982 (via SI/ST; not separately checked),
Fearnhead, Giagos and Sherlock 2014; Bretó et al. 2009; Peterson 1976; Li, Rahmandad and Sterman 2025.
Existing topic: [state-space](state-space.md).

**Consolidation: the process library.** After M4/M5/M7/M9, move the forms into a declarative library
of SD processes (move, inflow, outflow, link, co-flow, delay object, gap, effect), each with its
columns, constraints and reading into flows, so a new form is a library entry, not a code path in
`matrix.py`/`flows.py`. Not a bench mechanism; measured by "no change in skill, fewer special cases".
*Sources:* Bridewell et al. 2008; Langley and Arvay 2015; Brence, Todorovski and Džeroski 2021; Hoffmann,
Fröhner and Noé 2019; Clark et al. 2008. Topic: [process-library](process-library.md).

### 4.3 Lower priority or deferred

- **Fluctuation-dissipation / linear inverse models** (ST section 6.2) for settled loops: with full
  observation the drift estimate equals our one-step regression; what is new is the noise covariance,
  which M4 already uses. Its "tau test" (the estimated matrix depends on the lag when a state is
  hidden) is a hidden-stock detector worth adding to M7's battery. (Penland and Sardeshmukh 1995; Ching
  and Tam 2017.)
- **Harmonic phase maps** (ST section 2.3) need schedules that enter at a known place; useful as a
  prior for ordering stocks and hidden stages in schedule-driven examples, after M7.
- **Simulation-based / amortised inference, ODEFormer-style proposers**: need I2 first (d'Ascoli et al.
  2024 shows such models fail outside their training distribution).
- **LLM priors from names**: only as a prior on which processes to try first, never as evidence; after
  I1's leakage check exists (names permuted must not change skill unless the prior is switched on).
- **Experiment design for live runs** (Box and Hill 1967): after M11 produces equivalence classes to
  discriminate; needs the user's sign-off.

---

## 5. Research-programme rules the literature supports

1. **Instrument before adding mechanisms**, and report three axes separately: *coverage* (oracle
   skill), *selection* (judge rank of the best candidate), *generalisation* (gap between the 31
   examples and the generated validation pool). (RP sections 9, 12; Rice 1976.)
2. **Start every experiment from a failure, not a technique**: name the runs, their failure class
   (I1) and the residual signature (M3), and write down before running which rows should change and
   which should not. That is strong inference with multiple working hypotheses (Platt 1964;
   Chamberlin 1890).
3. **A mechanism test is severe only with a control.** Show the baseline failing and the mechanism
   working on the smallest synthetic model, *and* show no change on a model without the feature (Mayo
   2018).
4. **Adopt by a paired test over runs plus no significant loss on the generated validation pool**;
   score the sealed test pool only at adoption, and log it once (Demšar 2006; Dwork et al. 2015; Blum
   and Hardt 2015; Recht et al. 2019; Cobbe et al. 2020).
5. **Progressive, not degenerating**: a mechanism must help some generated model it was not designed
   on; a fix that only repairs the example it was designed for is a patch (Lakatos 1970).
6. **Off switch on everything, ablation every wave**: leave-one-out on the main line, an ablation path
   at consolidation, the 2x2 for overlapping winners; remove what contributes nothing (Fawcett and Hoos
   2016; Hooker 1995).
7. **One verifier, many generators**: every method enters as a candidate generator scored by the same
   judge; a generator earns its place by unique oracle wins in the coverage matrix, not by the headline
   (Romera-Paredes et al. 2024; Rice 1976).
8. **Fixed interfaces against a pile of tricks**: a change is one of a library process, a diagnostic, a
   generator, a constraint or prior, or a verifier change. A change that fits none is a redesign of the
   core and gets its own experiment (RP "avoiding haphazard amalgamation").
9. **Tune thresholds and prices on generated models, never on the 31**: per-system tuning makes
   published methods look better than they are (La Cava et al. 2021; Kaptanoglu et al. 2023).
10. **Treat "not supported by the data" runs as benchmark findings**, not engine failures (sd-population;
    Gutenkunst et al. 2007; Raue et al. 2009).
11. **Freeze the grader per wave**; grader fixes are versioned and re-baselined (as with v2.1), never
    folded into an experiment's numbers.
12. **State budgets as priors, never as answers**: a complexity budget is legitimate when it is what
    an analyst could say without the data; on the bench it is generic or swept, never derived from the
    truth (M15).
13. **Guard the forking paths**: the engine's workflow is fixed in code; the team's workflow over the
    benchmark is the garden of forking paths, which the sealed pool and pre-stated predictions protect
    (Gelman and Loken 2013; Freedman 1983 on screening after search).

---

## 6. What not to do, and why

| Do not | Why |
|---|---|
| Smooth, window or weak-form the data before fitting | Levels are exact counts and the noise is process noise; windows biased our fits (5-step windows: 0.08 for a true 0.2); weak forms help only with measurement noise (ED section 4.4). |
| Select structure by one-step fit, or judge at one horizon | One-step-optimal models run away (Aguirre and Billings 1995); our 20-step-only judge picked loops imitating an input (-62000%). |
| Let a refinement re-estimate the outside inflows | Internal dynamics leak into them (our output-error: 66.6%); time-varying inputs absorb misspecification (Kirchner 2009; Dehning et al. 2020; King et al. 2015). |
| Use held-out blocks that must forecast an unannounced input | That measures input extrapolation, not dynamics (our held-out judge: -4.8%). |
| Fix the change price at the textbook 2 x log n | It assumes a fixed number of changes and white residuals; it spiralled on sd-pipeline (change-price). |
| Enforce stability on the linear part | Some truths grow (population) or are unstable in their linear part and held by floors (sd-manufacturing). Check behaviour, with floors. |
| Add hinges/floors everywhere | They imitate unannounced seasons (floors experiment); offer them only where the data reach the threshold. |
| Treat drain bias as errors-in-variables | Our regressors are exact and predetermined; the bias is from pieces and unmodelled delays (C3). |
| Use Granger tests, transfer entropy or convergent cross mapping for structure | In closed-loop, strongly forced, synchronised systems they add nothing to our regression or point the wrong way (McCracken and Weigel 2014; Sugihara et al. 2012's own assumptions; ST section 6). |
| Use autoencoder latent coordinates as hidden stocks | They give coordinates, not stocks, and need far more data (Champion et al. 2019). |
| Run free-form symbolic regression over whole models | Exact recovery collapses with noise and varies by seed (La Cava et al. 2021); use it only for one effect curve inside a known flow (M5). |
| Build "fits about as well" sets from informal thresholds | GLUE-style bands do not mean what they say (Beven and Binley 1992; Mantovan and Todini 2006); use a proper likelihood or the behavioural agreement test of M11. |
| Fit cumulative quantities (levels) by least squares | Overconfident and biased (King et al. 2015); fit increments. |
| Drop a weakly significant flow that conservation or units require | Significance is not structural importance in short runs (Mass and Senge 1978); keep it with a prior value and say so. |
| Spend the next wave on the judge | The judge already picks the best candidate in 31 of 42 v1 runs; the gap is coverage (held-out-judge). |
| Tune anything to an example's id, names or the 31 examples' quirks | Forbidden by the goal; also the textbook route to a benchmark-only engine (Dwork et al. 2015; Kapoor and Narayanan 2023). |
| Start amortised/neural proposers before the generator exists | They fail outside their training distribution (d'Ascoli et al. 2024) and need thousands of generated systems. |

---

## Appendix A: citations checked

Checked 2026-10-17 against Crossref, publisher pages, arXiv, PMLR, library catalogues, MIT DSpace,
the System Dynamics Society proceedings and the Albany SD archive. Status: **V** verified as cited;
**C** verified with the correction shown; **N** not found as cited.

| Reference | DOI / URL | Status |
|---|---|---|
| Ljung (1999). System Identification: Theory for the User, 2nd ed. Prentice Hall PTR. | ISBN 0-13-656695-2 | V |
| Bock (1983). Recent advances in parameter identification techniques for O.D.E. In Numerical Treatment of Inverse Problems in Differential and Integral Equations, Birkhäuser, 95-121. | 10.1007/978-1-4684-7324-7_7 | C (title "O.D.E.") |
| Ribeiro, Tiels, Umenberger, Schön, Aguirre (2020). On the smoothness of nonlinear system identification. Automatica 121:109158. | 10.1016/j.automatica.2020.109158 | V |
| Piroddi, Spinelli (2003). An identification algorithm for polynomial NARX models based on simulation error minimization. Int. J. Control 76(17):1767-1781. | 10.1080/00207170310001635419 | V |
| Farina, Piroddi (2012). Identification of polynomial input/output recursive models with simulation error minimisation methods. Int. J. Systems Science 43(2):319-333. | 10.1080/00207721.2010.496055 | V |
| Aguirre, Billings (1995). Dynamical effects of overparametrization in nonlinear models. Physica D 80(1-2):26-40. | 10.1016/0167-2789(95)90053-5 | V |
| Billings, Voon (1986). Correlation based model validity tests for non-linear models. Int. J. Control 44(1):235-244. | 10.1080/00207178608933593 | V |
| Kristensen, Madsen, Jørgensen (2004). A method for systematic improvement of stochastic grey-box models. Comput. Chem. Eng. 28(8):1431-1449. | 10.1016/j.compchemeng.2003.10.003 | V |
| Ljung, Box (1978). On a measure of lack of fit in time series models. Biometrika 65(2):297-303. | 10.1093/biomet/65.2.297 | V |
| Umenberger, Wågberg, Manchester, Schön (2018). Maximum likelihood identification of stable linear dynamical systems. Automatica 96:280-292. | 10.1016/j.automatica.2018.06.036 | V |
| Lacy, Bernstein (2003). Subspace identification with guaranteed stability using constrained optimization. IEEE TAC 48(7):1259-1263. | 10.1109/TAC.2003.814273 | V |
| Van Overschee, De Moor (1994). N4SID. Automatica 30(1):75-93. | 10.1016/0005-1098(94)90230-5 | V |
| Bauer (2001). Order estimation for subspace methods. Automatica 37(10):1561-1573. | 10.1016/S0005-1098(01)00118-2 | V |
| Benvenuti, Farina (2004). A tutorial on the positive realization problem. IEEE TAC 49(5):651-664. | 10.1109/TAC.2004.826715 | V |
| Pillonetto, De Nicolao (2010). A new kernel-based approach for linear system identification. Automatica 46(1):81-93. | 10.1016/j.automatica.2009.10.031 | V |
| Bai, Perron (1998). Estimating and testing linear models with multiple structural changes. Econometrica 66(1):47-78. | 10.2307/2998540 | V |
| Ohlsson, Ljung, Boyd (2010). Segmentation of ARX-models using sum-of-norms regularization. Automatica 46(6):1107-1111. | 10.1016/j.automatica.2010.03.013 | V |
| Paoletti, Juloski, Ferrari-Trecate, Vidal (2007). Identification of hybrid systems: a tutorial. Eur. J. Control 13(2-3):242-260. | 10.3166/ejc.13.242-260 | V |
| Tobin (1958). Estimation of relationships for limited dependent variables. Econometrica 26(1):24-36. | 10.2307/1907382 | V |
| Granger, Newbold (1974). Spurious regressions in econometrics. J. Econometrics 2(2):111-120. | 10.1016/0304-4076(74)90034-7 | V |
| Schoukens, Tiels (2017). Identification of block-oriented nonlinear systems starting from linear approximations: a survey. Automatica 85:272-292. | 10.1016/j.automatica.2017.06.044 | V |
| Schoukens, Ljung (2019). Nonlinear system identification: a user-oriented road map. IEEE Control Systems Magazine 39(6):28-99. | 10.1109/MCS.2019.2938121 | V |
| Forssell, Ljung (1999). Closed-loop identification revisited. Automatica 35(7):1215-1241. | 10.1016/S0005-1098(99)00022-9 | V |
| Jansson (2003). Subspace identification and ARX modeling. IFAC Proceedings Volumes 36(16):1585-1590 (13th IFAC SYSID). | 10.1016/S1474-6670(17)34986-8 | C (volume and pages added) |
| Ho, Kalman (1966). Effective construction of linear state-variable models from input/output functions. Regelungstechnik 14:545-548. | 10.1524/auto.1966.14.112.545 | V |
| Brunton, Proctor, Kutz (2016). SINDy. PNAS 113(15):3932-3937. | 10.1073/pnas.1517384113 | V |
| Bridewell, Langley, Todorovski, Džeroski (2008). Inductive process modeling. Machine Learning 71:1-32. | 10.1007/s10994-007-5042-6 | V |
| Langley, Arvay (2015). Heuristic induction of rate-based process models. AAAI 2015 (29(1)). | 10.1609/aaai.v29i1.9219 | V |
| Čerepnalkoski, Taškova, Todorovski, Atanasova, Džeroski (2012). The influence of parameter fitting methods on model structure selection in automated modeling of aquatic ecosystems. Ecol. Modelling 245:136-165. | 10.1016/j.ecolmodel.2012.06.001 | V |
| Mangan, Kutz, Brunton, Proctor (2017). Model selection for dynamical systems via sparse regression and information criteria. Proc. R. Soc. A 473:20170009. | 10.1098/rspa.2017.0009 | V |
| Fasel, Kutz, Brunton, Brunton (2022). Ensemble-SINDy. Proc. R. Soc. A 478:20210904. | 10.1098/rspa.2021.0904 | V |
| Meinshausen, Bühlmann (2010). Stability selection. JRSS B 72(4):417-473. | 10.1111/j.1467-9868.2010.00740.x | V |
| Hoffmann, Fröhner, Noé (2019). Reactive SINDy. J. Chem. Phys. 150:025101. | 10.1063/1.5066099 | V |
| Callaham, Loiseau, Rigas, Brunton (2021). Nonlinear stochastic modelling with Langevin regression. Proc. R. Soc. A 477:20210092. | 10.1098/rspa.2021.0092 | V |
| Fearnhead, Giagos, Sherlock (2014). Inference for reaction networks using the linear noise approximation. Biometrics 70(2):457-466. | 10.1111/biom.12152 | V |
| Kaptanoglu, Callaham, Aravkin, Hansen, Brunton (2021). Promoting global stability in data-driven models of quadratic nonlinear dynamics. Phys. Rev. Fluids 6:094401. | 10.1103/PhysRevFluids.6.094401 | V |
| Daniels, Nemenman (2015). Automated adaptive inference of phenomenological dynamical models. Nat. Commun. 6:8133. | 10.1038/ncomms9133 | V |
| Rackauckas et al. (2020). Universal differential equations for scientific machine learning. arXiv:2001.04385. | arxiv.org/abs/2001.04385 | V |
| La Cava et al. (2021). Contemporary symbolic regression methods and their relative performance. NeurIPS Datasets and Benchmarks. | arxiv.org/abs/2107.14351 | V |
| d'Ascoli, Becker, Mathis, Schwaller, Kilbertus (2024). ODEFormer. ICLR 2024. | arxiv.org/abs/2310.05573 | V |
| Kaptanoglu, Zhang, Nicolaou, Fasel, Brunton (2023). Benchmarking sparse system identification with low-dimensional chaos. Nonlinear Dynamics 111(14):13143-13164. | 10.1007/s11071-023-08525-4 | C (volume and pages added) |
| Brence, Todorovski, Džeroski (2021). Probabilistic grammars for equation discovery. Knowledge-Based Systems 224:107077. | 10.1016/j.knosys.2021.107077 | V |
| Martinelli, Grignard, Soliman, Ballesta, Fages (2022). Reactmine (v1 title: a search algorithm for inferring chemical reaction networks from time series data). arXiv:2209.03185. | arxiv.org/abs/2209.03185 | V (later versions retitled "a statistical search algorithm...") |
| Horrocks, Bauch (2020). Algorithmic discovery of dynamic models from infectious disease data. Sci. Rep. 10:7061. | 10.1038/s41598-020-63877-w | V |
| Penland, Sardeshmukh (1995). The optimal growth of tropical sea surface temperature anomalies. J. Climate 8(8):1999-2024. | 10.1175/1520-0442(1995)008<1999:TOGOTS>2.0.CO;2 | V |
| Ching, Tam (2017). Reconstructing links in directed networks from noisy dynamics. Phys. Rev. E 95:010301(R). | 10.1103/PhysRevE.95.010301 | V |
| Romano, Rigaill, Runge, Fearnhead (2022). Detecting abrupt changes in the presence of local fluctuations and autocorrelated noise. JASA 117(540):2147-2162. | 10.1080/01621459.2021.1909598 | V |
| Haynes, Eckley, Fearnhead (2017). Computationally efficient changepoint detection for a range of penalties. JCGS 26(1):134-143. | 10.1080/10618600.2015.1116445 | V |
| Killick, Fearnhead, Eckley (2012). Optimal detection of changepoints with a linear computational cost. JASA 107(500):1590-1598. | 10.1080/01621459.2012.737745 | V |
| Chen, Liu (1993). Joint estimation of model parameters and outlier effects in time series. JASA 88(421):284-297. | 10.1080/01621459.1993.10594321 | V |
| Godfrey, Chapman (1990). Identifiability and indistinguishability of linear compartmental models. Math. Comput. Simul. 32(3):273-295. | 10.1016/0378-4754(90)90185-L | V |
| Davidson, Godfrey, Alquaddoomi, Nola, DiStefano (2017). DISTING. Comput. Methods Programs Biomed. 143:129-135. | 10.1016/j.cmpb.2017.02.025 | V (corrigendum 146:25) |
| Szederkényi, Banga, Alonso (2011). Inference of complex biological networks: distinguishability issues and optimization-based solutions. BMC Syst. Biol. 5:177. | 10.1186/1752-0509-5-177 | V |
| Craciun, Pantea (2008). Identifiability of chemical reaction networks. J. Math. Chem. 44(1):244-259. | 10.1007/s10910-007-9307-x | V |
| Vardi (1996). Network tomography. JASA 91(433):365-377. | 10.1080/01621459.1996.10476697 | V |
| Bretó, He, Ionides, King (2009). Time series analysis via mechanistic models. Ann. Appl. Stat. 3(1):319-348. | 10.1214/08-AOAS201 | V |
| Al-Osh, Alzaid (1987). First-order integer-valued autoregressive (INAR(1)) process. J. Time Ser. Anal. 8(3):261-275. | 10.1111/j.1467-9892.1987.tb00438.x | V |
| Savic, Jonker, Kerbusch, Karlsson (2007). Implementation of a transit compartment model for describing drug absorption in pharmacokinetic studies. J. Pharmacokinet. Pharmacodyn. 34(5):711-726. | 10.1007/s10928-007-9066-0 | V |
| Hurtado, Kirosingh (2019). Generalizations of the 'Linear Chain Trick': incorporating more flexible dwell time distributions into mean field ODE models. J. Math. Biol. 79(5):1831-1883. | 10.1007/s00285-019-01412-w | C (full title) |
| Goldstein, Dushoff, Ma, Plotkin, Earn, Lipsitch (2009). Reconstructing influenza incidence by deconvolution of daily mortality time series. PNAS 106(51):21825-21829. | 10.1073/pnas.0902958106 | V |
| Dayneka, Garg, Jusko (1993). Comparison of four basic models of indirect pharmacodynamic responses. J. Pharmacokinet. Biopharm. 21(4):457-478. | 10.1007/BF01061691 | V |
| Chen, Nordgren, Belin, et al. (2024). A fully automatic tool for development of population pharmacokinetic models. CPT Pharmacometrics Syst. Pharmacol. 13(10):1784-1797. | 10.1002/psp4.13222 | C (title, authors) |
| Duvnjak et al. (2024). Simulation-based evaluation of the Pharmpy Automatic Model Development tool for population pharmacokinetic modeling. CPT PSP 13(10):1707-1721. | 10.1002/psp4.13213 | C (full title) |
| Clark et al. (2008). Framework for Understanding Structural Errors (FUSE): a modular framework to diagnose differences between hydrological models. WRR 44(12):W00B02. | 10.1029/2007WR006735 | V |
| Jakeman, Hornberger (1993). How much complexity is warranted in a rainfall-runoff model? WRR 29(8):2637-2649. | 10.1029/93WR00877 | V |
| Kirchner (2009). Catchments as simple dynamical systems. WRR 45(2):W02429. | 10.1029/2008WR006912 | V |
| Kavetski, Kuczera, Franks (2006). Bayesian analysis of input uncertainty in hydrological modeling: 1. Theory (W03407); 2. Application (W03408). WRR 42(3). | 10.1029/2005WR004368 ; 10.1029/2005WR004376 | C (two parts; "BATEA" not in the title) |
| Beven (2006). A manifesto for the equifinality thesis. J. Hydrol. 320(1-2):18-36. | 10.1016/j.jhydrol.2005.07.007 | V |
| Raue et al. (2009). Structural and practical identifiability analysis of partially observed dynamical models by exploiting the profile likelihood. Bioinformatics 25(15):1923-1929. | 10.1093/bioinformatics/btp358 | V |
| Gutenkunst et al. (2007). Universally sloppy parameter sensitivities in systems biology models. PLoS Comput. Biol. 3(10):e189. | 10.1371/journal.pcbi.0030189 | V |
| Transtrum, Qiu (2014). Model reduction by manifold boundaries. PRL 113:098701. | 10.1103/PhysRevLett.113.098701 | V |
| King, Domenech de Cellès, Magpantay, Rohani (2015). Avoidable errors in the modelling of outbreaks of emerging pathogens. Proc. R. Soc. B 282(1806):20150347. | 10.1098/rspb.2015.0347 | V |
| Lariviere, Porteus (1999). Stalking information: Bayesian inventory management with unobserved lost sales. Manage. Sci. 45(3):346-363. | 10.1287/mnsc.45.3.346 | V |
| Little (1961). A proof for the queuing formula L = λW. Oper. Res. 9(3):383-387. | 10.1287/opre.9.3.383 | V |
| Meshkat, Sullivant, Eisenberg (2015). Identifiability results for several classes of linear compartment models. Bull. Math. Biol. 77(8):1620-1651. | 10.1007/s11538-015-0098-0 | V |
| Dehning et al. (2020). Inferring change points in the spread of COVID-19 reveals the effectiveness of interventions. Science 369(6500):eabb9789. | 10.1126/science.abb9789 | V |
| Sterman (2000). Business Dynamics. McGraw-Hill, Boston. | ISBN 0-07-231135-5 | C (publisher McGraw-Hill; "Irwin" imprint not confirmed) |
| Sterman (1984). Appropriate summary statistics for evaluating the historical fit of system dynamics models. Dynamica 10(2):51-66. | archives.albany.edu/concern/daos/nk322z25d | V |
| Barlas (1996). Formal aspects of model validity and validation in system dynamics. SDR 12(3):183-210. | 10.1002/(SICI)1099-1727(199623)12:3<183::AID-SDR103>3.0.CO;2-4 | V |
| Barlas (1989). Multiple tests for validation of system dynamics type of simulation models. EJOR 42(1):59-87. | 10.1016/0377-2217(89)90059-3 | V |
| Forrester, Senge (1980). Tests for building confidence in system dynamics models. TIMS Studies in the Management Sciences 14, North-Holland. | ISBN 0444854916 | V (pages 209-228 not seen) |
| Homer (2012). Partial-model testing as a validation tool for system dynamics (1983). SDR 28(3):281-294. | 10.1002/sdr.1478 | V |
| Oliva (2003). Model calibration as a testing strategy for system dynamics models. EJOR 151(3):552-568. | 10.1016/S0377-2217(02)00622-7 | V |
| Peterson (1980). Statistical tools for system dynamics. In Randers (ed.), Elements of the System Dynamics Method. | (1976 MIT paper found: archives.albany.edu, Peterson "Statistical Tools for System Dynamics") | N as a 1980 chapter; cited here as Peterson 1976 |
| Li, Rahmandad, Sterman (2025). Beyond least squares: estimation of dynamic models with alternative likelihoods and Kalman filtering. SDR 41(2):e70004. | 10.1002/sdr.70004 | C (title) |
| Kampmann, Oliva (2008). Structural dominance analysis and theory building in system dynamics. Syst. Res. Behav. Sci. 25(4):505-519. | 10.1002/sres.909 | V |
| Ríos-Ocampo, Gary (2022). Using analytical equations to represent nonlinear relationships. SDR 38(4):354-370. | 10.1002/sdr.1718 | C (title) |
| Hamilton, Margaret S. (1980). Estimating lengths and orders of delays in system dynamics models. In Randers (ed.), Elements of the System Dynamics Method, ch. 8, 162-181. | archives.albany.edu/concern/daos/dz011772b | C (pages) |
| Mass, Senge (1978). Alternative tests for the selection of model variables. IEEE Trans. SMC 8(6):450-460. | 10.1109/TSMC.1978.4309998 | V |
| Lyneis (2000). System dynamics for market forecasting and structural analysis. SDR 16(1):3-25. | 10.1002/(SICI)1099-1727(200021)16:1<3::AID-SDR183>3.0.CO;2-5 | V |
| Dogan (2007). Bootstrapping for confidence interval estimation and hypothesis testing for parameters of system dynamics models. SDR 23(4):415-436. | 10.1002/sdr.362 | V |
| Sterman (1989). Modeling managerial behavior: misperceptions of feedback in a dynamic decision making experiment. Manage. Sci. 35(3):321-339. | 10.1287/mnsc.35.3.321 | V |
| Yücel, Barlas (2011). Automated parameter specification in dynamic feedback models based on behavior pattern features. SDR 27(2):195-215. | 10.1002/sdr.457 | V |
| Schoenberg, Davidsen, Eberlein (2020). Understanding model behavior using the Loops that Matter method. SDR 36(2):158-190. | 10.1002/sdr.1658 | V |
| Abdelbari, Shafi (2019). A system dynamics modeling support system based on computational intelligence. Systems 7(4):47. | 10.3390/systems7040047 | V |
| Oreskes, Shrader-Frechette, Belitz (1994). Verification, validation, and confirmation of numerical models in the earth sciences. Science 263(5147):641-646. | 10.1126/science.263.5147.641 | V |
| Forrester, Nathan B. (1982). A Dynamic Synthesis of Basic Macroeconomic Theory. PhD thesis, MIT. | dspace.mit.edu/handle/1721.1/15739 | V |
| Senge (1977). Statistical estimation of feedback models. Simulation 28(6):177-184. | 10.1177/003754977702800606 | V |
| Graham (1980). Parameter estimation in system dynamics modeling. In Randers (ed.), Elements of the System Dynamics Method, 143-161. | (table of contents) | V |
| Pruyt, Cunningham, Kwakkel, de Bruijn (2014). From data-poor to data-rich: system dynamics in the era of big data. ISDC 2014, 2458-2469. | proceedings.systemdynamics.org/2014/proceed/papers/P1390.pdf | V |
| Box, Jenkins (1970). Time Series Analysis: Forecasting and Control. Holden-Day. | (library catalogues) | V |
| Box (1980). Sampling and Bayes' inference in scientific modelling and robustness. JRSS A 143(4):383-430. | 10.2307/2982063 | V |
| Gelman, Vehtari, Simpson, et al. (2020). Bayesian Workflow. arXiv:2011.01808. | arxiv.org/abs/2011.01808 | V |
| Platt (1964). Strong inference. Science 146(3642):347-353. | 10.1126/science.146.3642.347 | V |
| Chamberlin (1890). The method of multiple working hypotheses. Science ns-15(366):92-96. | 10.1126/science.ns-15.366.92 | V |
| Lakatos (1970). Falsification and the methodology of scientific research programmes. In Lakatos and Musgrave (eds.), Criticism and the Growth of Knowledge, CUP. | 10.1017/CBO9781139171434.009 | V |
| Fawcett, Hoos (2016). Analysing differences between algorithm configurations through ablation. J. Heuristics 22(4):431-458. | 10.1007/s10732-014-9275-9 | V |
| Hooker (1995). Testing heuristics: we have it all wrong. J. Heuristics 1:33-42. | 10.1007/BF02430364 | V |
| Cobbe, Hesse, Hilton, Schulman (2020). Leveraging procedural generation to benchmark reinforcement learning. ICML, PMLR 119:2048-2056. | proceedings.mlr.press/v119/cobbe20a.html | V |
| Dwork, Feldman, Hardt, Pitassi, Reingold, Roth (2015). The reusable holdout. Science 349(6248):636-638. | 10.1126/science.aaa9375 | V |
| Recht, Roelofs, Schmidt, Shankar (2019). Do ImageNet classifiers generalize to ImageNet? ICML, PMLR 97:5389-5400. | proceedings.mlr.press/v97/recht19a.html | V |
| Blum, Hardt (2015). The Ladder. ICML, PMLR 37:1006-1014. | proceedings.mlr.press/v37/blum15.html | V |
| Demšar (2006). Statistical comparisons of classifiers over multiple data sets. JMLR 7:1-30. | jmlr.org/papers/v7/demsar06a.html | V |
| Kapoor, Narayanan (2023). Leakage and the reproducibility crisis in machine-learning-based science. Patterns 4(9):100804. | 10.1016/j.patter.2023.100804 | V |
| Dawid (1984). Statistical theory: the prequential approach. JRSS A 147(2):278-292. | 10.2307/2981683 | V |
| Racine (2000). Consistent cross-validatory model-selection for dependent data: hv-block cross-validation. J. Econometrics 99(1):39-61. | 10.1016/S0304-4076(00)00030-0 | V |
| Bergmeir, Hyndman, Koo (2018). A note on the validity of cross-validation for evaluating autoregressive time series prediction. CSDA 120:70-83. | 10.1016/j.csda.2017.11.003 | V |
| Burnham, Anderson (2002). Model Selection and Multimodel Inference, 2nd ed. Springer. | 10.1007/b97636 | V |
| Romera-Paredes et al. (2024). Mathematical discoveries from program search with large language models. Nature 625:468-475. | 10.1038/s41586-023-06924-6 | V |
| Rice (1976). The algorithm selection problem. Advances in Computers 15:65-118. | 10.1016/S0065-2458(08)60520-3 | V |
| Box, Hill (1967). Discrimination among mechanistic models. Technometrics 9(1):57-71. | 10.1080/00401706.1967.10490441 | V |
| Talts, Betancourt, Simpson, Vehtari, Gelman (2018). Validating Bayesian inference algorithms with simulation-based calibration. arXiv:1804.06788. | arxiv.org/abs/1804.06788 | V |
| Freedman (1983). A note on screening regression equations. Am. Stat. 37(2):152-155. | 10.1080/00031305.1983.10482729 | V |
| Mayo (2018). Statistical Inference as Severe Testing. CUP. | 10.1017/9781107286184 | V |
| McCracken, Weigel (2014). Convergent cross-mapping and pairwise asymmetric inference. Phys. Rev. E 90:062903. | 10.1103/PhysRevE.90.062903 | V |
| Mantovan, Todini (2006). Hydrological forecasting uncertainty assessment: incoherence of the GLUE methodology. J. Hydrol. 330:368-381. | 10.1016/j.jhydrol.2006.04.046 | V |
| Beven, Binley (1992). The future of distributed models: model calibration and uncertainty prediction. Hydrol. Process. 6:279-298. | 10.1002/hyp.3360060305 | V |
| Gelman, Loken (2013). The garden of forking paths. Working paper, Columbia University. | stat.columbia.edu/~gelman/research/unpublished/p_hacking.pdf | V |
| Champion, Lusch, Kutz, Brunton (2019). Data-driven discovery of coordinates and governing equations. PNAS 116(45):22445-22451. | 10.1073/pnas.1906995116 | V |
| Sugihara et al. (2012). Detecting causality in complex ecosystems. Science 338(6106):496-500. | 10.1126/science.1227079 | V |

Count: 130 checked; 118 verified as cited, 11 verified with corrections, 1 not found as cited. Sources
the six reviews cite but that are not in this table (for example Tóth 2010, Shumway and Stoffer 1982)
were not checked here; where this playbook names one, it says so or uses it only alongside a checked
source.

## Appendix B: facts about our data that decide which methods apply

- **Process noise, exact levels.** Each flow's amount per step is Poisson around its rate (computed
  from levels at the start of the step); levels are integers with no measurement error
  (`sdtruth.py`). One-step regression on start-of-step levels has no errors-in-variables problem.
- **Caps.** When a stock's outflows (and co-flows using it) want more than it holds, all of them are
  scaled to what it holds and floored. Those steps break Poisson mean-variance and are censored
  observations of the rates.
- **Floors.** `desired_rate` never goes below 0, so gap and linear forms are kinked.
- **Schedules.** Unannounced changes recur by period; announced ones are eras.
- **The grader feeds the truth's outside inflows** into stocks the truth feeds from outside, from ~150
  starts at H = 20 and 100. A model whose internal dynamics are right scores well even if its inflow
  estimate is poor; a model whose inflow pieces carry internal dynamics scores badly. This is why the
  inflow load column (I1) and the "never re-estimate inflows in refinement" rule matter.
