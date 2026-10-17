# SD tools and structure discovery: what exists, what to use, what is ours

Research note, 2026-10-17. Question: is SD Lab's discovery (a stock-and-flow model found from
measured stock levels) re-inventing existing tools, and which libraries and methods should we
adopt, interoperate with, or study?

Versions, licences and activity dates were read from PyPI, npm, CRAN and the GitHub API on
2026-10-17 unless another source is cited. "Pushed" is the date of the latest push to the repository.
Statements about SD Lab come from `MODEL.md`, `docs/DISCOVERY.md`, `docs/DISCOVERY-LOOP.md` and
`docs/DISCOVERY-EXPERIMENTS.md` in this repository.

## Bottom line

1. **Simulators and model formats are a solved problem; we should interoperate, not compete.**
   Mature open-source engines read Vensim `.mdl` and XMILE: PySD in Python, BPTK-Py in Python
   (XMILE only), SDEverywhere in JS/C/Wasm, and Simlin in Rust with Python and JS bindings. Simlin's
   Python binding (`pysimlin`) can also **write** XMILE and `.mdl`. That gives us an export path that
   costs very little and makes found models usable in Vensim and Stella.
2. **Calibration of a *given* structure is mature in SD practice.** Vensim fits parameters by
   simulation error (Powell search on a payoff) and offers an extended Kalman filter. Stella has
   built-in optimisation. The current best-practice papers (Li, Rahmandad and Sterman 2025; Andrade
   and Duggan 2021; Stanify) point to count likelihoods (Poisson or negative binomial), Kalman
   filtering with process noise, and Bayesian HMC. None of these tools proposes structure.
3. **Structure discovery from data, with SD semantics, is essentially unserved.** Generic
   equation-discovery tools (PySINDy, PySR, SysIdentPy, DataDrivenDiffEq.jl) find per-variable
   equations. They do not, out of the box, express a flow as one quantity that leaves one stock and
   enters another. Nor do they handle "outside" versus "move" ambiguity, unit-conversion ratios,
   co-flows, eras or Poisson counts. Causal discovery (Tigramite) gives graphs, not flows. The few
   SD-specific attempts are small academic prototypes on textbook models: echo-state networks plus
   genetic programming (Abdelbari and Shafi), and a 2026 ISDC "generative algorithm" that reports
   only partial success on a workforce/inventory model. LLM work (sd-ai, the System Dynamics Bot)
   builds models from *text*, not data. **Every one of the about 25 tools on Wikipedia's
   comparison of SD software was checked (section 1.1a). None infers structure from data**; the
   most any of them does is calibrate parameters of a structure a person drew. OpenModelica
   (section 1.5) is no exception. **The closest real prior art is outside SD**: chemical
   reaction-network inference (Reactive SINDy; stoichiometrically informed symbolic regression).
   Its stoichiometric matrix is our flow matrix.
4. **What to borrow**: count likelihoods and the Kalman/state-space view (for hidden stocks and
   shared noise); ensembles and inclusion probabilities (E-SINDy); weak-form and integral
   formulations (noise robustness); constrained least squares (conservation as linear equalities);
   hybrid/switching SINDy ideas (eras); Loops-that-Matter for explaining found models. Keep the
   matrix method as the core.

---

## 1. Simulation and modelling tools

### 1.1 What each one is

| Tool | What it is | Licence | Language | Library use from Python / JS | Status |
|---|---|---|---|---|---|
| **Vensim** (Ventana) | Desktop SD environment, editions PLE (free for personal/academic use), PLE Plus, Professional, DSS. Professional adds optimisation, subscripts (arrays), causal tracing and Monte Carlo; DSS adds compiled simulation, external functions and macros ([Vensim editions](https://as26.vensim.com/?p=465)). | Proprietary | C/C++ | A Vensim DLL, wrapped by `venpy` in Python. Windows only; PLE can only set constants before a run ([venpy](https://github.com/pbreach/venpy)). | Vensim 10.4.0 is the latest release listed ([Vensim editions](https://as26.vensim.com/?p=465)) |
| **Stella Architect / Professional, iThink** (isee systems) | Desktop SD environment. It has four stock types: reservoir, conveyor, queue and oven ([isee help: Stocks](https://iseesystems.com/resources/help/v3/Content/08-Reference/01-ObjectsAndProperties/01-BuildingBlocks/Stocks.htm), [discrete stocks](https://www.iseesystems.com/resources/help/v3/Content/08-Reference/05-Computational_Details/InitializingDiscreteStocks.htm)). Optimisation has been built in since version 1.5 and is also used for calibration ([isee blog](https://blog.iseesystems.com/?p=4250)). Loops-that-Matter analysis has been built in since 2.0 ([Schoenberg et al. 2021](https://proceedings.systemdynamics.org/2021/papers/P1036.pdf)). The sd-ai gateway has been in Stella since 4.3 ([isee help](https://www.iseesystems.com/resources/help/v4/Content/03-BuildingModels/Using_AI/SD-AIGateway.htm), [SDS seminar](https://systemdynamics.org/making-system-dynamics-more-accessible-through-ai-guided-modeling/)). | Proprietary | Native XMILE format | Not as a library, but its XMILE files are read by PySD, BPTK-Py, SDEverywhere and Simlin | Active |
| **AnyLogic** | Multi-method tool (SD, agent-based, discrete-event). Stock equations are built from the diagram ([AnyLogic help: stock](https://anylogic.help/anylogic/system-dynamics/stock.html)). The free PLE is for learning only and caps SD variables at 200 per agent type ([editions](https://anylogic.help/anylogic/ui/editions.html)). | Proprietary | Java | Java models only | Active |
| **Powersim Studio** | Desktop SD with arrays and scripting ([ISDC 2024 workshop](https://proceedings.systemdynamics.org/2024/abstracts/1001.html)). A free Studio 10 Express edition exists. An SDK is sold for connecting to other tools ([Capterra](https://www.capterra.com/p/110874/Powersim-Studio/)). | Proprietary | .NET | Through the SDK | Active (workshops through 2026: [ISDC 2026](https://proceedings.systemdynamics.org/2026/abstracts/1069.html)) |
| **Insight Maker** / `simulation` | Web SD and agent-based modelling. Its engine is the npm package `simulation`, which also reads ModelJSON and Insight Maker files ([README](https://github.com/scottfr/simulation)). It has a built-in optimiser that can fit parameters to data ([Insight Maker optimisation](https://insightmaker.com/optimization)). | **AGPL-3.0** (repository LICENSE) | JavaScript | JS library (`simulation` 9.0.0, 2026-06-27) | Pushed 2026-06 |
| **PySD** | Translates Vensim `.mdl` and XMILE into Python, then runs, modifies and observes the model ([docs](https://pysd.readthedocs.io/), [JOSS paper](https://theoj.org/joss-papers/joss.04329/10.21105.joss.04329.pdf)). Since 3.0 it parses to an abstract model representation ([JOSS](https://theoj.org/joss-papers/joss.04329/10.21105.joss.04329.pdf)). An experimental Julia/ModelingToolkit backend is unreleased in 3.15.0 ([changelog](https://github.com/SDXorg/pysd/blob/master/docs/whats_new.rst)). Unsupported functions become placeholders ([docs](https://pysd.readthedocs.io/)). | MIT | Python (≥3.9) | Python library. **Import only**; no export to `.mdl` or XMILE. | 3.14.3 (2025-03-23); pushed 2026-10; 463 stars |
| **BPTK-Py** (transentis) | SD, agent-based and hybrid models in Python, with an SD DSL and a compiled Rust engine. It runs in Pyodide and transpiles XMILE (Stella/iThink) to Python ([README](https://github.com/transentis/bptk_py)). | MIT | Python (≥3.12) + Rust | Python library | 3.4.1 (2026-10-16); 37 stars |
| **SDEverywhere** (Climate Interactive) | Transpiles Vensim and Stella (XMILE) models to C, JavaScript and WebAssembly, with model-check and comparison tools ([README](https://github.com/climateinteractive/SDEverywhere)). | MIT | TypeScript | JS/TS (`@sdeverywhere/cli` 0.7.49, 2026-09-20) | Pushed 2026-10; 89 stars |
| **Simlin** (Bobby Powers) | Web SD editor and engine, compiled to WebAssembly ([README](https://github.com/bpowers/simlin)). `pysimlin` loads XMILE, Vensim `.mdl`, sd-ai JSON and Simlin JSON. It simulates, runs Loops-that-Matter analysis, edits and builds models, and **saves back in XMILE, `.mdl` or JSON**. It also ships an MCP server for AI agents ([pysimlin README](https://github.com/bpowers/simlin/blob/main/src/pysimlin/README.md), [simlin-mcp](https://github.com/bpowers/simlin/blob/main/src/simlin-mcp/README.md)). | Apache-2.0 | Rust (engine), TS, Python bindings | Python (`pysimlin` 0.8.5, 2026-09-15; macOS ARM64 / Linux only; Python ≥3.11) and JS | Pushed 2026-10-12; 99 stars |
| `sd.js` | Bobby Powers' earlier JS engine | MIT | JS | npm 5.2.9 | **Last release 2020-12**: superseded by Simlin |
| `stockflow` (jdherman) | A thin wrapper around scipy `odeint` | MIT | Python | Python | Last push 2017: dormant |
| `pyndamics` (bblais) | A small dynamics simulator | MIT | Python | Python | Last push 2020; not on PyPI |
| `pysd2cat` | Not found on PyPI or in our searches. Ask the requester for the source. | | | | |
| EMA Workbench (TU Delft) | Exploratory modelling and analysis (scenarios, sensitivity), which wraps PySD and Vensim models ([PySD complementary projects](https://github.com/SDXorg/pysd/blob/master/docs/complement.rst)) | BSD-3 | Python | Python (`ema-workbench` 3.0.0, 2026-03-12) | Active |

### 1.1a Every tool on Wikipedia's "Comparison of system dynamics software"

Every package in the table at
[Wikipedia: Comparison of system dynamics software](https://en.wikipedia.org/wiki/Comparison_of_system_dynamics_software)
(read 2026-10-17) is listed below. For each one, the key question is: **can it find a model's
structure from data, or only calibrate parameters of a structure a person drew?** Open-source
entries were checked against their repositories and package indexes. Commercial entries are
described from the Wikipedia row unless another source is linked.

| Package | Licence | Language | Maintained? | Library use from Python / JS | XMILE / Vensim import-export | Finds structure from data? |
|---|---|---|---|---|---|---|
| AMESim (Siemens) | Proprietary | C | Commercial product | No | No (Modelica supported) | **No** |
| Analytica | Proprietary (free limited edition) | C++ | Commercial | No | No | **No** (optimisation and Monte Carlo only) |
| AnyLogic | Proprietary (free PLE) | Java | Commercial | Java only | No | **No** (calibration experiment for parameters) |
| ASCEND | GPL | C | Wikipedia's last update is 2012; the project says it is migrating to GitHub ([ascend4.org](https://ascend4.org/), [GitHub](https://github.com/ascend4/ascend4)) | Not as an SD library (it is a general equation solver) | No | **No** |
| Berkeley Madonna | Proprietary | C++, Java | Users guide 9.2.2, 2020 ([guide](https://www.berkeleymadonna.com/downloads/BM_Users_Guide_9.2.pdf)) | No | No | **No** (a curve fitter for parameters) |
| Dymola (Dassault) | Proprietary | C++ | Commercial | Via FMI export | No (Modelica, FMI) | **No** |
| DYNAMO | Proprietary | Pascal | Historic (1986), not distributed | No | No | **No** |
| GoldSim | Proprietary | C++ | Commercial | No | No | **No** |
| iThink / Stella (isee) | Proprietary | C++, JS | Commercial, active | No (files only) | XMILE native | **No.** Optimisation/calibration of parameters. sd-ai drafts models from *text* ([sd-ai](https://github.com/UB-IAD/sd-ai)). |
| **LunaSim** | Free/open source (Wikipedia; we found no repository) | JavaScript | Papers 2024-2026 ([ISDC 2024](https://proceedings.systemdynamics.org/2024/abstracts/1049.html), [ISDC 2026](https://proceedings.systemdynamics.org/2026/abstracts/1550.html)) | Web app | Not stated | **No.** Its "Copilot" generates models from chat, not data ([ISDC 2025 paper](https://proceedings.systemdynamics.org/2025/papers/P1167.pdf)). |
| MapleSim | Proprietary | Java, C, Maple | Commercial | No | No (Modelica) | **No** |
| **NetLogo** | GPL-2.0 | Scala/Java | Active (pushed 2026-10-16, [GitHub](https://github.com/NetLogo/NetLogo)) | Java | No | **No** (agent-based; SD is secondary) |
| **OpenModelica** | OSMC Public License (GPL-3 or OSMC-PL terms; [repo licence file](https://github.com/OpenModelica/OpenModelica/blob/master/OSMC-License.txt)) | C, C++, MetaModelica | Active: v1.27.1, 2026-09-08 ([GitHub](https://github.com/OpenModelica/OpenModelica)) | Python via OMPython 4.1.0 (PyPI) and FMUs (`fmpy`) | No XMILE or Vensim | **No.** Parameter estimation of FMUs only (OMSysIdent), and that is stale. See section 1.5. |
| **PathSim** | MIT | Python | Active: 0.27.1, 2026-10-12 ([GitHub](https://github.com/pathsim/pathsim)) | Python library (block diagrams, differentiable) | No | **No** |
| SAAM II | Proprietary | — | Commercial | No | No | **No.** It fits parameters of user-drawn compartmental models, with Bayesian MAP ([Wikipedia](https://en.wikipedia.org/wiki/SAAM_II)). |
| **se-lib** | MIT | Python | Active: 0.53, 2026-07-07 (PyPI; [se-lib.org](http://se-lib.org)) | Python library (SD and discrete-event simulation) | No | **No** |
| Silico | Proprietary | — | Unknown | No | No | **No** |
| Simcad Pro | Proprietary | — | Commercial | No | No | **No** |
| **Simantics System Dynamics** (VTT, Semantum) | EPL | Java, Modelica | Docs mention Simantics 1.8.0 and OpenModelica 1.9.0 beta, so it looks dated ([wiki](https://wiki.simantics.org/index.php/Simantics_System_Dynamics), [site](https://sysdyn.simantics.org/)) | No | Exports Modelica code | **No** |
| Simulink | Proprietary | — | Commercial | MATLAB | No | **No** (MATLAB's System Identification Toolbox fits generic models, not SD structures; see section 3) |
| **StochSD** | AGPL-3.0 | JavaScript (Insight Maker engine) | Active (pushed 2026-10-11, [GitHub](https://github.com/stochsd/stochsd)) | Web app | No | **No** (optimisation and parameter estimation tools, per Wikipedia) |
| Vensim | Proprietary (free PLE) | C, C++ | Commercial, 10.4.0 | DLL (Windows; [venpy](https://github.com/pbreach/venpy)) | `.mdl` native | **No.** Calibration optimisation, Kalman filtering and MCMC for parameters ([Vensim payoff docs](https://vensim.com/documentation/payoffcomputation.html)). |
| VisSim | Proprietary | C | Wikipedia's last update is 2011 | No | No | **No** |
| Wolfram SystemModeler | Proprietary | — | Commercial | Mathematica | No (Modelica, FMI) | **No.** `SystemModelCalibrate` fits the parameters of a given model ([reference](https://reference.wolfram.com/language/ref/SystemModelCalibrate.html)). |
| SystemDynamics Modelica library (Cellier et al.) | BSD-3 | Modelica | Low activity: v2.1.2, 2023-02 ([GitHub](https://github.com/modelica-3rdparty/SystemDynamics)) | Through OpenModelica | No | **No** |
| Business Simulation Library (BSL) | EUPL-1.2 | Modelica | Low activity: pushed 2024-04 ([GitHub](https://github.com/modelica-3rdparty/BusinessSimulation)) | Through a Modelica tool | No | **No** |

**Plain answer: none of the tools on that list can infer an SD model's structure from data.** The
best any of them offers is calibration of parameters in a structure a person drew: Vensim
(optimiser, Kalman filter, MCMC), Stella, AnyLogic, Berkeley Madonna, SAAM II, Wolfram's
`SystemModelCalibrate`, StochSD, and OpenModelica's OMSysIdent. The only "generation" features
(Stella's sd-ai, LunaSim Copilot) draft models from text with LLMs. The open-source SD engines
outside the list (PySD, BPTK-Py, SDEverywhere, Simlin) have no structure inference either.

### 1.2 SD Lab's format compared with theirs

SD Lab's model is a JSON list of stocks and flows. Each flow's rate takes one of five forms:
`constant`, `proportional`, `gap`, `available` or `linear` (Σ k × level). A rate can be
multiplied by `effects`: a linear clamp or a piecewise-linear table of another stock's level.
`uses` declares co-flows, and announced eras switch rates. Levels and rates are floored at 0, and
hidden (`inferred`) stocks are drawn as exp, Erlang or pipe delays (`MODEL.md`).

What the standard tools support that we do not:

| Capability | Vensim / Stella / XMILE | SD Lab |
|---|---|---|
| **General equation language**: auxiliaries, IF THEN ELSE, MIN/MAX, arithmetic on any variables | Yes. XMILE requires a full expression language with maths, statistical, delay, test-input and time builtins ([XMILE 1.0 §3](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). | No: five fixed rate forms, with no auxiliaries |
| **Graphical functions (lookups)** | Continuous, extrapolate and discrete ([XMILE §3.1.4](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). Vensim warns when a lookup's input is not dimensionless ([Vensim units](https://vensim.com/documentation/22280.html)). | Partly: `effects` are multiplicative lookups of one stock's level, with linear clamp or table shapes |
| **Delay and smoothing builtins** | DELAY, DELAY1, DELAY3, DELAYN, SMTH1, SMTH3, SMTHN, TREND, FORCST ([XMILE](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). PySD implements them for both Vensim and XMILE ([PySD delay table](https://github.com/SDXorg/pysd/blob/master/docs/tables/delay_functions.tab)). | Only as discovered hidden stocks (exp = DELAY1-like, Erlang-2, pipe = DELAY FIXED). They cannot be written as equations. |
| **Arrays / subscripts** | An optional XMILE feature ([XMILE](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). Vensim Professional and above ([Vensim](https://as26.vensim.com/?p=465)). PySD's Julia builder handles full subscripts ([changelog](https://github.com/SDXorg/pysd/blob/master/docs/whats_new.rst)). | No. Our "group" field only restricts discovery. |
| **Conveyors, queues, ovens** | Optional XMILE features. Stella implements them ([isee help](https://iseesystems.com/resources/help/v3/Content/08-Reference/01-ObjectsAndProperties/01-BuildingBlocks/Stocks.htm)). | No. A "pipe" hidden stock is the closest equivalent (a conveyor without leakage). |
| **Units checking** | XMILE has unit definitions and equations ([XMILE](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). Vensim reports dimensional errors and warnings ([Vensim Units Check](https://vensim.com/documentation/22270.html)). | Units are labels per stock. Discovery uses them only to read moves versus links and to choose ratios. There is no dimensional check of equations. |
| **Non-negative stocks and uniflows** | XMILE `<behavior>` sets non-negativity per stock or flow ([XMILE](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)) | Every rate and level is floored at 0 (`simulate.py`) |
| **Reality checks** (constraint tests) | Vensim Reality Check ([Vensim functions](https://www.vensim.com/documentation/ref_functions.html)) | No |
| **Loop dominance analysis** | Loops that Matter in Stella ([Schoenberg, Davidsen and Eberlein 2020](https://www.arxiv.org/abs/1908.11434)) and in pysimlin ([README](https://github.com/bpowers/simlin/blob/main/src/pysimlin/README.md)) | No |

What we have that they do not: live runs of programs and machines, measured runs from sensors and
PromQL, and **discovery**. Co-flows and eras can be written in Vensim or Stella with ordinary
equations, but nothing there finds them from data.

### 1.3 Interoperating through XMILE and `.mdl`

- **XMILE 1.0** has been an OASIS Standard since December 2015 ([OASIS announcement](https://oasis-open.org/?p=4521),
  [spec](https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html)). Its required core (§3.1-3.5:
  stocks, flows, auxiliaries, graphical functions, operators, builtins) covers everything SD Lab can
  express. Our `effects` become a flow equation multiplied by graphical functions. `uses` becomes a
  second outflow equal to `per` × the first flow. Eras become `IF TIME >= …` or a `STEP` sum. A
  hidden exp stock becomes a stock with an outflow of level/delay.
- **Export (recommended)**: generate XMILE ourselves. It is a small, well-specified XML
  subset, and writing it keeps us free of dependencies. Then **validate round-trips with
  `pysimlin`** (Apache-2.0), which loads XMILE and can `save_as` `.mdl`
  ([pysimlin README](https://github.com/bpowers/simlin/blob/main/src/pysimlin/README.md)). It is
  the only open-source library we found that writes Vensim format. Alternatively, use pysimlin's
  edit API to build the model and save it in either format. Caveat: its wheels are macOS ARM64 and
  Linux only.
- **Import**: PySD (MIT) parses `.mdl` and XMILE into an abstract syntax
  ([JOSS](https://theoj.org/joss-papers/joss.04329/10.21105.joss.04329.pdf)), and so does pysimlin.
  We can only import models that fit our five forms. Anything else needs an "unsupported" report,
  or an `available`/opaque flow.
- **Test corpus**: SDXorg/test-models (MIT) holds canonical SD models in several formats
  ([repo](https://github.com/SDXorg/test-models)). These are candidate ground truths beyond our own
  `sd-*` examples, *if* they translate into our forms.

### 1.5 OpenModelica in plain terms, and whether it helps us

**What it is.** Modelica is a language for describing physical systems as **equations**, not as
step-by-step assignments.

- You write `der(x) = inflow - outflow` and connect components through ports. The tool works
  out which variable is computed from which. This is "acausal" modelling: a resistor model does
  not decide whether current or voltage is the input.
- The result is a system of differential-algebraic equations (DAEs). The compiler simplifies it
  symbolically and hands it to a numerical solver
  ([DLR on Modelica and FMI](https://www.dlr.de/en/rm/research/expertise/modelling/modelica);
  [arXiv 2606.22544](https://arxiv.org/pdf/2606.22544)).
- Reusable component libraries (electrical, mechanical, thermal, and the Modelica Standard
  Library) are the point of the language.
- Models can be exported as **FMUs**. The Functional Mock-up Interface is a free standard: a zip
  of XML, binaries and C code that more than 230 tools can run. It is maintained by the Modelica
  Association ([fmi-standard.org](https://fmi-standard.org/)).

**OpenModelica** is the open-source implementation, from the Open Source Modelica Consortium
(v1.27.1, 2026-09-08; [GitHub](https://github.com/OpenModelica/OpenModelica)). It consists of:

- the `omc` compiler;
- the OMEdit graphical editor;
- OMPython (4.1.0 on PyPI) and OMJulia scripting, with `setParameters`, `simulate` and
  `linearize` ([OMJulia/OMPython API](https://openmodelica.org/doc/OpenModelicaUsersGuide/1.18/omjulia.html));
- FMU export;
- **OMSimulator**, which co-simulates FMUs ([GitHub](https://github.com/OpenModelica/OMSimulator)).

**How it relates to SD.** A stock is just `der(stock) = Σ in − Σ out`, so SD models are easy to
write in Modelica. Two libraries do it:

- The **SystemDynamics** library, started by Fabricius (2002) and reworked by Cellier and his
  students (2.0, 2007). It contains Forrester's WORLD2 and Meadows' WORLD3, and models
  "exclusively based on signal flows". It is BSD-3, with its last release v2.1.2 (2023-02-07),
  which ported it to MSL 4.0. That is low activity
  ([GitHub](https://github.com/modelica-3rdparty/SystemDynamics),
  [docs](https://build.openmodelica.org/Documentation/SystemDynamics.WorldDynamics.html)).
  Cellier himself wrote that Modelica may be more than SD needs
  ([Modelica 2008 paper](https://modelica.org/events/conference2008/sessions/session4a2.pdf)).
- The **Business Simulation Library** (Reichert). It uses acausal connectors for **conserved
  flows of matter** and causal signals for information ([README](https://github.com/modelica-3rdparty/BusinessSimulation),
  [SDR 38(1) 2022](https://doi.org/10.1002/sdr.1703)). EUPL-1.2, last pushed 2024-04, developed
  against Wolfram SystemModeler. Notably, its split between conserved matter connectors and
  information signals is the same distinction as our **moves versus links**.

**What using it would look like for us.**

1. Write each found model as Modelica. For example:

   ```modelica
   model Pipeline
     Real inbox(start=40), working(start=10);
     parameter Real intake=5.75, k1=0.3, k2=0.2;
   equation
     der(inbox)   = intake - k1*inbox;
     der(working) = k1*inbox - k2*working;
   end Pipeline;
   ```

   (Or use the BSL's stock and flow components.)
2. Compile and simulate with `omc` or OMPython. Optionally export an FMU and run it from Python
   with `fmpy` (0.3.32, 2026-09-09, PyPI).
3. To fit parameters:
   - wrap the FMU in scipy, or
   - use OMSimulator's **OMSysIdent** (FMU parameter estimation with the Ceres solver; Python
     and C APIs). OMSysIdent is not bundled, worked on Linux only as of 2020, and was last pushed
     2021-10 ([user guide](https://openmodelica.org/doc/OpenModelicaUsersGuide/1.24/systemidentification.html),
     [GitHub](https://github.com/OpenModelica/OMSysIdent)).

Other estimation-adjacent features:

- **Data reconciliation** (with EDF, in OMEdit since 1.18). It corrects redundant measurements of
  *static* algebraic models ([guide](https://openmodelica.org/doc/OpenModelicaUsersGuide/1.22/dataReconciliation.html)).
- **Parameter sensitivities** (IDA and OMSens) ([guide](https://openmodelica.org/doc/OpenModelicaUsersGuide/1.26/parametersensitivity.html)).
- **Dynamic optimisation** (Optimica, CasADi) and **OMOptim** parameter sweeps (same guide's
  table of contents).

**Does it offer anything for discovery?** No. Every one of these features assumes the equations
are already written. Data reconciliation is for static balances, not dynamic structure. There is
no structure search, sparse regression or change-point machinery.

**Verdict: not useful to SD Lab's core, and not worth adopting.**

- Our models are explicit difference equations with no algebraic loops, so a DAE compiler buys
  nothing.
- It is a heavy toolchain (a C compiler plus `omc`). Its SD libraries are niche and quiet, and it
  reads neither XMILE nor Vensim.
- What is worth keeping is one **idea**: the BSL's conserved-matter versus information-signal
  connectors are a published precedent for our move/link distinction. If someone asks for FMU
  export later, generating a tiny Modelica file (as above) is cheap. XMILE (section 1.3) reaches
  the SD community, and Modelica does not.

---

## 2. Calibration and parameter estimation in SD practice

### 2.1 What the tools do

- **Vensim**: you define a *payoff* (calibration or policy). The optimiser maximises it with a
  Powell hill-climbing search. Optimisation needs Professional or DSS
  ([payoff](https://vensim.com/documentation/payoffcomputation.html), [ref_payoff](https://vensim.com/documentation/ref_payoff.html)).
  Extended payoffs offer log transforms, non-Gaussian errors and prior penalties
  ([extended payoffs](https://www.vensim.com/documentation/extended_payoffs.html)). **Kalman
  filtering**: Vensim corrects model states during the run with an extended (nonlinear) Kalman
  filter. The weights then mean data quality relative to the model, and `1step.err` holds the
  one-step residuals (same pages). This is the SD world's built-in answer to "one-step versus
  simulation error".
- **Stella**: built-in optimisation is used for calibration by minimising a fit metric such as the
  sum of squared errors ([isee blog](https://blog.iseesystems.com/?p=4250)). Architect can run it
  inside Excel ([product page](https://ssl.iseesystems.com/store/products/stella-architect.aspx)).
- **Insight Maker**: an optimiser with bounds and random starts, with examples of fitting to data
  ([optimisation](https://insightmaker.com/optimization)).
- **PySD route**: translate the model, then use scipy or EMA Workbench. PySD itself has no
  calibration module ([tools](https://github.com/SDXorg/pysd/blob/master/docs/tools.rst)).
- **Bayesian**:
  - Andrade and Duggan calibrate SD models with Hamiltonian Monte Carlo in a practical workflow,
    using SEIR as the case ([SDR 37(4) 2021, doi:10.1002/sdr.1693](https://ideas.repec.org/a/bla/sysdyn/v37y2021i4p283-309.html)).
  - Andrade's R package `readsdr` translates SD models into R (CRAN 0.3.0, 2024-04-05, MIT).
  - **Stanify** (Fiddaman and Moon) translates Vensim models into Stan programs, with priors and
    observation models declared on top. It uses simulation-based calibration to check the
    estimator ([ISDC 2023 poster](https://proceedings.systemdynamics.org/2023/papers/T1153.pdf),
    [repo](https://github.com/Data4DM/stanify), last pushed 2025-01, 5 stars: research code).
- **Likelihood choice (directly relevant to us)**: Li, Rahmandad and Sterman (2025) compare least
  squares with variance-scaled Gaussian, log-Gaussian, **Poisson and negative binomial**
  likelihoods, and with extended Kalman filtering. Least squares and the Gaussian variants give
  poor confidence intervals. **Negative binomial, and Kalman filtering with variance scaling and
  autocorrelated process noise, are the promising ones**
  ([SDR 41(2) 2025, doi:10.1002/sdr.70004](https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html)).
  Earlier work: Struben, Sterman and Keith on maximum likelihood plus bootstrapping
  ([chapter](https://mitmgmtfaculty.mit.edu/jsterman/parameterandconfidence)), in Rahmandad, Oliva
  and Osgood (eds.), *Analytical Methods for Dynamic Modelers*, MIT Press 2015
  ([JASSS review](https://www.jasss.org/20/3/reviews/5.html)).

### 2.2 Standard practice, and how it maps onto ours

- **Calibration as a test of a structural hypothesis**, done on **partitions** of the model.
  Oliva (2003) argues that small calibration problems reduce the risk of forcing structure to fit
  ([EJOR 151(3)](https://ideas.repec.org/a/eee/ejores/v151y2003i3p552-568.html),
  [author page](https://people.tamu.edu/~roliva/research/sd/calibration.html)). Homer's
  **partial-model testing** drives model pieces with empirical inputs
  ([Homer 1983, SDS archive](https://archives.albany.edu/concern/daos/2n49tk06b)). Our per-stock
  rows, with measured flows subtracted and other stocks' measured levels used as regressors, are
  exactly partial-model testing, applied automatically. Our "candidates judged by multi-step
  simulation" step is whole-model calibration used as the referee. The SD literature supports
  that split.
- **One-step versus simulation (output) error**: the field treats it as a continuum. Pure
  simulation error assumes no process noise. Kalman filtering corrects states and so moves
  towards one-step error, and Li et al. (2025) find that filtering with process noise gives
  better inference. Our single-step least squares is the equation-error end, and output-error
  refinement is the other end. **An EKF likelihood is the principled middle**, and it handles
  unmeasured (hidden) stocks naturally.
- **Counting noise**: Poisson and negative-binomial likelihoods are now recommended in SD
  ([Li et al. 2025](https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html)). Our ground-truth
  engine draws flows as Poisson (`sdtruth.py`). Our "jitter" weights approximate this
  heteroskedasticity. An explicit variance ∝ flow (quasi-Poisson) weight is a cleaner version.

---

## 3. Structure discovery from data

### 3.1 How SD Lab's problem is shaped

The data are counted levels x_t of measured stocks. The model is Δx_t = S · q(x_t, θ) + u_t + ε_t,
where:

- S is a **flow (stoichiometric) matrix**: −ratio on the source row, +1 on the target row.
- q are the flow rates, each in one of the SD forms, possibly × lookup effects.
- u_t is outside inflow: piecewise constant, with unannounced changes.
- ε_t is counting noise, which **is shared across the two rows a flow touches**. That is the
  co-flow/shared-noise covariance.

On top of that come eras, floors at 0, capacity caps, hidden stocks (latent states) and units.
The prior is sparsity in *flows*, not in *terms per row*. This is the structure of
**chemical reaction-network inference**, not of generic per-variable SINDy.

### 3.2 Method by method

| Method / library | What it is (maturity) | What it would buy us concretely | Fit with our setting |
|---|---|---|---|
| **PySINDy** | Sparse regression of ẋ on a library of candidate terms ([Brunton et al. 2016 PNAS](https://pmc.ncbi.nlm.nih.gov/articles/PMC4839439); [PySINDy JOSS 2022](https://joss.theoj.org/papers/10.21105/joss.03994)). 2.1.0 (2026-01-08), MIT, Python ≥3.10, pushed 2026-10, 1.9k stars. Optimisers: STLSQ, SR3, **ConstrainedSR3**, StableLinearSR3, TrappingSR3, SSR, FROLS, SINDyPI, MIOSR (needs **gurobipy**, which is commercial), SBR (numpyro), EnsembleOptimizer. Libraries: Polynomial, Fourier, Custom, Generalized, Tensored, Parameterized, PDE, WeakPDE, SINDyPI. `fit(x, t, u=…)` takes control inputs, and there is a `DiscreteSINDy` (all from the 2.1.0 wheel source). | (a) **ConstrainedSR3**: equality or inequality constraints C·ξ = d (or ≤ d) over the stacked coefficients of all rows (`constraint_order="target"`, wheel docstring). Conservation becomes "coefficient of level_A in row B = −(1/ratio) × the matching coefficient in row A's outflow". Sign constraints (flows run forwards) become inequalities. (b) **EnsembleOptimizer** (bagging or library bagging) gives **inclusion probabilities** per term ([E-SINDy, Fasel et al. 2022](https://arxiv.org/pdf/2111.10992)). This is a direct upgrade to our "fits about as well" ambiguity report. (c) **Weak-form SINDy** integrates against test functions instead of differencing, which is much more robust to noise ([Messenger and Bortz, arXiv 2005.04339 / 2007.02848](https://arxiv.org/abs/2007.02848v2)). (d) **SINDYc** treats inputs as columns ([Brunton, Proctor and Kutz 2016](https://ar5iv.arxiv.org/html/1605.06682)), so eras and known flows become `u`. (e) **SBR** gives horseshoe-prior posteriors over coefficients. | Generic SINDy is per row, with no "flow" object. Conservation must be added as coupled constraints, and the "outside versus move" choice is not a coefficient question. Its noise model is Gaussian on derivatives, with no Poisson option. It has no piecewise-constant unknown inputs and no hidden states (except via delays in the library). Floors and caps are outside its scope. Constrained-SINDy precedent: energy-preserving constraints in fluids ([Loiseau and Brunton 2018 JFM](https://arxiv.org/abs/1611.03271v2)). **Verdict**: borrow ideas (ensembles, weak form, constraints). A wholesale swap would need our own flow-parameterised library. |
| **Reactive SINDy** (Hoffmann, Fröhner and Noé 2019) | SINDy with **vector-valued ansatz functions, one per reaction**: a sparse tensor regression that recovers a parsimonious reaction network ([J. Chem. Phys. 150, 025101; bioRxiv](https://www.biorxiv.org/content/10.1101/442095.full.pdf)). The code was in the authors' `readdy` stack; there is no standalone maintained package. Known limits: the user proposes the candidate reactions, and rates are unconstrained, which can give negative concentrations ([Palma Banos et al. 2025](https://arxiv.org/abs/2510.20655)). | **The closest published formulation to ours**: a reaction = a flow, a stoichiometric vector = our ±ratio column, mass-action rate = our proportional/linear forms. It validates our "flows as columns of one regression" design, and its literature (sparsity over reactions, group lasso over a reaction's coefficients) is where to look for selection methods. | Very good conceptual fit. Same gaps as SINDy for counts, eras, floors and hidden stocks. Study it; do not depend on it. |
| **Stoichiometrically informed symbolic regression** (Palma Banos et al., arXiv 2510.20655, 2025/26) | Genetic search over candidate mechanisms plus differentiable optimisation of rate constants, from concentration time series ([arXiv](https://arxiv.org/abs/2510.20655)). No code found. | Evidence that a GA over *mechanisms* (whole structures) works for conservation-constrained systems, much like our candidate-model judge. | Study only. |
| **Likelihood-based reaction-network inference for counts** | Sparse maximum-likelihood network reconstruction ([arXiv 1902.04920](https://web3.arxiv.org/pdf/1902.04920)). Logistic regression on stochastic reaction trajectories to infer stoichiometry and connectivity (Choi, Kang and Rempala, [record](https://mdsoar.org/items/04b5dd5b-9f30-4eee-b520-26c32c877be0)). Synthetic likelihood ([arXiv 1810.02457](https://arxiv.org/pdf/1810.02457)). | Count-native objectives (Poisson/multinomial) for exactly "whole things move between compartments". | Directly relevant to our Poisson noise. Study it for the likelihood. |
| **Hybrid / abrupt SINDy** | **Hybrid-SINDy** clusters the data, fits SINDy per cluster, and selects switching models with information criteria ([Mangan, Askham and Proctor, arXiv 1808.03251](https://arxiv.org/pdf/1808.03251)). **Abrupt-SINDy** detects a change and makes the smallest sparse update to the previous model ([Quade et al. 2018, arXiv 1803.00894](https://arxiv.org/abs/1803.00894)). | (a) For **unannounced** changes in internal rates (not only in outside inflow), the abrupt-SINDy idea "detect, then sparse edit" matches our per-configuration columns that must pay by BIC. (b) Hybrid-SINDy's out-of-sample selection is a principled form of our held-out judge. | Ideas, not libraries. |
| **PySR** (SymbolicRegression.jl) | Genetic-programming symbolic regression with a multithreaded Julia backend. Custom losses, operator constraints and nesting limits ([GitHub](https://github.com/MilesCranmer/PySR)). 2.7.0 (2026-10-07), Apache-2.0. | Discovering **effect shapes** (lookup curves) and rate forms beyond our five: for example, fit the residual of one flow as f(level_B) to propose a table effect. A Poisson-deviance loss can be written as a custom loss. | It finds scalar expressions, not network structure; conservation and flows are not native. Needs a Julia runtime. Useful as a **second-stage form finder** on one flow at a time, not as the structure search. |
| **gplearn** | scikit-learn-style genetic programming ([GitHub](https://github.com/trevorstephens/gplearn)). 0.4.3 (2026-01-07), BSD-3. | Same role as PySR, in pure Python but slower. | Weaker than PySR. Low priority. |
| **AI Feynman** | Symbolic regression using symmetries, separability and dimensional analysis ([Udrescu and Tegmark 2020, Sci. Adv.](https://arxiv.org/pdf/1905.11481)). PyPI `aifeynman` 2.0.7, **last release 2020-10**. | Its **dimensional-analysis** idea matches our unit rules (a rate must be units/time). | Unmaintained. Take the idea only. |
| **Feyn / QLattice** (Abzu) | Symbolic regression service. PyPI `feyn` 3.5.0 is **CC-BY-NC-ND-4.0**. | — | Licence rules it out. |
| **SysIdentPy** | NARMAX/NARX/ARX identification with FROLS term selection and information criteria; neural NARX via PyTorch ([README](https://github.com/wilsonrljr/sysidentpy), [JOSS](https://joss.theoj.org/papers/10.21105/joss.02384)). 0.9.0 (2026-06-13), BSD-3, pushed 2026-09. | (a) **FROLS** (forward regression with orthogonal least squares, error-reduction ratio) is a well-studied alternative to our stepwise BIC for choosing columns. It is also in PySINDy as `FROLS`. (b) Its free-run (simulation) metrics and AIC/BIC/LILC/FPE criteria are a reference implementation for our judge. | Per-output models; no conservation, hidden states or Poisson noise. Borrow FROLS as a column-selection experiment. |
| **MATLAB System Identification Toolbox** | Subspace (`n4sid`), grey-box `idgrey` (linear structured state space) and `idnlgrey` (nonlinear grey-box) ([n4sid](https://atmos.washington.edu/~brodzik/for_yuter/20050614_opt/matlab6/help/toolbox/ident/n4sid.html), [idgrey](https://atmos.washington.edu/~brodzik/for_yuter/20050614_opt/matlab6/help/toolbox/ident/idgrey.html), [nonlinear grey-box](https://au.mathworks.com/help/ident/ref/nonlineargreyboxmodel.html)). Subspace methods cannot estimate a known structure's parameters; grey-box methods can ([MathWorks Answers](https://la.mathworks.com/matlabcentral/answers/128895)). | Conceptual: **subspace identification estimates the state dimension**, which is a principled count of hidden stocks. Grey-box identification is "calibrate our structure by prediction-error maximum likelihood". | Proprietary MATLAB. Do not adopt; the ideas are available in statsmodels and dynamax. |
| **Tigramite (PCMCI, PCMCI+, LPCMCI, RPCMCI, J-PCMCI+)** | Constraint-based causal discovery for time series ([README](https://github.com/jakobrunge/tigramite)): PCMCI ([Runge et al. 2019 Sci. Adv.](https://advances.sciencemag.org/content/5/11/eaau4996)). LPCMCI allows **latent confounders**; RPCMCI gives **regime-dependent graphs**. 5.2.10.1 (2026-01-14), **GPL-3.0**. | (a) A pre-screen for which stock pairs could be linked, with false-positive control. It would replace our "mirror correlation > √(2 ln pairs)/√n" grouping heuristic. (b) LPCMCI's latent-confounder output flags where a hidden stock might sit. (c) RPCMCI is the published version of "eras change the graph". | It outputs graphs, not flows or rates. ParCorr assumes linear Gaussian noise; `ParCorrWLS` handles heteroskedasticity. **GPL-3.0 is a problem** if SD Lab is ever distributed under a permissive licence. Use it as an offline benchmark or study, not a dependency. |
| **Granger causality** | `statsmodels.tsa.stattools.grangercausalitytests` ([docs](https://statsmodels.org/dev/generated/statsmodels.tsa.stattools.grangercausalitytests.html)) | A cheap pairwise test. | Superseded by PCMCI for multivariate cases; low value. |
| **Dynamic Bayesian networks** | pgmpy supports DBNs and structure learning ([JMLR 2024](https://www.jmlr.org/beta/papers/v25/23-0487.html)). 1.1.2, MIT. | — | Mostly discrete variables; the wrong abstraction for continuous flows. Do not adopt. |
| **Neural ODEs / universal differential equations** | UDEs: known mechanistic structure plus a learned neural term, then sparse regression on the learned term to recover equations ([Rackauckas et al., arXiv 2001.04385](https://arxiv.org/abs/2001.04385v4)). Julia: DiffEqFlux.jl (MIT, pushed 2026-10) and DataDrivenDiffEq.jl (MIT, pushed 2026-10; SINDy and symbolic regression in SciML, [README](https://github.com/SciML/DataDrivenDiffEq.jl)). Python: torchdiffeq (MIT, last release 2024-11) and **diffrax** (JAX, Apache-2.0, 0.7.2, 2026-02). | The UDE pattern applies directly to **effects**: keep the found flows, give each suspected flow a learned multiplier g(level), then fit a table to g. A differentiable simulator (diffrax or JAX) would allow **output-error / multiple-shooting refinement** of all parameters at once, with floors handled by softplus. | Heavy (Julia or JAX) and data-hungry. Black-box parts violate our "every flow is an SD equation" contract unless they are distilled afterwards. Worth one experiment on effects; not the core. |
| **Kalman filter / state-space EM** | **statsmodels** state space: custom models via `MLEModel`, and EM in `DynamicFactorMQ.fit_em` ([MLEModel](https://www.statsmodels.org/dev/generated/statsmodels.tsa.statespace.mlemodel.MLEModel.html), [fit_em](https://www.statsmodels.org/dev/generated/statsmodels.tsa.statespace.dynamic_factor_mq.DynamicFactorMQ.fit_em.html)); 0.15.0, BSD-3. **pykalman**: filter, smoother and EM ([GitHub](https://github.com/pykalman/pykalman)); 0.11.2 (2026-01). **dynamax** (JAX): linear-Gaussian, nonlinear-Gaussian and **generalised-Gaussian SSMs with non-Gaussian emissions**, EM or SGD learning, HMC via Blackjax ([README](https://github.com/probml/dynamax), [JOSS 2024](https://doi.org/10.21105/joss.07069)); 1.0.3 (2026-10-13), MIT. | (a) **Hidden stocks done properly**: once the structure is fixed, the model is a linear Gaussian SSM. Measured stocks are observed states; hidden stocks are unobserved states. A fixed transition matrix A(θ) = I + S·K holds the proportional/linear flows. EM or the Kalman likelihood estimates the delay and the initial hidden content, and the smoother gives the hidden level. Our "delayed regressor" exp kernel is the steady-state version of this. (b) **Shared noise**: the process-noise covariance Q = S·diag(rates)·Sᵀ is exactly the co-flow covariance (one flow's Poisson noise is −ratio on one row and +1 on another). Fitting with that Q is the generalised-least-squares answer to "shared-noise covariance". (c) The **Kalman likelihood** is the one-step/simulation compromise that Vensim and Li et al. (2025) recommend. (d) Piecewise-constant inflow becomes a random-walk state, or known breakpoints become an exogenous input. | Good for linear forms. Floors, caps and lookup effects need an EKF or UKF (dynamax nonlinear SSM). Poisson noise is approximated by Gaussian with variance ∝ rate (fine at our counts), or handled exactly with dynamax's generalised emissions. **Best fit for the hidden-stock, co-flow and scoring parts of our pipeline.** |
| **Change-point detection** | PELT ([Killick, Fearnhead and Eckley 2012 JASA, arXiv 1101.1438](https://arxiv.org/pdf/1101.1438)). **ruptures** (PELT, binary segmentation, window and dynamic-programming methods, many costs, including Poisson) ([README](https://github.com/deepcharles/ruptures), [Truong et al. 2020 review](https://doi.org/10.1016/j.sigpro.2019.107299)). 1.1.10 (2025-09-10), BSD-2, pushed 2026-10. | We already run PELT. ruptures is a reference to **test our implementation and penalty against**, including the 2 log n "textbook" penalty our log already flags. | Mature. We may keep our own (numba, inside the regression), but compare against ruptures in a unit test. |
| **SD-specific data-to-structure work** | Abdelbari and Shafi: evolutionary echo-state networks learn causal-loop-like structure from observed dynamics, then a GP ensemble learns equations ([JAISCR 2018](https://reference-global.com/article/10.1515/jaiscr-2018-0010); [UNSW thesis](https://unsworks.unsw.edu.au/fapi/datastream/unsworks:51876/SOURCE02?view=true); [Systems 7(4):47, 2019](https://doi.org/10.3390/systems7040047)). Tested on small textbook models. ISDC 2026, "From Data to Model Structure: A Generative Algorithm…": net-flow equations from stock time series; succeeds on teacup and predator-prey, **partial on workforce/inventory** ([abstract](https://proceedings.systemdynamics.org/2026/abstracts/1226.html)). A "SINDy-inspired sparse orthogonal regression" for causal loop diagrams from real data ([arXiv 2606.21530](https://arxiv.org/pdf/2606.21530)). | Confirms that the problem is open and that published attempts recover *net* flows per stock (CLD-level), not conserved moves between stocks with SD rate forms. No code to adopt. | Our bench (11 ground-truth SD models, with skill@H) is already more demanding than anything in these papers. |
| **LLM-based SD model generation** | **sd-ai** (isee and UB-IAD): an open-source service between Stella and LLMs, with an evaluation suite ([repo](https://github.com/UB-IAD/sd-ai), MIT, JS, pushed 2026-10-14). Its paper reports causal-translation and conformance scores across 11 LLMs ([Schoenberg et al., arXiv 2503.15580](https://arxiv.org/abs/2503.15580)). **System Dynamics Bot** (text to CLD; about 60% of links recovered; [SDR 40(3) 2024](https://ideas.repec.org/a/bla/sysdyn/v40y2024i3ne1782.html)). ChatGPT writing SD models ([Campuzano-Bolarín et al.](https://merit.url.edu/en/publications/from-natural-language-to-executable-models-how-chatgpt-writes-a-s/)); narrative-to-structure with GPT-4o ([WSC 2025](https://www.informs-sim.org/wsc25papers/con265.pdf)); "Code-First SD" with LLM-generated Python ([ISDC 2026](https://proceedings.systemdynamics.org/2026/abstracts/1116.html)). An ISDC 2026 abstract reports bounded tasks (explanation, loop narration) to be more reliable than general model generation ([abstract](https://proceedings.systemdynamics.org/2026/abstracts/1032.html)). | **Priors, not discovery**: an LLM reading stock names and units ("tickets resolved", "staff") can propose plausible flows and groups. That narrows candidates. Our discovery then tests them against data. sd-ai JSON is readable by pysimlin, which is an interop target. | These systems build from *text*, never from measured levels. Complementary to ours. |

### 3.3 Fit against our specific difficulties

| Difficulty | Best existing handle | Gap left for us |
|---|---|---|
| Counting (Poisson) noise | Poisson / negative-binomial likelihoods ([Li et al. 2025](https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html)); count-based reaction-network inference; dynamax generalised emissions | Plug into our weights or judge; no library does it inside structure search |
| Unannounced piecewise-constant inflow | PELT / ruptures; random-walk state in a Kalman model | Joint with structure: ours (pieces inside the row regression) is already the right shape |
| Announced eras | SINDYc (era as input); Hybrid-SINDy; RPCMCI regime graphs | Ours (per-configuration columns paying by BIC) matches abrupt-SINDy's "sparse edit" idea |
| Floors at 0, capacity caps | XMILE non-negative stocks and uniflows (simulation only); constrained / EKF filtering | No discovery tool handles them. Censored-regression (Tobit-style) rows, or excluding floored steps from the fit, is our own work |
| Conservation between stocks | Reactive SINDy (stoichiometry); ConstrainedSR3 equality constraints | No tool treats "outside versus move" as a choice. Our unit and conservation rules are novel in this setting |
| Hidden stocks | Kalman/EM state-space (statsmodels, pykalman, dynamax); subspace order estimation; LPCMCI latent flags | Choosing *where* a hidden stock sits remains a structure search, but its delay and content can be estimated properly |
| Co-flows / shared noise | Process-noise covariance S·diag(q)·Sᵀ in a state-space likelihood | Ours to implement: a small GLS change |
| Multiplicative lookup effects | UDE (learn g, then distil); PySR on the residual of one flow; SINDy with Custom/Tensored libraries | Choosing which stock drives an effect, and the table shape, is open |

---

## 4. Recommendations

### 4.1 Ranked: adopt, interoperate, study

1. **Kalman/state-space scoring and hidden stocks (adopt the method; dynamax or statsmodels as
   the library).** *Experiment*: strategy `kalman-judge`. Score each candidate model by its
   Kalman one-step likelihood, using process noise Q = S·diag(q̂)·Sᵀ (counting noise shared by
   each flow's two ends) plus a random-walk inflow state, in place of or beside the multi-step
   simulation judge. Second, estimate hidden-stock delays and initial content by EM, against the
   delayed-regressor grid. Mechanism test: on `tests/synth.py`, a two-stock chain with one hidden
   stage; the EM delay should land within 10% and the grid search should not. Bench: sd-hidden-chain,
   sd-hospital, sd-kanban, sd-saas. This addresses the literature's strongest finding
   ([Li et al. 2025](https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html)) and our
   hidden-stock and co-flow items in one model.
2. **Count-aware weighting (adopt).** *Experiment*: `poisson-weights`. Replace jitter weights with
   iteratively reweighted least squares under variance ∝ (sum of the flows touching a row),
   i.e. quasi-Poisson, and add the off-diagonal shared-noise terms (GLS across rows). Cheap, and
   directly the noise the truth engine uses. Bench everything; watch sd-population and sd-orders,
   whose large levels have large variance.
3. **Ensembles and inclusion probabilities (adopt the idea; PySINDy `EnsembleOptimizer` as the
   reference).** *Experiment*: `bagged-matrix`. Run the matrix method on block-bootstrap resamples
   of the steps, keep flows by inclusion probability (E-SINDy), and report probabilities in place
   of "fits about as well". Hypothesis: it removes spurious links such as the +0.026 working → inbox
   term in sd-pipeline that the experiment log notes. Bench all; read `parts` as well as skill.
4. **Export to XMILE, validated with pysimlin (interoperate).** Write an XMILE writer for our
   model, round-trip it through `pysimlin` (load, simulate, compare with `sdlab/discovery/simulate.py`
   on all `sd-*` truths), and offer `.mdl` via pysimlin's `save_as`. This makes found models
   usable in Vensim and Stella, gives Loops-that-Matter analysis for free, and lets an AI agent use
   simlin's MCP tools on found models. Import via PySD or pysimlin for models that fit our forms.
5. **Weak / integral formulation (study, then experiment).** *Experiment*: `weak-rows`. Fit each
   row on integrals over short windows against test functions (weak SINDy) rather than single-step
   differences. Hypothesis: lower variance than single steps without the bias that plain windows
   caused (our log records 5-step windows biasing working → review to 0.08 instead of 0.2). The
   weak form weights steps smoothly instead of summing them.
6. **Constrained regression for conservation (experiment; PySINDy `ConstrainedSR3` or
   cvxpy directly).** *Experiment*: `constrained-flows`. Fit all rows jointly, with flows as
   shared columns (Reactive-SINDy style) and sign inequalities (rates ≥ 0, flows run forwards).
   This replaces the post-hoc "trust receivers within 30%" and "refit test" rules with one convex
   problem. Hypothesis: it fixes sd-support-tiers and sd-orders, where per-row fits disagree about
   a shared flow. Compare with stepwise BIC on the bench.
7. **Effect discovery via residual symbolic regression (study; PySR for one experiment).** For a
   flow whose residual correlates with a third stock's level, fit g(level) with PySR (or a
   monotone spline), then snap it to our `linear` or `table` effect. Bench: sd-supply (a rate set
   by a third stock) and any examples with effects.
8. **FROLS as an alternative column selector (experiment, cheap).** It is in PySINDy and
   SysIdentPy. Compare with stepwise BIC on collinear rows (sd-saas trials → churned versus
   paying; sd-population).
9. **Benchmarks against generic tools (study; for the write-up).** Run PySINDy (STLSQ and E-SINDy,
   with the measured levels as library) and Tigramite PCMCI+ on the `sd-*` datasets and grade them
   with our grader. That documents whether our SD-specific machinery earns its keep. It is
   expected to, because they cannot express moves, eras or inflow pieces.
10. **LLM priors from names and units (study).** Use sd-ai-style prompting to propose likely flows
    and groups from stock names, as a prior penalty in the score, never as the answer. Measure on
    examples with descriptive names.

### 4.2 What not to adopt, and why

- **Do not replace the core with generic SINDy, PySR or symbolic regression.** They model rows,
  not flows. They have no notion of outside versus move, unit ratios, inflow pieces or eras, and
  they assume Gaussian noise on derivatives. We would rebuild all of our SD rules on top and lose
  the matrix method's speed.
- **Tigramite as a dependency**: GPL-3.0, and it outputs graphs, not rates. Use it only for
  comparison.
- **Neural ODE / UDE as the model**: black-box terms break the "every flow is an SD equation"
  contract. They need Julia or JAX, and much more data than our runs give. At most use the UDE
  pattern to *propose* an effect shape, then distil it.
- **DBNs (pgmpy)**: discrete-variable oriented; the wrong abstraction.
- **Commercial engines (Vensim DLL, AnyLogic, Powersim SDK, MATLAB)**: proprietary, platform-bound
  (the Vensim DLL is Windows only and needs DSS for full use), and none discovers structure.
  Interoperate through files (XMILE or `.mdl`) instead.
- **MIOSR in PySINDy**: needs gurobipy, a commercial solver.
- **Feyn/QLattice**: non-commercial, no-derivatives licence. **AI Feynman**: unmaintained since 2020.
- **Insight Maker's `simulation` engine**: AGPL; we have our own simulator.
- **OpenModelica / Modelica** (section 1.5): an acausal DAE toolchain that our explicit
  difference-equation models do not need. Its estimation tools (OMSysIdent, stale since 2021)
  assume the equations are already known. Keep only the BSL's matter-versus-information idea.
- **Rewriting our simulator onto PySD, BPTK-Py or Simlin**: our simulator *defines* the semantics
  that discovery fits (floors, co-flow sharing, effects). Keep it, and check agreement through the
  XMILE round-trip instead.

### 4.3 Is our core genuinely unserved?

**Yes, for the combination that matters.** Simulation, file formats, calibration of a given
structure, and loop analysis are well served, and we should lean on them (sections 1 and 2).
Discovering an **SD stock-and-flow structure** from measured stock levels is a different problem:

- flows that conserve between stocks, with unit ratios;
- outside inflows that change unannounced;
- announced eras;
- hidden delay stocks;
- co-flows;
- floors;
- results expressed in SD rate forms and judged by behaviour.

Our searches found no open-source tool or mature method for it. Generic equation discovery covers
the regression core but not the SD semantics. SD-specific attempts are small prototypes with
partial success ([ISDC 2026 abstract](https://proceedings.systemdynamics.org/2026/abstracts/1226.html);
[Abdelbari and Shafi](https://reference-global.com/article/10.1515/jaiscr-2018-0010)). LLM tools
work from text ([sd-ai](https://arxiv.org/abs/2503.15580)). The nearest rigorous relative is
reaction-network inference ([Reactive SINDy](https://www.biorxiv.org/content/10.1101/442095.full.pdf)).
We should cite it as our lineage and mine it for selection methods and count likelihoods.

## Sources

Tools and libraries:
- PySD: https://github.com/SDXorg/pysd, https://pysd.readthedocs.io/, https://theoj.org/joss-papers/joss.04329/10.21105.joss.04329.pdf
- BPTK-Py: https://github.com/transentis/bptk_py
- SDEverywhere: https://github.com/climateinteractive/SDEverywhere
- Simlin and pysimlin: https://github.com/bpowers/simlin, https://github.com/bpowers/simlin/blob/main/src/pysimlin/README.md
- Insight Maker engine: https://github.com/scottfr/simulation, https://insightmaker.com/optimization
- XMILE: https://docs.oasis-open.org/xmile/xmile/v1.0/xmile-v1.0.html, https://oasis-open.org/?p=4521
- Vensim: https://vensim.com/documentation/payoffcomputation.html, https://www.vensim.com/documentation/extended_payoffs.html, https://vensim.com/documentation/22270.html, https://as26.vensim.com/?p=465, https://github.com/pbreach/venpy
- Stella: https://blog.iseesystems.com/?p=4250, https://iseesystems.com/resources/help/v3/Content/08-Reference/01-ObjectsAndProperties/01-BuildingBlocks/Stocks.htm
- AnyLogic: https://anylogic.help/anylogic/ui/editions.html
- PySINDy: https://github.com/dynamicslab/pysindy, https://joss.theoj.org/papers/10.21105/joss.03994
- PySR: https://github.com/MilesCranmer/PySR
- SysIdentPy: https://github.com/wilsonrljr/sysidentpy
- Tigramite: https://github.com/jakobrunge/tigramite
- dynamax: https://github.com/probml/dynamax
- statsmodels state space: https://www.statsmodels.org/dev/generated/statsmodels.tsa.statespace.mlemodel.MLEModel.html
- pykalman: https://github.com/pykalman/pykalman
- ruptures: https://github.com/deepcharles/ruptures
- DataDrivenDiffEq.jl: https://github.com/SciML/DataDrivenDiffEq.jl
- sd-ai: https://github.com/UB-IAD/sd-ai
- Stanify: https://github.com/Data4DM/stanify

Wikipedia list and OpenModelica:
- Comparison of SD software: https://en.wikipedia.org/wiki/Comparison_of_system_dynamics_software
- OpenModelica: https://github.com/OpenModelica/OpenModelica, https://github.com/OpenModelica/OMSimulator, https://github.com/OpenModelica/OMSysIdent, https://openmodelica.org/doc/OpenModelicaUsersGuide/1.24/systemidentification.html, https://openmodelica.org/doc/OpenModelicaUsersGuide/1.22/dataReconciliation.html
- Modelica SD libraries: https://github.com/modelica-3rdparty/SystemDynamics, https://github.com/modelica-3rdparty/BusinessSimulation
- FMI: https://fmi-standard.org/
- StochSD: https://github.com/stochsd/stochsd
- PathSim: https://github.com/pathsim/pathsim
- NetLogo: https://github.com/NetLogo/NetLogo
- Wolfram SystemModelCalibrate: https://reference.wolfram.com/language/ref/SystemModelCalibrate.html

Papers:
- Li, Rahmandad and Sterman 2025: https://ideas.repec.org/a/bla/sysdyn/v41y2025i2ne70004.html
- Andrade and Duggan 2021: https://ideas.repec.org/a/bla/sysdyn/v37y2021i4p283-309.html
- Oliva 2003: https://ideas.repec.org/a/eee/ejores/v151y2003i3p552-568.html
- Homer: https://archives.albany.edu/concern/daos/2n49tk06b
- SINDy: https://pmc.ncbi.nlm.nih.gov/articles/PMC4839439
- SINDYc: https://ar5iv.arxiv.org/html/1605.06682
- E-SINDy: https://arxiv.org/pdf/2111.10992
- Weak SINDy: https://arxiv.org/abs/2007.02848v2
- Constrained sparse Galerkin regression: https://arxiv.org/abs/1611.03271v2
- Hybrid-SINDy: https://arxiv.org/pdf/1808.03251
- Abrupt-SINDy: https://arxiv.org/abs/1803.00894
- Reactive SINDy: https://www.biorxiv.org/content/10.1101/442095.full.pdf
- Stoichiometrically informed symbolic regression: https://arxiv.org/abs/2510.20655
- Universal differential equations: https://arxiv.org/abs/2001.04385v4
- AI Feynman: https://arxiv.org/pdf/1905.11481
- PELT: https://arxiv.org/pdf/1101.1438
- Loops that Matter: https://www.arxiv.org/abs/1908.11434
- sd-ai evaluation: https://arxiv.org/abs/2503.15580
- System Dynamics Bot: https://ideas.repec.org/a/bla/sysdyn/v40y2024i3ne1782.html
- ISDC 2026 generative algorithm: https://proceedings.systemdynamics.org/2026/abstracts/1226.html
- Abdelbari and Shafi: https://reference-global.com/article/10.1515/jaiscr-2018-0010
