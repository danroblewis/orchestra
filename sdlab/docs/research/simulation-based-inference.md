# Amortised / simulation-based inference of structure

**Status:** idea (not started)

## Why
A network trained on many generated models could propose structures from data directly, with our fitting and judge verifying them: discovery that has 'seen' thousands of systems.

## How it could be tried
Needs [procedural-generator](procedural-generator.md). Encode a run (levels, eras) -> predict an adjacency/flow-kind matrix and forms; use proposals as seeds for [structure-search](structure-search.md).
