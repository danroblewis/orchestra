# Evolving discovery code against generated models

**Status:** idea (not started)

## Why
Progress is limited by how many hypothesis -> strategy -> bench loops people can run. LLM-guided
program evolution improves a scored program by mutating its code (FunSearch, AlphaEvolve). We have both
things it needs:
- a strict, cheap verifier: skill on generated models;
- small modules with narrow interfaces: the change scan, the row fit, conservation, reading flows.

The rule-heavy modules (`read_flows`, `conserve`, the inflow-form decision) are where hand tuning has
piled up rules, and where evolution could search alternatives systematically. This is a meta-level
experiment. It is only sound on the procedural generator: evolved against the 31 examples, it would
overfit them by construction.

## How it could be tried
- An offline harness `tests/evolve/`; nothing runs in the engine.
- A population of variants of one module, mutated by an LLM that is given the module, the scores and
  the failure classes from bench instrumentation.
- Each variant is evaluated on 50-200 models from the generator's development pool, in parallel.
- Keep the Pareto front of skill against code size. Select on the validation pool, and score the 31
  examples only once at the end.
- Winners then go through the normal experiment process (strategy, mechanism test, bench) before any
  adoption.
- Mechanism test of the harness: a planted bug (`pelt` minimum piece 50) is undone within N
  generations, and held-out generated models are reported at every generation.

## Sources
Romera-Paredes et al. (2024) Nature 625:468-475 (FunSearch); Novikov et al. (2025) AlphaEvolve,
arXiv:2506.13131; Cobbe et al. (2020) ICML, PMLR 119:2048-2056; Dwork et al. (2015) Science
349(6248):636-638; [procedural-generator](procedural-generator.md); [bench-instrumentation](bench-instrumentation.md).
