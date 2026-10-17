# Benchmark v2: co-flows and effects in the ground truth

**Status:** done

## What
The engine gained co-flows (`uses`); co-flows added to 15 examples (controls kept: pipeline,
hidden-chain, eras, population, reservoirs, saas); ten new examples: co-flows (bakery, print-shop,
clinic-doses, cloud-credits, brewery) and effects (sawmill, learning-curve, emergency, farm-soil,
webshop-stock). Commits `5d5fd8d`, `d9f6187`, `500ee7f`. Details: docs/DISCOVERY-GOAL.md.

## Baseline "v2" (main line)
17 of 62 runs meet the goal; mean skill@20 31.6%, skill@100 32.1%, parts 55.4%. Discovery never
proposes a co-flow or an effect; effect examples are read as links (sd-sawmill -331%/-276% skill@20),
co-flow examples run away (sd-bakery default -1170%).

## Notes
- The grader keys a use and an effect on the same flow as separate parts.
- SD Lab's `effects` (linear clamp or table, multiplying a rate) are the standard SD "effect of X on Y"
  lookup; general equations (exp, log, powers, functions of two stocks) are not supported:
  see [general-equations](general-equations.md).
