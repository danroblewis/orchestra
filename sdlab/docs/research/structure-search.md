# Searching SD structures: greedy, beam search, MCTS, genetic algorithms

**Status:** running (wave 2, benchmark v2)

## Hypothesis
An explicit search over SD model structures (edit moves: add/remove/redirect flows, move <-> link,
hidden stocks, effects, co-flows, inflow forms), each candidate's numbers fitted quickly, scored by
multi-step behaviour on the data plus a complexity penalty, finds models the matrix method cannot
express. Search methods compared on equal budgets with a shared space, fitter and scorer, each method's
settings swept, seeded from the matrix result vs from empty.

Branch `exp/structure-search`. Results will be recorded here when it reports (and in its branch's DISCOVERY-EXPERIMENTS.md entry).
