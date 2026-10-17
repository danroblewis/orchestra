# Existing SD tools and discovery methods (survey)

**Status:** done  
**Verdict:** no existing tool discovers SD structure from data; reuse building blocks and formats

The full report with sources: [SD-TOOLS-AND-DISCOVERY.md](SD-TOOLS-AND-DISCOVERY.md).

## Findings
- None of the ~25 tools in Wikipedia's comparison of SD software (Vensim, Stella, AnyLogic,
  Analytica, Powersim, Wolfram SystemModeler, OpenModelica, NetLogo, StochSD, PathSim, se-lib,
  Simantics...), nor PySD, BPTK-Py, SDEverywhere or Simlin, infers stock-and-flow structure from data.
  They calibrate parameters of drawn models (Vensim optimiser, Kalman filter, MCMC). The only
  "generating" features draft models from text with an LLM (Stella sd-ai, LunaSim Copilot).
- Simulators and formats are solved: PySD, BPTK-Py, SDEverywhere, Simlin read Vensim and/or XMILE;
  `pysimlin` also writes Vensim `.mdl`. Our format maps onto XMILE; we lack a general equation language,
  delay/smooth builtins, arrays, conveyors, unit checking.
- Calibration practice supports our design (partial-model testing; calibration as a structure test)
  and recommends count likelihoods (Poisson / negative binomial) or Kalman filtering over plain least
  squares (Li, Rahmandad & Sterman 2025).
- Closest prior art: chemical reaction-network inference (Reactive SINDy), whose reaction matrix is
  our flow matrix. Generic PySINDy / PySR / SysIdentPy fit one equation per variable, not flows.
- OpenModelica: equation-based acausal modelling for engineering physics (FMU export; Cellier's
  SystemDynamics library; OMSysIdent for parameters). Not useful for discovery; one idea to borrow:
  the Business Simulation Library's split of conserved material flows vs information signals.

## Ranked recommendations (each a candidate experiment)
1. Kalman / state-space scoring and EM for hidden stocks -> [state-space](state-space.md)
2. Count-aware weights -> [count-likelihoods](count-likelihoods.md)
3. Bootstrap ensembles -> [bayesian-structure](bayesian-structure.md)
4. XMILE export -> [xmile-export](xmile-export.md)
5. Weak-form fitting -> [weak-form](weak-form.md)
6. One constrained joint fit -> [joint-constrained-fit](joint-constrained-fit.md)
7. PySR for effect shapes -> [symbolic-regression](symbolic-regression.md)
8. FROLS instead of stepwise BIC -> [frols](frols.md)
9. PySINDy and PCMCI+ baselines -> [pysindy](pysindy.md), [causal-discovery](causal-discovery.md)
10. LLM priors from names and units -> [llm-priors](llm-priors.md)

Not to adopt: generic SINDy/PySR as the core, Tigramite (GPL, graphs not rates), neural ODEs as the
model, dynamic Bayesian networks, commercial engines, MIOSR (needs Gurobi), Feyn, AI Feynman, OpenModelica.
