# Neighbouring fields: compartmental and network models identified from data

Part of the literature chain for SD Lab discovery. This document covers one tradition: fields that
solve almost exactly our problem under other names. These are compartmental analysis and
pharmacokinetics, epidemic models fitted to case counts, chemical reaction networks, population
ecology, conceptual hydrology, queueing networks and network tomography, and inventory systems.
For what we already do, see [../../DISCOVERY.md](../../DISCOVERY.md). For the tools already
surveyed (PySINDy, Reactive SINDy, Kalman/EM, PELT, Tigramite, ...), see
[../SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md). This document does not repeat them.

Our problem in their words: a **linear (or mildly nonlinear) compartmental system with fully
observed compartments, a few unobserved ones, an unobserved environment compartment, discrete
time, Poisson/binomial demographic noise, piecewise-constant exogenous inputs, known
interventions, and nonnegativity/capacity constraints**. Every field below has studied some subset
of that.

---

## Summary (ranked by expected value for the engine)

1. **Report indistinguishability classes, then pick a canonical member.** Compartmental analysis
   proved long ago that different structures can give identical outputs. Examples: the
   Godfrey-Chapman rules; DISTING lists 2, 3 and 5 equivalent models for small 2-, 3- and
   4-compartment examples. Reaction-network theory showed that different reaction graphs can give
   *identical ODEs* (Craciun-Pantea; Szederkényi et al. found that "a unique topology cannot be
   determined even if all variables are measured"). Sparsity alone does not pick the truth. We
   should **enumerate the equivalent rewrites of a found structure** (a move vs out+in, a series vs
   parallel hidden path, where a loss leaves a hidden chain) and choose by an explicit
   tie-break: fewest outside flows, fewest hidden stocks. We should not let BIC noise decide. Our
   skill metric already accepts any member.
2. **Use the exact discrete-step count likelihood: binomial thinning plus multinomial splitting
   (Euler-multinomial).** Epidemiology (pomp's `reulermultinom`; Bretó et al. 2009) and
   integer-valued time series (INAR(1), Al-Osh & Alzaid 1987) model one step of a stock with
   proportional drains *exactly as our simulator does*. The model is leavers ~ Binomial(X, 1−e^{−KΔt}),
   split among destinations by k_j/K, plus Poisson inflow. It gives the right variance (∝ X, not
   constant) and the **negative covariance between source and target** of every move for free.
   Its Gaussian version is the linear noise approximation (LNA) used in reaction-network inference:
   covariance S·diag(q)·Sᵀ. This is the principled form of our "jitter weights" and "shared noise"
   ideas.
3. **Second moments identify flows that means cannot.** Network tomography (Vardi 1996) proved
   that Poisson origin-destination flows are identifiable from link counts *only because* of
   their covariances. Reactmine (Martinelli et al. 2022) finds reactions by grouping transitions
   whose concentration changes share a fixed ratio. Both support our co-flow / "mirror"
   evidence. Make the **covariance of the per-step changes** a first-class score term in the
   search, not a tie-breaker.
4. **Hidden stocks are transit compartments: estimate their number and mean time, and expect only
   the mean to be well identified.** Pharmacometrics (Savic et al. 2007 transit absorption; Sun &
   Jusko 1998), epidemiology (the linear chain trick, Hurtado & Kirosingh 2019) and hydrology
   (Young's data-based mechanistic modelling: transfer-function order, then a series/parallel tank
   interpretation) all model unobserved delays as Erlang chains. The mean residence time is
   robust. The shape (number of tanks) is weakly identified. Series vs parallel arrangements are
   often indistinguishable. Pharmpy AMD on simulated truth recovered distribution and elimination
   but **missed absorption (the hidden delay) more often**, which is exactly our failure pattern.
5. **Search over a component grammar, judge by simulation.** Hydrology's FUSE (79 structures
   built from parts of four models), SUPERFLEX and MARRMoT, and pharmacometrics' Pharmpy AMD and
   pyDarwin (a genetic algorithm over NONMEM structures), all treat structure as a
   combination of standard parts, fit each candidate, and select by an information criterion
   *plus* simulation diagnostics (visual predictive checks). They report that structure choice
   matters about as much as parameters, and that automatic tools **drift toward over-complex
   models** (Roche's AMD evaluation). Use multi-step simulation error as a guard against
   over-complexity at the end of the search.
6. **Treat unannounced changes as time-varying rates inside a filter, not only as inflow pieces.**
   Epidemiology fits transmission rates that change unannounced, using change points (Dehning et
   al. 2020) or a random walk on the log rate (Dureau et al. 2013), with particle filters / IF2
   (pomp). The same machinery handles hidden stocks with Poisson observations. It is the right
   **final refinement and judge** for hard examples, but it is slow and multimodal, so start it
   from our regression answer.
7. **Use gradient matching as the initialiser and trajectory/likelihood fitting as the arbiter.**
   Ecology's gLV regression on log-differences (Stein et al. 2013; MDSINE) and the CRN "global
   model then statistical reduction" approach (Burnham et al. 2008) are our current method. Their
   documented failure is bias under noise and sparse sampling, which made MDSINE and its successors
   move to Bayesian trajectory models. Expect regression-selected structures to need a
   simulation-based refit (already noted in our output-error topic).
8. **Learn drain laws from quiet periods, and treat floors and caps as censoring.** Kirchner (2009)
   identifies a catchment's storage-discharge law from recession periods, when input is near zero,
   then *inverts* it to recover the unmeasured input ("hydrology backwards"). Inventory theory
   treats sales capped by stock as **censored demand** (Lariviere & Porteus 1999). Both are direct
   templates. Fit rate laws on windows without inflow or constraints, estimate unknown inflow as the
   inverted residual, and use a censored likelihood on steps where a floor or cap binds.
9. **Use practical identifiability to collapse structure the data cannot support.** Profile
   likelihood (Raue et al. 2009), sloppiness (Gutenkunst et al. 2007) and the manifold boundary
   approximation (Transtrum & Qiu 2014) show that many fitted parameters are unidentifiable from
   finite data. MBAM's model reductions are literally "this delay goes to zero, merge these two
   compartments". This gives a test for hidden stocks and effects: **if a flat profile's limit is
   a simpler model, take the simpler model**.
10. **Do not trust equifinal ensembles built with informal likelihoods, and do not fit cumulative
    counts.** GLUE (Beven & Binley 1992) made equifinality mainstream, but its thresholded
    "behavioural" sets are criticised for arbitrary, overconfident uncertainty. King et al. (2015)
    showed that fitting cumulative case counts gives badly overconfident, biased estimates. Our
    windowed sums of *changes* are safe. Any future least-squares fit of *levels*, or any "fits about
    as well" ensemble, must use a proper likelihood on increments.

---

## 0. How each field maps onto ours

| Our term | Compartmental / PK | Epidemiology | Reaction networks | Ecology | Hydrology | Queueing / tomography | Inventory |
|---|---|---|---|---|---|---|---|
| stock | compartment | S, I, R class | species | population | storage (tank) | queue length | on-hand, WIP, supply line |
| flow between stocks | transfer k_ij | transition (infection, recovery) | reaction with stoichiometry | predation, conversion | percolation, routing | routing between nodes | shipments, orders |
| outside | environment, "compartment 0" | births, deaths, import | inflow/outflow (CSTR) | immigration | rain, evaporation, outflow | external arrivals/departures | demand, supplier |
| proportional drain | first-order elimination | per-capita rate | first-order reaction | mortality | linear reservoir Q = S/k | infinite-server queue | lead-time delay |
| gap form | indirect response toward baseline | — | reversible reaction to equilibrium | logistic | — | — | order-up-to / anchoring and adjustment |
| effect (stock level × rate) | Michaelis-Menten, Emax | mass action βSI/N | mass action | Holling responses, gLV interaction | nonlinear reservoir Q = aS^b | load-dependent service | stock-out effects |
| hidden stock | unsampled peripheral / transit compartment | latent (E) class | intermediate complex | unobserved stage/species | groundwater store | in-service jobs | pipeline / in-transit |
| co-flow | — | — | multi-product stoichiometry | biomass conversion | — | fork/join | bill of materials |
| announced era | dosing regime, occasion | intervention date | perturbation experiment | antibiotic/diet pulse | land-use change | config change | policy change |
| unannounced input change | — | importation pulse, R_t change | — | environmental forcing | unmeasured rain | load shift | demand shift |
| floor / cap | — | — | — | — | storage capacity, threshold | finite buffer, blocking | stock-out, capacity |
| counting noise | — | demographic stochasticity, reporting | intrinsic noise (CME) | demographic noise | — | Poisson arrivals | Poisson demand |

---

## 1. Compartmental analysis and structural identifiability

### What they share with us
A linear compartmental system is ẋ = A x + B u with A a compartmental matrix: off-diagonals ≥ 0
are transfers, diagonals are minus total outflow, and column sums ≤ 0 give conservation, with the
excess going to the environment. This is our model with proportional flows, exactly. The classic
texts are Jacquez, *Compartmental Analysis in Biology and Medicine* (3rd ed., BioMedware 1996),
Godfrey, *Compartmental Models and Their Application* (Academic Press 1983), and Anderson,
*Compartmental Modeling and Tracer Kinetics* (Lecture Notes in Biomathematics 50, Springer 1983,
[doi:10.1007/978-3-642-51861-4](https://doi.org/10.1007/978-3-642-51861-4)). The qualitative theory
(nonnegativity, stability, no oscillation in linear compartmental systems with symmetric-like
structure) is reviewed by Jacquez & Simon, *SIAM Review* 35(1):43-79, 1993
([doi:10.1137/1035003](https://doi.org/10.1137/1035003)).

### Identifiability: the core results
- **Structural identifiability** asks whether the parameters can be determined from perfect
  input-output data. The concept and the first test (Laplace transform / transfer-function
  coefficients) are in Bellman & Åström, *Math. Biosci.* 7:329-339, 1970
  ([doi:10.1016/0025-5564(70)90132-X](https://doi.org/10.1016/0025-5564(70)90132-X)). Cobelli &
  DiStefano made it systematic for physiology: *Am. J. Physiol.* 239:R7-R24, 1980
  ([doi:10.1152/ajpregu.1980.239.1.R7](https://doi.org/10.1152/ajpregu.1980.239.1.R7)).
- **What to do when unidentifiable**: reparameterise to identifiable combinations, or add
  measurements and inputs. See Walter & Lecourtier, "Unidentifiable compartmental models: what to
  do?", *Math. Biosci.* 56:1-25, 1981
  ([doi:10.1016/0025-5564(81)90025-0](https://doi.org/10.1016/0025-5564(81)90025-0)).
- **Graph results for linear models**. Meshkat, Sullivant & Eisenberg, *Bull. Math. Biol.* 77,
  2015 ([doi:10.1007/s11538-015-0098-0](https://doi.org/10.1007/s11538-015-0098-0)) and the later
  arXiv line (e.g. [arXiv 1910.13549](https://arxiv.org/abs/1910.13549),
  [2102.04417](https://arxiv.org/abs/2102.04417)) characterise identifiability from the graph:
  cycles, leaks, and where inputs and outputs sit. Rule of thumb from this line: **more than one
  leak to the environment in an unobserved part of the graph usually breaks identifiability**.
- **Indistinguishability**: two *structures* that produce the same outputs for all inputs.
  Godfrey & Chapman, "Identifiability and indistinguishability of linear compartmental models",
  *Math. Comput. Simul.* 32(3):273-295, 1990
  ([doi:10.1016/0378-4754(90)90185-L](https://doi.org/10.1016/0378-4754(90)90185-L)), give
  necessary geometric rules. For example, the shortest path length from each input compartment to
  each output compartment is preserved, as are the number of compartments reachable from inputs and
  the number that reach outputs. **DISTING** (Davidson, Godfrey, Alquaddoomi, Nola & DiStefano,
  *Comput. Methods Programs Biomed.* 143:129-135, 2017,
  [doi:10.1016/j.cmpb.2017.02.025](https://doi.org/10.1016/j.cmpb.2017.02.025),
  [PDF](https://qcb.ucla.edu/wp-content/uploads/sites/14/2021/01/DISTING-CMPB-Paper.pdf)) computes
  the indistinguishable alternatives. For its 2-, 3- and 4-compartment test models it finds 2, 3
  and 5 alternatives. Recent graph-based sufficient conditions:
  [arXiv 2309.10861](https://arxiv.org/abs/2309.10861), [arXiv 2412.01135](https://arxiv.org/abs/2412.01135).

### Software
- **DAISY** (differential algebra; Bellu, Saccomani, Audoly & D'Angiò, *Comput. Methods Programs
  Biomed.* 88:52-61, 2007, [doi:10.1016/j.cmpb.2007.07.002](https://doi.org/10.1016/j.cmpb.2007.07.002)).
- **SIAN** (global identifiability, randomised; Hong, Ovchinnikov, Pogudin & Yap, *Bioinformatics*
  35(16):2873-2874, 2019, [arXiv 1812.10180](https://arxiv.org/abs/1812.10180); Maple and Julia).
- **StructuralIdentifiability.jl** (Dong, Goodbrake, Harrington & Pogudin, *SIAM J. Appl. Algebra
  Geom.* 7(1):194-235, 2023, [arXiv 2111.00991](https://arxiv.org/abs/2111.00991);
  [GitHub](https://github.com/SciML/StructuralIdentifiability.jl)). It is local and global and
  returns the *identifiable combinations*, which is the useful output for us.
- **STRIKE-GOLDD** (MATLAB; Villaverde, Barreiro & Papachristodoulou, *PLoS Comput. Biol.*
  12(11):e1005153, 2016, [doi:10.1371/journal.pcbi.1005153](https://doi.org/10.1371/journal.pcbi.1005153)).
- **DISTING** (web app; above).

### What this means for us
- **Our measured stocks are fully observed.** With full-state observation and persistent
  excitation, the matrix A of a linear compartmental system is identifiable (it is a regression of
  x_{t+1} on x_t). So our *structural* problems are concentrated in three places:
  1. **The environment is an unobserved compartment.** "A → B" and "A → outside plus outside → B"
     have identical *means* whenever B's inflow from outside can mimic k·A. That happens when A is
     nearly constant in a window. Only second moments (covariance) or variation in A separate them.
  2. **Hidden stocks** are unobserved compartments. The Godfrey-Chapman and graph results apply
     directly: a hidden chain between A and B with a leak from the hidden part is generally not
     identifiable (the leak trades off against the ratio and delay), and series vs parallel
     hidden paths can be indistinguishable.
  3. **Practical identifiability** (finite, noisy, weakly excited data) is where most of our
     failures live; see section 2 and the sloppiness results.
- **Transferable step (post-search):** generate the *equivalence neighbourhood* of the found
  structure with local rewrites known to preserve outputs:
  - move ↔ out+in when the source is near-constant;
  - hidden chain series ↔ parallel;
  - leak placement within a hidden chain;
  - ratio ↔ rate rescaling for a hidden stock with unknown units.

  Refit each rewrite, then (a) report the class, and (b) choose the member by a declared preference
  order, not by tiny BIC gaps. A symbolic check of small hidden-stock motifs with
  StructuralIdentifiability.jl, done once offline, would tell us which motifs to even offer. For
  example: is "A → H → B, H → out" identifiable from A and B? (Generally the H → out leak is
  confounded with the A → H rate unless B's inflow has its own scale.)

---

## 2. Pharmacokinetics / pharmacodynamics and pharmacometric model selection

### What they share with us
Choosing the number of compartments, where elimination happens, whether absorption has a delay
(transit compartments), and whether a drug effect multiplies a production or loss rate (indirect
response models). The data are sparse and noisy, and the model is selected from a finite family.

### Methods that work
- **Information criteria for compartment number**, since Yamaoka, Nakagawa & Uno, *J.
  Pharmacokinet. Biopharm.* 6:165-175, 1978
  ([doi:10.1007/BF01117450](https://doi.org/10.1007/BF01117450)), which introduced AIC to PK.
- **NONMEM practice** (population nonlinear mixed effects; Beal & Sheiner). Structural model
  first (1 vs 2 vs 3 compartments; first-order vs zero-order vs transit absorption; linear vs
  Michaelis-Menten elimination), then variability, then covariates by stepwise forward
  inclusion / backward elimination with likelihood-ratio tests (the "SCM" procedure in PsN).
- **Transit compartments for hidden delays**: Sun & Jusko, *J. Pharm. Sci.* 87(6):732-737, 1998
  ([doi:10.1021/js970414z](https://doi.org/10.1021/js970414z)); Savic, Jonker, Kerbusch &
  Karlsson, *J. Pharmacokinet. Pharmacodyn.* 34:711-726, 2007
  ([doi:10.1007/s10928-007-9066-0](https://doi.org/10.1007/s10928-007-9066-0)). Savic estimates
  the *number* of transit compartments as a continuous parameter (via a gamma-function form) and
  the mean transit time. They found it more stable and better fitting than a lag time. **This is
  the exact model for our "delayed copy" hidden stocks.**
- **Indirect response models** (Dayneka, Garg & Jusko, *J. Pharmacokinet. Biopharm.* 21:457-478,
  1993, [doi:10.1007/BF01061691](https://doi.org/10.1007/BF01061691)) are four models in which a
  driver's level stimulates or inhibits the *production* or the *loss* of a response stock through
  an Emax/Imax factor. **This is precisely SD's multiplicative effect of a stock's level on a
  flow**, in two placements (inflow vs outflow) and two directions. The pharmacometric practice is
  to fit all four and compare. The placements are often confused unless the response's own
  turnover is well excited.
- **Simulation-based diagnostics** (visual predictive checks). Bergstrand, Hooker, Wallin &
  Karlsson, *AAPS J.* 13:143-151, 2011
  ([doi:10.1208/s12248-011-9255-z](https://doi.org/10.1208/s12248-011-9255-z)). A model is
  accepted only if data simulated from it bracket the observed data. This is our skill@H in spirit.
- **Automated structure search**:
  - Genetic algorithm over NONMEM model features: Bies et al., *J. Pharmacokinet. Pharmacodyn.*
    33:195-221, 2006 ([doi:10.1007/s10928-006-9004-6](https://doi.org/10.1007/s10928-006-9004-6)),
    now productised as **pyDarwin** (Certara, Python, open source).
  - **Pharmpy AMD** (Python, open source; Chen et al., *CPT Pharmacometrics Syst. Pharmacol.*
    13(10):1784-1797, 2024, [doi:10.1002/psp4.13222](https://doi.org/10.1002/psp4.13222)). It runs
    modules for structure, then IIV, IOV, residual error and covariates, and selects by BIC. On 10
    real datasets its final models had lower BIC than the published ones. A simulation evaluation
    against 10 known true models (Duvnjak et al., *CPT PSP* 13(10):1707-1721, 2024,
    [doi:10.1002/psp4.13213](https://doi.org/10.1002/psp4.13213)) found that **distribution and
    elimination were recovered well, absorption less so**. A Roche real-data evaluation (PAGE 2024
    abstract) reported a **trend toward more complex models** than human modellers chose.

### Lessons on identifiability and equifinality
- With output measured only in plasma, peripheral compartments are interchangeable
  (the DISTING examples are PK models). For us: hidden stocks hanging off one measured stock.
- Lag time vs transit chain vs a slow extra compartment all fit absorption data. Transit chains
  win on stability because they are *smooth* in their parameters; a hard lag is not.
- **Stepwise covariate modelling inflates false inclusions.** This is well known in the field, and
  the usual answer is a stricter backward elimination (p < 0.001) after a looser forward step
  (p < 0.05). This mirrors our add-then-tidy search, and suggests our tidy step should be
  *stricter* than our add step.

### Transferable steps
- Hidden stock candidate = **Erlang/transit chain with (n, mean time)**, n chosen from {1, 2, 3,
  4} or continuous, as one candidate family. Report the mean time as the finding. Treat n as soft.
- Effects: try the **four indirect-response placements** (stimulate or inhibit, inflow or outflow
  of the affected stock) for each candidate driver, with an Emax-style saturating form as well as
  linear.
- Search: forward with a looser gate, **backward with a stricter one**; final acceptance by a
  simulation check.

### Implementations
NONMEM (commercial), Monolix (commercial), nlmixr2 (R, open), **Pharmpy** (Python, open; has
model-search tools), **pyDarwin** (Python, open; GA, Gaussian-process and random-forest Bayesian
optimisation over a model-feature grid), PsN (Perl; SCM, VPC).

### Failure modes
Over-complex models from automatic search; absorption/delay misidentified; local optima in
nonlinear mixed-effects fits that make structural comparison noisy (a worse structure "wins"
because the better one's fit did not converge). For us, the last point means **refit every
candidate from several starts before comparing**.

---

## 3. Epidemic compartmental models fitted to counts

### What they share with us
SIR-family models are SD models: stocks of people, flows between them, mass-action effects (the
infection flow is β·S·I/N, a flow whose rate depends on another stock's level), hidden stocks
(exposed, unreported), counting noise, unannounced changes in rates (behaviour), announced
interventions (lockdown dates), and discrete-time simulation.

### Methods that work
- **Plug-and-play likelihood inference on partially observed Markov processes**: the model is
  only *simulated*, never differentiated.
  - Particle filter likelihoods; iterated filtering **IF2**: Ionides, Nguyen, Atchadé, Stoev &
    King, *PNAS* 112(3):719-724, 2015
    ([doi:10.1073/pnas.1410597112](https://doi.org/10.1073/pnas.1410597112)).
  - Particle MCMC: Andrieu, Doucet & Holenstein, *JRSS B* 72:269-342, 2010
    ([doi:10.1111/j.1467-9868.2009.00736.x](https://doi.org/10.1111/j.1467-9868.2009.00736.x)).
  - The R package **pomp**: King, Nguyen & Ionides, *J. Stat. Softw.* 69(12), 2016
    ([doi:10.18637/jss.v069.i12](https://doi.org/10.18637/jss.v069.i12)).
  - The landmark application to measles: He, Ionides & King, *J. R. Soc. Interface* 7:271-283,
    2010 ([doi:10.1098/rsif.2009.0151](https://doi.org/10.1098/rsif.2009.0151)).
- **Euler-multinomial process model with gamma noise on rates**: Bretó, He, Ionides & King,
  *Ann. Appl. Stat.* 3(1):319-348, 2009
  ([doi:10.1214/08-AOAS201](https://doi.org/10.1214/08-AOAS201)). In each step, each compartment
  loses Binomial(X, 1−exp(−ΣkΔt)) members, split multinomially among destinations. Multiplicative
  gamma white noise on rates adds overdispersion while keeping conservation exact. **This is the
  process model of our ground truth.**
- **Change points in transmission**: Dehning et al., *Science* 369:eabb9789, 2020
  ([doi:10.1126/science.abb9789](https://doi.org/10.1126/science.abb9789)) fit an SIR model with
  a few change points in the spreading rate (with priors on their dates) by Bayesian MCMC (PyMC).
  Change-point models were compared by LOO. **Random-walk rates**: Dureau, Kalogeropoulos &
  Baguelin, *Biostatistics* 14(3):541-555, 2013
  ([doi:10.1093/biostatistics/kxs052](https://doi.org/10.1093/biostatistics/kxs052)). **R_t
  estimation** from incidence counts: Cori et al., *Am. J. Epidemiol.* 178(9):1505-1512, 2013
  ([doi:10.1093/aje/kwt133](https://doi.org/10.1093/aje/kwt133)), EpiEstim.
- **Linear chain trick** for hidden stages: Hurtado & Kirosingh, *J. Math. Biol.* 79:1831-1883,
  2019 ([doi:10.1007/s00285-019-01412-w](https://doi.org/10.1007/s00285-019-01412-w)). Erlang (and
  more general phase-type) dwell times become chains of identical compartments. Wearing, Rohani &
  Keeling, *PLoS Med.* 2(7):e174, 2005
  ([doi:10.1371/journal.pmed.0020174](https://doi.org/10.1371/journal.pmed.0020174)), showed that
  exponential vs gamma latent periods change estimated parameters and intervention conclusions:
  **the shape of a hidden delay matters for dynamics even when it is weakly identified**.

### Identifiability lessons
- Tuncer & Le, *Math. Biosci.* 299:1-18, 2018
  ([doi:10.1016/j.mbs.2018.02.004](https://doi.org/10.1016/j.mbs.2018.02.004)): SEIR-type models
  fitted to one observed stream are often only partially identifiable. The reporting fraction and
  the transmission rate trade off, and so do the latent period and infectious period.
- King, Domenech de Cellès, Magpantay & Rohani, "Avoidable errors in the modelling of outbreaks
  of emerging pathogens", *Proc. R. Soc. B* 282:20150347, 2015
  ([doi:10.1098/rspb.2015.0347](https://doi.org/10.1098/rspb.2015.0347)). Fitting **cumulative
  counts** by least squares gives badly overconfident, biased estimates, and deterministic models
  understate uncertainty. Fit increments with a process-noise-aware likelihood.
- Funk & King, "Choices and trade-offs in inference with infectious disease models", *Epidemics*
  30:100383, 2020 ([doi:10.1016/j.epidem.2019.100383](https://doi.org/10.1016/j.epidem.2019.100383)).
  A practical map of when to use deterministic vs stochastic models and which inference to use.
- **Time-varying rates absorb structural error.** A free random-walk β will "explain" any
  misspecification (a missing compartment shows up as a wiggling β). Penalise or limit the number
  of change points, as Dehning did.

### Transferable steps
- **Likelihood**: replace weighted least squares in the judge (and eventually in the search) with
  the Euler-multinomial / binomial-thinning likelihood. It is cheap for fully observed stocks
  because every transition count is *nearly* determined by the level changes. Its Gaussian
  approximation (mean S·q, covariance S·diag(q)·Sᵀ) is a GLS step.
- **Unannounced changes**: let PELT also propose change points in *internal rates* (a flow's k),
  not only in outside inflows, with a BIC price per change. Test that a change point is not
  standing in for a missing structure: a structure fix should remove the need for the change point.
- **Hidden stocks**: final refinement by particle filter / IF2 with the hidden stock as a latent
  state. Use it only for the top few candidate structures; it is too slow for the search.

### Implementations
pomp, panelPomp, spatPomp (R); **particles** (N. Chopin's Python SMC library); PyMC and Stan for
change-point SIR; EpiEstim (R); Python ports of IF2 exist but are less mature than pomp.

### Failure modes
Particle filter likelihoods are noisy, so comparing structures needs many particles or replicate
runs. IF2 is multimodal and needs a global search over starting values. Deterministic-skeleton fits
to cumulative data are overconfident. Change-point counts can grow unchecked without a penalty.

---

## 4. Chemical reaction network (CRN) inference

### What they share with us
A reaction is a flow with a stoichiometric vector; conservation laws are left null vectors of the
stoichiometric matrix S; mass-action kinetics is our proportional form, and bimolecular mass action
is an effect. The CRN literature is the closest *formal* match to "which stocks exchange material,
and at what ratio". Reactive SINDy and the likelihood-based count methods are already in
[../SD-TOOLS-AND-DISCOVERY.md](../SD-TOOLS-AND-DISCOVERY.md) section 3.2. What follows adds to it.

### Methods that work
- **Global model, then statistical reduction**: Burnham, Searson, Willis & Wright, "Inference of
  chemical reaction networks", *Chem. Eng. Sci.* 63(4):862-873, 2008
  ([doi:10.1016/j.ces.2007.10.010](https://doi.org/10.1016/j.ces.2007.10.010)). Write one ODE model
  containing every admissible reaction, estimate by linear regression on rates, then prune with
  statistical tests. This is our approach in reverse (backward rather than forward).
- **Reactmine**: Martinelli, Grignard, Soliman, Ballesta & Fages, [arXiv
  2209.03185](https://arxiv.org/abs/2209.03185), 2022/23; code at gitlab.inria.fr/julmarti/crninf.
  It adds reactions one at a time in a bounded-depth search tree. Candidates are ranked by how
  *constant* their implied kinetics are on the transitions that support them, which works because
  a reaction's signature is co-varying changes in fixed stoichiometric ratios. Kinetic parameters
  are then re-optimised on the full trace. On simulated hidden networks it recovered the network
  "or an equivalent variant", where SINDy failed when all reactions were active at once. A
  successor (Reactmine-2, statistical beam search) was presented at SCML 2026. **Closest
  published algorithm to our search.** It supports beam search over our greedy search and a
  ratio-consistency screen for co-flows.
- **Linear noise approximation (LNA) likelihood**: Komorowski, Finkenstädt, Harper & Rand,
  *BMC Bioinformatics* 10:343, 2009 ([doi:10.1186/1471-2105-10-343](https://doi.org/10.1186/1471-2105-10-343));
  Fearnhead, Giagos & Sherlock, *Biometrics* 70:457-466, 2014
  ([doi:10.1111/biom.12152](https://doi.org/10.1111/biom.12152)). A Gaussian state-space model
  whose noise covariance is S·diag(propensities)·Sᵀ, filtered with a Kalman filter. Exact
  stochastic alternatives: particle MCMC for stochastic kinetic models (Golightly & Wilkinson,
  *Interface Focus* 1:807-820, 2011, [doi:10.1098/rsfs.2011.0047](https://doi.org/10.1098/rsfs.2011.0047)).
- **Rational kinetics (saturation)**: implicit-SINDy (Mangan, Brunton, Proctor & Kutz, *IEEE
  Trans. Mol. Biol. Multi-Scale Commun.* 2(1):52-63, 2016,
  [doi:10.1109/TMBMC.2016.2633265](https://doi.org/10.1109/TMBMC.2016.2633265)) finds
  Michaelis-Menten-type rates by rewriting the rational form as an implicit linear relation. This
  gives a linear-algebra route to saturating effects.
- **Bayesian network inference over kinetics**: Oates & Mukherjee, *Ann. Appl. Stat.* 6(3),
  2012 ([doi:10.1214/11-AOAS532](https://doi.org/10.1214/11-AOAS532)). Exact model averaging over
  parent sets with ODE-based likelihoods. A template for posterior inclusion probabilities per flow.

### Identifiability lessons (strong and directly relevant)
- **Different networks, identical ODEs.** Craciun & Pantea, "Identifiability of chemical reaction
  networks", *J. Math. Chem.* 44(1):244-259, 2008
  ([doi:10.1007/s10910-007-9307-x](https://doi.org/10.1007/s10910-007-9307-x)) give conditions
  under which the reaction graph and rate constants can be recovered from the mass-action ODEs.
  In general they cannot: distinct graphs can be *dynamically equivalent*.
- Szederkényi, Banga & Alonso, *BMC Syst. Biol.* 5:177, 2011
  ([doi:10.1186/1752-0509-5-177](https://doi.org/10.1186/1752-0509-5-177)): with LP/MILP
  formulations, they find that for literature networks **a unique topology cannot be determined
  even if the model structure is assumed known and all variables are measured**. They also find
  that sparsity-enforcing methods do not in general recover the "true" reactions. Toolbox:
  CRNreals (*Bioinformatics* 28(11):1549-1550, 2012). They compute the *sparsest* and *densest*
  dynamically equivalent realisations. **The sparsest/densest pair brackets the equivalence class:
  a cheap way to report "the structure is determined up to these flows".**
- The relevant SD case: a *flow* A → B with rate kA, versus a decay A → ∅ with rate kA plus
  creation ∅ → B with rate kA. These produce the same ODE (both are "reactions" in CRN terms).
  The difference shows up only in the *noise*: one event vs two independent events. This is the
  formal statement of our move-vs-outside ambiguity, and of why the shared-noise evidence is the
  only separator.

### Transferable steps
- **Ratio-consistency screen** (Reactmine-style). For every stock pair (and triple, for co-flows),
  check whether per-step changes co-vary at a constant ratio from {1, 2, 3, ½, ⅓}. Rank candidate
  flows by that consistency before the regression search.
- **Equivalence bracket**. After the search, solve two small LPs over the found structure's
  neighbourhood: the sparsest and densest structures that reproduce the fitted mean dynamics.
  Report the difference as the ambiguity set.
- **LNA / GLS likelihood** with covariance S·diag(q)·Sᵀ in the judge.

### Failure modes
Weak excitation (all reactions active together) defeats per-step regression. Sparsity picks *a*
member of the equivalence class, not *the* truth. Unconstrained rates go negative. Search cost
explodes with the number of species; bounded depth and beam width are needed.

---

## 5. Ecology: interaction networks from population time series

### What they share with us
Inferring who affects whom from abundance time series with demographic and sampling noise,
external perturbations (antibiotics, diet: announced eras), and unobserved species. The difference
is that ecological interactions are mostly *effects*, not conserved transfers. gLV has no
conservation, so ecology is our guide for the *effects* half of the problem.

### Methods that work
- **gLV by regression on log-differences** (gradient matching). For gLV, d log x_i/dt = r_i +
  Σ_j a_ij x_j + perturbation terms, which is linear in the parameters. Stein et al., *PLoS
  Comput. Biol.* 9(12):e1003388, 2013
  ([doi:10.1371/journal.pcbi.1003388](https://doi.org/10.1371/journal.pcbi.1003388)), with Tikhonov
  regularisation and cross-validation, on C. difficile mouse data. Fisher & Mehta's LIMITS
  (*PLoS ONE* 9(7):e102451, 2014, [doi:10.1371/journal.pone.0102451](https://doi.org/10.1371/journal.pone.0102451))
  uses sparse stepwise regression with bagging.
- **MDSINE**: Bucci et al., *Genome Biol.* 17:121, 2016
  ([doi:10.1186/s13059-016-0980-6](https://doi.org/10.1186/s13059-016-0980-6)). Bayesian variable
  selection over interactions, with perturbations as indicator inputs, smoothing of noisy
  trajectories, and a statement of which interactions are well supported (Bayes factors).
  **MDSINE2**: Gibson, Kim, Acharya, ... Gerber, *Nat. Microbiol.* 10:2550-2564, 2025
  ([doi:10.1038/s41564-025-02112-6](https://doi.org/10.1038/s41564-025-02112-6); code on GitHub,
  Python). It groups taxa into **interaction modules** that share interactions and perturbation
  responses, and models measurement noise and process stochasticity together. Scaling by modules
  matches our "groups".
- **Multivariate autoregressive (MAR) models** on log abundances: Ives, Dennis, Cottingham &
  Carpenter, *Ecol. Monogr.* 73(2):301-330, 2003. Interactions near equilibrium as a linear VAR,
  plus stability measures.
- **Empirical dynamic modelling (EDM)**:
  - **Convergent cross mapping** (Sugihara et al., *Science* 338:496-500, 2012,
    [doi:10.1126/science.1227079](https://doi.org/10.1126/science.1227079)).
  - Equation-free forecasting (Ye et al., *PNAS* 112(13):E1569-E1576, 2015,
    [doi:10.1073/pnas.1417063112](https://doi.org/10.1073/pnas.1417063112)).
  - **S-map Jacobians** that track time-varying interaction strengths (Deyle et al., *Proc. R.
    Soc. B* 283:20152258, 2016, [doi:10.1098/rspb.2015.2258](https://doi.org/10.1098/rspb.2015.2258)).

  Python: pyEDM; R: rEDM.
- **Synthetic likelihood** for noisy, chaotic population models (Wood, *Nature* 466:1102-1104,
  2010, [doi:10.1038/nature09319](https://doi.org/10.1038/nature09319)). Match summary statistics
  when the trajectory likelihood is too rough to optimise.

### Identifiability and equifinality lessons
- gLV is structurally identifiable with full observation (Remien, Eckwright & Ridenhour, *R. Soc.
  Open Sci.* 8:201378, 2021, [doi:10.1098/rsos.201378](https://doi.org/10.1098/rsos.201378)), but
  **practically** poorly identified near equilibrium. Near a fixed point only the Jacobian is
  visible, so many (r, A) pairs fit. Perturbations (our eras) are what make it work, so MDSINE
  designs around them.
- Gradient matching on log-differences is **biased** with noise and sparse sampling (log of noisy
  low counts; zeros). Comparisons of methods (e.g. Carrara et al., *Methods Ecol. Evol.* 6:895-906,
  2015, [doi:10.1111/2041-210X.12363](https://doi.org/10.1111/2041-210X.12363)) found
  performance depends heavily on noise and on how far the system is from equilibrium.
- CCM identifies coupling in weakly coupled deterministic systems but **fails under strong
  coupling (synchrony) and shared forcing**: it can report causality in the wrong direction. Our
  systems are strongly coupled by conservation and driven by shared inputs, so CCM is low value
  for us.

### Transferable steps
- **Effects as a per-capita regression.** For a flow suspected of an effect, regress its per-unit
  rate (flow / source level) on the candidate driver's level. This is gLV's trick applied to one
  flow. It is linear for a linear effect curve and gives a table-curve shape by binning.
- **Perturbation indicators**: announced eras enter as indicator inputs on rates (MDSINE), with
  the structure shared across eras. Our current design already does this; MDSINE is evidence that it
  works.
- **Modules**: when many stocks are similar, share coefficients within a module (a group lasso /
  clustering prior). This is the scaling path to hundreds of stocks.
- **Equilibrium warning**: if a run sits near steady state, report that effects and gaps are
  practically unidentifiable instead of returning a confident answer.

### Failure modes
Near-equilibrium data, log-of-zero issues, compositional (relative) data, over-regularisation, and
CCM's false positives under synchrony.

---

## 6. Hydrology: conceptual tank models, structure uncertainty and equifinality

### What they share with us
A catchment model is a small SD model of linear or nonlinear reservoirs in series and parallel,
driven by an input (rain) and an output (evaporation), with thresholds (floors and caps: a soil
store spills when full). Usually only one stock-derived outflow (streamflow) is measured. Hydrology
has the longest and most self-critical literature on *which structure* and *how many tanks*.

### Methods that work
- **Multi-model / flexible frameworks**:
  - **FUSE** (Clark et al., "Framework for Understanding Structural Errors", *WRR* 44:W00B02,
    2008, [doi:10.1029/2007WR006735](https://doi.org/10.1029/2007WR006735)) built 79 structures
    from components of four models. **Structure mattered about as much as parameters.**
  - **SUPERFLEX** (Fenicia, Kavetski & Savenije, *WRR* 47:W11510, 2011,
    [doi:10.1029/2010WR010174](https://doi.org/10.1029/2010WR010174); application: Kavetski &
    Fenicia, [doi:10.1029/2011WR010748](https://doi.org/10.1029/2011WR010748)). Python
    **superflexpy** (Dal Molin et al., *GMD* 14:7047-7072, 2021,
    [doi:10.5194/gmd-14-7047-2021](https://doi.org/10.5194/gmd-14-7047-2021)).
  - **MARRMoT** (Knoben et al., *GMD* 12:2463-2480, 2019,
    [doi:10.5194/gmd-12-2463-2019](https://doi.org/10.5194/gmd-12-2463-2019)), 46 conceptual
    structures in one framework, MATLAB/Octave.

  All of them treat a model as **reservoirs + flux equations + connections**, which is our
  representation, and compare structures systematically.
- **Data-based mechanistic (DBM) modelling** (Peter Young). Identify a transfer function from
  input to output, let the data choose its order (refined instrumental variable estimation, SRIV,
  with the YIC criterion), then decompose by partial fractions into **parallel first-order tanks**
  ("quick" and "slow" pathways). Interpret mechanistically only afterwards. See Young & Beven,
  *Environmetrics* 5:335-363, 1994; Young, *Hydrol. Process.* 17:2195-2217, 2003; and the CAPTAIN
  toolbox (MATLAB). A related result: Jakeman & Hornberger, "How much complexity is warranted in a
  rainfall-runoff model?", *WRR* 29(8):2637-2649, 1993
  ([doi:10.1029/93WR00877](https://doi.org/10.1029/93WR00877)). Rainfall-runoff data support only
  about **4-6 parameters** (IHACRES: two parallel linear stores plus a nonlinear loss).
- **"Catchments as simple dynamical systems"** (Kirchner, *WRR* 45:W02429, 2009,
  [doi:10.1029/2008WR006912](https://doi.org/10.1029/2008WR006912)). Assume discharge depends only
  on storage. Estimate the sensitivity function g(Q) = dQ/dS from −dQ/dt / Q during **recession
  periods, when rain and evaporation are negligible**. Then invert the model to infer the unmeasured
  input ("doing hydrology backwards"). Later tests show that it works in wet periods and fails when
  vegetation or extra stores matter.
- **Input uncertainty as latent multipliers**: BATEA (Kavetski, Kuczera & Franks, *WRR* 42,
  2006, [doi:10.1029/2005WR004368](https://doi.org/10.1029/2005WR004368)) gives each storm's rain
  a latent multiplier, estimated jointly with the model. This is the hydrological version of our
  **unannounced piecewise-constant inputs**.
- **Likelihoods with heteroscedastic, autocorrelated errors**: Schoups & Vrugt, *WRR* 46:W10531,
  2010 ([doi:10.1029/2009WR008933](https://doi.org/10.1029/2009WR008933)). Variance grows with the
  level, which is the same reason our weights must follow the level for Poisson noise.

### Equifinality
- **GLUE** (Beven & Binley, *Hydrol. Process.* 6:279-298, 1992,
  [doi:10.1002/hyp.3360060305](https://doi.org/10.1002/hyp.3360060305); Beven, "A manifesto for
  the equifinality thesis", *J. Hydrol.* 320:18-36, 2006,
  [doi:10.1016/j.jhydrol.2005.07.007](https://doi.org/10.1016/j.jhydrol.2005.07.007)). Many
  structures and parameter sets are "behavioural". Keep them all, weighted by an informal
  likelihood. GLUE's critics (Mantovan & Todini 2006; Stedinger et al. 2008) showed that its
  informal likelihoods and thresholds give uncertainty bands that do not mean what they say.
- **Lesson**: equifinality is real, but the right response is a formal likelihood plus model
  averaging over an explicitly enumerated structure set (FUSE/SUPERFLEX + Bayesian evidence). A
  thresholded ensemble is not enough.

### Identifiability lessons for hidden stocks
- From one outflow, a transfer function of order n is identifiable, but **its realisation as
  tanks is not**. Two tanks in series and two in parallel with mixing can give the same transfer
  function. DBM therefore picks the *parallel* form by convention, and justifies it by physics
  afterwards. This is the same indistinguishability as in section 1.
- Thresholds (storage caps, spill) make structures *more* distinguishable when they bind, and
  invisible when they do not. Floors and caps should be offered only where the data reach them.

### Transferable steps
- **Order first, then realise.** For each measured stock B with an inflow suspected of coming
  through hidden stocks, fit a low-order discrete transfer function from the candidate source A's
  outflow to B's inflow. Choose the order by BIC/YIC; poles give delay(s). Realise it as the
  *simplest* chain, and report alternative realisations as equivalent.
- **Recession-window identification.** Fit each stock's drain law on windows where its inflows are
  near zero (or known), then hold it fixed while estimating inflows. This decouples the
  "constant inflow vs proportional drain" confusion.
- **Inversion for unknown inputs.** Once drains are fixed, outside inflow = Δx + outflows. Run
  PELT on that series. This is what we do; Kirchner and BATEA support it, and warn that any drain
  misspecification is then attributed to the input.
- **Complexity budget.** Jakeman & Hornberger's 4-6 parameter result suggests an explicit cap on
  parameters per measured series, a sanity check against over-complex winners.

### Implementations
superflexpy (Python), MARRMoT (MATLAB/Octave), FUSE (Fortran; also inside SUMMA), CAPTAIN
(MATLAB; DBM/SRIV), DREAM (MCMC, MATLAB/Python ports), GLUE implementations in SPOTPY (Python).

### Failure modes
Equifinality with informal likelihoods; input error masquerading as structure error; thresholds
that never bind; tank-realisation non-uniqueness; overfitting with more than ~6 parameters per
output; storage-only assumptions breaking when extra stores exist (Kirchner in dry periods).

---

## 7. Queueing networks, network tomography and count time series

### What they share with us
Stocks are queue lengths; flows are routing probabilities times service rates; arrivals are Poisson.
Network tomography infers origin-destination flows from aggregate link counts, which are sums of
unobserved flows: an under-determined linear inverse problem with Poisson structure. Infinite-server
queues are our proportional drains, and Little's law is how we size hidden stocks.

### Methods that work
- **Network tomography**: Vardi, "Network tomography: estimating source-destination traffic
  intensities from link data", *JASA* 91(433):365-377, 1996
  ([doi:10.1080/01621459.1996.10476697](https://doi.org/10.1080/01621459.1996.10476697)).
  **Link means alone do not determine OD rates (more unknowns than links), but under Poisson
  OD flows the link covariances do.** He estimated by EM and by the method of moments using
  second moments. Extensions: Bayesian (Tebaldi & West, *JASA* 93:557-573, 1998), time-varying
  (Cao, Davis, Vander Wiel & Yu, *JASA* 95:1063-1075, 2000), tomogravity priors (Zhang, Roughan,
  Duffield & Greenberg, SIGMETRICS 2003), and a review (Castro, Coates, Liang, Nowak & Yu,
  *Stat. Sci.* 19(3):499-517, 2004, [doi:10.1214/088342304000000422](https://doi.org/10.1214/088342304000000422)).
- **Queueing inference from partial observation**:
  - The queue inference engine (Larson, *Manage. Sci.* 36(5):586-601, 1990,
    [doi:10.1287/mnsc.36.5.586](https://doi.org/10.1287/mnsc.36.5.586)).
  - Bayesian inference for queueing networks with latent arrival and departure times by Gibbs
    sampling (Sutton & Jordan, *Ann. Appl. Stat.* 5(1):254-282, 2011,
    [doi:10.1214/10-AOAS392](https://doi.org/10.1214/10-AOAS392)).
  - Non-parametric estimation of the **service-time distribution of an M/G/∞ queue from the
    queue-length process alone** (Bingham & Pitts, *Ann. Inst. Stat. Math.* 51:71-97, 1999,
    [doi:10.1023/A:1003831118254](https://doi.org/10.1023/A:1003831118254); Goldenshluger,
    [arXiv 1508.00076](https://arxiv.org/abs/1508.00076)). The queue length's autocorrelation
    function *is* the service-time survival function, so **the delay distribution of a stock can be
    read from the autocorrelation of its level**.
- **Integer-valued autoregression**. INAR(1): X_t = α∘X_{t−1} + ε_t, with binomial thinning
  α∘X ~ Binomial(X, α) and Poisson innovations (Al-Osh & Alzaid, *J. Time Ser. Anal.* 8(3):261-275,
  1987, [doi:10.1111/j.1467-9892.1987.tb00438.x](https://doi.org/10.1111/j.1467-9892.1987.tb00438.x);
  McKenzie 1985; survey: Weiß, *An Introduction to Discrete-Valued Time Series*, Wiley 2018).
  **This is exactly one SD stock with a proportional drain and a constant Poisson inflow, in
  discrete time.** Estimation is by conditional least squares (= our regression), Yule-Walker, or
  conditional ML, where the transition probability is a binomial-Poisson convolution. Multivariate
  INAR with binomial *routing* is a counting queueing network.
- **Little's law** (Little, *Oper. Res.* 9(3):383-387, 1961,
  [doi:10.1287/opre.9.3.383](https://doi.org/10.1287/opre.9.3.383)).

### Identifiability lessons
- **First moments under-determine; second moments resolve.** This is the clearest published
  statement of why our shared-noise evidence matters. It also comes with a warning: the
  second-moment estimators are high-variance and need long series. Vardi's identifiability needs
  the Poisson mean-variance link, which our counting noise provides.
- Service-time (delay) *shape* is recoverable non-parametrically only with long, stationary
  records. With short records, only the mean is reliable (Little's law).

### Transferable steps
- **Moment check for moves vs outside.** For a candidate A → B, the model predicts
  Cov(ΔA, ΔB) ≈ −E[flow]. For the out+in alternative it predicts ≈ 0. Compute this per window
  and use it as a score term, or as a hypothesis test before the BIC comparison.
- **Autocorrelation-based delay screen.** The autocorrelation of a measured stock's level (or
  the cross-correlation of A's outflow with B's inflow) estimates the residence-time distribution.
  Use it to propose a hidden stock's delay and shape (Erlang order) before fitting.
- **CML for INAR as the per-stock likelihood.** It handles small counts exactly, where the
  Gaussian approximation is poor (stocks with levels near 0-20).

### Implementations
R: `tscount` (INGARCH), `ZINARp`; Python: statsmodels (no INAR built-in; easy to code), network
tomography codes are mostly research scripts. Sutton & Jordan's sampler was research code.

### Failure modes
Second-moment estimators need long data; time-varying rates break stationarity assumptions;
blocking (finite buffers) creates nonlinearity that looks like a hidden stock.

---

## 8. Supply chain and inventory systems

### What they share with us
SD's own home ground: stocks of inventory, WIP and supply line, ordering rules with gap forms and
delays, demand as an outside input, stock-outs as floors, capacity as caps.

### Methods and findings
- **Fitting decision rules to data**: Sterman, "Modeling managerial behavior: misperceptions of
  feedback in a dynamic decision making experiment", *Manage. Sci.* 35(3):321-339, 1989
  ([doi:10.1287/mnsc.35.3.321](https://doi.org/10.1287/mnsc.35.3.321)). Beer-game orders were fitted
  by nonlinear least squares to an **anchoring-and-adjustment rule**: order = expected demand +
  α(desired inventory − inventory) + β(desired supply line − supply line). Subjects' β was far
  below α (they underweighted the supply line, a hidden stock). This is the canonical SD "gap"
  rate form with *two* gap terms, one on a stock the decision maker partly ignores.
- **Control-theoretic family of inventory structures**: IOBPCS (Towill, *Int. J. Prod. Res.*
  20(6):671-687, 1982, [doi:10.1080/00207548208947797](https://doi.org/10.1080/00207548208947797))
  and APIOBPCS (John, Naim & Towill, *Int. J. Prod. Econ.* 34(2):197-207, 1994). These are a small
  set of block-diagram templates (exponential forecast, inventory gap, WIP gap, pipeline delay)
  that cover most replenishment systems. They are a ready *structure grammar* for inventory-like
  examples, and identification reduces to estimating 3-4 time constants.
- **Censored demand**: when sales are capped by stock on hand, observed outflow = min(demand,
  stock). Lariviere & Porteus, "Stalking information: Bayesian inventory management with
  unobserved lost sales", *Manage. Sci.* 45(3):346-363, 1999
  ([doi:10.1287/mnsc.45.3.346](https://doi.org/10.1287/mnsc.45.3.346)), and a large literature on
  Kaplan-Meier / Tobit demand estimation.
- **Record inaccuracy**: DeHoratius & Raman, *Manage. Sci.* 54(4):627-641, 2008
  ([doi:10.1287/mnsc.1070.0789](https://doi.org/10.1287/mnsc.1070.0789)). Recorded inventory
  differed from physical inventory in about 65% of records. "Measured stocks" can carry systematic
  drift (an unmodelled outside flow: shrinkage).
- **General system identification** for these linear structures: Ljung, *System Identification:
  Theory for the User*, 2nd ed., Prentice Hall 1999 (prediction-error methods, grey-box models).

### Transferable steps
- Offer a **two-gap rate form** (own stock and supply-line stock) as a candidate for flows into
  pipelines. Sterman's fit shows real decision rules use it, with very unequal weights.
- **Censored-likelihood rows** where a stock hits zero: the outflow on those steps is a lower
  bound on demand, not a measurement of the rate law. Drop those steps from rate-law fits or treat
  them as censored. This is the floors-and-caps topic, with prior art.
- **Small-drift outside flow** (shrinkage) as a cheap default candidate when the conservation row
  shows a steady leak.

### Failure modes
Orders are decisions with heterogeneous, nonlinear rules; censoring hides demand; measured stocks
can be wrong; bullwhip oscillation can be confused with a hidden delay.

---

## 9. Practical identifiability, sloppiness and model reduction (cross-cutting)

- **Profile likelihood**: Raue et al., *Bioinformatics* 25(15):1923-1929, 2009
  ([doi:10.1093/bioinformatics/btp358](https://doi.org/10.1093/bioinformatics/btp358)). Profile
  each parameter. A flat profile means non-identifiable, and its shape tells structural from
  practical non-identifiability.
- **Sloppiness**: Gutenkunst et al., *PLoS Comput. Biol.* 3(10):e189, 2007
  ([doi:10.1371/journal.pcbi.0030189](https://doi.org/10.1371/journal.pcbi.0030189)). The Fisher
  information eigenvalues of systems-biology models span many decades, so predictions can be good
  while parameters are poorly determined. This supports our skill-based judging: *predict like the
  truth* is achievable when *parameters like the truth* is not.
- **Manifold boundary approximation (MBAM)**: Transtrum & Qiu, *Phys. Rev. Lett.* 113:098701,
  2014 ([doi:10.1103/PhysRevLett.113.098701](https://doi.org/10.1103/PhysRevLett.113.098701)).
  Follow the sloppiest direction to the edge of parameter space. The limit (a rate → ∞ or → 0, two
  parameters → ∞ with a fixed ratio) is a *simpler model* with one fewer parameter. In
  compartmental terms, the limits are "this hidden stock's delay → 0, merge it away", "this flow
  → 0, delete it", and "fast exchange → lump two stocks".
- **Transferable step**: after the search, for each hidden stock and effect, check the profile
  (or FIM eigenvector) of its parameters. If the data are consistent with the boundary limit (delay
  0, effect slope 0), replace the component with the limit model and re-judge. This is a principled
  "tidy" step for structure, beyond per-term BIC.

---

## 10. Transferable techniques: a pipeline view

Ordered as steps in our engine. "New" means not currently in discovery; "upgrade" means it refines
an existing step.

| # | Pipeline step | Technique | Source field | Status |
|---|---|---|---|---|
| 1 | Preprocessing | Mark windows where a floor or cap binds; treat their outflows as censored (min(demand, stock)) | inventory (lost sales), hydrology thresholds | new |
| 2 | Preprocessing | Mark quiet windows (no inflow, or a known inflow) per stock, and fit drain laws there first | hydrology (Kirchner recession analysis) | new |
| 3 | Candidate screen | Ratio-consistency screen: per-step changes of stock pairs and triples co-varying at fixed ratios → candidate moves and co-flows | CRN (Reactmine), tomography (Vardi second moments) | upgrade to our mirror-correlation grouping |
| 4 | Candidate screen | Delay screen: cross-correlation of A's outflow with B's inflow, and level autocorrelation → hidden-stock mean delay and Erlang order | queueing (M/G/∞ inference), hydrology (DBM order selection) | upgrade to hidden-stock proposals |
| 5 | Candidate family | Hidden stock = transit chain (n ∈ 1..4, mean time τ); report τ, treat n as soft | PK (Savic transit), epi (linear chain trick) | upgrade |
| 6 | Candidate family | Effects in four placements (stimulate or inhibit, inflow or outflow) with linear and saturating (Emax / Michaelis-Menten) curves; per-capita rate regression on a driver | PK (indirect response), ecology (gLV), CRN (implicit SINDy) | new |
| 7 | Candidate family | Two-gap rate form (own stock and supply-line stock) for pipeline inflows | supply chain (Sterman 1989, IOBPCS) | new |
| 8 | Search | Forward with a loose gate, backward with a strict gate; beam search instead of greedy | PK (SCM), CRN (Reactmine beam) | upgrade (structure-search topic) |
| 9 | Search | Change points in *internal rates* as well as inflows, each paying a BIC price; check that a structure fix removes them | epi (Dehning change points), SINDy-abrupt | new |
| 10 | Score | Gaussian LNA/GLS likelihood with covariance S·diag(q)·Sᵀ, or the exact binomial-thinning + Poisson likelihood for small counts | epi (Euler-multinomial), CRN (LNA), INAR | upgrade (count-likelihoods, shared-noise topics) |
| 11 | Post-search | Equivalence neighbourhood: enumerate output-preserving rewrites (move ↔ out+in, series ↔ parallel hidden paths, leak placement); sparsest and densest realisations; canonical choice by declared preference | compartmental (Godfrey-Chapman, DISTING), CRN (Szederkényi LP) | new (identifiability topic) |
| 12 | Post-search | Boundary reduction: profile or FIM along each hidden stock and effect; take the limit model if supported | systems biology (MBAM, profile likelihood) | new |
| 13 | Refinement | Multi-start trajectory refit of the top-k structures; particle-filter / IF2 likelihood when hidden stocks are present | PK practice (multi-start), epi (pomp IF2) | upgrade (output-error, state-space topics) |
| 14 | Acceptance | Simulation check: does the model's simulated spread bracket the data? A parameter budget per measured series | PK (VPC), hydrology (Jakeman-Hornberger) | upgrade to the held-out judge |
| 15 | Reporting | Structure inclusion probabilities from bootstrap or Bayesian selection; "near equilibrium: effects not identifiable" warnings | ecology (MDSINE), compartmental identifiability | upgrade |

---

## 11. Pitfalls these fields hit, and what to expect

1. **Equivalent structures will be "found" as different answers** on different data lengths or
   seeds. Expect our default and long runs to disagree in structure while agreeing in skill.
   Without a canonical tie-break, parts-recovery metrics will look noisy.
2. **Automatic structure search over-complicates** (Pharmpy AMD real-data evaluation; stepwise
   covariate model inflation). Each extra hidden stock or effect that wins by a small BIC margin is
   suspect.
3. **Hidden delays are the hardest part** (Pharmpy absorption; Tuncer & Le latent periods;
   hydrology tank realisation). The mean delay is reliable; shape, leak placement and series vs
   parallel are not.
4. **Time-varying parameters absorb misspecification** (epidemiology's wiggling β; hydrology's
   storm multipliers). Free inflow pieces will hide missing flows. Price every change point, and
   check whether a structural addition removes it.
5. **Gradient matching is biased under counting noise and at low counts** (ecology). Regression
   on differences selects structures that a simulation refit may reject. Keep the simulation judge.
6. **Near steady state nothing is identifiable** beyond the Jacobian (gLV; compartmental
   "persistent excitation"). Examples that settle early (sd-population, per our excitation check)
   should yield "cannot tell", not a confident wrong model.
7. **Informal likelihood ensembles mislead** (GLUE criticism). "Fits about as well" lists need a
   proper likelihood and a calibrated threshold.
8. **Fitting cumulative quantities (levels by least squares) is overconfident and biased** (King
   et al. 2015). Always fit increments.
9. **Multimodal likelihoods**: nonlinear and hidden-state fits have local optima (NONMEM practice;
   IF2). Comparing structures with unconverged fits picks the wrong structure. Multi-start every
   finalist.
10. **Shared forcing creates spurious links** (CCM under synchrony; Granger). Stocks driven by the
    same unannounced input co-move without exchanging anything. The conservation row and the
    covariance sign (a move gives *negative* covariance; shared forcing gives positive) are the
    separators.
11. **Censoring is easy to miss**: a capped outflow looks like a rate law that saturates (a false
    effect), and a floored stock looks like a drain that weakens with level.
12. **Second-moment evidence needs long series** (Vardi). Expect co-flow and move-vs-outside
    discrimination to work on long runs and to be weak on default-length runs.

---

## 12. Reading list (prioritised)

**Read first (highest transfer):**
1. Godfrey & Chapman 1990, Identifiability and indistinguishability of linear compartmental models. *Math. Comput. Simul.* 32(3):273-295. [doi:10.1016/0378-4754(90)90185-L](https://doi.org/10.1016/0378-4754(90)90185-L)
2. Davidson et al. 2017, DISTING. *Comput. Methods Programs Biomed.* 143:129-135. [doi:10.1016/j.cmpb.2017.02.025](https://doi.org/10.1016/j.cmpb.2017.02.025) · [PDF](https://qcb.ucla.edu/wp-content/uploads/sites/14/2021/01/DISTING-CMPB-Paper.pdf)
3. Szederkényi, Banga & Alonso 2011, Inference of complex biological networks: distinguishability issues and optimization-based solutions. *BMC Syst. Biol.* 5:177. [doi:10.1186/1752-0509-5-177](https://doi.org/10.1186/1752-0509-5-177)
4. Martinelli et al. 2022/23, Reactmine. [arXiv 2209.03185](https://arxiv.org/abs/2209.03185)
5. Bretó, He, Ionides & King 2009, Time series analysis via mechanistic models. *Ann. Appl. Stat.* 3(1):319-348. [doi:10.1214/08-AOAS201](https://doi.org/10.1214/08-AOAS201)
6. Vardi 1996, Network tomography. *JASA* 91(433):365-377. [doi:10.1080/01621459.1996.10476697](https://doi.org/10.1080/01621459.1996.10476697)
7. Savic et al. 2007, Implementation of a transit compartment model for describing drug absorption. *J. Pharmacokinet. Pharmacodyn.* 34:711-726. [doi:10.1007/s10928-007-9066-0](https://doi.org/10.1007/s10928-007-9066-0)
8. Hurtado & Kirosingh 2019, Generalizations of the linear chain trick. *J. Math. Biol.* 79:1831-1883. [doi:10.1007/s00285-019-01412-w](https://doi.org/10.1007/s00285-019-01412-w)
9. Chen et al. 2024 and Duvnjak et al. 2024, Pharmpy AMD. *CPT PSP* 13(10). [doi:10.1002/psp4.13222](https://doi.org/10.1002/psp4.13222), [doi:10.1002/psp4.13213](https://doi.org/10.1002/psp4.13213)
10. Clark et al. 2008, FUSE. *WRR* 44:W00B02. [doi:10.1029/2007WR006735](https://doi.org/10.1029/2007WR006735)
11. Kirchner 2009, Catchments as simple dynamical systems. *WRR* 45:W02429. [doi:10.1029/2008WR006912](https://doi.org/10.1029/2008WR006912)
12. Transtrum & Qiu 2014, Model reduction by manifold boundaries. *PRL* 113:098701. [doi:10.1103/PhysRevLett.113.098701](https://doi.org/10.1103/PhysRevLett.113.098701)

**Then:**
- Bellman & Åström 1970, *Math. Biosci.* 7:329-339. [doi:10.1016/0025-5564(70)90132-X](https://doi.org/10.1016/0025-5564(70)90132-X)
- Cobelli & DiStefano 1980, *Am. J. Physiol.* 239:R7-R24. [doi:10.1152/ajpregu.1980.239.1.R7](https://doi.org/10.1152/ajpregu.1980.239.1.R7)
- Walter & Lecourtier 1981, *Math. Biosci.* 56:1-25. [doi:10.1016/0025-5564(81)90025-0](https://doi.org/10.1016/0025-5564(81)90025-0)
- Jacquez & Simon 1993, *SIAM Rev.* 35(1):43-79. [doi:10.1137/1035003](https://doi.org/10.1137/1035003)
- Jacquez 1996, *Compartmental Analysis in Biology and Medicine*, 3rd ed.; Godfrey 1983, *Compartmental Models and Their Application*; Anderson 1983, *Compartmental Modeling and Tracer Kinetics*.
- Bellu et al. 2007, DAISY. [doi:10.1016/j.cmpb.2007.07.002](https://doi.org/10.1016/j.cmpb.2007.07.002)
- Hong et al. 2019, SIAN. *Bioinformatics* 35(16):2873-2874. [arXiv 1812.10180](https://arxiv.org/abs/1812.10180)
- Dong et al. 2023, StructuralIdentifiability.jl. *SIAGA* 7(1):194-235. [arXiv 2111.00991](https://arxiv.org/abs/2111.00991)
- Villaverde et al. 2016, STRIKE-GOLDD. [doi:10.1371/journal.pcbi.1005153](https://doi.org/10.1371/journal.pcbi.1005153)
- Meshkat, Sullivant & Eisenberg 2015. [doi:10.1007/s11538-015-0098-0](https://doi.org/10.1007/s11538-015-0098-0)
- Raue et al. 2009, profile likelihood. [doi:10.1093/bioinformatics/btp358](https://doi.org/10.1093/bioinformatics/btp358)
- Gutenkunst et al. 2007, sloppiness. [doi:10.1371/journal.pcbi.0030189](https://doi.org/10.1371/journal.pcbi.0030189)
- Yamaoka et al. 1978, AIC in PK. [doi:10.1007/BF01117450](https://doi.org/10.1007/BF01117450)
- Dayneka, Garg & Jusko 1993, indirect response models. [doi:10.1007/BF01061691](https://doi.org/10.1007/BF01061691)
- Sun & Jusko 1998, transit compartments. [doi:10.1021/js970414z](https://doi.org/10.1021/js970414z)
- Bergstrand et al. 2011, VPC. [doi:10.1208/s12248-011-9255-z](https://doi.org/10.1208/s12248-011-9255-z)
- Bies et al. 2006, GA for NONMEM structures. [doi:10.1007/s10928-006-9004-6](https://doi.org/10.1007/s10928-006-9004-6)
- Ionides et al. 2015, IF2. [doi:10.1073/pnas.1410597112](https://doi.org/10.1073/pnas.1410597112)
- King, Nguyen & Ionides 2016, pomp. [doi:10.18637/jss.v069.i12](https://doi.org/10.18637/jss.v069.i12)
- He, Ionides & King 2010, measles. [doi:10.1098/rsif.2009.0151](https://doi.org/10.1098/rsif.2009.0151)
- Andrieu, Doucet & Holenstein 2010, PMCMC. [doi:10.1111/j.1467-9868.2009.00736.x](https://doi.org/10.1111/j.1467-9868.2009.00736.x)
- Dehning et al. 2020, change points. [doi:10.1126/science.abb9789](https://doi.org/10.1126/science.abb9789)
- Dureau et al. 2013, time-varying drivers. [doi:10.1093/biostatistics/kxs052](https://doi.org/10.1093/biostatistics/kxs052)
- Cori et al. 2013, EpiEstim. [doi:10.1093/aje/kwt133](https://doi.org/10.1093/aje/kwt133)
- Wearing, Rohani & Keeling 2005. [doi:10.1371/journal.pmed.0020174](https://doi.org/10.1371/journal.pmed.0020174)
- Tuncer & Le 2018. [doi:10.1016/j.mbs.2018.02.004](https://doi.org/10.1016/j.mbs.2018.02.004)
- King et al. 2015, Avoidable errors. [doi:10.1098/rspb.2015.0347](https://doi.org/10.1098/rspb.2015.0347)
- Funk & King 2020. [doi:10.1016/j.epidem.2019.100383](https://doi.org/10.1016/j.epidem.2019.100383)
- Craciun & Pantea 2008. [doi:10.1007/s10910-007-9307-x](https://doi.org/10.1007/s10910-007-9307-x)
- Burnham et al. 2008, Inference of chemical reaction networks. [doi:10.1016/j.ces.2007.10.010](https://doi.org/10.1016/j.ces.2007.10.010)
- Komorowski et al. 2009, LNA inference. [doi:10.1186/1471-2105-10-343](https://doi.org/10.1186/1471-2105-10-343)
- Fearnhead, Giagos & Sherlock 2014, LNA for reaction networks. [doi:10.1111/biom.12152](https://doi.org/10.1111/biom.12152)
- Golightly & Wilkinson 2011, PMCMC for stochastic kinetics. [doi:10.1098/rsfs.2011.0047](https://doi.org/10.1098/rsfs.2011.0047)
- Mangan et al. 2016, implicit SINDy for rational kinetics. [doi:10.1109/TMBMC.2016.2633265](https://doi.org/10.1109/TMBMC.2016.2633265)
- Oates & Mukherjee 2012. [doi:10.1214/11-AOAS532](https://doi.org/10.1214/11-AOAS532)
- Hoffmann, Fröhner & Noé 2019, Reactive SINDy. *J. Chem. Phys.* 150:025101. [doi:10.1063/1.5066099](https://doi.org/10.1063/1.5066099)
- Stein et al. 2013, gLV for microbiota. [doi:10.1371/journal.pcbi.1003388](https://doi.org/10.1371/journal.pcbi.1003388)
- Bucci et al. 2016, MDSINE. [doi:10.1186/s13059-016-0980-6](https://doi.org/10.1186/s13059-016-0980-6)
- Gibson et al. 2025, MDSINE2. [doi:10.1038/s41564-025-02112-6](https://doi.org/10.1038/s41564-025-02112-6)
- Fisher & Mehta 2014, LIMITS. [doi:10.1371/journal.pone.0102451](https://doi.org/10.1371/journal.pone.0102451)
- Remien et al. 2021, gLV identifiability. [doi:10.1098/rsos.201378](https://doi.org/10.1098/rsos.201378)
- Ives et al. 2003, MAR models. *Ecol. Monogr.* 73(2):301-330.
- Sugihara et al. 2012, CCM. [doi:10.1126/science.1227079](https://doi.org/10.1126/science.1227079)
- Ye et al. 2015, EDM forecasting. [doi:10.1073/pnas.1417063112](https://doi.org/10.1073/pnas.1417063112)
- Deyle et al. 2016, S-map interactions. [doi:10.1098/rspb.2015.2258](https://doi.org/10.1098/rspb.2015.2258)
- Wood 2010, synthetic likelihood. [doi:10.1038/nature09319](https://doi.org/10.1038/nature09319)
- Fenicia, Kavetski & Savenije 2011, SUPERFLEX. [doi:10.1029/2010WR010174](https://doi.org/10.1029/2010WR010174)
- Dal Molin et al. 2021, superflexpy. [doi:10.5194/gmd-14-7047-2021](https://doi.org/10.5194/gmd-14-7047-2021)
- Knoben et al. 2019, MARRMoT. [doi:10.5194/gmd-12-2463-2019](https://doi.org/10.5194/gmd-12-2463-2019)
- Jakeman & Hornberger 1993. [doi:10.1029/93WR00877](https://doi.org/10.1029/93WR00877)
- Young & Beven 1994, DBM rainfall-flow. *Environmetrics* 5:335-363; Young 2003, *Hydrol. Process.* 17:2195-2217.
- Kavetski, Kuczera & Franks 2006, BATEA. [doi:10.1029/2005WR004368](https://doi.org/10.1029/2005WR004368)
- Schoups & Vrugt 2010, generalised likelihood. [doi:10.1029/2009WR008933](https://doi.org/10.1029/2009WR008933)
- Beven & Binley 1992, GLUE. [doi:10.1002/hyp.3360060305](https://doi.org/10.1002/hyp.3360060305); Beven 2006, equifinality manifesto. [doi:10.1016/j.jhydrol.2005.07.007](https://doi.org/10.1016/j.jhydrol.2005.07.007)
- Castro et al. 2004, Network tomography review. [doi:10.1214/088342304000000422](https://doi.org/10.1214/088342304000000422)
- Sutton & Jordan 2011, Bayesian queueing networks. [doi:10.1214/10-AOAS392](https://doi.org/10.1214/10-AOAS392)
- Larson 1990, Queue inference engine. [doi:10.1287/mnsc.36.5.586](https://doi.org/10.1287/mnsc.36.5.586)
- Bingham & Pitts 1999, M/G/∞ estimation. [doi:10.1023/A:1003831118254](https://doi.org/10.1023/A:1003831118254)
- Al-Osh & Alzaid 1987, INAR(1). [doi:10.1111/j.1467-9892.1987.tb00438.x](https://doi.org/10.1111/j.1467-9892.1987.tb00438.x); Weiß 2018, *An Introduction to Discrete-Valued Time Series*.
- Little 1961. [doi:10.1287/opre.9.3.383](https://doi.org/10.1287/opre.9.3.383)
- Sterman 1989, beer game decision rules. [doi:10.1287/mnsc.35.3.321](https://doi.org/10.1287/mnsc.35.3.321)
- Towill 1982, IOBPCS. [doi:10.1080/00207548208947797](https://doi.org/10.1080/00207548208947797)
- Lariviere & Porteus 1999, unobserved lost sales. [doi:10.1287/mnsc.45.3.346](https://doi.org/10.1287/mnsc.45.3.346)
- DeHoratius & Raman 2008, inventory record inaccuracy. [doi:10.1287/mnsc.1070.0789](https://doi.org/10.1287/mnsc.1070.0789)
- Ljung 1999, *System Identification: Theory for the User*, 2nd ed.

**Citation confidence.** Bibliographic details for Godfrey & Chapman, DISTING, Szederkényi,
Reactmine, MDSINE/MDSINE2, IF2, SIAN, StructuralIdentifiability.jl, FUSE, SUPERFLEX, Pharmpy AMD,
Burnham, Sutton & Jordan, Bingham & Pitts and Hurtado & Kirosingh were checked by web search for
this report. The other DOIs are from the author's knowledge of standard references. They are
believed correct, but have not each been resolved; verify one before quoting it in code or papers.
