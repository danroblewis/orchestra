# Causal inference: the algebra of causation, and what it can do for discovery

Literature research note, 2026-10-17. It answers the question: "I have heard there is an algebra of
causation, a way to prove causation and tell it from correlation. Could it help our discovery
feature?" It covers four things: Pearl's structural causal models and do-calculus, causality in dynamic
and feedback systems, interventions and experiment design for causal discovery, and what applies to
SD Lab now that it can make announced **injections** (commit `6d210c4`: add an amount to a stock at a
step and watch the system respond).

Context: SD Lab's discovery (see [DISCOVERY-GOAL.md](../../DISCOVERY-GOAL.md)) sees measured stock
levels at discrete steps. The data have counting (Poisson) noise, conservation between stocks, floors
at 0 and caps, unannounced outside inflows that change piece by piece, announced eras, unmeasured
(hidden) stocks, feedback loops that settle, and now announced injections. Discovery regresses each
stock's change on the levels at the start of the step (`sdlab/discovery/matrix.py`). It cuts the
outside inflow into pieces with PELT, and picks among variants by multi-step behaviour
(`identify.py`).

Not repeated here: Granger causality, transfer entropy and convergent cross mapping, with their
failure modes ([signals and time series](signals-and-time-series.md), section 6); optimal input design,
Box-Hill discrimination and instrumental variables in system identification
([system identification](system-identification.md), sections 5 and 14); structural identifiability of
compartmental models ([compartmental analogues](compartmental-analogues.md), section 1;
[identifiability](../identifiability.md)). The [playbook](../PLAYBOOK.md) (C10) already ranks
Granger, TE and CCM as sanity baselines only. This note agrees and does not reopen that.

Citations: every source in the reading list (section 6) was checked by web search (Crossref, arXiv,
PMLR, JMLR, publisher pages). Its status is marked there. Chapter numbers given for books (Pearl
2009; Peters, Janzing and Schölkopf 2017) are from memory and were not checked.

---

## 0. The short answer, in plain words

Yes, there is an algebra of causation. Judea Pearl built it in the 1990s on **structural causal
models**: a set of equations "each variable := a function of its causes plus its own noise", drawn as
a graph. It adds one operator to probability, **do(X = x)**. *Seeing* X = x (conditioning) means
looking only at the cases where X happened to be x. *Doing* X = x means reaching in and setting X,
cutting X off from whatever normally sets it. Three rules (the **do-calculus**) rewrite expressions
with do() into expressions without it. When the rewriting succeeds, the causal effect can be computed
from passive data, and it gives the formula. When it fails, it is *proved* that no amount of passive
data can give the answer, and an experiment is needed. The rules are complete: if they cannot
remove the do(), nothing can.

What it can prove, and what it cannot:
- **It cannot get causation out of correlation alone.** The causal hierarchy theorem (Bareinboim et
  al. 2022) says that data at one level (observations) almost never settle questions at the next
  (interventions, then counterfactuals). Something extra is always needed: assumptions (a graph, time
  order, conservation, the SD equation forms) or experiments.
- **It can say exactly which assumptions are needed, and which experiment would remove the need.**
  For us that is the valuable part.

For SD Lab, the core observation is this. **Our engine already does the causal part that time order
gives for free.** A stock's change depends on levels at the start of the step, so time orients every
arrow, and feedback loops unroll into a chain in time with no cycles. When everything is measured,
nothing outside drives two stocks at once, and the noise is independent per step, our regression of
each stock's change on the previous levels *is* the causal structure. Theory says so (section 2.1).
Our failures happen exactly where those conditions break:
- an **unannounced outside inflow** that also shapes the levels used as regressors (a confounder: this
  is the "drain biased by inflow pieces" problem);
- **hidden stocks** (latent variables);
- **settled loops** where causes stop moving, and balancing loops whose effects cancel (no excitation,
  and failures of "faithfulness");
- **eras** that change some equations but do not say which.

Causal inference has a standard tool for each of these. Injections are *interventions* with a known
target, time and amount, so they are perfect instruments and perfect experiments. Eras are
*environments* with unknown targets. The best ideas below use injections and eras in the way the
causal literature says they should be used.

The ranked ideas (detail in section 5):
1. **An interventional judge**: measure each injection's response directly, with no model, and make
   every candidate reproduce it. It catches models that fit flat data but collapse when shaken.
2. **Injections as instruments**: fit drains with instrumental variables built from the injection
   amounts, which no unannounced inflow can be correlated with.
3. **Invariance across eras and probes**: find which rows an era actually changed, and split numbers
   only there. Keep a predictor set only if it stays invariant when injections shift its inputs.
4. **Probe design**: choose which stock to inject, when and how much, to separate the candidates that
   still fit and to break confounding.
5. **A causal identifiability report**: per link, say whether the data can identify it and which
   probe would make it identifiable (folded into [identifiability](../identifiability.md)).

---

## 1. The algebra of causation

Running example: a population model, **adults -> births -> children**. Children mature into
adults, adults age into elderly, and births = b x adults. That last one is a *link*: adults are not
used up by giving birth. In a time step, the structural equations are:

```
births(t)        := b * adults(t)            + noise_births(t)
maturing(t)      := m * children(t)          + noise_maturing(t)
children(t+1)    := children(t) + births(t) - maturing(t) + immigration_children(t)
adults(t+1)      := adults(t)   + maturing(t) - ageing(t) + immigration_adults(t)
```

### 1.1 Structural causal models (SCMs)

**Plain words.** An SCM is a list of assignments, one per variable: the variable *is set by* a
function of its direct causes (its *parents*) and an independent noise term. The arrows of the graph
go from parents to children. Joint probabilities come from running the assignments with random
noise. Interventions come from replacing some assignments. (Pearl 2009, ch. 1, 7; Peters, Janzing
and Schölkopf 2017, ch. 6.)

**SD reading.** An SD model, unrolled over steps, is an SCM. Each stock's next level is assigned from
its current level and the flows. Each flow is assigned from the levels its rate equation reads. The
counting noise of each flow is that flow's noise term. The unrolled graph has no cycles, even though
the SD diagram has loops. The loop adults -> births -> children -> maturing -> adults becomes
adults(t) -> births(t) -> children(t+1) -> maturing(t+1) -> adults(t+2).

**What an SCM gives that a regression does not.** A regression gives one conditional distribution,
fitted to the data it saw. An SCM says what happens when an assignment is replaced. That is exactly
what the page's "what if" needs, and exactly what an injection does.

### 1.2 Seeing versus doing: the do-operator

**Plain words.** P(children rises | adults is high) is *seeing*: it includes every reason adults
might be high, for example a wave of family immigration that also brought children. P(children rises
| do(adults := high)) is *doing*: it includes only adults' effect, because the intervention cut adults
off from its usual causes. The two differ whenever something drives both (a *confounder*).

**SD example (our real failure).** An unannounced inflow of families raises adults *and* children at
the same time. Regress children's change on adults' level, and the birth rate b absorbs the
immigration of children: seeing overestimates doing. An injection of 100 adults at a random step is
do(adults(t) := adults(t) + 100). The immigration cannot know about it. Children's response over the
following steps measures b alone.

Formally, do(X = x) deletes X's assignment, sets X = x, and keeps every other assignment. In the
graph, it deletes every arrow *into* X (Pearl 1995; Pearl 2009, ch. 3).

### 1.3 Reading independences from the graph: d-separation, Markov, faithfulness

**Plain words.** Three small patterns explain all of it:
- **chain** A -> M -> B (adults -> births -> children): A and B are dependent, but independent once
  you know M. Once births are measured, adults tell you nothing more about children's inflow.
- **fork** A <- C -> B (adults <- immigration -> children): A and B are dependent through C, and
  independent given C. This is confounding.
- **collider** A -> C <- B (births -> children <- immigration): A and B are independent, but become
  *dependent* once you condition on C. If you select the steps where children rose a lot, births and
  immigration become negatively related: one explains away the other.

*d-separation* applies these rules along every path. The **Markov condition** says the graph's
d-separations hold as independences in the data. It is true for any SCM with independent noise
(Pearl 2009, ch. 1; Spirtes, Glymour and Scheines 2000). **Faithfulness** is the converse: every
independence in the data comes from a d-separation, never from an exact cancellation of effects.

**Where faithfulness fails in SD.** Balancing loops exist to cancel. A staffing loop hires when the
backlog grows. Near equilibrium, the backlog barely moves and is almost uncorrelated with hiring, even
though hiring causes it. Andersen (2013) shows that control and homeostatic systems are where to
*expect* faithfulness to fail. Uhler et al. (2013) show that "nearly unfaithful" cases, which no finite
sample can tell from unfaithful ones, are common. Zhang and Spirtes (2008) give weaker assumptions
that can be checked in part. **Consequence for us:** any step of discovery that drops a term
*because it does not correlate* assumes faithfulness. Our forward stepwise selection does this
implicitly. A term joins only if it helps on its own margin, so balancing pairs whose contributions
cancel can both be missed. The backward variant (start from every level, `backward_max`) is the
standard remedy, and injections are the real one: they move a cause while its controller lags behind.

**Markov equivalence.** Different graphs can imply the same independences. A -> B -> C, A <- B <- C
and A <- B -> C all say "A independent of C given B". Passive data can at best identify the
equivalence class (Verma and Pearl 1990). For us, time order removes most of this ambiguity (arrows
point forward in time). What remains is ambiguity between *mechanisms*, not directions: a link
versus a move, or a hidden stock versus a slow drain. Independence patterns do not settle those;
conservation and second moments do ([shared-noise](../shared-noise.md)).

### 1.4 The do-calculus: three rules

**Plain words.** Three rules say when you may (1) drop or add an observation, (2) swap an action for
an observation, or (3) drop or add an action. Each rule is licensed by a d-separation in a modified
graph. Apply them until no do() remains. If you succeed, you have a formula in observable quantities.

For disjoint sets X, Y, Z, W. G with a bar over X means arrows *into* X are removed. G with a bar
under Z means arrows *out of* Z are removed (Pearl 1995; Pearl 2009, ch. 3.4):

- **Rule 1 (observations):** P(y | do(x), z, w) = P(y | do(x), w) if Y and Z are d-separated by X, W
  in G with arrows into X removed.
- **Rule 2 (action/observation exchange):** P(y | do(x), do(z), w) = P(y | do(x), z, w) if Y and Z are
  d-separated by X, W in G with arrows into X and arrows out of Z removed.
- **Rule 3 (actions):** P(y | do(x), do(z), w) = P(y | do(x), w) if Y and Z are d-separated by X, W
  in G with arrows into X removed, and arrows into Z(W) removed, where Z(W) is the Z-nodes that are not
  ancestors of any W-node in that graph.

The rules are **complete**: if an interventional distribution can be computed from the observational
one in a given graph with hidden variables, the rules find the formula (Huang and Valtorta 2006;
Shpitser and Pearl 2006). The **ID algorithm** does the search mechanically and returns either the
formula or a proof of non-identifiability (a "hedge"). It builds on Tian and Pearl (2002). Pearl
(2012) is a readable retrospective.

### 1.5 Backdoor and front-door

**Backdoor criterion (plain words).** To get X's effect on Y from passive data, adjust for a set Z of
variables that blocks every path from X to Y beginning with an arrow *into* X, and that contains no
effect of X. Then P(y | do(x)) = sum over z of P(y | x, z) P(z).

*SD example:* the effect of adults(t) on children(t+1). Backdoor paths run through adults' past
causes: adults(t-1), maturing, immigration. Conditioning on all levels at t blocks them, provided
nothing unmeasured drives both adults and children. That proviso is the whole story. Our row
regression conditions on every level at t, so it is a backdoor adjustment, and it is valid exactly
when there is no unmeasured common driver.

**Front-door criterion (plain words).** If X's effect goes entirely through a *measured* mediator M,
M is not confounded with X, and the confounding of M with Y runs only through X, then
P(y | do(x)) = sum over m of P(m | x) sum over x' of P(y | m, x') P(x'). This holds even when X and Y
share an unmeasured cause.

*SD example:* SD Lab can measure a flow (a model may name a flow to have it measured;
`opts["known"]` takes measured flows out of the rows). When births are counted, the adults -> children
effect is identifiable even if an unannounced inflow drives both adults and children. That is the
front door, and it is also why discovery already subtracts measured flows first. **Theory confirms
current practice**: a measured flow is worth more than any amount of passive level data on the two
stocks it connects.

### 1.6 Identifiability of causal effects

**Plain words.** An effect is *identifiable* when every SCM that matches the graph and produces the
observed data gives the same answer. The simplest non-identifiable case is the "bow": X -> Y plus an
unmeasured common cause of X and Y. No passive data separate the arrow from the common cause.

*SD example:* a stock whose outside inflow is unannounced and also feeds the stock that drains into it
(shared demand on two queues). The drain coefficient between them sits in a bow and cannot be
identified from levels alone. The fixes are: an instrument (an era switch or an injection upstream
that does not touch the confounder: [era-instruments](../era-instruments.md),
[injection-instruments](../injection-instruments.md)), a measured flow (front door), or an injection
into the source (do()).

**Caution.** Causal-effect identifiability (can P(y | do(x)) be computed?) is not *parameter*
identifiability (can each rate constant be pinned down?), which the compartmental literature
studies ([compartmental analogues](compartmental-analogues.md), section 1). A hidden stock between
A and B leaves A's total effect on B over time identifiable, because the hidden stock is a mediator
and not a confounder. Its internal parameters, beyond the mean delay, may not be.

### 1.7 Counterfactuals

**Plain words.** A counterfactual asks about *this* run: "the clinic ran out of doses on day 40;
would vaccinations have stopped if we had delivered 200 more on day 35?" An SCM answers in three
steps (Pearl 2009, ch. 7):
1. **abduction:** infer the noise values (and outside inflows) that produced what was seen;
2. **action:** change the assignment (deliver 200 more on day 35);
3. **prediction:** rerun the model with the same noise.

It needs the *equations*, not only the graph. With counting noise, the per-flow draws cannot all be
recovered from the levels (two flows into one stock add their draws), so the answers hold only up to
that noise. For large stocks that matters little.

*For SD Lab:* the grader's skill@H already compares the model and the truth "started from the same
states and fed the same outside inflows". That is close to a counterfactual comparison: the
exogenous inputs are held fixed while the mechanism differs. The page's what-if experiments are
counterfactual queries. They are only as good as the structural equations, which is why level 2
evidence (injections) matters.

### 1.8 The causal hierarchy

Three levels, each with its own kind of question (Bareinboim, Correa, Ibeling and Icard 2022; Pearl
2009, epilogue):

| level | question | SD Lab |
|---|---|---|
| 1 association | what does seeing x tell me about y? | one-step regression on passive levels |
| 2 intervention | what happens to y if I set x? | injections; eras with a known change; the page's "what if" |
| 3 counterfactual | in this run, what would y have been had x been different? | replaying a run with the same inflows and a changed model or input |

The **causal hierarchy theorem** (Bareinboim et al. 2022) says that for almost every SCM, level 1
data underdetermine level 2, and level 2 data underdetermine level 3. You climb only with assumptions
or with data from the higher level. **Our observational fit is level 1, and our goal (behave like the
truth from new states, under what-ifs) is level 2.** This explains the injection commit's finding: on
sd-population at 3000 steps, a model learned from flat data collapses when the system is shaken
(-46%). It was a level 1 answer to a level 2 question. The SD equation forms and conservation are
the assumptions that let us climb without experiments. Injections are the level 2 data that let us
check.

### 1.9 Potential outcomes (Rubin) and how they relate

**Plain words.** For each unit there are two potential outcomes, Y(1) with the treatment and Y(0)
without. The causal effect is the difference. Only one is ever seen: the "fundamental problem of
causal inference" (Holland 1986). Averages can still be estimated when treatment is assigned
independently of the potential outcomes (*ignorability*, guaranteed by randomising) and units do not
affect each other (*SUTVA*) (Rubin 1974; Imbens and Rubin 2015; Hernán and Robins 2020).

**Relation to SCMs.** The two frameworks are logically equivalent for the questions both can state.
A potential outcome Y(x) is the counterfactual Y computed by an SCM under do(X = x) (Pearl 2009, ch.
7). The SCM adds a graph for deciding when ignorability holds. Potential outcomes add a tradition of
design and estimation (randomisation, matching, IV under monotonicity).

*For SD Lab:* a unit is a stretch of run, the treatment is "inject a into stock A at step t", and the
outcome is each stock's path over the next H steps. **If injection times and amounts are chosen at
random**, ignorability holds by construction. The average response after injections, minus the
average without, is then an unbiased estimate of the dynamic causal effect, with no model at all.
That is the basis of idea 1. SUTVA fails in the small: injections closer together than the system's
memory overlap. Space them by more than the slowest response time, or model the overlap linearly
(local projections, section 3.4).

### 1.10 What the algebra can and cannot prove: summary

| it can | it cannot |
|---|---|
| decide, for a given graph with hidden variables, whether an effect is computable from passive data, and give the formula (do-calculus, ID algorithm) | tell you the graph; the graph is an assumption or comes from discovery |
| prove an effect from a randomised intervention, with no model (potential outcomes, randomisation) | turn correlation into causation without assumptions (causal hierarchy theorem) |
| rule out graphs that contradict the independences, up to Markov equivalence (given faithfulness) | tell apart Markov-equivalent graphs without interventions, time order or distributional assumptions |
| show which interventions would make an effect identifiable | give rate *forms* (linear, effect curve, co-flow); those are the SD library's job |
| answer counterfactuals given the structural equations | handle conservation laws and equilibria in the standard acyclic form (needs the extensions in section 2) |
|  | guarantee faithfulness, which balancing loops violate |

---

## 2. Causality in dynamic systems and time series

### 2.1 Time-unrolled SCMs: when Granger is causal

Unroll a discrete-time system into one variable per stock per step. Assume (a) every relevant
variable is measured (*causal sufficiency*), (b) no effects within a step (*no instantaneous
effects*), and (c) the graph is the same at every step. Then the full time graph is identifiable from
observational data, and "X Granger-causes Y" coincides with "X is a cause of Y" (Peters, Janzing and
Schölkopf 2017, ch. 10; Eichler 2012). Eichler and Didelez (2010) connect Granger non-causality to
the *effect of interventions* in time series. White and Lu (2010) give the econometric version.

**For us:** our per-stock regression on the previous levels is a conditional Granger analysis
([signals](signals-and-time-series.md) 6.3), so under (a)-(c) it is causal discovery. Our data
violate each assumption in a known way:
- (a) fails because of hidden stocks and unannounced outside inflows. Both are latent processes with
  memory: a latent inflow piece lasts many steps and shapes the levels used as regressors. That is
  latent confounding across time.
- (b) fails for moves and co-flows in a precise way. The same draw leaves one stock and arrives at
  another in the same step, so the two stocks' changes share a noise term. In graph language, that is
  a bidirected edge between the two changes at lag 0. It is the signature [shared-noise](../shared-noise.md)
  exploits. A link has no such edge.
- (c) fails at announced eras (known times), unannounced changes and pulses.
- Our windows (aggregation) also break the step-level picture (subsampling: Hyttinen et al. 2016;
  [signals](signals-and-time-series.md) on Gong et al. 2015).

### 2.2 Causal discovery algorithms for time series

- **PCMCI** (Runge et al. 2019a) runs a condition-selection step (PC1) per variable, then a
  momentary conditional independence (MCI) test that conditions on both ends' parents. That controls
  false positives under autocorrelation. **PCMCI+** (Runge 2020) adds contemporaneous edges.
  **LPCMCI** (Gerhardus and Runge 2020) allows latent confounders. Runge (2018) lists the assumptions
  in detail; Runge et al. (2019b) review the field for Earth-system data.
- **tsFCI** (Entner and Hoyer 2010) and **SVAR-FCI** (Malinsky and Spirtes 2018) adapt FCI to time
  series with latent variables. They output partial ancestral graphs: arrows that are certain,
  undetermined, or due to hidden common causes.
- **VAR-LiNGAM** (Hyvärinen, Zhang, Shimizu and Hoyer 2010) uses non-Gaussian noise to orient
  instantaneous effects (LiNGAM: Shimizu et al. 2006). **TiMINo** (Peters, Janzing and Schölkopf 2013)
  uses restricted functional forms.
- **Subsampled data:** Hyttinen et al. (2016) recover the step-level graph consistent with
  coarser-sampled data, by constraint optimisation.

**Value for SD Lab: low as engines, modest as diagnostics.** These methods output a graph, need
faithfulness (which our balancing loops break), test independences that counting noise at low
levels makes weak, and know nothing of conservation. Our model class is much narrower and stronger:
rows of stoichiometry times rates. One use remains. A *latent-variable* method (LPCMCI, tsFCI) marks
pairs of stocks as "confounded by something unmeasured" (bidirected edges). In our world that points
to a hidden stock or a shared unannounced inflow. It could serve as a cheap pre-check before the
hidden-stock search, but [mass-balance-hidden](../mass-balance-hidden.md) and lagged residual
correlations already do this with more physics. Tigramite (PCMCI) is GPL-3.0, so offline use only.
Keep [causal-discovery](../causal-discovery.md) as an offline baseline idea.

### 2.3 Feedback and cycles: equilibrium and cyclic SCMs

An SCM may have cycles if each assignment is read as an equilibrium condition. Bongers, Forré, Peters
and Mooij (2021) set out the foundations. A cyclic SCM may have no solution or several. Interventions
can make solutions appear or vanish. Marginalising latent variables is subtle. d-separation must be
replaced by **σ-separation** in general. Methods that learn cyclic graphs: CCD (Richardson 1996);
ICA-based (Lacerda et al. 2008); linear cyclic models with latent variables learned from experiments
(Hyttinen, Eberhardt and Hoyer 2012). The last one is close to our setting: linear, feedback,
hidden variables, and experiments that each intervene on some variables.

**For us:** we observe every step, so the *unrolled* model is acyclic and we do not need cyclic SCM
theory to fit. It matters in two places:
1. **Equilibrium what-ifs on the page** ("where will the backlog settle if we hire two people?") are
   cyclic SCM questions. The answer exists only if the new equilibrium is unique and stable.
2. **Data that only see equilibria** (long windows over a settled loop) carry only cyclic SCM
   information. Many dynamic structures then share one equilibrium SCM (next section).

### 2.4 From ODEs to SCMs, and why equilibrium data mislead

- **Mooij, Janzing and Schölkopf (2013)** show when the equilibria of a first-order ODE are described
  by a deterministic (possibly cyclic) SCM, and that interventions on the ODE and on the SCM agree when
  they do. Its equations come from setting each derivative to zero. **Rubenstein, Bongers, Schölkopf
  and Mooij (2018)** extend this to *dynamic* SCMs: the asymptotic behaviour under time-varying
  inputs, for example periodic forcing (our daily and weekly schedules). **Bongers, Blom and Mooij
  (2022)** cover random differential equations. **Hansen and Sokol (2014)** define interventions for
  SDEs.
- **Iwasaki and Simon (1994)** and **Dash (2005)** make a warning precise. Equilibration can change the
  *causal ordering*. A model that is right about the equilibria can be wrong about interventions
  that disturb them. Dash shows that structure learned from equilibrium data can mislead
  manipulation predictions. This is the theory behind the injection commit's finding: a model learned
  from flat data collapses when the system is shaken.
- **Conservation laws.** **Blom, Bongers and Mooij (2020)** show that SCMs cannot fully describe some
  dynamical systems at equilibrium. Their motivating example is a simple (bio)chemical reaction. They
  introduce **causal constraints models** (CCMs) for this, which also represent functional laws such as
  the ideal gas law. A conserved total is such a law: at equilibrium it fixes a level that no single
  equation "causes". **Blom, van Diepen and Mooij (2021)** generalise Simon's (1953) *causal ordering*
  to sets of equations: which variables each equation determines, and which independences follow.
  **Blom and Mooij (2023)** study *perfectly adapted* systems (integral feedback). Their equilibrium
  independences hide real causes, a systematic faithfulness failure. SD goal-seeking loops that
  integrate a gap are such systems.

**What the theory says about stock-and-flow networks.** In discrete time, with every step observed,
a stock-and-flow network is an ordinary dynamic SCM with two special features:
1. **Stoichiometry is a known part of the graph.** A flow's variable enters two stocks with
   opposite signs (S · F). So the skeleton between stocks and flows is constrained before any data
   arrive. Flows are the unmeasured variables, and each stock's change is a known signed sum of them.
   In causal terms the flow draws are latent variables with known children. That is why conservation
   constraints, and the covariance of changes, are so informative.
2. **At equilibrium the standard theory breaks** (CCMs, perfect adaptation). This is a reason to take
   information from transients (injections, era switches, pulses) and not from settled stretches.

### 2.5 The closest published analogue: CausalKinetiX

Pfister, Bauer and Peters (2019, PNAS) learn *kinetic* (mass-action ODE) models from noisy,
discrete-time observations of **several experiments**. Their premise is that one invariant kinetic
model holds in every experiment. They prefer structures whose fitted dynamics stay stable and
predictive across experiments over structures that fit best overall. They report that this predicts
unseen experiments markedly better than purely predictive selection. Their ODEs are close to ours
(terms linear in parameters, products of species), and their "experiments" correspond to our eras and
injection runs. *The scoring details here are from the paper as recalled. The abstract was checked;
the method section was not re-read, so read the paper before implementing.*

---

## 3. Interventions and experiment design for causal discovery

### 3.1 Kinds of intervention, and what ours are

- **Hard (surgical) interventions** set a variable and cut all its incoming arrows (do()).
- **Soft (parametric, mechanism-changing) interventions** change the mechanism but keep its parents
  (Eberhardt and Scheines 2007; Korb et al. 2004). **Shift interventions** add a known amount.
- **Uncertain or unknown-target interventions:** the change is known to happen, but not where (Eaton
  and Murphy 2007; Squires, Wang and Uhler 2020; Mooij, Magliacane and Claassen 2020).

**Ours.**
- An **injection** (`{t, stock, amount}`) is a shift intervention on one stock's level at the start of
  a step, with known target, time and amount. Unrolled in time, it is a hard intervention on
  "level(t) after the injection" relative to its pre-injection value. Every structural equation stays
  the same after it, so every row's equation is *invariant* across injected and calm stretches.
  Chosen at random, injections are independent of every unannounced inflow and every noise draw.
  They are ideal instruments.
- An **announced era** is a soft intervention with a known time and an **unknown target**. Some flow
  rates change; which ones is not said.
- An **unannounced change** (inflow piece, latent era) is an unknown intervention at an unknown time.
- A **pulse** found in the data ([impulse-inputs](../impulse-inputs.md)) is an estimated shift
  intervention: an injection nobody announced.

### 3.2 How many interventions, and which

Results for static DAGs:
- **Eberhardt, Glymour and Scheines (2005):** with N variables, no hidden ones, no selection bias and
  no feedback cycles, log2(N) + 1 experiments are sufficient and in the worst case necessary when each
  experiment may randomise any number of variables at once. If each experiment intervenes on one
  variable only, N-1 experiments suffice and are in the worst case necessary. (That result is from
  Eberhardt, Glymour and Scheines 2006, which the 2005 paper cites.)
- **Eberhardt and Scheines (2007)** compare hard ("structural") and soft ("parametric")
  interventions. Hard ones need N-1 single experiments or log2(N) + 1 combined ones. Soft
  interventions on *every* variable at once can identify the graph in **a single experiment**, under
  causal sufficiency (their Theorem 2). The intervened variables keep their causes, so their
  dependence on those causes stays visible. Our injections are soft in exactly this sense: a level
  shifted by a known random amount keeps its own dynamics.
- **Hauser and Bühlmann (2012)** characterise the equivalence classes that a mix of observational and
  interventional data leaves (interventional Markov equivalence) and learn them greedily (GIES).
  **Hauser and Bühlmann (2014)** give two optimal active-learning strategies. One is greedy: intervene
  on the single variable that lets the most edges be oriented in the worst case. The other finds, in
  polynomial time, a smallest set of interventions of any size that makes the graph fully
  identifiable.
- **Hyttinen, Eberhardt and Hoyer (2013)** relate experiment selection to *separating systems*, for
  graphs with cycles and latent variables too. **He and Geng (2008)**, **Tong and Koller (2001)** and
  **Murphy (2001)** choose the next intervention by expected information. **Shanmugam et al. (2015)**
  bound the number of small interventions needed. **Kocaoglu, Shanmugam and Bareinboim (2017)** add
  latent variables. **Agrawal et al. (2019)** design budgeted experiments for a target part of the
  graph.

**Translation for us.** Orientation, the main subject of these papers, is free for us: arrows point
forward in time. What interventions buy us is different:
1. **breaking latent confounding** (shared unannounced inflows: the bow in 1.6);
2. **excitation** (settled loops whose levels no longer move: faithfulness and collinearity);
3. **telling mechanisms apart** (link vs move, hidden stock vs slow drain, the elderly -> adults
   reversal on sd-population).

The counting results carry over in spirit. One probe per stock (N-1) is the safe design. Probes into
several stocks at once, with independent random amounts, separate their effects by regression, like a
multi-input excitation signal. That is Eberhardt and Scheines' single simultaneous soft experiment,
in sysid clothing. It needs the amounts to be independent across stocks and the responses to stay
roughly linear. The "which one next"
results carry over directly: probe the stock whose *outgoing* structure the surviving candidates
disagree on most (section 5, idea 4).

### 3.3 Invariance: environments instead of known interventions

**Invariant causal prediction (ICP)**, Peters, Bühlmann and Meinshausen (2016). Plain words: the
mechanism that produces Y from its true causes is the same in every environment. Spurious predictors
are not. For every candidate predictor set S, test whether the residuals of Y on X_S have the same
distribution in every environment. Every accepted set must contain the true causes, so ICP reports
the intersection of the accepted sets. With probability at least 1 - α it contains no non-cause. It
needs: Y itself not intervened on in any environment, and no hidden confounder of Y with its
predictors (for the basic version). It **says nothing** (empty set) when it cannot tell, rather than
guessing.

Extensions that fit our setting:
- **Nonlinear ICP:** Heinze-Deml, Peters and Meinshausen (2018).
- **Sequential ICP:** Pfister, Bühlmann and Peters (2019). For time series, invariance across time,
  with no need to name the environments.
- **Switching regressions** with discrete latent regimes: Christiansen and Peters (2020). Relevant to
  [latent-eras](../latent-eras.md).
- **Regression invariance** to orient edges: Ghassami et al. (2017).
- **CD-NOD:** Huang et al. (2020) use the time index as a surrogate for unknown changing factors, and
  find *which* mechanisms change.
- **Joint causal inference (JCI):** Mooij, Magliacane and Claassen (2020) add context variables (era
  indicators, injection indicators) to the graph as variables in their own right. Standard discovery
  then finds both the system's graph and the contexts' *targets*.
- **Anchor regression:** Rothenhäusler et al. (2021) interpolate between least squares (γ = 1) and IV
  (γ -> ∞) using exogenous "anchors". Injection amounts and era indicators are anchors.

**Careful with eras.** An era that changes the rate of a move A -> B changes *both* A's and B's
equations. ICP on those two rows *must* reject invariance at that era, which is correct, but then it
says nothing about their parents. Use eras for ICP only on rows they do not touch. The other way
round, the rows that fail invariance at an era are exactly the era's targets (JCI, CD-NOD).
Injections never change an equation, so they are valid environments for every row.

### 3.4 Impulse responses and external instruments

Macroeconometrics measures *dynamic causal effects* of shocks. Sims (1980) introduced VAR impulse
responses. Jordà (2005) estimates them directly by **local projections**: regress y(t+h) on the
shock at t and controls, separately for each h. Stock and Watson (2018) identify dynamic causal
effects with **external instruments**: measured shocks that are exogenous and relevant. Our announced
injections are the ideal case of an external instrument. Their timing and size are known and chosen
independently of everything else. A local projection of every stock's level h steps after an
injection, on the injection amount, gives a model-free response table. Any correct model must
reproduce it (idea 1). The same amounts serve as instruments for the rows (idea 2).

### 3.5 Relation to system identification's experiment design

The two traditions say the same thing in different words:
- **Closed loop.** Sysid: a closed-loop system is identifiable only with an external excitation signal
  ([system identification](system-identification.md), sections 5 and 14). Causal: feedback makes
  every level a descendant of every noise, so a regressor is confounded with past errors (a valid
  adjustment needs every common cause measured). An external signal is an instrument.
- **Persistence of excitation** corresponds to failures of faithfulness, and to the lack of overlap
  in potential-outcomes terms. The causes must move independently enough to be told apart.
- **D-optimal and Box-Hill discrimination** (sysid) correspond to active causal learning
  (Tong-Koller, He-Geng, Hauser-Bühlmann). Choose the experiment whose outcomes the surviving models
  disagree on most. Sysid adds amplitude, spectrum and cost. Causal learning adds *which variable to
  intervene on*, and the guarantee that an intervention removes confounding that no passive design
  can.

---

## 4. Our data against the assumptions

| assumption | used by | our data | consequence |
|---|---|---|---|
| causal sufficiency (no hidden common causes) | backdoor via regression, PCMCI, basic ICP | **no**: hidden stocks, unannounced inflows shared by several stocks | use instruments (injections, eras), front door (measured flows), or LPCMCI/FCI-type outputs |
| no instantaneous effects | Granger = causal, PCMCI | **almost**: flows read start-of-step levels; moves and co-flows share a draw within the step | treat the shared draw as a known bidirected edge (conservation); [shared-noise](../shared-noise.md) |
| acyclic graph | standard SCM/do-calculus | **yes once unrolled** | cyclic theory only for equilibrium questions |
| faithfulness | all constraint-based discovery; forward stepwise | **often violated** in balancing loops near equilibrium and integral control (Andersen 2013; Blom and Mooij 2023) | backward variants; injections to excite; never drop a term only for low correlation |
| stationarity / one graph over time | Granger, PCMCI, VAR-LiNGAM | **no**: eras, pieces, pulses, growth | treat changes as environments (ICP, JCI, CD-NOD) |
| Gaussian or continuous noise | most CI tests, VAR-LiNGAM's opposite | Poisson counts, small integers at low levels | weight by counting variance ([count-likelihoods](../count-likelihoods.md)); non-Gaussianity is a weak, untrusted signal |
| no measurement error | all | **yes**: levels are exact counts | regressing on start-of-step levels is unbiased when nothing is confounded |
| known interventions | interventional discovery, IV | **injections: yes** (target, time, amount); eras: time only | injections are instruments and experiments; eras are environments with unknown target |
| SUTVA (no interference between units) | potential-outcome estimates of responses | injections closer than the system's memory overlap | space probes, or estimate overlapping responses jointly (local projections) |

---

## 5. Applicable ideas, ranked, with experiment briefs

The ranking is by expected value for the goal (behave like the truth). It weighs: does it target a
failure we have measured, are its assumptions met by our data, and is it cheap to test. Ideas 1 to 4
have their own idea documents. Idea 5 is folded into an existing one.

**Bench prerequisite for 1, 2 and 4.** No benchmark example has injections. The engine accepts them
as a run argument (`Truth.run(..., injections=...)`), and the grader already makes them in both
models. Add a bench option `--probes K` to `tests/bench/evaluate.py`. It gives discovery's run and
the fresh grading run each K injections, drawn from a fixed seed: random stock among the measured
ones, random step in the middle 80%, amount ±(0.5 to 1.5) x that stock's median level, spaced at
least 50 steps apart. This changes no simulation (injections are inputs, like eras). Report probed
results *beside* the goal numbers, never in place of them. The goal is defined on unprobed runs.

### Idea 1. An interventional judge: injection responses every candidate must reproduce

- **What it does.** For each probed stock A and each stock B, estimate B's response h = 0..H steps
  after an injection into A by local projection: regress B(t+h) - B(t-1) on the injection amount at
  t, with the levels at t-1 as controls, over all t. Because injections are random, this is an
  unbiased level 2 estimate with no model. Simulate each candidate's response to the same injections
  from the same states. Score the squared gap between the two response tables, scaled by each
  table entry's standard error. Use it as a gate (reject candidates outside the band) or as a judge
  term.
- **Why.** Our judge scores behaviour on the data it saw, which is level 1. A model can fit flat data
  and still be wrong about what happens when the system is pushed. The injection commit measured
  this: sd-population at 3000 steps, -46% on a probed run.
- **Assumptions.** Random timing (we control it). Roughly linear response at the probe size, or
  probes small enough. Spacing longer than the response, or joint estimation of overlapping ones.
  All met by construction.
- **Mechanism test.** Population chain children -> adults -> elderly, births = 0.03 x adults (link),
  3000 steps, counting noise, near equilibrium, 8 probes. Candidate pool: the main line's variants,
  plus the flat-data model with the elderly -> adults reversal. Pass: the response judge ranks the
  reversal below a candidate with the true direction. The chosen model's skill@20 on a fresh probed
  run is at least 20 points above the behaviour judge's choice. Control: no probes leaves the judge
  unchanged.
- Document: [injection-response-judge](../injection-response-judge.md).

### Idea 2. Injections as instruments for confounded rows

- **What it does.** A row whose regressors are correlated with an unannounced inflow gives a biased
  drain. Discovery currently uses the injections only as known changes, so least squares still mixes
  injection-driven variation with confounded variation. Fit such rows by 2SLS or anchor regression,
  with the injection amounts into the row's stock and its upstream stocks at lags 1..k as
  instruments. Gate it on first-stage F > 10. If the IV drain differs from the pieces fit by more
  than 2 SE, re-measure the pieces with the IV drain fixed.
- **Why.** Drain bias from inflow pieces is the playbook's conflict C3. Examples: the pipeline inbox
  drains at 0.11 against a true 0.3; the change-price spiral. [era-instruments](../era-instruments.md)
  proposes era switches as instruments. Injections are stronger, exogenous by construction, and
  available in every probed run.
- **Assumptions.** Exclusion (an injection affects the row's change only through the levels) holds
  once the known injection is subtracted from the change, as `matrix.py` already does. Relevance
  needs probes big enough against counting noise.
- **Mechanism test.** a -> b at 0.2, b drains at 0.3, and b has an unannounced outside inflow that
  changes every 20-60 steps (a random walk of levels), 1000 steps, 10 probes into b and 10 into a.
  Baseline (least squares with injections subtracted): b's drain off by more than 0.05. IV: within
  0.02. Control: no probes gives a first-stage F below 10, so the main line is unchanged.
- Document: [injection-instruments](../injection-instruments.md).

### Idea 3. Invariance across eras and probes: which rows an era changed, and which predictors are real

- **What it does.** (a) **Era targets.** The "numbers per era" variant now gives *every* level a row
  uses its own number in each configuration. Instead, test each row, and each coefficient, for change
  at each announced era: a Chow-type test of the row's residuals before and after, as in JCI and
  CD-NOD. Split only what fails. Conservation pairs a failing source row with a failing receiving row,
  which names the flow the era changed. (b) **ICP on probes.** For a row, a candidate predictor set
  is accepted only if its residuals are invariant between probed and calm stretches. Report the
  intersection of accepted sets, and drop a link that is in the chosen model but not in the
  intersection.
- **Why.** Splitting every coefficient per era multiplies parameters and lets noise in. On short era
  runs that costs skill. The latent-eras and row-crossover results show judges fooled by flexible
  candidates. ICP's empty answer when it cannot decide is a natural "not supported by the data"
  signal for [bench-instrumentation](../bench-instrumentation.md).
- **Assumptions.** (a) needs eras long enough on each side (at least about 30 steps). (b) needs no
  confounder of the row with its predictors other than through what injections move, and enough
  probes to shift the predictors' distribution.
- **Mechanism test.** (a) Chain a -> b -> c with outside inflow into a; an announced era at t = 500
  changes only b -> c from 0.2 to 0.4; 1000 steps. Pass: rows b and c flagged, a not; the b -> c move
  named; parameter error and skill@100 better than split-everything. Control: an era announced with
  no change flags nothing in 95% of seeds. (b) b and c share an unannounced inflow, and the truth has
  no c -> b link. The main line picks a spurious c -> b link. With 10 probes into c, ICP's
  intersection excludes it.
- Document: [invariant-rows](../invariant-rows.md).

### Idea 4. Probe design: which stock to inject, when and how much

- **What it does.** Take the surviving candidates: the variants within the judge's noise, or a
  bootstrap ensemble. For each probe in a menu (each measured stock, ± one or two amounts, a few
  times including settled stretches), simulate every candidate and score the predicted divergence
  between them, scaled by Poisson variance (Box-Hill). Prefer probes into stocks whose *outgoing*
  edges the candidates disagree on (causal active learning). Prefer simultaneous probes with
  independent random amounts when several stocks are disputed (the simultaneous soft design of Eberhardt and Scheines 2007). Run
  the top probes, rediscover, repeat. In the product this becomes the "to tell these apart, try ..."
  report. Running it on a live system needs the user's sign-off.
- **Why.** Random probes waste injections on stocks whose structure is already clear. sd-population
  is not excited enough to decide ([benchmark-excitation](../benchmark-excitation.md)).
- **Assumptions.** The candidate set contains a correct-enough model (else the design chases the
  wrong question). Probe size within linear range.
- **Mechanism test.** sd-population-like chain with 8 probes. Compare designed probes (2 rounds of
  4) against 8 random probes and against none. Pass: designed probes pick the true direction and
  give higher skill@20 on a fresh probed run than random ones, in at least 8 of 10 seeds.
- Document: [probe-design](../probe-design.md); links from [experiment-design](../experiment-design.md).

### Idea 5. A causal identifiability report (folded into identifiability)

For the chosen structure, build the unrolled graph with hidden stocks and unannounced shared inflows
as latent nodes. Run the ID criterion (backdoor, front door through measured flows, IV through eras
and injections) per link. Report: "identified from the data", "identified only through the
instrument X", or "not identifiable: an injection into A would identify it". That feeds idea 4 and
the page. It is reporting rather than skill, so it is ranked last, and it is added as a literature
note to [identifiability](../identifiability.md), not as a separate experiment.

### Not recommended (and why)

- **PCMCI+/LPCMCI or tsFCI as a structure engine:** graph-only, need faithfulness, blind to
  conservation, weak at low counts. Keep as an offline bench baseline ([causal-discovery](../causal-discovery.md)).
- **VAR-LiNGAM to orient instantaneous effects:** orientation within a step is already given by
  conservation (a move's sign). Poisson non-Gaussianity is weak at high counts.
- **Cyclic/equilibrium SCM learning:** we see every step, so the unrolled acyclic model is the right
  object. Equilibrium theory matters for what-ifs and as a warning, not as a fitting method.
- **A separate front-door estimator:** discovery already subtracts measured flows (`opts["known"]`).
  Theory confirms it; nothing to add.

---

## 6. Reading list (checked)

Status: **V** verified as cited; **C** verified with a correction (the corrected form is given);
**V\*** paper and venue verified, page numbers not checked against a live source.
★ = start here.

### The algebra of causation
- ★ V Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*, 2nd ed. Cambridge University Press. doi:10.1017/CBO9780511803161
- V Pearl, J. (1995). Causal diagrams for empirical research. *Biometrika* 82(4):669-688. doi:10.1093/biomet/82.4.669
- V\* Pearl, J. (2012). The do-calculus revisited. *Proc. UAI 2012*, 4-11. arXiv:1210.4852
- V\* Huang, Y., Valtorta, M. (2006). Pearl's calculus of intervention is complete. *Proc. UAI 2006*, 217-224. arXiv:1206.6831
- V\* Shpitser, I., Pearl, J. (2006). Identification of joint interventional distributions in recursive semi-Markovian causal models. *Proc. AAAI 2006*, 1219-1226.
- V\* Tian, J., Pearl, J. (2002). A general identification condition for causal effects. *Proc. AAAI 2002*, 567-573.
- ★ V Bareinboim, E., Correa, J.D., Ibeling, D., Icard, T. (2022). On Pearl's hierarchy and the foundations of causal inference. In *Probabilistic and Causal Inference: The Works of Judea Pearl*, ACM Books, 507-556. doi:10.1145/3501714.3501743
- V Rubin, D.B. (1974). Estimating causal effects of treatments in randomized and nonrandomized studies. *J. Educational Psychology* 66(5):688-701. doi:10.1037/h0037350
- V Holland, P.W. (1986). Statistics and causal inference. *JASA* 81(396):945-960. doi:10.1080/01621459.1986.10478354
- V Imbens, G.W., Rubin, D.B. (2015). *Causal Inference for Statistics, Social, and Biomedical Sciences*. Cambridge University Press. doi:10.1017/CBO9781139025751
- V Hernán, M.A., Robins, J.M. (2020). *Causal Inference: What If*. Chapman & Hall/CRC.
- V Spirtes, P., Glymour, C., Scheines, R. (2000). *Causation, Prediction, and Search*, 2nd ed. MIT Press. doi:10.7551/mitpress/1754.001.0001 (print 2000; the DOI record is dated 2001)
- V\* Verma, T., Pearl, J. (1990). Equivalence and synthesis of causal models. *Proc. 6th UAI*, 255-270.
- ★ V Peters, J., Janzing, D., Schölkopf, B. (2017). *Elements of Causal Inference: Foundations and Learning Algorithms*. MIT Press (open access).
- C Uhler, C., Raskutti, G., Bühlmann, P., Yu, B. (2013). Geometry of the faithfulness assumption in causal inference. *Annals of Statistics* 41(2):436-463. doi:10.1214/12-AOS1080 (title corrected)
- V Andersen, H. (2013). When to expect violations of causal faithfulness and why it matters. *Philosophy of Science* 80(5):672-683. doi:10.1086/673937
- V Zhang, J., Spirtes, P. (2008). Detection of unfaithfulness and robust causal inference. *Minds and Machines* 18(2):239-271. doi:10.1007/s11023-008-9096-4
- V Dawid, A.P. (2002). Influence diagrams for causal modelling and inference. *International Statistical Review* 70(2):161-189. doi:10.1111/j.1751-5823.2002.tb00354.x (regime indicators: an announced era is one)
- V Glymour, C., Zhang, K., Spirtes, P. (2019). Review of causal discovery methods based on graphical models. *Frontiers in Genetics* 10:524. doi:10.3389/fgene.2019.00524
- V\* Simon, H.A. (1953). Causal ordering and identifiability. In Hood, W.C., Koopmans, T.C. (eds.), *Studies in Econometric Method*, Wiley, 49-74.
- V Iwasaki, Y., Simon, H.A. (1994). Causality and model abstraction. *Artificial Intelligence* 67(1):143-194. doi:10.1016/0004-3702(94)90014-0
- V Dash, D. (2005). Restructuring dynamic causal systems in equilibrium. *Proc. AISTATS 2005*, PMLR R5:81-88. https://proceedings.mlr.press/r5/dash05a.html
- V Sachs, K., Perez, O., Pe'er, D., Lauffenburger, D.A., Nolan, G.P. (2005). Causal protein-signaling networks derived from multiparameter single-cell data. *Science* 308(5721):523-529. doi:10.1126/science.1105809 (interventional discovery in practice)

### Time series, cycles and dynamical systems
- ★ V Runge, J., Nowack, P., Kretschmer, M., Flaxman, S., Sejdinovic, D. (2019a). Detecting and quantifying causal associations in large nonlinear time series datasets. *Science Advances* 5(11):eaau4996. doi:10.1126/sciadv.aau4996
- V Runge, J., Bathiany, S., Bollt, E., et al. (2019b). Inferring causation from time series in Earth system sciences. *Nature Communications* 10:2553. doi:10.1038/s41467-019-10105-3
- C Runge, J. (2018). Causal network reconstruction from time series: From theoretical assumptions to practical estimation. *Chaos: An Interdisciplinary Journal of Nonlinear Science* 28(7):075310. doi:10.1063/1.5025050
- (PCMCI+ and LPCMCI: Runge 2020, UAI; Gerhardus and Runge 2020, NeurIPS; cited in [signals](signals-and-time-series.md).)
- V\* Entner, D., Hoyer, P.O. (2010). On causal discovery from time series data using FCI. *Proc. PGM 2010*, 121-128. (pages from secondary references)
- V Malinsky, D., Spirtes, P. (2018). Causal structure learning from multivariate time series in settings with unmeasured confounding. *Proc. ACM SIGKDD Workshop on Causal Discovery*, PMLR 92:23-47.
- V Hyvärinen, A., Zhang, K., Shimizu, S., Hoyer, P.O. (2010). Estimation of a structural vector autoregression model using non-Gaussianity. *JMLR* 11:1709-1731.
- V Shimizu, S., Hoyer, P.O., Hyvärinen, A., Kerminen, A. (2006). A linear non-Gaussian acyclic model for causal discovery. *JMLR* 7:2003-2030.
- C Peters, J., Janzing, D., Schölkopf, B. (2013). Causal inference on time series using restricted structural equation models. *NIPS 26*, 154-162. (pages added)
- V Eichler, M. (2012). Graphical modelling of multivariate time series. *Probability Theory and Related Fields* 153(1-2):233-268. doi:10.1007/s00440-011-0345-8
- ★ V Eichler, M., Didelez, V. (2010). On Granger causality and the effect of interventions in time series. *Lifetime Data Analysis* 16(1):3-32. doi:10.1007/s10985-009-9143-3
- C White, H., Lu, X. (2010). Granger causality and dynamic structural systems. *J. Financial Econometrics* 8(2):193-243. doi:10.1093/jjfinec/nbq006 (DOI added)
- V Hyttinen, A., Plis, S., Järvisalo, M., Eberhardt, F., Danks, D. (2016). Causal discovery from subsampled time series data by constraint optimization. *Proc. PGM 2016*, PMLR 52:216-227.
- V Bongers, S., Forré, P., Peters, J., Mooij, J.M. (2021). Foundations of structural causal models with cycles and latent variables. *Annals of Statistics* 49(5):2885-2915. doi:10.1214/21-AOS2064
- V Hyttinen, A., Eberhardt, F., Hoyer, P.O. (2012). Learning linear cyclic causal models with latent variables. *JMLR* 13:3387-3439.
- V Richardson, T.S. (1996). A discovery algorithm for directed cyclic graphs. *Proc. UAI 1996*, 454-461. arXiv:1302.3599
- C Lacerda, G., Spirtes, P., Ramsey, J., Hoyer, P.O. (2008). Discovering cyclic causal models by independent components analysis. *Proc. UAI 2008*, 366-374. arXiv:1206.3273 (pages added)
- ★ V Mooij, J.M., Janzing, D., Schölkopf, B. (2013). From ordinary differential equations to structural causal models: the deterministic case. *Proc. UAI 2013*, 440-448. arXiv:1304.7920
- C Rubenstein, P.K., Bongers, S., Schölkopf, B., Mooij, J.M. (2018). From deterministic ODEs to dynamic structural causal models. *Proc. UAI 2018*, 114-123. arXiv:1608.08028 (pages added)
- C Bongers, S., Blom, T., Mooij, J.M. (2022). Causal modeling of dynamical systems. arXiv:1803.08784 (preprint; first posted 2018 as "From random differential equations to structural causal models: the stochastic case")
- C Hansen, N., Sokol, A. (2014). Causal interpretation of stochastic differential equations. *Electronic Journal of Probability* 19:100, 1-24. doi:10.1214/EJP.v19-2891
- ★ V Blom, T., Bongers, S., Mooij, J.M. (2020). Beyond structural causal models: causal constraints models. *Proc. UAI 2019*, PMLR 115:585-594.
- V Blom, T., van Diepen, M.M., Mooij, J.M. (2021). Conditional independences and causal relations implied by sets of equations. *JMLR* 22(178):1-62.
- C Blom, T., Mooij, J.M. (2023). Causality and independence in perfectly adapted dynamical systems. *Journal of Causal Inference* 11(1):20210005. doi:10.1515/jci-2021-0005 (venue corrected)
- ★ V Pfister, N., Bauer, S., Peters, J. (2019). Learning stable and predictive structures in kinetic systems. *PNAS* 116(51):25405-25411. doi:10.1073/pnas.1905688116 (CausalKinetiX)

### Interventions, experiment design, invariance
- ★ V Eberhardt, F., Glymour, C., Scheines, R. (2005). On the number of experiments sufficient and in the worst case necessary to identify all causal relations among N variables. *Proc. UAI 2005*, 178-184. arXiv:1207.1389
- (unverified here: cited by the 2005 paper) Eberhardt, F., Glymour, C., Scheines, R. (2006). N-1 experiments suffice to determine the causal relations among N variables. In Holmes, D.E., Jain, L.C. (eds.), *Innovations in Machine Learning*, Springer.
- ★ V Eberhardt, F., Scheines, R. (2007). Interventions and causal inference. *Philosophy of Science* 74(5):981-995. doi:10.1086/525638 (the counts by intervention type were read in the preprint)
- V Eberhardt, F. (2017). Introduction to the foundations of causal discovery. *Int. J. Data Science and Analytics* 3(2):81-91. doi:10.1007/s41060-016-0038-6
- V Korb, K.B., Hope, L.R., Nicholson, A.E., Axnick, K. (2004). Varieties of causal intervention. *PRICAI 2004*, LNCS 3157:322-331. doi:10.1007/978-3-540-28633-2_35
- C Eaton, D., Murphy, K. (2007). Exact Bayesian structure learning from uncertain interventions. *AISTATS 2007*, PMLR 2:107-114. (title corrected)
- V Squires, C., Wang, Y., Uhler, C. (2020). Permutation-based causal structure learning with unknown intervention targets. *UAI 2020*, PMLR 124:1039-1048.
- V Hauser, A., Bühlmann, P. (2012). Characterization and greedy learning of interventional Markov equivalence classes of directed acyclic graphs. *JMLR* 13:2409-2464.
- ★ V Hauser, A., Bühlmann, P. (2014). Two optimal strategies for active learning of causal models from interventional data. *Int. J. Approximate Reasoning* 55(4):926-939. doi:10.1016/j.ijar.2013.11.007
- V Hyttinen, A., Eberhardt, F., Hoyer, P.O. (2013). Experiment selection for causal discovery. *JMLR* 14:3041-3071.
- V He, Y.-B., Geng, Z. (2008). Active learning of causal networks with intervention experiments and optimal designs. *JMLR* 9:2523-2547.
- V Tong, S., Koller, D. (2001). Active learning for structure in Bayesian networks. *Proc. IJCAI 2001*, 863-869.
- V Murphy, K.P. (2001). Active learning of causal Bayes net structure. Technical report, UC Berkeley. https://www.cs.ubc.ca/~murphyk/Papers/alearn.pdf
- V Shanmugam, K., Kocaoglu, M., Dimakis, A.G., Vishwanath, S. (2015). Learning causal graphs with small interventions. *NeurIPS 28*, 3195-3203.
- V Kocaoglu, M., Shanmugam, K., Bareinboim, E. (2017). Experimental design for learning causal graphs with latent variables. *NeurIPS 30*, 7018-7028.
- V Agrawal, R., Squires, C., Yang, K., Shanmugam, K., Uhler, C. (2019). ABCD-Strategy: Budgeted experimental design for targeted causal structure discovery. *AISTATS 2019*, PMLR 89:3400-3409.
- ★ V Peters, J., Bühlmann, P., Meinshausen, N. (2016). Causal inference by using invariant prediction: identification and confidence intervals. *JRSS B* 78(5):947-1012. doi:10.1111/rssb.12167
- V Heinze-Deml, C., Peters, J., Meinshausen, N. (2018). Invariant causal prediction for nonlinear models. *J. Causal Inference* 6(2):20170016. doi:10.1515/jci-2017-0016
- ★ V Pfister, N., Bühlmann, P., Peters, J. (2019). Invariant causal prediction for sequential data. *JASA* 114(527):1264-1276. doi:10.1080/01621459.2018.1491403
- V Christiansen, R., Peters, J. (2020). Switching regression models and causal inference in the presence of discrete latent variables. *JMLR* 21(41):1-46.
- V Ghassami, A., Salehkaleybar, S., Kiyavash, N., Zhang, K. (2017). Learning causal structures using regression invariance. *NeurIPS 30*, 3011-3021.
- V Huang, B., Zhang, K., Zhang, J., Ramsey, J., Sanchez-Romero, R., Glymour, C., Schölkopf, B. (2020). Causal discovery from heterogeneous/nonstationary data. *JMLR* 21(89):1-53.
- ★ V Mooij, J.M., Magliacane, S., Claassen, T. (2020). Joint causal inference from multiple contexts. *JMLR* 21(99):1-108.
- V Rothenhäusler, D., Meinshausen, N., Bühlmann, P., Peters, J. (2021). Anchor regression: heterogeneous data meet causality. *JRSS B* 83(2):215-246. doi:10.1111/rssb.12398

### Impulse responses and external instruments
- V Sims, C.A. (1980). Macroeconomics and reality. *Econometrica* 48(1):1-48. doi:10.2307/1912017
- ★ V Jordà, Ò. (2005). Estimation and inference of impulse responses by local projections. *American Economic Review* 95(1):161-182. doi:10.1257/0002828053828518
- ★ V Stock, J.H., Watson, M.W. (2018). Identification and estimation of dynamic causal effects in macroeconomics using external instruments. *Economic Journal* 128(610):917-948. doi:10.1111/ecoj.12593

### Tally
73 sources checked by web search: 56 verified as cited (V), 7 verified with page numbers not checked
against a live source (V\*), and 10 verified with a correction (C: titles, venues, DOIs or pages). One
more (Eberhardt, Glymour and Scheines 2006) was not checked directly: it is cited through the 2005
paper. None was not found. The CausalKinetiX method summary in section 2.5 rests on the abstract;
the method section was not re-read.
