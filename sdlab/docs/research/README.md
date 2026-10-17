# Discovery research

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
| [Hidden stocks from delayed copies of levels](hidden-stocks.md) | running (wave 1, benchmark v1) | - |
| [Numerical gradients and derivative-free optimisers](numerical-optimisation.md) | running (wave 2, benchmark v2) | - |
| [PySINDy with SD-shaped libraries and conservation constraints](pysindy.md) | running (wave 2, benchmark v2) | - |
| [Rates floored at zero and outflows capped by what a stock holds](floors-and-caps.md) | running (wave 1, benchmark v1) | - |
| [Searching SD structures: greedy, beam search, MCTS, genetic algorithms](structure-search.md) | running (wave 2, benchmark v2) | - |
| [Symbolic regression for rate equations and effect curves](symbolic-regression.md) | running (wave 2, benchmark v2) | - |
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
