# Discovery research

**Start here: [PLAYBOOK.md](PLAYBOOK.md)**, the synthesis of the literature and our experiments: the procedure the research supports for discerning an SD model from data, mapped onto our pipeline, with a ranked experiment plan and checked citations.
Literature reports it draws on: [system identification](literature/system-identification.md), [equation discovery](literature/equation-discovery.md), [signals and time series](literature/signals-and-time-series.md), [the System Dynamics field](literature/system-dynamics-field.md), [compartmental analogues](literature/compartmental-analogues.md), [research process](literature/research-process.md); and the [tools survey](SD-TOOLS-AND-DISCOVERY.md).

Wave 4 candidates, ranked, with ready-to-run briefs and every brainstormed idea: [IDEAS-WAVE4.md](IDEAS-WAVE4.md).

One document per research topic: what was asked, what was done (branch and commit), results, verdict and open ideas.
The step-by-step history of the main line is in [../DISCOVERY-EXPERIMENTS.md](../DISCOVERY-EXPERIMENTS.md); how experiments are run is in [../DISCOVERY-LOOP.md](../DISCOVERY-LOOP.md).
When an experiment reports, update its topic document (status, results, verdict, open ideas) and this index.

| topic | status | verdict |
|---|---|---|
| [Benchmark v2: co-flows and effects in the ground truth](benchmark-v2.md) | done | - |
| [Choosing candidates on held-out data](held-out-judge.md) | done (wave 1, benchmark v1) | reject |
| [Does the ground-truth data keep exercising its model?](benchmark-excitation.md) | done | yes, except sd-population |
| [Existing SD tools and discovery methods (survey)](tools-survey.md) | done | no existing tool discovers SD structure from data; reuse building blocks and formats |
| [Pricing outside-inflow changes honestly](change-price.md) | done (wave 1, benchmark v1) | reject (a narrower gate is neutral) |
| [Refining rates by multi-step (output) error](output-error.md) | done (wave 1, benchmark v1) | needs a combination: keep as a final step after structural fixes |
| [Shared noise: telling moves, links and co-flows apart](shared-noise.md) | done (wave 1, benchmark v1 + co-flow engine) | needs a combination (with a fix for drain bias) |
| [Gradient descent through a differentiable SD simulator](gradient-descent.md) | running (wave 2, benchmark v2) | - |
| [Hidden stocks from delayed copies of levels](hidden-stocks.md) | done (wave 1, benchmark v1) | needs a combination |
| [Numerical gradients and derivative-free optimisers](numerical-optimisation.md) | running (wave 2, benchmark v2) | - |
| [PySINDy with SD-shaped libraries and conservation constraints](pysindy.md) | done (wave 2, benchmark v2) | reject as a strategy; carry two pieces forward |
| [Rates floored at zero and outflows capped by what a stock holds](floors-and-caps.md) | done (wave 1, benchmark v1) | needs a combination |
| [Searching SD structures: greedy, beam search, MCTS, genetic algorithms](structure-search.md) | running (wave 2, benchmark v2) | - |
| [Symbolic regression for rate equations and effect curves](symbolic-regression.md) | done (wave 2, benchmark v2) | needs a combination (+19 points; judge blocker) |
| [A procedural generator of ground-truth SD models](procedural-generator.md) | idea (not started) | - |
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
| [Co-flows found where the used stock runs dry](starved-coflows.md) | idea (not started, wave 4) | - |
| [Unannounced eras: recurring regimes found in the data, then fitted as eras](latent-eras.md) | done (wave 4, benchmark v2.1) | needs a combination: best so far (+11.5/+11.6, 12 -> 17 of 62); one regime stands in for an inflow |
| [Outside inflows as a repeating profile](periodic-inflows.md) | idea (not started, wave 4) | - |
| [Assembling the model row by row from the candidates](row-crossover.md) | done (wave 4, benchmark v2.1) | needs a combination (+6.1/+13.4, 14 of 62 meet the goal; judge fooled on webshop, moderation) |
| [Pulses: one-step arrivals and short bursts as their own kind of input](impulse-inputs.md) | idea (not started, wave 4) | - |
| [Hidden stocks reconstructed from a unit's mass balance](mass-balance-hidden.md) | done (wave 4, benchmark v2.1) | needs a combination (6 real hidden stocks, no false ones; +1.1/+2.0) |
| [Moves paced by a third stock: reading the matrix as stoichiometry times rates](paced-moves.md) | idea (not started, wave 4) | - |
| [Drains measured where nothing flows in (recession analysis)](recession-drains.md) | done (wave 4, benchmark v2.1) | needs a combination (+10.5/+15.2, 16 of 62; fresh 14) |
| [An LLM structural critic in the loop](llm-critic.md) | idea (not started, wave 4) | - |
| [Judge noise: tied candidates told apart by simplicity](judge-ties.md) | idea (not started, wave 4) | - |
| [Closed subsystems: totals that never change](conserved-totals.md) | idea (not started, wave 4) | - |
| [Do no harm: falling back to persistence where the model is known to be worse](persistence-fallback.md) | idea (not started, wave 4) | - |
| [Rows fitted with their own noise model (AR residuals)](ar-rows.md) | idea (not started, wave 4) | - |
| [Announced eras as instruments for drains biased by inflow pieces](era-instruments.md) | idea (not started, wave 4) | - |
| [Evolving discovery code against generated models](evolve-discovery.md) | idea (not started, wave 4) | - |
