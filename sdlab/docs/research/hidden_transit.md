# A hidden transit stock, its pair's rows refitted by a Kalman filter

**Status:** done (ladder rung 015, benchmark v2.1, 100 generated models)  
**Strategy:** `hidden_transit` (`sdlab/sdlab/discovery/strategies/hidden_transit/`), tests in
`tests/test_ladder_hidden_transit.py`  
**Verdict:** adopt as a candidate for the main line: the first strategy to pass the hidden-stock rung
(015: 3 of 4 variants; 026: 4 of 4), no change on any other ladder case, and a significant gain on
the examples bench (see Results). The one 015 variant it misses is at the data's own resolution.

## Why every strategy failed 015

015 is `outside -> A = 20`, `A -> H = 0.2 A`, `H -> B = 0.1 H` (H not measured), `B -> outside = 0.2 B`,
everything starting at 0. Without noise the only information is the first ~150 steps of the
transient (after that the levels sit at equilibrium to 4 decimals); with counts the Poisson draws
keep exciting it.

| strategy | none-short | none-long | counts-short | counts-long | why |
|---|---|---|---|---|---|
| `matrix` (and the 33 strategies built on its rows) | F | F | F | F | no unmeasured stock to represent it: reads it as a move `A -> B` 0.081 A, a loss `A -> outside` 0.119 A, B's drain 0.046 and a negative constant on B |
| `hidden_delays` | F: H **right** (k 0.2, delay 10), but B's drain 0.23 and a spurious constant outflow of B (4.96) kept, plus a link `outside -> H` | F: no copy accepted | F: k 0.60, delay 14, A's inflow 59 | F: no copy accepted | the delayed copy is a regression column beside the row's other terms: the receiving row keeps its constant and pieces, and with counts the copy (a filter of A's level, not of what really left A) is an errors-in-variables column; 0.1 is on its delay grid, which is why none-short came out exact |
| `mass_balance` | F: never proposed | F: never proposed | F: k 0.225, delay 11.3, B 0.232 | F: delay 13.2 (32%) | its pairs need "A loses to outside" **and** "B gets from outside"; the main line hands it a move `A -> B` and B's constant as a negative outflow, so A -> B is not a pair. With counts its filter (a) leaves A's share alpha free, and B's response to A is symmetric in the delay and B's drain (below), so the likelihood is flat in (d, kB), the "flat likelihood" its topic document reports; (b) does not use that what left A towards H is also seen in A's change; (c) uses A's loss at the main line's (biased) rate |

The scorer is right about what it matches (a chain through an unmeasured stock and a `via` flow both
score as `(hidden, A, B) = {k_in, delay}`; `hidden_delays` none-short shows the hidden part "ok"). Its
**tolerance on 015's noisy variants is not**: see "A scorer issue" below.

## The two facts the method rests on

1. **The mirror.** With A measured, B's response is `kin d / ((z - 1 + d)(z - 1 + kb))`: swap d and kb
   and scale kin by kb / d, and B's levels are reproduced exactly (015: delay 10, kb 0.2, kin 0.2 vs
   delay 5, kb 0.1, kin 0.1). Only A's balance tells them apart: in the mirror only half of A's loss
   goes to H and the rest must leave to outside. So "all of A's loss goes to H" (kin = kA) is the
   default, and a share is accepted only when better by BIC. A free share makes the likelihood flat.
2. **Shared counting noise.** Each flow is a count around its rate (variance = rate). What left A
   towards H in a step appears in A's change (minus) and in H's (plus), and what left H appears in H's
   change and in B's. A and B are measured exactly, so only H is uncertain: a **scalar** Kalman filter
   whose update uses both A's and B's innovations, with covariance -var(A->H) between A's change and
   H's. A filter on B alone, or a regression on a filtered copy of A, reads the delay too long
   (prototype: copy regression 16.1 on counts-long, filter without A 13.2, this filter 10.2).

## What it does

On top of the main line's chosen model, for each pair (A loses in proportion to its level to outside
or to B; B gets an outside constant, or a link or move from A; same unit and group; not back along a
found move B -> A):

- **Local model** (`kalman.py`): `A' = xA + cA(t) - kA A`, `H' = (1-d) H + kin A`, `B' = xB + cB + d H - kb B`,
  where xA, xB are what the kept flows do at the measured levels (their gross throughput is part of the
  variance). Replaced: A's proportional losses (to outside and to B), A's and B's outside constants,
  links into B from A, B's proportional drain to outside.
- **A's inflow** is one constant, or the main line's pieces of it, never searched: for a given kA each
  piece's value is the mean of A's change plus kA A over it (H does not enter A's mean).
- **Noise scale**: whole-number data are counts, scale 1 (the counts' variance pins the rates' sizes
  where a short run's means cannot: on 015 counts-short A's inflow 21.6 vs 23.2 with the scale
  concentrated out); other data concentrate the scale out (a weighted least squares; exact without noise).
- **Fit** (`fit.py`): starts from the minima of a least-squares profile over the delay (B's row is
  linear once d is given) and their mirrors; L-BFGS-B then a short simplex polish; variants: B with or
  without an outside constant, A's inflow as one constant or in pieces; then a share kin < kA on the
  best variant.
- **The alternatives**, scored by the same likelihood: the plain pair (B gets a share of A's loss at
  once) over the same variants, and the found model's own rows (its pieces cost two numbers each).
- **Acceptance**: a cheap least-squares screen first; then the transit's BIC must beat the best
  alternative by `4 log n`; the delay must lie between 1.5 steps and T / 15; and the full model with H
  (H started from its filtered level, `inferred_levels`) must behave better on the data (judge at 5,
  20, 100 steps) than the found model with B's outside inflow (and A's, when the transit holds A's
  constant) at its mean, and at most 1.5x worse than the found model with all its pieces. Greedy, best
  gain first, at most 2 transit stocks, each stock in one pair.

## Ladder results (current matrix and hidden_transit columns; letters none-short, none-long, counts-short, counts-long)

| case | matrix | hidden_transit |
|---|---|---|
| 001-014, 016-025, 027 | as matrix | identical letters and recall on every case (no transit stock accepted anywhere else) |
| **015-hidden-stock** | FFFF 66.7% | **PPFP 100%** |
| **026-hidden-stock-driven** (new) | FFFF 66.7% | **PPPP 100%** |
| total (108 items) | 37 pass, 14 equivalent | **44 pass**, 14 equivalent |

015 found numbers: none-short and none-long exact (k 0.2000, delay 10.000, kb 0.2000, inflow 20.000);
counts-long k 0.202, delay 10.18, kb 0.203, inflow 20.21; counts-short k 0.216 (7.8%), delay 10.61
(6.1%), inflow 21.56 (7.8%) but **B's drain 0.2221 (11.0%)**: the only part outside 10%.
`hidden_delays` and `mass_balance` remain FFFF on 015 and on 026. Run time: ~95 s of discovery for
the whole ladder (matrix ~38 s with the same load); 0.2-2 s per item.

New case **026-hidden-stock-driven** (added, isolates a sub-problem): 015 with A's outside inflow
stepping 10 / 30 every 100 steps, unannounced. The main line reads the steps as pieces on A; the
transit must keep them (re-measured) and not mistake them for H. Before re-measuring A's pieces inside
the fit, counts-long failed (A's inflow 23.3, a spurious `A -> outside` share 0.032).

## A scorer issue (015 counts variants): no oracle for hidden stocks

The oracle's `z x SE` allowance applies only when the truth is linear in the measured stocks, so
015's noisy variants are graded with a bare 10% on every number. The data cannot deliver that:

- **The truth's own structure, fitted by this filter's maximum likelihood on 40 fresh seeds of 015
  counts** (scratch study, `fit_transit` on `data.simulate` runs): 300 steps: inflow 20.27 +- 0.99,
  kin 0.2015 +- 0.0099, **delay 10.51 +- 1.45**, kb 0.2022 +- 0.0092; delay within 10% in 48% of
  seeds, all four numbers within 10% in **47.5%**. 2000 steps: delay 10.62 +- 1.20, all four within 10%
  in **60%**. The profile likelihood confirms it: on 2000-step seeds -2 log L rises by only ~0.6-1.3
  one step either side of the optimum (an SE of about one step, 10%, at any length the ladder uses),
  because at equilibrium only the counting noise carries the delay.
- On 015 counts-short itself, A's row alone (the truth's structure for A) gives inflow 22.98 +- 3.03
  and kA 0.230 +- 0.030 (15% SE); B's row fitted **with H observed** gives kb 0.185 +- 0.027 (13% SE).

So a pass on 015 counts-short (and, at 60%, counts-long) is partly luck. Proposed change to
`sdlab/ladder/score.py` / `oracle.py` (not made: shared module): give hidden-stock cases an oracle,
the truth's structure with H's level taken from `all_levels` (or, better, this filter's ML fit of the
truth's structure, which needs no hidden data) and its SEs (delay by the delta method from d), and
allow `z x SE` on `k_in`, the delay and the other parts as for linear cases.

## Bench results

Examples (benchmark v2.1; baseline 29.6% / 29.3% / 12 of 62, fresh 28.9% / 29.7% / 12):

| strategy | skill@20 / @100 | fresh @20 / @100 | goal (fresh) | parts |
|---|---|---|---|---|
| matrix (v2.1) | 29.6 / 29.3 | 28.9 / 29.7 | 12 (12) | 53.5% |
| mass_balance v3 (its topic document) | 30.7 / 31.3 | 30.1 / 31.7 | 12 | |
| **hidden_transit** | **31.2 / 33.5** | **30.6 / 34.0** | **13 (13)** | **55.0%** |

Paired with v2.1: skill@20 10 better, 1 worse, 51 the same (sign test p = 0.012, Wilcoxon p = 0.024);
skill@100 9 better, 2 worse (Wilcoxon p = 0.014). Transit stocks accepted in 11 runs, each worth a
part (+1): sd-fishery default / long +37.7 / +36.3 at skill@20 (+128 / +110 at @100), sd-webshop-stock
+5.1 / +15.7 (@100 +15.9 / +31.5), sd-farm-soil @100 +10.5 / +6.0, sd-hidden-chain +2.0 / +2.2,
sd-housing default +0.9, sd-manufacturing long +1.0. Worse by more than 2 points: sd-recycling default
(-6.8 @20, -3.6 @100: the true rail stock between bales and shelves, found with a share 0.11 of 0.18
and delay 14 against the truth's 6; its sender's loss is a co-flow the local model does not have).
Discovery ~680 s over the 62 runs (longest sd-ev-fleet long, 129 s), about mass_balance's.

Before the last two guards (no slack in the behaviour check; margin 4 log n, at most 1.5x the found
model, not back along a move) the first runs accepted false stocks on sd-moderation long (-47 points,
a 1.1-step "delay"), sd-manufacturing default (finished -> H -> inspection, -7.6) and two generated
models without hidden stocks (gen 25, both lengths, 61% -> -100%; gen 36 long 43% -> -50%).

Generated models (dev pool, 100 models, 200 runs), paired with `matrix`'s run on the same models
(`2026-10-18T23-43-22` "matrix generated (censored reference)": -52.4% / -48.1%, 7 of 200 meet the goal):

| strategy | skill@20 / @100 | fresh @20 / @100 | goal | parts | discovery |
|---|---|---|---|---|---|
| matrix | -52.4 / -48.1 | -52.4 / -48.1 | 7 of 200 | 1938 | 492 s |
| **hidden_transit** | **-51.1 / -47.7** | **-51.0 / -47.6** | **8 of 200** | **1942** | 728 s |

(Each run clipped at -100%.) No run is worse at either horizon. Changed runs: gen 53 long (hidden
delay) -19% -> 93% at @20, 30% -> 97% at @100 (newly meets the goal); gen 34 default -27% -> 37%
(@100 63% -> 84%); gen 49 default and gen 76 long -100% -> -52% / -58%; gen 22, gen 60 +1 part;
gen 7 default +1.3 / +2.5. One false transit stock (gen 47 long, 5 -> 4 parts, skill unchanged at
-100%).

## Verdict

Adopt as a candidate for the main line (behind its own acceptance, which is what keeps it off every
non-hidden ladder case and off the generated models without hidden delays). It is the first strategy
to pass the hidden-stock rung, it fixes the two reasons `mass_balance` could not (the mirror and the
shared noise), and on the examples it finds more true hidden stocks than `mass_balance` did.

## Open ideas

- **The oracle for hidden cases** (above): until then 015's counts variants measure luck as much as
  method.
- **Chains of hidden stocks** (an Erlang delay, A -> H1 -> H2 -> B): the filter generalises to a
  small state; choose the number of stages by BIC, or by a subspace estimate of the order of B's
  response to A (the Hankel singular values of the A -> B impulse response).
- **Pairs the main line hides**: B's arrivals read as a link from a third stock, A's loss as a
  co-flow (recycling's bales -> rail), or a transit whose receiver is fed only by a move (the
  candidate rule needs an outside constant on B or a move/link from A).
- **The whole model in one filter**: every row's counting noise, with all transit stocks at once, in
  place of the pair-by-pair greedy search (the local model already handles kept flows as inputs).
- **Refit the rest after acceptance**: the kept flows (other rows reading B, or A's other outflows)
  were measured beside the wrong pair; one more pass of the main line with H's filtered level as a
  known column would let them settle.
- Use the counting-noise lag signature directly as a screen: with counts, the cross-correlation of
  A's innovations with B's peaks at the transit's delay (B's arrivals echo what left A), a test that
  needs no fit.
