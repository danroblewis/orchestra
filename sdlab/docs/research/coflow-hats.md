# Co-flows and cyclic links after effect_hats (strategy `coflow_hats`)

**Status:** done for this round (distilled cases 128-132; whole ladder run at `9d891b0`), code at `9d891b0`
**Verdict:** keep as a co-flow and cycle specialist: 128 and 132 pass in every variant (no strategy passed
either before), 129 passes none-short and counts-long; 130 and 131 still fail; on the whole ladder 558
pass / 213 equivalent against effect_hats's 547 / 210, 5 cells worse than effect_hats (053 #4-#6
none-long, 131 none-short), 16 better. The realistic hard cases are unchanged.

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

Gates added after the first whole-ladder run (`af06c28`) lost 16 cells to effect_hats on a fresh
paired rerun (cyclic links accepted on noise-free ties, e.g. 020 none-long; a drain read as a co-flow on
price ties, 041 #6; a starved co-flow whose cap never bound; SIR read as a drain using its own
receiver), all in `9d891b0`: a cyclic link must behave 10% better (`cycle_gain`) unless the row's own
pieces follow the cycle (a piece per half period: then `seg_margin`); a drain read as a co-flow must
price `coflow_gain` x log T (2) better; a starved co-flow is kept only where its cap binds on at least
1% of steps; two drains on one curve are not read as a co-flow on a stock the base also feeds.
Speed: the candidates are refitted and priced, and only the best `extra_most` (4) are re-cut and
judged (starved: the best 2 over all dry stocks); the extra stages run only on runs of at most
`extras_max_steps` (3000) steps, since the realistic models' long runs (7000-14400 steps) time out
otherwise (effect_hats alone takes ~250 s of the 300 s there). The first run timed out on 24
realistic cells; the second on 9.

Tests: `tests/test_ladder_coflow_hats.py` (per from opposite jumps; 128, 129, 132 none-short pass; a
chain gets no co-flow or cycle).

## Results
`uv run sdlab-ladder status --strategies effect_hats,coflow_hats` after `uv run sdlab-ladder run
--strategies coflow_hats --jobs 2 --timeout 300` (and a `sync` of the same strategy to finish it) on
`9d891b0`, 2026-10-19; both strategies' rows are marked stale since (other agents changed shared code
afterwards), and effect_hats's rows are older runs. Letters: none-short, none-long, counts-short,
counts-long.

| case | effect_hats | coflow_hats |
|---|---|---|
| 128-coflow-on-outside-inflow | EEFF | **PPPP** |
| 129-coflow-runs-empty | FFFF | **P**FF**P** |
| 130-move-slowed-by-used-stock | FFFF | FFFF |
| 131-effect-fed-by-its-flow | EEFF | FEFF |
| 132-link-with-daily-cycle | FFFF | **PPPP** |

Whole ladder (every cell either ran): coflow_hats 558 P / 213 E / 498 F / 9 T; effect_hats 547 / 210 /
479 / 12 (30 not run). Worse than effect_hats: 053-sweep-excitation #4, #5, #6 none-long and #6
none-short (P -> E), 131 none-short (E -> F). Better: 128 (4), 129 (2), 132 (4), 043 #3 counts-short
(F -> P), 055 #7 counts-long and 154 counts-long (F -> E). In the fresh paired rerun of the
differing cases at `af06c28` (both strategies, same day), 016-coflow went E -> P in three variants;
the `coflow_gain` gate of `9d891b0` gave that up (its co-flow and drain readings price within 3 of
each other).

Hard cases (realistic, two variants each): sd-clinic-doses, sd-cloud-credits, sd-print-shop, sd-bakery,
sd-webshop-stock, sd-learning-curve, sd-moderation: the same letters (all F, sd-moderation's long run
a timeout) and the same recall as effect_hats. The long runs skip the extra stages; on the short runs
no co-flow or cycle candidate was accepted. The fixes have not carried back yet.

## What remains, and why
- **129 none-long, counts-short.** none-long: the matrix fitted on the steps where R is above its median
  reads Q's row backwards (Q growing with itself, a constant draining it in pieces: near its balance
  any such pair fits); the drain offered in its place starts at the cross term's k with per 1, the
  inflows re-measured from that biased split are cut wrong (15 and 20 pooled), and the refit drifts
  (k 0.44 -> 0.22). counts-short: the co-flow is found (Q's drain 0.28, per 2.10) but R's own drain is
  lost.
- **130.** The case writes R's restocking as one inflow (550 - S) / 5; any strategy reading it as an
  inflow of 110 and a drain of 0.2 x S (the same equation, apart from a floor that never binds) fails
  the link part, and with an effect in the case the scorer does not test equivalence. So 130 cannot
  pass unless that reading is chosen, which nothing in the data supports: a scorer question (reported,
  not changed). Besides, without noise the effect is found with the co-flow as a second drain on the
  same curve; reading them as one co-flow (`drain_coflows`) fits the two rows with one curve and prices
  worse than two free curves, so the separate reading is kept.
- **131.** Without noise the curve of E is straight over the range E covers (200-400, one piece of
  the table), so E x f(B) plus a plain k x B fits as exactly as B x f(E) and prices better (fewer
  knots); the W -> E move / link is unidentifiable without noise (`analyse`). With counting noise the
  screen finds no effect at all (best row gain -11 against a bar of +15; the curve's modulation is
  about 10% of the flow).


## The declared boundary (2026-10-20)

Outside flows only where the case declares them ([declared-boundary.md](declared-boundary.md)). The package
carries its own `boundary.py`, copied from matrix/boundary.py at 723f72c (HIDDEN_PRICE 0, CLAIM_PRICE 2),
with changes of its own marked "(this copy)": a guard refit budget (GUARD_FITS 60, then a flow outside is
dropped without a refit), an estimated side may hold a flow reading a measured input (the cases declare
"estimate" for any flow not driven by inputs alone, 217), no self-move among the alternatives, and the
helpers `inside`, `keep_inside`, `placement_ok`. In its own search: the earned main line's row hooks and per-candidate guard (as matrix, 67f5b9e); effect placements only on declared sides; finished trials guarded; co-flow, cycle and starved candidates that leave the boundary are not offered. Every answer ends with
`boundary.apply` (the guard and the moves; with no boundary declared, outside flows are priced boundary
claims, listed in `boundary_claims`). The eiv copy holds an instrumented refit with nothing to prune to the
pruned model's longest-horizon test (303 meas-long).

Paired on the CPU pool (commits 71ec999, 9cfeb75, d5cd56a; before = this strategy at 3cc5c54 on the same
HEAD, branch boundary-before-hats): Kubernetes 300-305 (28 cells, jobs 54 -> 119) 26 -> 28 pass (304 none-long, 305 none-long fail -> pass); 40 Tests
cells (008, 028, 059, 114, 117, 154, 196, 203, 208, 213 x none/counts short/long; jobs 57 -> 120)
8 -> 8 pass, 8 -> 8 equivalent, no status change. Invented boundary (k8s / tests): 2 -> 0 / 11 -> 0. Timeouts unchanged (154 counts-long times out on
both sides where it did). Kubernetes 316-317 (job 122, after only, 8 cells each; none-long skipped by the pool): no pass; timeouts only on 317 (meas-long in five of the six, counts-long in effect_hats and own_tables, meas-short in own_tables), where the stored results at 793b5b5 already timed out on 317's long variants; coflow_hats now finishes 317 counts-long and meas-long.
