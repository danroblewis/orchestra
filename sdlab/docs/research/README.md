# Discovery research

**Start here: [PLAYBOOK.md](PLAYBOOK.md)**, the synthesis of the literature and our experiments: the procedure the research supports for discerning an SD model from data, mapped onto our pipeline, with a ranked experiment plan and checked citations.
Literature reports it draws on: [system identification](literature/system-identification.md), [equation discovery](literature/equation-discovery.md), [signals and time series](literature/signals-and-time-series.md), [the System Dynamics field](literature/system-dynamics-field.md), [compartmental analogues](literature/compartmental-analogues.md), [research process](literature/research-process.md), [causal inference](literature/causal-inference.md) (Pearl's do-calculus, causality in dynamic systems, interventions and invariance, applied to injections and eras); and the [tools survey](SD-TOOLS-AND-DISCOVERY.md).

Wave 4 candidates, ranked, with ready-to-run briefs and every brainstormed idea: [IDEAS-WAVE4.md](IDEAS-WAVE4.md).

One document per research topic: what was asked, what was done (branch and commit), results, verdict and open ideas.
The step-by-step history of the main line is in [../DISCOVERY-EXPERIMENTS.md](../DISCOVERY-EXPERIMENTS.md); how experiments are run is in [../DISCOVERY-LOOP.md](../DISCOVERY-LOOP.md).
When an experiment reports, update its topic document (status, results, verdict, open ideas) and this index.

**Summary of every effort and how well it worked, with diagrams: [tries.md](tries.md).**

**Every experiment's strategy is now on the main line**, side by side and each still isolated (its own
module, shared-module changes behind options that default to `matrix`'s behaviour): the list, one line
each, is [sdlab/discovery/strategies/README.md](../../sdlab/discovery/strategies/README.md). Waves 1-4 are
all there (`sindy`, `gradient` and `numopt_cma` need `uv sync --extra research`); not brought in:
structure search, the LLM critic, active probing and natural experiments (unfinished), and the gplearn
comparison script of exp/symbolic-regression.

| topic | status | verdict |
|---|---|---|
| [Benchmark v2: co-flows and effects in the ground truth](benchmark-v2.md) | done | - |
| [Choosing candidates on held-out data](held-out-judge.md) | done (wave 1, benchmark v1) | reject |
| [Does the ground-truth data keep exercising its model?](benchmark-excitation.md) | done | yes, except sd-population |
| [Existing SD tools and discovery methods (survey)](tools-survey.md) | done | no existing tool discovers SD structure from data; reuse building blocks and formats |
| [Pricing outside-inflow changes honestly](change-price.md) | done (wave 1, benchmark v1) | reject (a narrower gate is neutral) |
| [Refining rates by multi-step (output) error](output-error.md) | done (wave 1, benchmark v1) | needs a combination: keep as a final step after structural fixes |
| [Shared noise: telling moves, links and co-flows apart](shared-noise.md) | done (wave 1, benchmark v1 + co-flow engine) | needs a combination (with a fix for drain bias) |
| [Gradient descent through a differentiable SD simulator](gradient-descent.md) | done (wave 2, benchmark v2) | needs a combination (refined +2.9/+1.2, 18 of 62; generous structure ~70x slower, no better) |
| [Hidden stocks from delayed copies of levels](hidden-stocks.md) | done (wave 1, benchmark v1) | needs a combination |
| [Numerical gradients and derivative-free optimisers](numerical-optimisation.md) | done (wave 2, benchmark v2) | needs a combination (+1.0/+2.1, 20 of 62 with finite differences, 8x time; the optimiser is not the bottleneck) |
| [PySINDy with SD-shaped libraries and conservation constraints](pysindy.md) | done (wave 2, benchmark v2) | reject as a strategy; carry two pieces forward |
| [Rates floored at zero and outflows capped by what a stock holds](floors-and-caps.md) | done (wave 1, benchmark v1) | needs a combination |
| [Searching SD structures: greedy, beam search, MCTS, genetic algorithms](structure-search.md) | running (wave 2, benchmark v2) | - |
| [Symbolic regression for rate equations and effect curves](symbolic-regression.md) | done (wave 2; re-measured on v2.1) | best single mechanism on v2.1: 47.2% / 42.6% (+17.6/+13.3, p=0.002); needs a combination |
| [A procedural generator of ground-truth SD models](procedural-generator.md) | done (I2; merged) | main line on 300 generated models: -49% mean skill@20, 22 of 600 runs meet the goal (examples: 29.6%) |
| [Amortised / simulation-based inference of structure](simulation-based-inference.md) | idea (not started) | - |
| [Bayesian structure learning and bootstrap ensembles](bayesian-structure.md) | idea (not started) | - |
| [Causal discovery on time series (PCMCI+, Granger)](causal-discovery.md) | idea (not started) | - |
| [Experiment design / active excitation in live runs](experiment-design.md) | idea (not started) | - |
| [FROLS term selection](frols.md) | idea (not started) | - |
| [General rate equations (exp, log, powers, two-stock functions)](general-equations.md) | idea (not started) | - |
| [Identifiability: which structures the data cannot tell apart](identifiability.md) | idea (not started) | - |
| [Kalman filtering and state-space EM](state-space.md) | idea (not started) | - |
| [Koopman operators / DMD with control](koopman-dmd.md) | idea (not started) | - |
| [LLM priors from stock names and units](llm-priors.md) | idea (not started) | - |
| [Loop-dominance analysis](loop-dominance.md) | idea (not started) | - |
| [One constrained joint fit of all stocks](joint-constrained-fit.md) | idea (not started) | - |
| [Online identification](online-identification.md) | idea (not started) | - |
| [Poisson / negative-binomial likelihoods and count-aware weights](count-likelihoods.md) | idea (not started) | - |
| [Reaction-network inference methods](reaction-networks.md) | idea (not started) | - |
| [Regime models for unannounced changes](regime-models.md) | idea (not started) | - |
| [Scaling to hundreds of stocks](scaling.md) | idea (not started) | - |
| [Weak-form fitting](weak-form.md) | idea (not started) | - |
| [XMILE export and interoperability](xmile-export.md) | idea (not started) | - |
| [A complexity budget the analyst states](complexity-budget.md) | idea (not started) | - |
| [Bench instrumentation: coverage, selection, failure classes, ablation](bench-instrumentation.md) | done (I1; infra/bench-instrumentation) | on v2.1: 44 of 50 failing runs not representable, 1 not chosen, 5 not supported; judge picked the best candidate in 33 of 62 |
| [Behaviour-consistency gate against runaway models](behaviour-consistency.md) | done (wave 3, benchmark v2.1) | reject for the main line (25.3% with the 5x test; no change without); keep gate.py for flexible strategies |
| [Effects as basis-expanded flow columns in the regression](effect-columns.md) | idea (not started) | - |
| [A diagnose-and-expand loop driven by residual signatures](residual-diagnostics.md) | idea (not started) | - |
| [Outside-input changes estimated on innovations, jointly with the dynamics](inflow-innovations.md) | idea (not started) | - |
| [Hidden stocks by constrained deconvolution and order counting](delay-deconvolution.md) | idea (not started) | - |
| [Partial-model simulation per row](partial-model-simulation.md) | idea (not started) | - |
| [Floors and caps as censoring, offered only where the data reach them](censored-floors.md) | idea (not started) | - |
| [Inflow-conditioned held-out judge and era hold-out](inflow-conditioned-judge.md) | done (wave 3, benchmark v2.1) | reject as the main judge; keep judges.py; judge additions with/without, fed the base model's inflow |
| [Behaviour-mode fingerprints as structure priors](behaviour-fingerprints.md) | idea (not started) | - |
| [A declarative library of SD processes](process-library.md) | idea (not started) | - |
| [Co-flows found where the used stock runs dry](starved-coflows.md) | done (wave 4, benchmark v2.1) | adopt as extra candidates (+10.9/+15.0, 14 of 62; fresh +10.5/+14.5); losses where the judge picks a wrong co-flow |
| [Unannounced eras: recurring regimes found in the data, then fitted as eras](latent-eras.md) | done (wave 4, benchmark v2.1) | needs a combination: best so far (+11.5/+11.6, 12 -> 17 of 62); one regime stands in for an inflow |
| [Outside inflows as a repeating profile](periodic-inflows.md) | done (wave 4, benchmark v2.1) | needs a combination; strong adopt candidate (+11.7/+17.4, 15 of 62, holds on fresh runs) |
| [Assembling the model row by row from the candidates](row-crossover.md) | done (wave 4, benchmark v2.1) | needs a combination (+6.1/+13.4, 14 of 62 meet the goal; judge fooled on webshop, moderation) |
| [Pulses: one-step arrivals and short bursts as their own kind of input](impulse-inputs.md) | done (wave 4, benchmark v2.1) | adopt after combining with the judge/gate (+7.4/+7.7, 14 of 62; fresh 15) |
| [Hidden stocks reconstructed from a unit's mass balance](mass-balance-hidden.md) | done (wave 4, benchmark v2.1) | needs a combination (6 real hidden stocks, no false ones; +1.1/+2.0) |
| [Moves paced by a third stock: reading the matrix as stoichiometry times rates](paced-moves.md) | done (wave 4, benchmark v2.1) | paced moves: reject as they stand; gap inflows: needs a combination (+5.3/+5.5, services meets the goal) |
| [Drains measured where nothing flows in (recession analysis)](recession-drains.md) | done (wave 4, benchmark v2.1) | needs a combination (+10.5/+15.2, 16 of 62; fresh 14) |
| [An LLM structural critic in the loop](llm-critic.md) | idea (not started, wave 4) | - |
| [Judge noise: tied candidates told apart by simplicity](judge-ties.md) | idea (not started, wave 4) | - |
| [Closed subsystems: totals that never change](conserved-totals.md) | idea (not started, wave 4) | - |
| [Do no harm: falling back to persistence where the model is known to be worse](persistence-fallback.md) | idea (not started, wave 4) | - |
| [Rows fitted with their own noise model (AR residuals)](ar-rows.md) | idea (not started, wave 4) | - |
| [Announced eras as instruments for drains biased by inflow pieces](era-instruments.md) | idea (not started, wave 4) | - |
| [Evolving discovery code against generated models](evolve-discovery.md) | idea (not started, wave 4) | - |
| [Inflow attribution: which stocks get outside inflow, and unbiased drains](inflow-attribution.md) | done (wave 4, benchmark v2.1) | needs a combination (+3.8/+7.0, not significant alone; found a genuine pieces-gate bug) |
| [Symbolic effects with an addition judge](symbolic-addition-judge.md) | done (combination, benchmark v2.1) | anchor rule rejected; plain symbolic on v2.1 is the best single mechanism (47.2%/42.6%, p=0.002); safe rule keeps a third of it with no losses |
| [An interventional judge: injection responses every candidate must reproduce](injection-response-judge.md) | idea (not started; causal inference) | - |
| [Injections as instruments for rows confounded by unannounced inflows](injection-instruments.md) | idea (not started; causal inference) | - |
| [Invariance across eras and probes: which rows an era changed, and which predictors are real](invariant-rows.md) | idea (not started; causal inference) | - |
| [Probe design: which stock to inject, when and how much](probe-design.md) | idea (not started; causal inference) | - |
| [A hidden transit stock, its pair's rows refitted by a Kalman filter](hidden_transit.md) | done (ladder rung 015, benchmark v2.1, 100 generated) | adopt candidate: first to pass 015 (PPFP; new 026 PPPP), no other ladder case changes; examples 31.2%/33.5% (+1.5/+4.2, p=0.012), 13 of 62; generated +1.3/+0.4, no run worse |
| [Independent systems under a common cause: exact ties, shared change places](common_cause.md) | ladder done (028-038), bench in progress | 032 noise-free cause found (a shared eigenvalue makes the levels exactly collinear; BIC on rounding error); passes 028-038 in 43 of 44 variants (earned_pieces 32, lna 36); whole ladder 309 pass (earned_pieces 290, lna 340) |
| [Earned pieces: an outside inflow changes only where the data earns it](earned_pieces.md) | done (ladder, benchmark v2.1, 100 generated) | adopt candidate: passes 002-006, 012-014, 019, 020 in all variants; ladder 469 pass / 179 equivalent of 720 (matrix 345 / 116), 4 cells worse than matrix; examples 35.8%/35.4% (+6.2/+6.1, Wilcoxon p=0.043 @20), 15 of 62; generated +11.2/+4.2 vs matrix (p=0.009 @20) |
