# Co-flows and cyclic links after effect_hats (strategy `coflow_hats`)

**Status:** in progress (distilled cases 128-132; whole-ladder run pending)
**Verdict:** pending

## Question
The distilled co-flow and effect cases (128-132, from sd-clinic-doses, sd-cloud-credits, sd-print-shop,
sd-bakery, sd-webshop-stock, sd-learning-curve and sd-moderation; `docs/LADDER.md`, "Distilled
cases") failed for every leader (combined, kalman_lna, structures, effect_hats, lna_stack). Why, and
can one strategy recover them without losing cells elsewhere?

## What was done
A copy of `effect_hats` (`sdlab/discovery/strategies/effect_hats/` at commit `89adae4`; every module
copied unchanged, then changed only as listed here) in `sdlab/discovery/strategies/coflow_hats/`.
After effect_hats's model is chosen (an effect, the re-cut base, or the base), candidates are tried
one at a time (two rounds); each is refitted jointly, its inflows pooled and re-cut, and kept only if
it prices better (one-step BIC) and behaves within `margin` (1.1x) of the model without it on the
judge:

- **A co-flow on an outside inflow** (`coflows.inflow_coflow_candidates`): for every pair of changing
  outside inflows (into V, into D), D's jumps at V's jump times are compared; if D's falls as V's
  rises (median ratio positive: the start of `per`), V's inflow gets `uses` of D, D's inflow is
  rebuilt without V's part, and the joint refit re-reads the per from D's row.
- **A drain following a stock read as a co-flow** (`coflows.cross_coflow_candidates`): the matrix's
  "D drains faster when V is high" (D -> outside = k x V) becomes `uses` of D on each flow into or out
  of V in turn (per started at the ratio of the rates' means); V's own drain is offered if the model
  has none.
- **A co-flow whose used stock runs dry** (`coflows.starved_candidates`): for each stock C that runs
  low for a while (the shared `starvation.stocks_running_dry`), the matrix (each variant without
  eras) is fitted on the steps where C is above its median, and the drains of C that follow another
  stock become co-flows (as above; also from the chosen and base models' structures). A row the kept
  steps leave ambiguous (read as growing with itself while a constant in pieces drains it) has its
  pieces read back as its inflow. The inflows are measured again on every step with the model
  stepped with its cap (`starvation.remeasure_inflows`), then twice: the steps where C held less than
  1.2x what its users want are found from the model, every number refitted without them, and the
  inflows pooled and re-cut (residuals on the left-out steps from the capped model, `capped_res`).
- **A link whose strength follows a cycle** (`cycles.py`): for a row whose residual (under the model,
  or after its levels alone) repeats (the shared `periodic.candidates`), and each other stock X, the
  row's change is regressed on X split by phase beside its own level and a constant; the per-phase
  coefficients are cut into phase segments (`periodic.segment_profile`) and the row's outside flows
  replaced by the cyclic link, written as `byTime` eras; the joint refit fits one number per phase
  segment. Held to the re-cut base's looser judge margin (`seg_margin`, 3x), since the base's inflow
  pieces follow the cycle step by step and the judge feeds each model its own pieces.
- **Two drains on one effect curve** (`translate.py`, `drain_coflows`): with no move on the curve,
  the base stock's own drain and another stock's drain on the same curve are also offered as the
  base's drain using the other up (both readings go to the price).

Other changes to the copy: a co-flow's per costs a number in the price and a cyclic link one per cut
and one for its period (`price.size`); the joint fit's "column has no weight" bar is 1e-24 of the
largest column (was 1e-12: on noise-free data a quiet row's weight times a large level fell below
it, and live inflow pieces were zeroed), and its share of left-out steps may be raised (`max_skip`).

Tests: `tests/test_ladder_coflow_hats.py` (per from opposite jumps; 128, 129, 132 none-short pass; a
chain gets no co-flow or cycle).

## Results
Pending: the whole-ladder run of the committed code.
