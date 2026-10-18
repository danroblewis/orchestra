# Experiment design / active excitation in live runs

**Status:** idea (not started)

## Why
Feedback loops that settle stop telling us anything; SD Lab controls the machines in live runs, so it could nudge the system to make structure identifiable.

## How it could be tried
Choose perturbations that maximise information about uncertain flows (optimal experiment design).

## Notes
Acting on a live system needs the user's sign-off before anything runs for real.

## Literature
- [Causal inference](literature/causal-inference.md), sections 3.1-3.5. Injections (commit `6d210c4`) are soft shift interventions with known target, time and amount. Random ones are randomised experiments, and the instruments that break confounding by unannounced inflows. Counting results: Eberhardt, Glymour, Scheines (2005, UAI) give log2(N)+1 multi-variable experiments and N-1 single ones; Eberhardt, Scheines (2007, Phil. Sci. 74:981-995) show simultaneous soft interventions on every variable suffice in one experiment. Active strategies: Hauser, Bühlmann (2014, IJAR 55:926-939); He, Geng (2008, JMLR 9:2523-2547). The causal and sysid views agree: an external signal is an instrument in a closed loop. The causal side adds *which stock* to probe.
- Concrete experiments: [probe-design](probe-design.md) (which probes to run), [injection-response-judge](injection-response-judge.md) (judge candidates by the measured responses), [injection-instruments](injection-instruments.md) (use the probes as instruments). All three need a bench option `--probes K`.
