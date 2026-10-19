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
| [A hidden transit stock, its pair's rows refitted by a Kalman filter](hidden_transit.md) | done (ladder rung 015, benchmark v2.1, 100 generated) | adopt candidate: first to pass 015 (PPFP; new 026 PPPP), no other ladder case changes; examples 31.2%/33.5% (+1.5/+4.2, p=0.012), 13 of 62; generated +1.3/+0.4, no run worse. Stages (2026-10-19, 2b6a827): hidden stages on one stock's inflow; distilled 133 PPPP, 134 FFFP, 135 PPFP, 172 PPFP (all FFFF before); canonical 105, 107 PPFP, 110 PPPP; no pass lost, false stages on 34 failing cells |
| [Independent systems under a common cause: exact ties, shared change places](common_cause.md) | stopped (ladder done; bench stopped under load, partial) | 032 noise-free cause found (a shared eigenvalue makes the levels exactly collinear; BIC on rounding error); 028-038 43 of 44 variants pass (earned_pieces 32, lna 36); whole ladder (472 items) 309 pass (earned_pieces 290, lna 340); examples partial (31 runs) 25.6% skill@20 vs earned_pieces 34.3%: needs work; slow |
| [Earned pieces: an outside inflow changes only where the data earns it](earned_pieces.md) | done (ladder, benchmark v2.1, 100 generated) | adopt candidate: passes 002-006, 012-014, 019, 020 in all variants; ladder 469 pass / 179 equivalent of 720 (matrix 345 / 116), 4 cells worse than matrix; examples 35.8%/35.4% (+6.2/+6.1, Wilcoxon p=0.043 @20), 15 of 62; generated +11.2/+4.2 vs matrix (p=0.009 @20) |
| [Case-study sources: real data and published SD models for harder tests](case-study-sources.md) | done (survey, research only) | 20 sources ranked; ingest first: test-models/PySD-Cookbook/SDMR via a PySD converter, BLS labour-force flows (flows measured), gauseR + boarding-school flu, OWID technology adoption; cascaded tanks needs exogenous inputs (user approval) |
| [Control-theory cases: textbook feedback loops on the ladder](control-cases.md) | done (cases 200-218, commits cd9e8b1, 34e948c, a319289) | 16 control cases (P/PI/PID, cruise, tank, dead time, cascade, feedforward, windup, on/off, admission queue, closed-loop identification) and control metrics (control.py); leaders 14 pass / 91 equivalent / 343 fail of 448, at most 3 of 34 achievable cells (structures); distilled 216-218 |
| [Censored: floors and caps fitted in the form the engine steps them](censored.md) | done (ladder, benchmark v2.1, 100 generated; commit 3a0f24c) | adopt as a final step: passes 024 and 025 in all variants (every strategy failed both); ladder 442 pass / 134 equivalent of 720 (matrix 345 / 116), 2 cells worse; examples 39.0%/46.0% (+9.4/+16.7, p=0.004/0.04), 16 of 62; generated +1.3/-1.3 (neutral); floors cost ~2-3 bench points |
| [Drifting drain: a drain whose rate drifts, beside a steady inflow](drifting_drain.md) | done (ladder, 453358e) | keep as a specialist: 121 PPPP (every leader failed), no pass lost; BLS (drifting moves) not reached |
| [Own tables: a stock's outside flows as a table of its own level](own_tables.md) | done (ladder, 67a604b) | keep as a specialist: 122, 123, 196 pass where the data allow, phys-draining-tank concave, no pass lost |
| [Effects as tent columns, fitted jointly; inflows pooled and re-cut](effect-hats.md) | done (ladder rungs 017-018, benchmark v2.1, 100 generated) | adopt candidate with work left: first to pass 018 (PPFP; 017 PPFF, the counting variants data-limited); ladder 475 pass / 159 equivalent of 720 (matrix 345 / 116), no cell worse; examples 46.6%/43.1% (+17.0/+13.8, Wilcoxon p=0.004 @20), 14 of 62, but sd-sawmill worse and ~24x matrix's time; generated +4.8/-2.5 (p=0.21) |
| [Realistic triage: why the 33 realistic cases fail, by mechanism; the grader checked](realistic-triage.md) | done (triage of 33 cases, grading study 0dc412d, distilled cases 152-161) | hidden stages (19 cases), inflows standing in for flows (15), co-flows (17) lead; the grader's inflow swap costs sound models in 9-15 of ~62 runs per strategy, but "own inflows" grading is mostly replay (a no-dynamics model scores 0.36-0.40) |
| [realistic_hats: effect_hats that answers in time, plus hidden transit stocks](realistic-hats.md) | done (realistic + 462 hand-written cells, commits 52cd6d1, 06b0062) | keep: 0 test cells worse, 15 better (015, 026, 085, 062); realistic timeouts 12 -> 1, goals 14 -> 15, mean @20 over all 66 runs 40.8% -> 43.8% (timeouts as 0; 22.6% -> 42.3% as -100%), paired on the 54 both graded +0.4 points, none worse (06b0062) |
| [loop_transit: realistic_hats with hidden stages that close a loop](loop_transit.md) | done (whole ladder, c3161de) | keep for its target: 156 none-short, none-long and counts-long fail -> pass (counts-short data-limited: delay 1.78 for 2); paired with realistic_hats on 1218 cells 4 better, 1 worse (045-random-link#7 none-long: a tiny spurious stage); realistic hard cases unchanged (sd-recycling, sd-ev-fleet blocked by other mechanisms) |
| [realistic_flows: realistic_hats with co-flows and the rows' own drains](realistic-flows.md) | in progress (round 2 on the realistic examples) | pending |
| [Co-flows and cyclic links after effect_hats](coflow-hats.md) | in progress (distilled cases 128-132) | pending |
| [Revisiting past ideas on the ladder: unique wins, retire/unpark, six new strategies](revisit.md) | done (ladder 001-048; commit 2bbc025) | every strategy's unique wins vs lna; no parked strategy has a win of its own left (unpark none; retire 6 parked and 19 dominated matrix-plus-one-mechanism strategies after adding rungs for their mechanisms); `lna_stack` (pulses + products + recurring inflow levels + noise-free SD conventions over lna) 381 of 472 vs lna 340, 41 wins, 0 losses, fresh skill@20 0.913 vs 0.831; stages for combined: lna_levels, lna_pulses, lna_products, gap_prior; `lna_loops` rejected (passes data-limited cells, wrecks noisy chains' behaviour); 2026-10-19: the five lna variants ported onto lna's hooks (dc73851): 062 passes, lna_stack's 36 errors/timeouts gone (realistic skill@20 0.368 -> 0.413 on the cells graded before), one cell lost (101 cs, numerical) |
| [lna: flows chosen by the likelihood of per-step changes under counting noise](lna.md) | done (ladder 001-062 and realistic, benchmark v2.1, 100 generated; commit f3270a8) | adopt the mechanism for structure: ladder 578 pass of 912 (matrix 378); every noisy variant of 007-016 passes but 010 and 016 short (data-limited); not for behaviour: examples -13.8 / -16.2 points (9 better, 14 worse of 62), generated neutral (44 better, 56 worse of 200), realistic cases 21.3% vs 29.6% at skill@20 |
| [kalman_lna: the stocks as hidden states, the levels as noisy reports](kalman_lna.md) | done (noisy cases 080-088 and the whole ladder; bench v2.1; commits ec2f9e8, 6a93270) | adopt for noisy reports: 85 of 97 achievable noisy cells against combined 35 (meas 13/15, gaps 14/15, weekly 9/11, outliers 12/15, bias 7/11, lag 15/15); 088 long passes to 20% error (others fail from 2%); clean cells as combined (639 passes each) |
| [odefit: per-step models fitted by output error, for smooth measured data](odefit.md) | done (physics and standard tests; commits 8d8e8c6, 333f814) | adopt for physics and smooth measured data: physics 25 of 28 (best before 15), gap to the best-SD reference -0.6 points, long-run error 8.3% (reference 17%); distilled 141-143 12 of 12 (leaders fail every meas cell); standard tests vs matrix: 20 fail -> pass, 1 pass -> equivalent, none lost |
| [archetypes: classic SD structures fitted by their free run, chosen by AICc, for short series](archetypes.md) | work in progress (real cases and twins, distilled 112/120/136; commit 3c3e009) | adopt for short series: real held-out 4.9% (best other 0.9%), twins 10.0% (best other -1.3%), 12 twin passes + 20 equivalent (others 0), agreement recall 57% (others 5%); Gause real forecasts still below combined (-7.0% vs -4.2%) |
| [Combined: the specialists side by side, one judge](combined.md) | done (ladder 001-048 and realistic, commit ded5e80; benchmark v2.1 and 100 generated, 696189d) | adopt as the ladder's combination: one-step counting likelihood + BIC on the numbers written, candidates refitted on equal terms, a 4x runaway guard; 001-048 415 of 472 (lna 340, lna_stack 374, ceiling 437), hand-written 140 of 152 (lna 94), no cell lna passes lost; realistic skill@20 41.1% (was 21.9%; matrix 31.8, effect_hats 49.9: no in-data guard closes that without losing test cells); examples +1.7/+12.3 vs v2.1, +27.5 @20 vs lna (p=0.004); generated -6.7% @20, 39 of 200 meet the goal (lna -51.8%, 6), +45.1 paired (p=3e-13) |
| [A ground-truth model of services on Kubernetes](k8s-model.md) | done (examples sd-k8s-platform and sd-k8s-small, realistic cases; generator sdlab/examples/k8s/build.py) | 35 services (479 stocks, 227 measured; 1,130 flows) and a 5-service first rung, a minute a step for a week: HPA, pods, throttling, OOM kills, cluster autoscaler, databases, a measured traffic input; engine 10x faster, bit-identical; leaders: matrix 87% skill@20 on the small case (long), combined/structures/kalman_lna return empty models (combined's 240 s budget), effect_hats times out; every leader fails or times out on the platform |
| [structures: products of stocks, multi-stock goal gaps, hidden Erlang chains](structures.md) | done, first version (ladder all, realistic, benchmark v2.1; commit 7e0a2bf) | adopt as the canonical-structure specialist: 100-110 30 pass + 7 equivalent of 44 (combined 3 + 1); distilled 124/126/127/137/138/139 17 + 4 of 24 (combined 2); whole ladder 762 + 160 vs combined 710 + 120 of 1,246 paired cells, 99 better, 6 worse (not yet diagnosed); realistic models identical to combined's in all 66 runs; bench 40.2%/48.2% (ad4e110), 36.7%/44.5% (2909e47) at skill@20/@100 |
| [Ideas 2026-10-18: what still fails, ranked ideas and an offline judge study](ideas-2026-10-18.md) | done (research; tests/study_combined_r2.py) | top two built (combined_misfit, combined_lean, both as combined_r2); prequential, cross-fed and stability judges rejected |
| [combined_misfit: multi-step error picks where no candidate fits the counts](combined_misfit.md) | done (ladder, examples bench; e0bc5f5, self-contained 0bb2b02) | adopt into combined: realistic skill@20 45.2% (stored combined 40.6%), tests unchanged but one cell (678 vs 679); bench 42.6% / 49.3%, 17 of 66 meet the goal |
| [combined_lean: change places at a modified-BIC price, weak flows dropped](combined_lean.md) | done (ladder; 781c56c) | adopt into combined, gated: strict 649 vs 618 of 936, passes 682 vs 679, noisy 32 vs 26; 3 true weak links lost (008/046#8/082 counts-short) |
| [combined_r2: both](combined_r2.md) | done (ladder; bench not run) | the round-2 proposal: 682 pass, 649 strict, realistic 44.1% |

