# Probe design: which stock to inject, when and how much

**Status:** idea (not started)

## Why
Random injections help (the injection commit: 8 probes fix sd-population's elderly -> adults
reversal), but they spend probes on stocks whose structure is already clear. Active causal learning
chooses the next intervention by what the surviving hypotheses disagree on. Examples:
- Tong and Koller (2001), Murphy (2001) and He and Geng (2008) choose by expected information.
- Hauser and Bühlmann (2014) give two strategies. One greedily picks the single variable whose
  intervention orients the most edges. The other finds a smallest set of interventions of any size
  that identifies the graph.
- Eberhardt and Scheines (2007): simultaneous soft interventions on every variable can identify the
  graph in one experiment.

For us, time order already orients every arrow. What probes must settle is confounding (shared
unannounced inflows), excitation (settled loops) and mechanism (link vs move, hidden stock vs slow
drain). The system-identification counterpart is Box-Hill / T-optimal discrimination
([system identification](literature/system-identification.md), section 14). This idea merges the two:
*which stock* to probe comes from the causal side, *when and how much* from the sysid side.

## How it could be tried
- Needs `--probes K` on the bench (see [injection-response-judge](injection-response-judge.md)) and
  a way to run discovery in rounds: discover, design, probe, rediscover.
- Module `sdlab/discovery/design.py`.
  - Surviving candidates: the variants within the judge's noise band of the best, or a bootstrap
    ensemble ([bayesian-structure](bayesian-structure.md)).
  - Menu: each measured stock; amounts ±0.5 and ±1.5 x its median level; times on settled stretches
    (low local variance) and elsewhere; also one "all stocks at once with independent random amounts"
    probe.
  - For each probe, simulate every candidate from the current state. Score the predicted divergence
    as the sum over stocks and the next H steps of squared differences between candidates, divided by
    Poisson variance. Prefer probes into stocks whose outgoing flows differ between candidates.
  - Pick the top probe(s), spaced by at least H.
- Mechanism test (`tests/test_probe_design.py`): an sd-population-like chain, 3000 steps, 8 probes in
  total. Compare designed probes (2 rounds of 4) with 8 random probes and with none.
  - Pass: designed probes recover the true direction, and score higher skill@20 on a fresh probed
    run than random ones, in at least 8 of 10 seeds.
  - Control: when all candidates agree, the design falls back to random probes and the result
    matches random.
- Bench: examples where the judge picks among near-ties (from [judge-ties](judge-ties.md) and the
  bench instrumentation), with budgets of 4 and 8 probes.
- In the product: report the top probe as "to tell these apart, try ...". Running a probe on a live
  system needs the user's sign-off ([experiment-design](experiment-design.md)).

## Sources
- Literature report [causal inference](literature/causal-inference.md), sections 3.2, 3.5 and 5 (idea 4).
- Eberhardt, Glymour, Scheines (2005). On the number of experiments sufficient and in the worst case necessary to identify all causal relations among N variables. UAI 2005, 178-184.
- Eberhardt, Scheines (2007). Interventions and causal inference. Philosophy of Science 74(5):981-995. doi:10.1086/525638
- Hauser, Bühlmann (2014). Two optimal strategies for active learning of causal models from interventional data. IJAR 55(4):926-939. doi:10.1016/j.ijar.2013.11.007
- Hyttinen, Eberhardt, Hoyer (2013). Experiment selection for causal discovery. JMLR 14:3041-3071.
- He, Geng (2008). Active learning of causal networks with intervention experiments and optimal designs. JMLR 9:2523-2547.
- Agrawal, Squires, Yang, Shanmugam, Uhler (2019). ABCD-Strategy. AISTATS 2019, PMLR 89:3400-3409.
- Box, Hill (1967) and Atkinson, Fedorov (1975), via [system identification](literature/system-identification.md), section 14.
