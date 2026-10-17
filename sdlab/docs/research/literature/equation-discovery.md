# Equation discovery and scientific machine learning: what it says about reverse-engineering SD models

**Part of the literature chain** (one tradition per document; a later step synthesises them).
Tradition covered: discovering differential/difference equations from data, from BACON to SINDy,
symbolic regression, gradient matching, neural/universal ODEs and their benchmarks.
Not repeated here: the tools survey in [../SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md)
(PySINDy optimisers, PySR, gplearn, AI Feynman, SysIdentPy, Tigramite, Kalman libraries). This
document is about the *ideas* and the evidence for them, mapped onto our pipeline
([../../DISCOVERY.md](../../DISCOVERY.md)).

## A fact about our data that reorders this whole literature

Most of this tradition assumes **measurement noise on a continuous trajectory**: you see
x(t) + ε and must estimate dx/dt. Most of its machinery (smoothing, total-variation
differentiation, weak forms, GP gradient matching, collocation) exists to cope with that.

Our ground truth (`sdlab/sdtruth.py`, read for this review) is different:

- It is an **explicit discrete map with dt = 1**: x_{t+1} = x_t + S · q(x_t, u_t), where q is the
  vector of flow amounts. There is no hidden continuous ODE to approximate; the forward difference
  *is* the equation.
- The noise is **process (demographic) noise**: each flow's amount is drawn Poisson around its rate,
  then the stocks move by those whole amounts. **Measured levels are exact integers**: there is no
  measurement error on the regressors.
- Outflows are **capped by what the stock holds** (shared pro rata), rates are **floored at 0**, and
  co-flows draw on a third stock.

Consequences, used throughout:

1. **Derivative estimation is not our problem.** One-step differences are exact draws of
   S · Poisson(q(x_t)). Regressing Δx_t on functions of x_t is unbiased (no errors-in-variables);
   smoothing levels before differencing would *add* bias. The two-stage "smooth then regress"
   literature (section 5) matters to us only for its later stage: profiling and simulation refinement.
2. The right statistical frame is **stochastic kinetics / Kramers-Moyal regression** (section 4.9):
   the conditional mean of Δx is S·q (the drift), and the conditional covariance is
   S·diag(q)·Sᵀ (the diffusion). **The covariance carries structure**: two stocks joined by a flow
   have negatively correlated one-step changes, with magnitude equal to that flow's rate.
3. Weak-form and windowed fitting buy noise robustness under *measurement* noise. Under process
   noise they discard information (they sum independent draws) unless the regressors are integrated
   exactly. Our windows are a box-test-function weak form; that is why they help with speed and
   fast-turnover masking but not with bias (section 4.4).
4. What remains genuinely hard for us is what the literature also finds hardest: **hidden
   variables, collinear candidate terms (identifiability), regime changes, non-smooth terms (floors
   and caps), and selecting among near-equivalent structures**.

## Summary: what this tradition suggests for us, ranked

1. **Keep "flows as columns of one regression" and make the library a declarative SD process
   grammar.** Process-based modelling (IPM, HIPM, ProBMoT, RPM; Langley, Todorovski, Džeroski,
   1999-2017) and Reactive SINDy (Hoffmann et al. 2019) are the same idea as ours: a model is a sum
   of *processes*, each a rate expression times a stoichiometric vector, chosen from a library of
   generic processes with alternative rate forms. Their lesson: write the library as data (generic
   process templates with typed slots, alternative rate forms, constraints such as "at most one
   outflow form per pair"), so effects, co-flows, delays and gap forms are new *templates*, not new
   code paths. Effects are the template `rate(source) × f(level C)` with f from a small family.
2. **Select structure on simulation, not on one-step fit, for the final ranking.** The process-
   modelling literature found that the parameter-fitting method changes which structure wins
   (Čerepnalkoski et al. 2012), and SINDy benchmarks repeatedly show one-step-optimal models that run
   away. Use the fast regression to propose a shortlist (top K structures, Pareto front of size vs
   fit), then re-fit each by multi-step/output error (multiple shooting) and rank by held-out
   skill@H. This is "two-stage then refine", the standard recipe from Varah (1982) and Ramsay et al.
   (2007) to RPM and ProBMoT.
3. **Use the second moment.** With Poisson process noise, Cov(Δx_t | x_t) = S·diag(q)·Sᵀ. Fit drift
   and diffusion together (Kramers-Moyal / Langevin regression, linear noise approximation): the
   off-diagonal covariance of one-step changes is a direct, almost free test of "is there a flow
   between A and B, and how big", independent of collinearity in the drift regression. It also
   gives the correct GLS weights (variance ∝ rate). This is the single most under-used signal for
   our setting, and it separates moves from co-incident outside flows.
4. **Bag the data and report inclusion probabilities (E-SINDy / stability selection).** Bootstrapping
   blocks of time and re-running the selection (Fasel et al. 2022; Meinshausen and Bühlmann 2010;
   ARGOS, Egan et al. 2024) is the most robust improvement in noisy-SINDy benchmarks. Keep flows
   with high inclusion probability; ensemble-average coefficients; use the bag for "fits about as
   well" alternatives. Bayesian-ARGOS (2026) shows a screening-then-Bayesian variant at 1% of the
   cost.
5. **Impose physics as constraints, not as penalties, and add a stability constraint.** Conservation
   (stoichiometry), non-negative rates, sign constraints and **stability of the found loop** (Loiseau
   and Brunton 2018 constrained SINDy; Kaptanoglu et al. 2021 trapping SINDy; PySINDy StableLinearSR3)
   shrink the search space and stop runaway models. A found linear model whose Jacobian
   I + S·K has spectral radius > 1 where the data were stationary should be rejected or
   constrained.
6. **Hidden stocks: delay-coordinate library terms first, latent-state fitting second.** The
   literature's working tools for unmeasured variables are (a) time-delay/filtered copies of measured
   variables as library terms (Takens; HAVOK, Brunton et al. 2017; our exp/erlang/pipe kernels), and
   (b) fitting a candidate that contains the latent state by simulation or data assimilation
   (Somacal et al. 2022; Ribera et al. 2022; ProGED for partial observation, Omejc et al. 2024).
   Autoencoder methods (SINDy-autoencoder, deep delay autoencoders) find *some* coordinates, not
   interpretable stocks; skip them.
7. **Eras: shared support, per-era coefficients (group sparsity).** Sequential grouped threshold
   ridge regression (Rudy et al. 2019) selects the same terms across data sets while letting
   coefficients differ; abrupt-SINDy and hybrid-SINDy handle unannounced switches. This is our
   "structure shared, numbers per era" idea, with a tested selection rule.
8. **Effect curves: learn a free multiplier, then distil to the SD grammar.** The UDE recipe
   (Rackauckas et al. 2020) and Cranmer et al. 2020's "fit a flexible model, then symbolically
   regress its parts" both work best when the unknown function is one-dimensional and embedded in a
   known structure. For us: after structure, give a suspected flow a piecewise-linear multiplier of
   one candidate stock (linear in its knot values, so it stays inside least squares), then snap it
   to a linear or table effect. Free-form symbolic regression over whole equations is
   unnecessary and fragile under noise (SRBench, ODEBench).
9. **Treat floors and caps as part of the model, not as noise.** Equation-discovery methods that
   ignore non-smooth terms produce biased coefficients near boundaries; hybrid and weak-form hybrid
   work (Mangan et al. 2019; Messenger, Dwyer and Dukic 2024) handles switching explicitly. Exclude
   or censor the capped steps (a stock emptied this step tells you only "rate ≥ content"), and
   simulate with the floor and cap in the output-error stage.
10. **Benchmark the way the field learned to: many generated systems, noise sweeps, and exact-
    structure plus prediction metrics, with hyperparameters chosen automatically.** SRBench, ODEBench,
    the Strogatz set and dysts showed that methods tuned per system look far better than they are,
    that noise is the dominant failure, and that "fits the derivative" ≠ "predicts the trajectory".
    Our skill@H is the right metric; a procedural generator of SD models (an "SDBench") would stop us
    over-fitting 31 examples and, later, could pre-train an amortised proposer (ODEFormer-style).

---

## 1. Early computational scientific discovery

### 1.1 BACON and the heuristic-search view (Langley 1977-1987)

**Idea.** Discovery is heuristic search through a space of terms. BACON looked at tables of
measured quantities, noticed that two variables rise together or one falls as the other rises, and
formed products or ratios until it found an invariant (it rediscovered Kepler's third law, Boyle's
law, Ohm's law). Data-driven, small spaces, noise-free.
- Langley, P. (1981). Data-driven discovery of physical laws. *Cognitive Science* 5(1):31-54.
  https://doi.org/10.1207/s15516709cog0501_4
- Langley, P., Simon, H. A., Bradshaw, G. L., Zytkow, J. M. (1987). *Scientific Discovery:
  Computational Explorations of the Creative Processes*. MIT Press.

**For us.** The "look for an invariant" heuristic survives in one useful form: **conservation
rows**. The sum of all stocks in one unit is an invariant up to outside flows; our per-unit total
row is a BACON-style invariant test. Otherwise historical.

### 1.2 LAGRANGE, LAGRAMGE: equation discovery for dynamics (Džeroski and Todorovski 1993-1997)

**Idea.** Generate candidate ODE right-hand sides from a set of terms (products of variables and
their derivatives up to some degree), fit each by linear regression, keep the ones that fit.
LAGRANGE (1993) enumerated polynomial terms: this is SINDy two decades early, with exhaustive
search instead of sparsity. LAGRAMGE (1997) replaced the enumeration with a **user-supplied context-
free grammar**, so domain knowledge restricts which expressions can appear (e.g., "a growth term is
a Monod expression of a nutrient").
- Džeroski, S., Todorovski, L. (1993). Discovering dynamics. *Proc. ICML 1993*, 97-103.
- Džeroski, S., Todorovski, L. (1995). Discovering dynamics: from inductive logic programming to
  machine discovery. *J. Intelligent Information Systems* 4:89-108.
  https://doi.org/10.1007/BF00962824
- Todorovski, L., Džeroski, S. (1997). Declarative bias in equation discovery. *Proc. ICML 1997*,
  376-384.

**For us.** The grammar idea is the important one: a declarative description of *what an SD rate
may look like*. Our five forms are a hard-coded grammar. The modern descendant is ProGED
(section 1.4).

### 1.3 Inductive process modelling: IPM, HIPM, ProBMoT, RPM, SC-IPM (cover in depth)

This is **the closest tradition to stock-and-flow discovery** and the one to borrow most from.

**Core idea.** A model is a set of **entities** (variables, some observed, some not) and
**processes**. Each process has a **rate expression** and contributes terms to the derivatives of
the variables it affects. The derivative of a variable is the **sum** of the contributions of all
processes touching it. Domain knowledge is a library of **generic processes**: templates with typed
slots (e.g., `grazing(Predator, Prey)` with alternative rate forms Holling I/II/III), plus
constraints (which processes are mandatory, mutually exclusive, or must occur together). The
system instantiates generic processes on the actual entities, enumerates (or searches) admissible
combinations, fits each candidate's parameters by simulation error, and ranks.

That *is* an SD model: entities = stocks, processes = flows, the stoichiometric contribution
(-1 on source, +1 on target) = a process's effects, generic processes with alternative rate forms
= our equation forms, and the library constraints = our pruning rules (no outflow from `final`,
same group, unit ratios).

Key papers, in order:
- Langley, P., Sanchez, J. N., Todorovski, L., Džeroski, S. (2002). Inducing process models from
  continuous data. *Proc. ICML 2002*, 347-354. (IPM; ecosystem and battery models.)
- Todorovski, L., Bridewell, W., Shiran, O., Langley, P. (2005). Inducing hierarchical process
  models in dynamic domains. *Proc. AAAI 2005*, 892-897. (HIPM: hierarchical generic processes,
  constraints on combinations.)
- Atanasova, N., Todorovski, L., Džeroski, S., Kompare, B. (2006). Constructing a library of domain
  knowledge for automated modelling of aquatic ecosystems. *Ecological Modelling* 194:14-36.
  https://doi.org/10.1016/j.ecolmodel.2005.10.002 (How to write the library: what a domain-specific
  library of generic processes looks like in practice.)
- Bridewell, W., Langley, P., Todorovski, L., Džeroski, S. (2008). Inductive process modeling.
  *Machine Learning* 71:1-32. https://doi.org/10.1007/s10994-007-5042-6 (The reference paper:
  formalism, search, evaluation on ecology and biochemistry; discusses overfitting and ensembles.)
- Čerepnalkoski, D., Taškova, K., Todorovski, L., Atanasova, N., Džeroski, S. (2012). The influence
  of parameter fitting methods on model structure selection in automated modeling of aquatic
  ecosystems. *Ecological Modelling* 245:136-165. https://doi.org/10.1016/j.ecolmodel.2012.06.001
  (ProBMoT. **Finding: the parameter estimator (local vs global, e.g. differential evolution) changes
  which structure is selected.** Structure search is only as good as the fitting inside it.)
- Simidjievski, N., Todorovski, L., Džeroski, S. (2016). Modeling dynamic systems with efficient
  ensembles of process-based models. *PLoS ONE* 11(4):e0153507.
  https://doi.org/10.1371/journal.pone.0153507 (Bagging/boosting over process-based models
  improves prediction on real lake data.)
- Tanevski, J., Todorovski, L., Džeroski, S. (2016). Learning stochastic process-based models of
  dynamical systems from knowledge and data. *BMC Systems Biology* 10:30.
  https://doi.org/10.1186/s12918-016-0273-4 (Process-based models as stochastic reaction networks:
  **directly our count-noise setting**.)
- Tanevski, J., Todorovski, L., Džeroski, S. (2020). Combinatorial search for selecting the
  structure of models of dynamical systems with equation discovery. *Engineering Applications of
  AI* 89:103423. https://doi.org/10.1016/j.engappai.2019.103423
- Langley, P., Arvay, A. (2015). Heuristic induction of rate-based process models. *Proc. AAAI
  2015*. https://ojs.aaai.org/index.php/AAAI/article/view/9219 (RPM: **because a process's effect
  is proportional to its rate, estimate derivatives once and select processes by multiple linear
  regression** instead of simulating every candidate. Orders of magnitude faster; scales to larger
  models. This is precisely our current design.)
- Langley, P., Arvay, A. (2017). Flexible model induction through heuristic process discovery.
  *Proc. AAAI 2017*. https://ojs.aaai.org/index.php/AAAI/article/view/11166 (FPM/SC-IPM: invents new
  generic processes when the library is insufficient.)
- Džeroski, S., Todorovski, L. (eds.) (2007). *Computational Discovery of Scientific Knowledge*.
  Springer LNAI 4660. https://doi.org/10.1007/978-3-540-73920-3

**What problem in our setting it addresses.** Structure (which flows), rate-form choice per flow,
hidden entities (IPM allows unobserved variables, fitted by simulation), and the organisation of
domain knowledge.

**Concrete step in our pipeline.**
- Rewrite the candidate generator as an **SD process library in data**: generic flows
  `move(A→B)`, `inflow(→A)`, `outflow(A→)`, `coflow(A→B uses C)`, `delay(A→H→B)`, each with
  alternative rate templates `{const, prop(src), gap(goal, tgt), linear(src), prop(src)×effect(C)}`
  and constraints (exclusive alternatives per pair, forbidden on `final`, unit ratio). The search
  then instantiates templates rather than code paths; adding a form means adding a template.
- Keep RPM's insight (regression first) for speed, ProBMoT's (simulation fit decides) for the final
  choice, and Simidjievski's ensembles for prediction.

**Maturity.** Research systems (Lisp/Java); ProBMoT is Java, not maintained as a library. Evaluated
on real ecological data (Lake Bled, Lake Kasumigaura, Danish lakes) and biochemical networks.

**Failure modes.** Combinatorial explosion of structures (each needs a nonlinear fit); local
minima in parameter fitting distort structure ranking; models that fit training data well predict
poorly (hence ensembles); library completeness is a hard prior (RPM/FPM address it).

### 1.4 Probabilistic grammars: ProGED (Brence, Todorovski, Džeroski 2021-2024)

**Idea.** Replace the hard grammar with a **probabilistic context-free grammar**: sample candidate
equations from it (domain knowledge = production probabilities), fit constants, rank by error. Monte
Carlo sampling instead of exhaustive enumeration; extensions enforce **dimensional consistency**
via attribute grammars, and handle ODEs with **partially observed** states by fitting through
simulation.
- Brence, J., Todorovski, L., Džeroski, S. (2021). Probabilistic grammars for equation discovery.
  *Knowledge-Based Systems* 224:107077. https://doi.org/10.1016/j.knosys.2021.107077
- Brence, J., Džeroski, S., Todorovski, L. (2023). Dimensionally-consistent equation discovery
  through probabilistic attribute grammars. *Information Sciences* 632:742-756.
  https://doi.org/10.1016/j.ins.2023.03.073
- Omejc, N., Gec, B., Brence, J., Todorovski, L., Džeroski, S. (2024). Probabilistic grammars for
  modeling dynamical systems from coarse, noisy, and partial data. *Machine Learning* 113.
  https://doi.org/10.1007/s10994-024-06522-1 (Introduces **Dynobench**, ten systems extending the
  Strogatz set; robust to coarse sampling, noise and missing variables.) Code: `ProGED` on PyPI.

**For us.** A grammar is the natural way to express "SD rate forms" with units checked, and to set
**priors over structures** (an LLM or a modeller can set production probabilities). Sampling
structures from a prior and scoring them is an alternative to greedy search for small groups.

---

## 2. Free-form discovery: Bongard and Lipson, Schmidt and Lipson (Eureqa)

**Idea.** Genetic programming over expression trees, with (a) **partial-derivative pairs** as the
fitness target so that trivial invariants are rejected, (b) a **Pareto front of accuracy vs
complexity** rather than a single best, and (c) for dynamics, **active probing**: "estimation-
exploration" chooses new experiments that discriminate between competing models.
- Bongard, J., Lipson, H. (2007). Automated reverse engineering of nonlinear dynamical systems.
  *PNAS* 104(24):9943-9948. https://doi.org/10.1073/pnas.0609476104 (Partitioning: model one
  variable at a time, substituting the data for the others; snipping; active probing. Real system:
  a pendulum and a lac operon model.)
- Schmidt, M., Lipson, H. (2009). Distilling free-form natural laws from experimental data.
  *Science* 324(5923):81-85. https://doi.org/10.1126/science.1165893 (Eureqa; conserved quantities
  from motion-tracked pendulums.)
- Schmidt, M. D., Vallabhajosyula, R. R., Jenkins, J. W., Hood, J. E., Soni, A. S., Wikswo, J. P.,
  Lipson, H. (2011). Automated refinement and inference of analytical models for metabolic
  networks. *Physical Biology* 8(5):055011. https://doi.org/10.1088/1478-3975/8/5/055011 (Yeast
  glycolysis; recovers much of a known model, including hidden-variable handling by refinement.)

**For us.**
- **Partitioning** = fit one stock's row with the others' measured levels as inputs. We already do
  this implicitly; the lesson is that per-row fits must then be **reconciled** (conservation couples
  rows; the Lipson line has no conservation).
- **Pareto front** (size vs fit) as the output instead of a single winner: report the knee and the
  next two, and hand the front to the simulation re-ranker.
- **Active probing** = our "the page suggests changing something and running again"; see the
  experiment-design topic.

**Failure modes.** GP is slow and stochastic; results vary across runs; derivative estimation on
noisy data; no stoichiometry. Eureqa became a commercial product (DataRobot) and is not available.

---

## 3. Symbolic regression (SR) proper

### 3.1 Genetic programming and its modern descendants

- Koza, J. R. (1992). *Genetic Programming*. MIT Press.
- **PySR / SymbolicRegression.jl**: Cranmer, M. (2023). Interpretable machine learning for science
  with PySR and SymbolicRegression.jl. arXiv:2305.01582. https://arxiv.org/abs/2305.01582
- **Operon**: Burlacu, B., Kronberger, G., Kommenda, M. (2020). Operon C++: an efficient genetic
  programming framework for symbolic regression. *GECCO 2020 Companion*.
  https://doi.org/10.1145/3377929.3398099
- Kronberger, G., Burlacu, B., Kommenda, M., Winkler, S. M., Affenzeller, M. (2024). *Symbolic
  Regression*. CRC Press. (Textbook; parameter-identifiability and simplification chapters are
  relevant.)
- Virgolin, M., Pissis, S. P. (2022). Symbolic regression is NP-hard. *TMLR*.
  https://openreview.net/forum?id=LTiaPxqe2e

### 3.2 Neural and pre-trained SR

- **Deep symbolic regression (DSR)**: Petersen, B. K., et al. (2021). Deep symbolic regression:
  recovering mathematical expressions from data via risk-seeking policy gradients. *ICLR 2021*.
  https://arxiv.org/abs/1912.04871; unified framework uDSR: Landajuela, M., et al. (2022). *NeurIPS
  2022*. https://arxiv.org/abs/2205.05282
- **AI Feynman**: Udrescu, S.-M., Tegmark, M. (2020). AI Feynman: a physics-inspired method for
  symbolic regression. *Science Advances* 6(16):eaay2631. https://doi.org/10.1126/sciadv.aay2631;
  AI Feynman 2.0 (Pareto-optimal, graph modularity), *NeurIPS 2020*. https://arxiv.org/abs/2006.10782
  (Dimensional analysis, separability, symmetry tests on a neural surrogate.)
- **Transformers, pre-trained on generated equations**: Biggio, L., et al. (2021). Neural symbolic
  regression that scales. *ICML 2021*. https://arxiv.org/abs/2106.06427; Kamienny, P.-A., d'Ascoli,
  S., Lample, G., Charton, F. (2022). End-to-end symbolic regression with transformers. *NeurIPS
  2022*. https://arxiv.org/abs/2204.10532
- **For dynamics specifically**: Becker, S., Klein, M., Neitz, A., Parascandolo, G., Kilbertus, N.
  (2023). Predicting ordinary differential equations with transformers. *ICML 2023*.
  https://arxiv.org/abs/2307.12617; d'Ascoli, S., Becker, S., Schwaller, P., Mathis, A., Kilbertus,
  N. (2024). **ODEFormer**: symbolic regression of dynamical systems with transformers. *ICLR 2024*.
  https://arxiv.org/abs/2310.05573 (Infers a whole multidimensional ODE from one noisy, irregular
  trajectory, without derivative estimation; introduces **ODEBench**, 63 ODEs: 23 1D, 28 2D, 10 3D,
  2 4D.)
- **LLM-guided SR**: Shojaee, P., et al. (2025). LLM-SR: scientific equation discovery via
  programming with large language models. *ICLR 2025*. https://arxiv.org/abs/2404.18400 (LLM proposes
  equation skeletons as code using variable names and domain knowledge; numeric optimiser fits
  constants.) LLM-SRBench (Shojaee et al., *ICML 2025*, https://arxiv.org/abs/2504.10415) shows
  that rediscovering *memorised* textbook laws inflates such methods' scores.

**What SR addresses for us.** Only one thing: **the shape of one rate expression** once the flow and
its stoichiometry are known, chiefly the effect curve f(level C). SR does not output conserved
moves between stocks.

**Concrete step.** On a selected flow, regress its implied amount (or the stock residual it
explains) against candidate driver levels with a *restricted* grammar: `base × f(C)`,
f ∈ {linear, saturating C/(C+K), threshold/clamp, table}. Use PySR only as an exploratory tool; in
production, enumerate the small grammar by least squares (it is linear in table knots).

**Failure modes (the benchmarks are blunt about this).** Exact recovery collapses with noise;
GP methods give different answers across seeds; pre-trained transformers fail outside the
distribution of equations they were trained on (dimension, operators, magnitudes); expression
bloat; constants are poorly identified when terms are collinear.

---

## 4. Sparse regression: SINDy and its family

### 4.1 The core: SINDy (Brunton, Proctor, Kutz 2016)

**Idea.** Build a library Θ(x) of candidate functions (polynomials, products, trig), and solve
ẋ ≈ Θ(x)Ξ with a sparsity-promoting regression (sequentially thresholded least squares, STLSQ), one
column of Ξ per state. Few active terms = interpretable equations. The paper also treats
**discrete-time maps**, x_{k+1} = Θ(x_k)Ξ, which is our case exactly.
- Brunton, S. L., Proctor, J. L., Kutz, J. N. (2016). Discovering governing equations from data by
  sparse identification of nonlinear dynamical systems. *PNAS* 113(15):3932-3937.
  https://doi.org/10.1073/pnas.1517384113
- Precursors: Wang, W.-X., Yang, R., Lai, Y.-C., Kovanis, V., Grebogi, C. (2011). Predicting
  catastrophes in nonlinear dynamical systems by compressive sensing. *PRL* 106:154101.
  https://doi.org/10.1103/PhysRevLett.106.154101; and NARMAX/FROLS (Billings 2013, *Nonlinear System
  Identification*, Wiley), which did sparse term selection decades earlier.
- Convergence: Zhang, L., Schaeffer, H. (2019). On the convergence of the SINDy algorithm. *Multiscale
  Model. Simul.* 17(3):948-972. https://doi.org/10.1137/18M1189828
- Optimisers: Zheng, P., Askham, T., Brunton, S. L., Kutz, J. N., Aravkin, A. Y. (2019). A unified
  framework for sparse relaxed regularized regression: SR3. *IEEE Access* 7:1404-1423.
  https://doi.org/10.1109/ACCESS.2018.2886528; Champion, K., Zheng, P., Aravkin, A. Y., Brunton, S. L.,
  Kutz, J. N. (2020). A unified sparse optimization framework to learn parsimonious physics-informed
  models from data. *IEEE Access* 8:169259. https://doi.org/10.1109/ACCESS.2020.3023625;
  Bertsimas, D., Gurnee, W. (2023). Learning sparse nonlinear dynamics via mixed-integer
  optimization. *Nonlinear Dynamics* 111:6585-6604. https://doi.org/10.1007/s11071-022-08178-9 (MIOSR:
  exact best-subset; does well in benchmarks.)
- Model selection: Mangan, N. M., Kutz, J. N., Brunton, S. L., Proctor, J. L. (2017). Model selection
  for dynamical systems via sparse regression and information criteria. *Proc. R. Soc. A*
  473:20170009. https://doi.org/10.1098/rspa.2017.0009 (Sweep the sparsity threshold, compute AIC
  on **simulated** trajectories of held-out data, keep models within ΔAIC of the best.)
- Software: PySINDy (de Silva et al. 2020, JOSS; Kaptanoglu et al. 2022, JOSS 7(69):3994,
  https://doi.org/10.21105/joss.03994); DataDrivenDiffEq.jl (SciML).

**Our relation to it.** Our discovery is a *flow-parameterised* SINDy on a discrete map with BIC
stepwise selection. The differences that matter: one coefficient group per flow touches two rows
(stoichiometry), selection is over flows not terms, and we have priors (units, groups, forwards).

**Failure modes (well documented).**
- **Collinearity of library columns** (e.g., levels of two stocks that move together near
  equilibrium; a stock and its delayed copy) makes thresholding pick the wrong one and inflates
  coefficients with opposite signs. STLSQ has no protection; SR3, MIOSR and ensembles help partially.
  The real cure is excitation (data) or priors.
- **Noise in derivatives** (not our problem; see the opening section).
- **Threshold hyperparameters** are system-specific; papers tune per system. Benchmarks show this
  makes published performance optimistic (Kaptanoglu et al. 2023; Egan et al. 2024).
- **Library incompleteness**: if the true term is absent, SINDy returns a dense approximation. A
  missing effect shows up as several spurious small terms.
- **Good one-step fit, unstable simulation**: no guarantee the found model is stable; hence
  trapping/stability constraints and simulation-based selection.

### 4.2 Implicit SINDy and SINDy-PI: rational rate laws

**Idea.** Michaelis-Menten-type rates (a/(b + x)) are not linear in a library. Implicit-SINDy
multiplies through by the denominator and finds the null space of an augmented library; SINDy-PI
makes this robust by trying each library term as the left-hand side ("parallel implicit").
- Mangan, N. M., Brunton, S. L., Proctor, J. L., Kutz, J. N. (2016). Inferring biological networks
  by sparse identification of nonlinear dynamics. *IEEE Trans. Mol. Biol. Multi-Scale Commun.*
  2(1):52-63. https://doi.org/10.1109/TMBMC.2016.2633265
- Kaheman, K., Kutz, J. N., Brunton, S. L. (2020). SINDy-PI: a robust algorithm for parallel implicit
  sparse identification of nonlinear dynamics. *Proc. R. Soc. A* 476:20200279.
  https://doi.org/10.1098/rspa.2020.0279

**For us.** Saturating effects (`rate × C/(C+K)`) and capacity-limited service (`min(demand,
capacity)` smoothed) are rational forms. Rather than implicit SINDy, which is noise-sensitive, a
**grid over K** (as we do for delays) keeps the problem linear: for each K, `C/(C+K)` is a column.

### 4.3 SINDy with control (SINDYc) and with switching

- Brunton, S. L., Proctor, J. L., Kutz, J. N. (2016). Sparse identification of nonlinear dynamics
  with control (SINDYc). *IFAC-PapersOnLine* 49(18):710-715.
  https://doi.org/10.1016/j.ifacol.2016.10.249
- Kaiser, E., Kutz, J. N., Brunton, S. L. (2018). Sparse identification of nonlinear dynamics for
  model predictive control in the low-data limit. *Proc. R. Soc. A* 474:20180335.
  https://doi.org/10.1098/rspa.2018.0335 (Shows SINDy needs far less data than neural nets for usable
  models; uses ensembles of short records.)
- Quade, M., Abel, M., Kutz, J. N., Brunton, S. L. (2018). Sparse identification of nonlinear
  dynamics for rapid model recovery. *Chaos* 28:063116. https://doi.org/10.1063/1.5027470
  (Abrupt-SINDy: detect a change, then a minimal sparse update.)
- Mangan, N. M., Askham, T., Brunton, S. L., Kutz, J. N., Proctor, J. L. (2019). Model selection for
  hybrid dynamical systems via sparse regression. *Proc. R. Soc. A* 475:20180534.
  https://doi.org/10.1098/rspa.2018.0534 (Hybrid-SINDy: cluster, fit per cluster, select by AIC
  on held-out data.)

**For us.** Outside inflows are control inputs `u`; announced eras are known switches; unannounced
inflow changes are unknown piecewise-constant `u` (which SINDYc does not estimate: our PELT pieces
inside the regression go further than the literature). Floors and caps are a hybrid system
(different equations when a stock is empty); Hybrid-SINDy's "cluster by regime then fit" is a way
to fit the capped steps separately.

### 4.4 Weak and integral formulations

**Idea.** Multiply the equation by smooth test functions φ that vanish at window ends, integrate,
and move the time derivative onto φ by integration by parts: −∫φ̇ x dt = ∫φ Θ(x) dt Ξ. No derivative
of the data is needed and noise averages out. Integral SINDy (Schaeffer and McCalla) integrates
once without test functions.
- Schaeffer, H., McCalla, S. G. (2017). Sparse model selection via integral terms. *Phys. Rev. E*
  96:023302. https://doi.org/10.1103/PhysRevE.96.023302
- Reinbold, P. A. K., Gurevich, D. R., Grigoriev, R. O. (2020). Using noisy or incomplete data to
  discover models of spatiotemporal dynamics. *Phys. Rev. E* 101:010203.
  https://doi.org/10.1103/PhysRevE.101.010203
- Messenger, D. A., Bortz, D. M. (2021). Weak SINDy: Galerkin-based data-driven model selection.
  *Multiscale Model. Simul.* 19(3):1474-1497. https://doi.org/10.1137/20M1343166
- Bortz, D. M., Messenger, D. A., Dukic, V. (2023). Direct estimation of parameters in ODE models
  using WENDy: weak-form estimation of nonlinear dynamics. *Bull. Math. Biol.* 85:110.
  https://doi.org/10.1007/s11538-023-01208-6 (Weak form plus an iteratively reweighted
  errors-in-variables covariance: removes the bias weak SINDy has when regressors are noisy.)
- Messenger, D. A., Dwyer, G., Dukic, V. (2024). Weak-form inference for hybrid dynamical systems
  in ecology. *J. R. Soc. Interface* 21:20240376. https://doi.org/10.1098/rsif.2024.0376 (Hybrid
  continuous/discrete population models from sparse, intermittent data; real system: spongy moth
  epizootics.)

**For us.** Our windows are a weak form with box test functions on the *left* side (x at window
ends) and, depending on implementation, sums or averages of regressors over the window on the
*right*. Under our process noise:
- Summing Δx over a window does not reduce the signal-to-noise ratio of the *coefficient* estimate
  (sum of independent Poisson draws); it does help when what we regress against is only
  approximately known inside the window (unknown inflow pieces, fast-turnover stocks) and it speeds
  the search.
- The regressors inside the window must be the **exact sums of levels at each step**, not
  window-end averages; otherwise windowing introduces approximation bias for fast stocks.
- Smooth test functions are worth trying only if we ever ingest data with measurement error (real
  user data might be sampled or rounded). Put weak form behind that switch; do not expect it to fix
  benchmark-v2 failures.

### 4.5 Ensembles and stability selection (E-SINDy, ARGOS, PDE-STRIDE)

**Idea.** Fit on many bootstrap resamples (of time points, or of library terms), keep terms selected
in a high fraction of fits (inclusion probability), and average coefficients. This is stability
selection (Meinshausen and Bühlmann) applied to dynamics.
- Meinshausen, N., Bühlmann, P. (2010). Stability selection. *J. R. Stat. Soc. B* 72(4):417-473.
  https://doi.org/10.1111/j.1467-9868.2010.00740.x
- Fasel, U., Kutz, J. N., Brunton, B. W., Brunton, S. L. (2022). Ensemble-SINDy: robust sparse model
  discovery in the low-data, high-noise limit, with active learning and control. *Proc. R. Soc. A*
  478:20210904. https://doi.org/10.1098/rspa.2021.0904 (Bagging and library bagging; real data:
  Hudson's Bay lynx-hare.)
- Maddu, S., Cheeseman, B. L., Sbalzarini, I. F., Müller, C. L. (2022). Stability selection enables
  robust learning of differential equations from limited noisy data. *Proc. R. Soc. A*
  478:20210916. https://doi.org/10.1098/rspa.2021.0916 (PDE-STRIDE: picks the sparsity level
  automatically from stability.)
- Egan, K., Li, W., Carvalho, R. (2024). Automatically discovering ordinary differential equations
  from data with sparse regression. *Communications Physics* 7:20.
  https://doi.org/10.1038/s42005-023-01516-2 (ARGOS: denoise, sparse regression with automatic
  hyperparameters, bootstrap confidence intervals; reliable for 3D systems given moderate data and
  good signal-to-noise.)
- Zhang, Y., Li, W. (2026). Fast and principled equation discovery from chaos to climate.
  arXiv:2604.11929. https://arxiv.org/abs/2604.11929 (Bayesian-ARGOS: frequentist screening then
  focused Bayesian inference; claims better data efficiency than SINDy and ~100× cheaper than
  bootstrap ARGOS. Preprint.)

**For us.** Block-bootstrap the windows (blocks of consecutive windows to keep autocorrelation),
rerun the stepwise search (it takes about a second per group), and report each flow's inclusion
frequency. Use frequency ≥ 0.6-0.8 to accept, coefficient medians as estimates, and the empirical
spread for the "fits about as well" panel. Bagging also yields a natural **ensemble forecast**
(median of bagged models' simulations), which process-based modelling found improves prediction.

### 4.6 Constrained and physics-informed SINDy

**Idea.** Encode known physics as hard constraints on Ξ: energy conservation in quadratic
nonlinearities, symmetries, stability (trapping region), non-negativity.
- Loiseau, J.-C., Brunton, S. L. (2018). Constrained sparse Galerkin regression. *J. Fluid Mech.*
  838:42-67. https://doi.org/10.1017/jfm.2017.823
- Kaptanoglu, A. A., Callaham, J. L., Aravkin, A., Hansen, C. J., Brunton, S. L. (2021). Promoting
  global stability in data-driven models of quadratic nonlinear dynamics. *Phys. Rev. Fluids*
  6:094401. https://doi.org/10.1103/PhysRevFluids.6.094401 (Trapping SINDy.)

**For us.** Our stoichiometry is a stronger constraint than anything in this line: we parameterise
flows, so conservation holds by construction. What we lack is (a) **non-negativity of rate
coefficients** in proportional forms (a drain cannot have a negative share), enforced by
NNLS/bounded least squares rather than a post-hoc "runs forwards" check, and (b) **stability**: for
linear forms the found map is x_{t+1} = (I + S·K)x_t + c; require spectral radius ≤ 1 (or ≤ the
data's own growth) unless the data show growth.

### 4.7 Reaction networks: Reactive SINDy and relatives

- Hoffmann, M., Fröhner, C., Noé, F. (2019). Reactive SINDy: discovering governing reactions from
  concentration data. *J. Chem. Phys.* 150:025101. https://doi.org/10.1063/1.5066099
- Burnham, S. C., Searson, D. P., Willis, M. J., Wright, A. R. (2008). Inference of chemical reaction
  networks. *Chem. Eng. Sci.* 63(4):862-873. https://doi.org/10.1016/j.ces.2007.10.010
- Willis, M. J., von Stosch, M. (2016). Inference of chemical reaction networks using mixed integer
  linear programming. *Comput. Chem. Eng.* 90:31-43. https://doi.org/10.1016/j.compchemeng.2016.04.019
- Ji, W., Deng, S. (2021). Autonomous discovery of unknown reaction pathways from data by chemical
  reaction neural network. *J. Phys. Chem. A* 125(4):1082-1092. https://doi.org/10.1021/acs.jpca.0c09316
  (CRNN: a network whose weights *are* stoichiometric coefficients and rate constants under mass
  action; trained by gradient descent with sparsity; no candidate list needed.)

**For us.** Reactive SINDy's vector-valued ansatz (one coefficient multiplies a whole stoichiometric
vector) is our flow column. Willis and von Stosch show the selection can be posed as a **mixed-
integer program** with stoichiometric and balance constraints: an exact alternative to greedy for
groups of a few stocks. CRNN is the gradient-descent analogue and connects to the
gradient-descent topic: a differentiable SD simulator whose parameters are flow rates, with an L1
penalty on flows, is a CRNN with SD rate laws.

### 4.8 Bayesian SINDy and sparse Bayesian learning

**Idea.** Put a sparsity prior on coefficients (ARD / relevance vector machine, spike-and-slab,
regularised horseshoe), compute posteriors, and get both selection and uncertainty.
- Tipping, M. E. (2001). Sparse Bayesian learning and the relevance vector machine. *JMLR* 1:211-244.
  https://www.jmlr.org/papers/v1/tipping01a.html; Wipf, D. P., Rao, B. D. (2004). Sparse Bayesian
  learning for basis selection. *IEEE Trans. Signal Process.* 52(8):2153-2164.
  https://doi.org/10.1109/TSP.2004.831016
- Pan, W., Yuan, Y., Gonçalves, J., Stan, G.-B. (2016). A sparse Bayesian approach to the
  identification of nonlinear state-space systems. *IEEE Trans. Autom. Control* 61(1):182-187.
  https://doi.org/10.1109/TAC.2015.2426291
- Yuan, Y., Tang, X., Zhou, W., Pan, W., Li, X., Zhang, H.-T., Ding, H., Gonçalves, J. (2019). Data
  driven discovery of cyber physical systems. *Nature Communications* 10:4894.
  https://doi.org/10.1038/s41467-019-12490-1 (Sparse Bayesian learning for **switched/hybrid**
  systems: identifies modes and transition logic; real examples include a smart building.)
- Zhang, S., Lin, G. (2018). Robust data-driven discovery of governing physical laws with error
  bars. *Proc. R. Soc. A* 474:20180305. https://doi.org/10.1098/rspa.2018.0305 (Threshold SBL.)
- Nayek, R., Fuentes, R., Worden, K., Cross, E. J. (2021). On spike-and-slab priors for Bayesian
  equation discovery of nonlinear dynamical systems via sparse linear regression. *Mech. Syst.
  Signal Process.* 161:107986. https://doi.org/10.1016/j.ymssp.2021.107986
- Hirsh, S. M., Barajas-Solano, D. A., Kutz, J. N. (2022). Sparsifying priors for Bayesian
  uncertainty quantification in model discovery. *R. Soc. Open Sci.* 9:211823.
  https://doi.org/10.1098/rsos.211823 (Regularised horseshoe; PySINDy's `SBR`.)

**For us.** With a Gaussian (linear-noise) approximation, a group-ARD prior *per flow* (one
precision hyperparameter shared by a flow's 1-3 coefficients) gives a principled replacement for
our hand-tuned BIC add-ons, computes evidence in closed form, and yields posterior inclusion
probabilities. Our conservation and movement prices are effectively priors; SBL is the framework
for calibrating them from data instead of by hand. Spike-and-slab via Gibbs is affordable at our
sizes (tens of candidate flows per group).

### 4.9 Stochastic dynamics: drift and diffusion regression (the right frame for counts)

**Idea.** For a Markov process, the first two conditional moments of the increment identify the
drift and diffusion (Kramers-Moyal). Sparse-regress both. For reaction networks the linear noise
approximation / chemical Langevin equation gives diffusion = S·diag(q)·Sᵀ.
- Boninsegna, L., Nüske, F., Clementi, C. (2018). Sparse learning of stochastic dynamical equations.
  *J. Chem. Phys.* 148:241723. https://doi.org/10.1063/1.5018409
- Callaham, J. L., Loiseau, J.-C., Rigas, G., Brunton, S. L. (2021). Nonlinear stochastic modelling
  with Langevin regression. *Proc. R. Soc. A* 477:20210092. https://doi.org/10.1098/rspa.2021.0092
- Gillespie, D. T. (2000). The chemical Langevin equation. *J. Chem. Phys.* 113:297-306.
  https://doi.org/10.1063/1.481811
- Fearnhead, P., Giagos, V., Sherlock, C. (2014). Inference for reaction networks using the linear
  noise approximation. *Biometrics* 70(2):457-466. https://doi.org/10.1111/biom.12152
- Golightly, A., Wilkinson, D. J. (2011). Bayesian parameter inference for stochastic biochemical
  network models using particle MCMC. *Interface Focus* 1(6):807-820.
  https://doi.org/10.1098/rsfs.2011.0047

**For us (high value, cheap).**
- **Covariance screen.** Over steps where no stock is capped, the sample covariance of (Δx_A, Δx_B)
  estimates −(sum of rates of flows between A and B, times ratios) plus co-flow terms. A significantly
  negative covariance is direct evidence of a move A↔B; zero covariance with mirrored *means* says
  "an outside outflow from A and an outside inflow to B that happen to track each other". This
  directly attacks our "moves vs outside pairs" and "shared noise" problems and replaces the
  correlation pre-screen in section 7 of DISCOVERY.md with a statistic that has a physical
  meaning.
- **Variance check of a candidate.** For a found structure, Var(Δx_A | x) should equal the sum of the
  rates of all flows touching A (Poisson). Too much variance = a missing flow (or a bursty outside
  input); too little = a flow counted twice. This is a free diagnostic per stock.
- **Weights.** GLS with Σ_t = S·diag(q̂_t)·Sᵀ (iteratively reweighted) is the linear-noise
  maximum-likelihood fit. Exact Poisson likelihood is only available if individual flows are seen;
  for net changes, the Gaussian LNA is the standard approximation.

### 4.10 Hidden variables: delays, autoencoders, data assimilation

- Takens, F. (1981). Detecting strange attractors in turbulence. *Lecture Notes in Mathematics*
  898:366-381. https://doi.org/10.1007/BFb0091924
- Brunton, S. L., Brunton, B. W., Proctor, J. L., Kaiser, E., Kutz, J. N. (2017). Chaos as an
  intermittently forced linear system. *Nature Communications* 8:19.
  https://doi.org/10.1038/s41467-017-00030-8 (HAVOK: linear model in delay coordinates.)
- Champion, K., Lusch, B., Kutz, J. N., Brunton, S. L. (2019). Data-driven discovery of coordinates
  and governing equations. *PNAS* 116(45):22445-22451. https://doi.org/10.1073/pnas.1906995116
  (SINDy-autoencoder.)
- Bakarji, J., Champion, K., Kutz, J. N., Brunton, S. L. (2023). Discovering governing equations from
  partial measurements with deep delay autoencoders. *Proc. R. Soc. A* 479:20230422.
  https://doi.org/10.1098/rspa.2023.0422
- Somacal, A., Barrera, Y., Boechi, L., Jonckheere, M., Lefieux, V., Picard, D., Smucler, E. (2022).
  Uncovering differential equations from data with hidden variables. *Phys. Rev. E* 105:054209.
  https://doi.org/10.1103/PhysRevE.105.054209 (Fit candidate models with unobserved states by
  integrating them; choose by information criterion.)
- Ribera, H., Shirman, S., Nguyen, A. V., Mangan, N. M. (2022). Model selection of chaotic systems
  from data with hidden variables using sparse data assimilation. *Chaos* 32:063101.
  https://doi.org/10.1063/5.0066066
- Daniels, B. C., Nemenman, I. (2015). Automated adaptive inference of phenomenological dynamical
  models. *Nature Communications* 6:8133. https://doi.org/10.1038/ncomms9133 (Sir Isaac: grows a
  hierarchy of models, adding hidden variables one at a time in a fixed order, selected by Bayesian
  evidence; real data: yeast glycolysis, insect locomotion.) Also Daniels, B. C., Nemenman, I.
  (2015). Efficient inference of parsimonious phenomenological models of cellular dynamics using
  S-systems and alternating regression. *PLoS ONE* 10(3):e0119821.
  https://doi.org/10.1371/journal.pone.0119821

**For us.**
- Our hidden-stock candidates (exp/erlang/pipe filtered copies) are exactly the "delay-coordinate
  library" idea, specialised by Little's law to SD delays. The literature supports this as the
  first tool and is honest that it only works when the delayed signal is distinguishable.
- Daniels and Nemenman's **ordered hierarchy of hidden variables** (add one hidden stock at a time;
  stop by evidence) is a clean rule for "how many hidden stocks".
- The second tool, once a hidden stock is proposed, is to **fit it as a state** (simulate or Kalman-
  smooth through it) rather than as a filtered regressor: an exp filter is the steady-state
  approximation; a fitted state also gets the initial content and caps right. Somacal and Ribera
  show selection between hidden-variable candidates by simulation error/IC works on toy systems.
- Autoencoders (Champion; Bakarji) give coordinates that are not stocks and need lots of data.
  Not for us.

---

## 5. Gradient matching, collocation and generalised profiling

**Idea.** Avoid solving the ODE inside the optimiser: fit a smooth curve to the data (splines or a
GP), differentiate the curve, and fit the ODE parameters to match its derivatives (two-stage /
gradient matching). Ramsay's **generalised profiling** couples the two: the smoother is penalised
for violating the ODE, with a weight λ that is raised towards a fully ODE-consistent solution.
- Varah, J. M. (1982). A spline least squares method for numerical parameter estimation in
  differential equations. *SIAM J. Sci. Stat. Comput.* 3(1):28-46. https://doi.org/10.1137/0903003
- Voit, E. O., Almeida, J. (2004). Decoupling dynamical systems for pathway identification from
  metabolic profiles. *Bioinformatics* 20(11):1670-1681. https://doi.org/10.1093/bioinformatics/bth140
- Ramsay, J. O., Hooker, G., Campbell, D., Cao, J. (2007). Parameter estimation for differential
  equations: a generalized smoothing approach. *J. R. Stat. Soc. B* 69(5):741-796.
  https://doi.org/10.1111/j.1467-9868.2007.00610.x
- Liang, H., Wu, H. (2008). Parameter estimation for differential equation models using a framework
  of measurement error in regression models. *JASA* 103(484):1570-1583.
  https://doi.org/10.1198/016214508000000797
- Calderhead, B., Girolami, M., Lawrence, N. D. (2009). Accelerating Bayesian inference over
  nonlinear differential equations with Gaussian processes. *NeurIPS 2008*.
  https://papers.nips.cc/paper/3497; Dondelinger, F., Husmeier, D., Rogers, S., Filippone, M. (2013).
  ODE parameter inference using adaptive gradient matching with Gaussian processes. *AISTATS 2013*.
  https://proceedings.mlr.press/v31/dondelinger13a.html; Wenk, P., et al. (2020). ODIN: ODE-informed
  regression for parameter and state inference in time-continuous dynamical systems. *AAAI 2020*.
  https://arxiv.org/abs/1902.06278
- Heinonen, M., Yildiz, C., Mannerström, H., Intosalmi, J., Lähdesmäki, H. (2018). Learning unknown
  ODE models with Gaussian processes. *ICML 2018*. https://arxiv.org/abs/1803.04303
- Qian, Z., Kacprzyk, K., van der Schaar, M. (2022). D-CODE: discovering closed-form ODEs from
  observed trajectories. *ICLR 2022*. https://openreview.net/forum?id=wENMvIsxNN (Variational
  objective that avoids derivative estimation; plugs into SR.)
- Derivative estimation itself: Chartrand, R. (2011). Numerical differentiation of noisy, nonsmooth
  data. *ISRN Applied Mathematics* 2011:164564. https://doi.org/10.5402/2011/164564; van Breugel,
  F., Kutz, J. N., Brunton, B. W. (2020). Numerical differentiation of noisy data: a unifying
  multi-objective optimization framework. *IEEE Access* 8:196865. https://doi.org/10.1109/ACCESS.2020.3034077
- Multiple shooting: Bock, H. G. (1983). Recent advances in parameter identification techniques
  for ODE. In *Numerical Treatment of Inverse Problems*, Birkhäuser; Voss, H. U., Timmer, J.,
  Kurths, J. (2004). Nonlinear dynamical system identification from uncertain and indirect
  measurements. *Int. J. Bifurcation Chaos* 14(6):1905-1933. https://doi.org/10.1142/S0218127404010345

**For us.** Stage 1 (smoothing) is unnecessary and harmful on exact counts. Stage 2 is the valuable
part: **profiling/multiple shooting** is how to refine a regression-found structure by trajectory
error *without* the runaway and local-minimum problems of single shooting. Concretely: split the
series into segments of H steps (H ≈ 20 matching skill@20), start each segment at the measured
state, simulate the candidate (with floors and caps), and minimise the summed segment error over
the flow coefficients; hidden stocks get per-segment initial values tied by continuity penalties.
This is the "output-error" topic's final step, with the literature's standard way to make it
well-conditioned.

**Failure modes.** Smoothing across regime changes and spikes destroys them; GP gradient matching
is O(n³) and was mostly shown on tiny systems; profiling needs an inner solver per evaluation.

---

## 6. Neural ODEs, universal differential equations, physics-informed learning

- Chen, R. T. Q., Rubanova, Y., Bettencourt, J., Duvenaud, D. (2018). Neural ordinary differential
  equations. *NeurIPS 2018*. https://arxiv.org/abs/1806.07366
- Rubanova, Y., Chen, R. T. Q., Duvenaud, D. (2019). Latent ODEs for irregularly-sampled time series.
  *NeurIPS 2019*. https://arxiv.org/abs/1907.03907
- Rackauckas, C., Ma, Y., Martensen, J., Warner, C., Zubov, K., Supekar, R., Skinner, D., Ramadhan,
  A., Edelman, A. (2020). Universal differential equations for scientific machine learning.
  arXiv:2001.04385. https://arxiv.org/abs/2001.04385 (Known structure + neural term; then SINDy on
  the learned term to recover its equation. Example: recovering the missing interaction in
  Lotka-Volterra from short noisy data.)
- Kidger, P. (2022). *On Neural Differential Equations*. PhD thesis, Oxford.
  https://arxiv.org/abs/2202.02435
- Raissi, M., Perdikaris, P., Karniadakis, G. E. (2019). Physics-informed neural networks. *J. Comput.
  Phys.* 378:686-707. https://doi.org/10.1016/j.jcp.2018.10.045
- Cranmer, M., Sanchez-Gonzalez, A., Battaglia, P., Xu, R., Cranmer, K., Spergel, D., Ho, S. (2020).
  Discovering symbolic models from deep learning with inductive biases. *NeurIPS 2020*.
  https://arxiv.org/abs/2006.11287 (Train a structured network with sparse messages, then symbolic-
  regress each message; found a new dark-matter halo formula.)
- Hoedt, P.-J., Kratzert, F., Klotz, D., Halmich, C., Holzleitner, M., Nearing, G., Hochreiter, S.,
  Klambauer, G. (2021). MC-LSTM: mass-conserving LSTM. *ICML 2021*. https://arxiv.org/abs/2101.05186
  (Conservation built into the architecture: inputs are redistributed between cells by a
  column-stochastic matrix, i.e. a learned stock-and-flow network; applied to rainfall-runoff.)
- Greydanus, S., Dzamba, M., Yosinski, J. (2019). Hamiltonian neural networks. *NeurIPS 2019*.
  https://arxiv.org/abs/1906.01563 (Structure-preserving networks; the conservation analogue.)

**What it addresses for us.** (a) Unknown **effect curves** inside a known structure (UDE); (b) a
**differentiable simulator** for output-error fitting through floors/caps (soft versions) and hidden
stocks; (c) MC-LSTM shows that "mass-conserving redistribution between compartments" can be a
learnable architecture, i.e. a soft structure-search alternative: learn a dense column-stochastic
transfer matrix with a sparsity penalty, then read flows off it.

**Concrete step.** After the regression finds flows, run one UDE pass: each flow's rate gets a
multiplier g_f(x) = 1 + small MLP of the *other* measured levels (or a piecewise-linear function of
one candidate level); fit by multiple shooting; if some g_f varies materially, regress it on single
levels to choose the effect's driver and shape; refit with that table effect. Keep it as an
optional refinement; the effect templates in the regression (summary item 1) should come first,
because they are cheaper and stay identifiable.

**Failure modes.** Data hunger; neural terms absorb structural errors silently (a missing flow gets
learned as an "effect"), so distillation must be followed by re-selection; stiff or discontinuous
dynamics (caps) break gradient training; PINNs are slow and poorly suited to discrete counts.

---

## 7. Benchmarks and what they reveal

| Benchmark | What it is | What it showed |
|---|---|---|
| **Strogatz ODE set** (La Cava, Danai, Spector 2016, *EAAI* 55:292, https://doi.org/10.1016/j.engappai.2016.07.004; in PMLB) | 7 two-state ODEs from Strogatz's textbook, 14 regression targets | Small and 2D only; in SRBench it was the hardest ground-truth set to recover exactly. |
| **SRBench** (La Cava et al. 2021, *NeurIPS Datasets & Benchmarks*, https://arxiv.org/abs/2107.14351; living site https://cavalab.org/srbench) | 14 SR + 7 ML methods on 252 problems (Feynman, Strogatz, PMLB real data) | GP with parameter estimation (Operon, etc.) best on real data accuracy; exact recovery degrades sharply with noise; methods tuned to physics formulas (AI Feynman) are noise-fragile. Under noise, several methods are statistically indistinguishable. |
| **SRBench 2022 competition** (de Franca et al. 2024, *IEEE TEVC*, https://arxiv.org/abs/2304.01117) | Synthetic + real tracks, expert judging of interpretability | Accuracy and interpretability trade off; experts preferred simpler, domain-shaped expressions. |
| **ODEBench** (d'Ascoli et al. 2024, ICLR) | 63 ODEs, 1D-4D, noise and irregular sampling | Pre-trained transformer (ODEFormer) most robust to noise; SINDy and PySR need per-system tuning; all methods' exact recovery falls with dimension. |
| **dysts** (Gilpin 2021, *NeurIPS Datasets & Benchmarks*, https://arxiv.org/abs/2110.05266) and **sparse-ID benchmark** (Kaptanoglu, Zhang, Nicolaou, Fasel, Brunton 2023, *Nonlinear Dynamics*, https://arxiv.org/abs/2302.10787) | 70+ chaotic systems; 4 SINDy optimisers | Original STLSQ and MIOSR did best; ensembling improved noise robustness; weak form helped even on clean data; performance did not depend strongly on chaos, nonlinearity degree or syntactic complexity. |
| **Dynobench** (Omejc et al. 2024) | 10 systems extending Strogatz, coarse/noisy/partial | Grammar-constrained, simulation-fitted search (ProGED) robust to coarseness and missing variables. |
| **LLM-SRBench** (Shojaee et al. 2025) | Problems transformed to defeat memorisation | LLM methods' high scores on textbook sets partly reflect recall. |

**What this means for us.**
- None of these benchmarks has conservation between states, count noise, eras, floors or hidden
  delays. Our 31-example bench is already more specific to the task than any of them. Their
  lessons are about *method hygiene*:
  1. Per-system tuning hides failure. Every hyperparameter (thresholds, BIC add-ons, pre-screen bars)
     must be set once across all examples or chosen automatically (stability, information
     criteria on held-out data).
  2. Exact recovery is the wrong headline metric; trajectory prediction is the right one (skill@H),
     with structure accuracy as a diagnostic.
  3. Small curated sets are over-fitted by method developers. A **procedural generator** of SD
     models with randomised structure, noise and excitation is the standard remedy (and the
     prerequisite for amortised methods).

---

## 8. Where automatic discovery has succeeded on real (not toy) systems

Honest reading: real-data successes are few, small, and always with strong domain priors.

- **Process-based models of lakes and ecosystems** (Bridewell et al. 2008; Čerepnalkoski et al. 2012;
  Simidjievski et al. 2016): phytoplankton/zooplankton/nutrient models of real lakes, chosen from
  libraries of ecological processes; ensembles needed for good prediction. Closest analogue to us.
- **Infectious disease** (Horrocks, J., Bauch, C. T. (2020). Algorithmic discovery of dynamic models
  from infectious disease data. *Scientific Reports* 10:7061. https://doi.org/10.1038/s41598-020-63877-w):
  SINDy on measles, chickenpox and rubella case notifications recovered mass-action incidence and
  seasonal transmission; the measles model predicted an out-of-sample regime shift. Chickenpox
  over-fitted; rubella needed a spectral fit criterion. **Lesson: SIR-type compartments (stocks and
  flows) are discoverable from counts when the library is compartmental.**
- **Lynx-hare** (Fasel et al. 2022): E-SINDy recovers Lotka-Volterra-type models with uncertainty.
- **Yeast glycolysis and metabolic networks** (Schmidt et al. 2011; Daniels and Nemenman 2015):
  partial recovery; hidden variables handled by hierarchy.
- **Reaction mechanisms** (Hoffmann et al. 2019; Ji and Deng 2021): biochemical and combustion
  pathways from concentration data, mostly simulated with realistic noise.
- **Fluids and plasmas** (Loiseau and Brunton 2018; Kaptanoglu et al. 2021): reduced-order models
  with constraints from high-quality simulation data.
- **Ecological hybrid systems** (Messenger et al. 2024): spongy moth epizootic equations from
  intermittent data via weak form.
- **Astrophysics** (Cranmer et al. 2020; Lemos, P., Jeffrey, N., Cranmer, M., Ho, S., Battaglia, P.
  (2023). Rediscovering orbital mechanics with machine learning. *Mach. Learn.: Sci. Technol.*
  4:045002. https://doi.org/10.1088/2632-2153/acfa63): GNN + SR on structured problems.
- **SD-specific**: covered in the tools survey (Abdelbari and Shafi; ISDC 2026 abstracts); all
  small textbook models.

Common factors in every success: a **domain-shaped library** (compartmental, mass action, process
templates), **conservation or symmetry built in**, **validation by simulation/forecast** rather than
derivative fit, and a human choosing among a short list.

---

## 9. Workflow: how this tradition says to proceed

A pipeline for SD Lab assembled from the tradition's best practices, each step marked with what we
already have.

1. **Declare the library (process grammar).** Generic flows × rate templates × constraints, in data;
   units checked by attribute rules (ProGED); optional prior weights per template (from LLM priors or
   the modeller). *Have: hard-coded forms and pruning rules. Add: effect templates
   (`prop(src) × C`, `prop(src) × C/(C+K)` on a K grid, `prop(src) × table(C)` linear in knots),
   co-flow templates, and declarative constraints.*
2. **Build regressors exactly, no smoothing.** Δx_t per step; regressors at x_t; windows only as
   exact sums. Mark steps where a stock hit 0 or its cap as censored for the outflows of that stock.
   *Have: windows. Add: censoring.*
3. **Screen with both moments.** Drift: per-row residual correlation (have). Diffusion: covariance
   of one-step changes between stock pairs, conditional on level bins (add). A move A→B needs both
   a mirrored mean and a negative covariance; an outside pair needs only the first.
4. **Select sparsely with constraints and groups.** Flow-level (group) selection; non-negative
   proportional coefficients; per-era coefficients with shared support (SGTR); GLS weights from the
   linear-noise covariance. Options: current stepwise BIC; group-ARD/SBL; MIOSR/MILP for small
   groups (exact); FROLS. *Have: stepwise BIC + priors.*
5. **Bag it.** Block bootstrap → inclusion probabilities, coefficient intervals, alternatives.
   Automatic threshold via stability (PDE-STRIDE). *Add.*
6. **Propose hidden stocks hierarchically.** Delay-coordinate candidates (have); accept one hidden
   stock at a time by evidence (Daniels-Nemenman order); then refit it as a simulated state.
7. **Shortlist → refine by multiple shooting.** Take the Pareto front / top-K from steps 4-6, refit
   each by segment-wise simulation error with floors and caps; stability check of the linearisation;
   reject runaways. *Partly have (output-error topic).*
8. **Distil effects.** Optional UDE pass for remaining systematic residual on a flow; snap to an
   effect template; re-run step 4 so the new term competes fairly.
9. **Validate as the field does.** Held-out skill@H on later data and on bagged resamples; residual
   whiteness and Poisson variance checks per stock; report the structural alternatives that fit
   about as well and what experiment would separate them (Bongard-Lipson active probing).
10. **Benchmark hygiene.** One hyperparameter setting for all examples; noise and length sweeps; a
    procedural SD generator for generalisation; record structure accuracy and skill separately.

**What the tradition warns against.** Free-form symbolic search over whole models (noise-fragile,
slow, unidentifiable at our data sizes); trusting one-step fit for selection; smoothing count data;
per-example tuning; neural terms without distillation; autoencoder latent coordinates as "hidden
stocks".

---

## 10. Reading list (priority order)

**Read first (closest to our problem).**
1. Bridewell, Langley, Todorovski, Džeroski (2008). Inductive process modeling. *Machine Learning*
   71:1-32. https://doi.org/10.1007/s10994-007-5042-6
2. Langley, Arvay (2015). Heuristic induction of rate-based process models. *AAAI 2015*.
   https://ojs.aaai.org/index.php/AAAI/article/view/9219
3. Hoffmann, Fröhner, Noé (2019). Reactive SINDy. *J. Chem. Phys.* 150:025101.
   https://doi.org/10.1063/1.5066099
4. Callaham, Loiseau, Rigas, Brunton (2021). Langevin regression. *Proc. R. Soc. A* 477:20210092.
   https://doi.org/10.1098/rspa.2021.0092; with Fearnhead, Giagos, Sherlock (2014), LNA inference,
   *Biometrics* 70:457. https://doi.org/10.1111/biom.12152
5. Fasel, Kutz, Brunton, Brunton (2022). Ensemble-SINDy. *Proc. R. Soc. A* 478:20210904.
   https://doi.org/10.1098/rspa.2021.0904
6. Mangan, Kutz, Brunton, Proctor (2017). Model selection via sparse regression and information
   criteria. *Proc. R. Soc. A* 473:20170009. https://doi.org/10.1098/rspa.2017.0009
7. Čerepnalkoski et al. (2012). Parameter fitting methods and structure selection. *Ecological
   Modelling* 245:136-165. https://doi.org/10.1016/j.ecolmodel.2012.06.001
8. Horrocks, Bauch (2020). Algorithmic discovery of dynamic models from infectious disease data.
   *Sci. Rep.* 10:7061. https://doi.org/10.1038/s41598-020-63877-w

**Then (specific techniques).**
9. Brunton, Proctor, Kutz (2016). SINDy. *PNAS* 113:3932. https://doi.org/10.1073/pnas.1517384113
10. Rudy, Alla, Brunton, Kutz (2019). Data-driven identification of parametric partial differential
    equations. *SIAM J. Appl. Dyn. Syst.* 18(2):643-660. https://doi.org/10.1137/18M1191944 (SGTR:
    group sparsity across eras.)
11. Daniels, Nemenman (2015). Automated adaptive inference of phenomenological dynamical models.
    *Nat. Commun.* 6:8133. https://doi.org/10.1038/ncomms9133
12. Willis, von Stosch (2016). Reaction network inference by MILP. *Comput. Chem. Eng.* 90:31.
    https://doi.org/10.1016/j.compchemeng.2016.04.019
13. Ramsay, Hooker, Campbell, Cao (2007). Generalized smoothing. *JRSS-B* 69:741.
    https://doi.org/10.1111/j.1467-9868.2007.00610.x
14. Rackauckas et al. (2020). Universal differential equations. https://arxiv.org/abs/2001.04385
15. Hirsh, Barajas-Solano, Kutz (2022). Sparsifying priors. *R. Soc. Open Sci.* 9:211823.
    https://doi.org/10.1098/rsos.211823
16. Omejc et al. (2024). ProGED for coarse, noisy, partial data. *Machine Learning* 113.
    https://doi.org/10.1007/s10994-024-06522-1
17. Kaptanoglu et al. (2021). Trapping SINDy (stability). *Phys. Rev. Fluids* 6:094401.
    https://doi.org/10.1103/PhysRevFluids.6.094401
18. Mangan et al. (2019). Hybrid-SINDy. *Proc. R. Soc. A* 475:20180534.
    https://doi.org/10.1098/rspa.2018.0534
19. Bortz, Messenger, Dukic (2023). WENDy. *Bull. Math. Biol.* 85:110.
    https://doi.org/10.1007/s11538-023-01208-6 (only if real data with measurement noise arrives)

**Background and benchmarks.**
20. Schmidt, Lipson (2009). *Science* 324:81. https://doi.org/10.1126/science.1165893
21. Bongard, Lipson (2007). *PNAS* 104:9943. https://doi.org/10.1073/pnas.0609476104
22. La Cava et al. (2021). SRBench. https://arxiv.org/abs/2107.14351
23. d'Ascoli et al. (2024). ODEFormer / ODEBench. https://arxiv.org/abs/2310.05573
24. Kaptanoglu, Zhang, Nicolaou, Fasel, Brunton (2023). Benchmarking sparse system identification
    with low-dimensional chaos. https://arxiv.org/abs/2302.10787
25. Egan, Li, Carvalho (2024). ARGOS. *Commun. Phys.* 7:20. https://doi.org/10.1038/s42005-023-01516-2
26. Ji, Deng (2021). CRNN. *J. Phys. Chem. A* 125:1082. https://doi.org/10.1021/acs.jpca.0c09316
27. Hoedt et al. (2021). MC-LSTM. https://arxiv.org/abs/2101.05186
28. Cranmer et al. (2020). Symbolic models from deep learning. https://arxiv.org/abs/2006.11287
29. Langley (1981). BACON. *Cognitive Science* 5:31. https://doi.org/10.1207/s15516709cog0501_4
30. Džeroski, Todorovski (1995). Discovering dynamics. *J. Intell. Inf. Syst.* 4:89.
    https://doi.org/10.1007/BF00962824

*Citation note:* bibliographic details were checked against publisher or arXiv records for the
items most load-bearing here (ODEFormer/ODEBench, ARGOS, Bayesian-ARGOS, RPM/FPM, ProGED 2024,
ProBMoT 2012, CRNN, Messenger et al. 2024, Horrocks and Bauch 2020); the rest are from standard
references and should be spot-checked before being quoted in a paper. The Kaptanoglu et al. (2023)
venue is given as Nonlinear Dynamics from memory; the arXiv record is certain.
