# An interventional judge: injection responses every candidate must reproduce

**Status:** idea (not started)

## Why
The judge scores candidates by their behaviour on the data they were fitted to. In the causal
hierarchy that is level 1 evidence (association). The goal asks a level 2 question: does the model
behave like the truth from new states and under pushes? The causal hierarchy theorem (Bareinboim et
al. 2022) says level 1 data almost never settle level 2 questions without assumptions. The injection
commit (`6d210c4`) measured the gap. On sd-population at 3000 steps, a model learned from flat data
collapses when the system is shaken (-46% skill@20 on a probed run). It also reverses elderly ->
adults, which 8 probes at 300 steps fix.

Announced injections chosen at random times and amounts are randomised experiments. The average
response of each stock h steps after an injection is an unbiased estimate of the dynamic causal
effect, with no model at all. Local projections (Jordà 2005) estimate it, and external-instrument
identification (Stock and Watson 2018) justifies it. A correct model must reproduce that response
table. A model that only fits flat data will not.

## How it could be tried
- Bench prerequisite: `tests/bench/evaluate.py --probes K`. It gives the discovery run and the fresh
  grading run K injections from a fixed seed: a random measured stock, a random step in the middle
  80%, amount ±(0.5 to 1.5) x the stock's median level, at least 50 steps apart. Injections are run
  inputs, so no simulation changes. Report probed numbers beside the goal numbers, never instead of
  them.
- Module `sdlab/discovery/responses.py`.
  - For each probed stock A, each stock B and each h = 0..H (H = 50 or the spacing), regress
    B(t+h) - B(t-1) on the injection amount into A at t, with all levels at t-1 as controls. This
    gives the coefficient r[A,B,h] and its standard error, using HAC errors because the h-step
    differences overlap.
  - For each candidate, simulate from the measured state at each injection step, with and without
    the injection, using the same estimated inflows. The difference over the following H steps,
    divided by the amount and averaged, is the candidate's response m[A,B,h].
  - Score: mean over (A, B, h) of ((m - r) / se)^2.
- Strategy `response_judge`: two uses, tried separately.
  1. Gate: drop candidates whose score exceeds a chi-square band.
  2. Judge term: the behaviour error plus λ x the response score (λ chosen once, on generated
     models).
- Mechanism test (`tests/test_strategy_response_judge.py`): a population chain children -> adults ->
  elderly, births = 0.03 x adults (link), maturing 0.05, ageing 0.02, deaths from elderly 0.04.
  3000 steps, counting noise, near equilibrium, 8 probes.
  - Candidate pool: the main line's variants plus a hand-made flat-data model with elderly -> adults.
  - Pass: the response judge ranks the reversal below a candidate with the true direction, and the
    chosen model's skill@20 on a fresh probed run is at least 20 points above the behaviour judge's
    choice.
  - Controls: with no probes the strategy is the main line exactly; with probes and the true model
    in the pool, the true model's score is within the chi-square band in 95% of seeds.
- Bench: `--probes 8` on all examples, against the main line with the same probes. Watch
  sd-population, sd-services, sd-university and sd-fishery, the runaway examples.

## Sources
- Literature report [causal inference](literature/causal-inference.md), sections 1.8, 1.9, 3.4 and 5 (idea 1).
- Bareinboim, Correa, Ibeling, Icard (2022). On Pearl's hierarchy and the foundations of causal inference. ACM Books, 507-556. doi:10.1145/3501714.3501743
- Jordà (2005). Estimation and inference of impulse responses by local projections. AER 95(1):161-182. doi:10.1257/0002828053828518
- Stock, Watson (2018). Identification and estimation of dynamic causal effects in macroeconomics using external instruments. Economic Journal 128(610):917-948. doi:10.1111/ecoj.12593
- Dash (2005). Restructuring dynamic causal systems in equilibrium. AISTATS 2005, PMLR R5:81-88 (equilibrium-learned structure misleads under manipulation).
- Holland (1986). Statistics and causal inference. JASA 81(396):945-960 (randomisation and the fundamental problem).
