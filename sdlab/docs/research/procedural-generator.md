# A procedural generator of ground-truth SD models

**Status:** idea (not started)

## Why
31 hand-written examples invite tuning to them. Thousands of random models (chains, loops, hidden stocks, co-flows, effects, eras, unannounced changes) made with the same engine would show whether discovery generalises, and are the training data for [simulation-based-inference](simulation-based-inference.md).

## How it could be tried
A generator with knobs for structure size and features, sized for boundedness and excitation (the checks in [benchmark-excitation](benchmark-excitation.md)); a bench mode that samples N models per feature mix and reports skill by feature.

## Notes
Recommended first: it protects every other experiment from overfitting.
