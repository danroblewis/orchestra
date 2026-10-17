# Hidden stocks reconstructed from a unit's mass balance

**Status:** done (wave 4, benchmark v2.1)  
**Verdict:** needs a combination (finds only true hidden stocks, small skill gain; keep as an option
behind the behaviour gate / piece-proof judge)

## Why
20 of the 31 truths have a hidden stock, mostly a delay between two measured stocks of one unit:
cloud-credits postproc, sawmill kiln, learning-curve escalated, webshop in_transit, restaurant
plating, fishery cold_store, kanban undetected, ev-fleet returning, housing permits, support-tiers
trying. The main line reads such a delay as an outflow to outside plus inflow pieces into the
receiver. On sd-cloud-credits default it finds running -> outside at 0.44 (truth: 0.25 into postproc)
and gives results 36 inflow pieces. On sd-sawmill it finds planks -> outside at 0.23 (truth: 0.25 into
the kiln).

Conservation gives the hidden level directly: H(t) = H(0) + cumsum(what A sends "outside" - what B
receives from "outside"). So a found outflow paired with same-unit inflow pieces elsewhere becomes an
estimated level series; its drain is 1 / residence time by Little's law, and a false pairing drifts.

## What was done
Branch `exp/mass-balance-hidden` (from `3197240`), worktree
`.claude/worktrees/agent-aa1edba6e896f9fce`. Strategy `mass_balance` (and `mass_balance_all`, the
same with `mb_all`).

- `discovery/balance.py`: candidate pairs (A loses to outside, B of A's unit and group gets things
  from outside); A's found loss F and B's unexplained arrivals u, both evaluated at the measured
  levels with the found flows; the plain balance as one regression u(t) = d H0 + d alpha C(t-1) -
  d U(t-1) (C, U cumulative sums), used as the first gate; the plausibility checks (0 < alpha <= 1.05;
  H turns over at least 20 times in the run; H not below 0 by more than a tenth of its mean); the new
  model A -> H -> B, with B's arrivals (pieces, constant or a link from A) removed and B's own drain
  refitted with H.
- `discovery/balance_filter.py`: **the plain balance does not work on counting data.** C is A's loss
  at its rate, not what really left A each step; the difference summed over 2000 steps is a random
  walk as large as H itself (~200 on the mechanism model), and the cumsum fit came out d 0.08 / kB 0.27
  / skill -52%. So H is followed by a Kalman filter: B's change each step measures d x H(t-1) (and
  corrects it), then H moves by the balance (+ alpha F - what reached B), its variance growing by the
  counts' variance. alpha, d and B's drain kB maximise the innovations' likelihood (scale concentrated
  out, Nelder-Mead from 3 delays); H's start is a diffuse prior.
- `discovery/observer.py`: a found model's own unmeasured stocks estimated from any run's measured
  levels with its own flows into and out of them (measured stocks held at their data). The strategy's
  `inferred_levels` are this estimate, so the judge, the in-sample grade and the fresh-run grade all
  see the same kind of estimate.
- `discovery/simulate.py`: `behaviour_error(..., inferred=None)` (from `exp/hidden-delays`; off by
  default, `matrix` unchanged).
- Acceptance: a proposal must behave better on the data (the main line's judge at 5/20/100 steps, with
  H started from its estimate) than the model it came from with B's replaced arrivals held at their
  mean (the hidden-stocks rule). Accepted greedily, up to 3.

**Grader extension** (`tests/bench/grade.py`, `evaluate.py`), ported from `exp/hidden-delays`
(`2b8cbb8`) and extended for the fresh run: a found model's unmeasured stocks are kept apart from the
truth's and started from its own estimate (`inferred_levels`) on its own run; on the fresh run (and
whenever no estimate is stored) from the found model's own estimate on that run
(`observer.observe`, started from its stored first value), never from the truth. Evidence: without
it the grader drops H (a flow into an unknown stock leaves to outside, a rate on it reads 0), and
the mechanism model's correct a -> H -> b grades -1813% / -314% instead of 82% / 95%. Tested in
`test_the_grader_counts_it_as_a_hidden_stock_and_reestimates_it_on_another_run`. Unchanged for
every result without unmeasured stocks (`matrix` zero deltas on sd-saas, sd-eras, sd-pipeline).

## Mechanism test
`tests/test_strategy_mass_balance.py`: a -> h -> b (h unmeasured, 0.2 and 0.1; b drains 0.25), a's
inflow changing 3 times, 2000 steps.

| seed | mass_balance a->H / H->b / b drain | skill@20 / @100 | matrix skill@20 / @100 |
|---|---|---|---|
| 1 (the test) | 0.215 / 0.082 / 0.268, corr(H, h) 0.99 | 82% / 95% | -25% / 72% |
| 2 | 0.203 / 0.085 / 0.258 | 98% / 99% | 90% / 97% |
| 3 | 0.188 / 0.103 / 0.236 | 88% / 96% | -257% / 6% |
| Erlang-2 (two stages), seeds 1-3 | one H, 0.07-0.08 | 97%, 91%, 82% / 95-99% | -144%, -7%, -84% |

`matrix` on seed 1 reads a's loss as a drain to outside at 0.25 (biased by a's 33 pieces) and h's
arrivals as 12 pieces into b. Fresh run (seed 2) of the seed-1 model: 84%. Controls: a true loss of
a with an unrelated changing inflow into b is rejected by the balance (plain fit degenerate; the
reverse pair: residence 231 steps); a population (births a link from adults, children grow up) gets
no hidden stock. The brief's skill@20 > 0.9 is met on 2 of 3 seeds: the likelihood is flat in
(d, kB) (truth and fit within 5 log-likelihood units) and the error in alpha x kA follows kB's.

## Results (baseline v2.1: 29.6% / 29.3% in-sample, 28.9% / 29.7% fresh, 12 of 62 runs)

| attempt | skill@20 / @100 | fresh @20 / @100 | goal | time (sum) | notes |
|---|---|---|---|---|---|
| v1: filter, rest of A's loss kept to outside when the data prefers it, residence < T/10 | 30.0 / 31.1 | 29.3 / 31.5 | 12 | 701 s | false H on sd-ci long (live -> todo, d 0.001: -26 points); fishery +33/+37 |
| v2: H must turn over 20 times (residence < T/20) | 30.2 / 30.9 | 29.6 / 31.3 | 12 | 799 s | ci long back; fishery long's lucky false adults -> landed gone |
| **v3: conservation first (A loses only what H takes, its pieces re-measured)** | **30.7 / 31.3** | **30.1 / 31.7** | **12** | 675 s | committed default |
| v4 (`mass_balance_all`): v3 on all 16 candidates | 30.7 / 31.3 | 30.1 / 31.8 | 12 | 1489 s | the same models, 2.2x time |

v3 vs v2.1, runs moving more than 2 points: sd-fishery default 2.8% -> 35.7% (@100 -102% -> 5.5%;
fresh 29.6%), sd-fishery long -18.5% -> 7.4% (@100 -142% -> -62%), sd-webshop-stock long 63.6% ->
69.6% (@100 48.6% -> 72.8%), sd-webshop-stock default @100 54.9% -> 70.7%; sd-housing default 96.3% ->
94.0% (@100 97.1% -> 91.4%), sd-sawmill long @100 -5.1% -> -60.5%. Hidden stocks accepted: 6 runs,
**all true** (fishery cold_store x2, housing permits, sawmill kiln, webshop in_transit x2; parts +1
each). Proposed but rejected as worse than the reference: cloud-credits postproc, recycling rail.

## Verdict
Needs a combination. The balance finds only true hidden stocks once the 20-turnover rule is in
(precision 6/6), and the filter is what makes it work at all on counting data, but the gain is
small (+1.0 / +2.0 points, no run newly meets the goal): most target examples never offer a pair
(the chosen model has no loss to outside from the sender, or the receiver has no outside inflow,
e.g. kanban, ev-fleet, support-tiers, restaurant, learning-curve), and where H is found right the
rest of the model (co-flows on sawmill and cloud-credits, the fishing fleet) still dominates.

**Judge note.** The acceptance reference (B's arrivals at their mean) can be fooled: before the
turnover rule, a near-integrator H (d 0.001-0.003, residence of hundreds of steps) passed it on
sd-ci long and sd-fishery long by acting as a smoothed inflow. The 20-turnover rule blocks that, but
the mechanism adds a flexible state, so it should sit behind the behaviour-consistency gate or the
piece-proof judge when combined; all of it is options (`mb_against`, `mb_margin`, `mb_rest`,
`mb_all`, plausibility limits) and `balance.propose` can be called on any model's flows.

## Open ideas
- Pairs where A's loss is a co-flow or a link (recycling: bales' loss is "wagons" x 1.088 plus 0.25 x
  bales; only the proportional part was used, alpha 0.26).
- Offer pairs from moves too: a move A -> C whose receiver C is fed by pieces (the delay read as a
  move plus pieces), and B's arrivals read as links from a third stock.
- Combine with starved-coflows: on sawmill and cloud-credits the right hidden stock is found, but the
  co-flow error swamps it.
- The filter's likelihood is flat in (d, kB); refine d by multi-step error (output-error) after
  acceptance, or fit A's own drain jointly (A's pieces bias it: 0.25 vs 0.2 on the mechanism model).
- A stationarity test (KPSS on H's residual) in place of the turnover rule.
