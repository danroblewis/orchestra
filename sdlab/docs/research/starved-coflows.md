# Co-flows found where the used stock runs dry

**Status:** idea (not started)

## Why
In the co-flow examples the used stock runs dry for stretches, and while it does the engine scales the
flow down to what the used stock holds. The source queue then piles up 7-14 times its usual level
(sd-print-shop default: mono_queue 400 -> 5590 while toner sits near 30 g and paper near 64-108
sheets; sd-bakery: orders 86 -> 677 while flour is at 4-14 kg; sd-cloud-credits: queued 18 -> 146 while
credits are near 0 for about 15% of steps). The one-step fit mixes the two regimes. The source's drain
comes out at a fraction of the truth: bakery orders -> shelf 0.0046 + link 0.057 against 0.5;
print-shop mono_queue -> done 0.008 + link 0.078 against 0.5; cloud-credits queued -> running 0.16
against 0.3. Inflow pieces fill the gap (print-shop long: 1362 pieces). Fed the true inflows, a model
with no cap runs away (v2.1 skill@20: -1170%, -529%, -859%). Our simulator already applies the cap
when a flow declares `uses`, so what is missing is finding the `uses` and fitting the source row on
the steps where the cap does not bind. Starvation also shows in sd-kanban (capacity), sd-restaurant
(prep), sd-clinic-doses (doses), sd-brewery (yeast), sd-hospital (kits) and sd-moderation (credits).
This differs from [censored-floors](censored-floors.md), which censors a stock's *own* outflows when it
empties, and from [count-likelihoods](count-likelihoods.md), which reads `per` from shared noise but
leaves the starved steps in the fit. It turns the symbolic-regression open idea "a dedicated co-flow
search for flows limited when the used stock runs dry" into an experiment.

## How it could be tried
- Strategy `starved_coflows`, module `discovery/starvation.py`. For each stock C whose row has a
  cross term "C drains faster when A is high" (any unit), mark C's starved steps: steps where C's level
  at the start of the step is below what that term takes in a step.
- Test the signature: A's residual is positive on C-starved steps (A drains less than its rate says).
- Refit A's row and its receivers' rows with C-starved steps masked. Estimate `per` as C's loss over the
  flow's fitted amount on unstarved steps. That is a flow-rate column (per x k x A), not a raw level.
- Emit the move with `uses: [{stock: C, per}]` and drop the cross term. Enter the result as a candidate.
- Mechanism test (`tests/synth.py`): orders (inflow 40) -> shelf at 0.5 x orders using 0.5 flour per
  loaf; flour restocked by a gap (goal 600, time 10), switched unannounced to time 60 for 60 steps so
  that flour runs dry. Baseline: orders' drain below 0.25 and skill@20 below 0. Strategy: k within 0.05,
  `per` within 0.1, skill@20 above 0.9. Controls: fast restock, where flour never falls below 200, gives
  no masking and the matrix result within 0.01. A real outflow of C driven by A with no starvation gets
  no `uses`.
- Targets: sd-bakery, sd-print-shop, sd-cloud-credits, sd-clinic-doses, sd-kanban, sd-restaurant @100,
  sd-brewery, sd-hospital, sd-moderation.

## Sources
Tobin (1958) Econometrica 26(1):24-36; Lariviere and Porteus (1999) Manage. Sci. 45(3):346-363 (sales
capped by stock are censored demand); Paoletti et al. (2007) Eur. J. Control 13(2-3):242-260 (known
switching surfaces); Martinelli et al. (2022) Reactmine, arXiv:2209.03185 (fixed-ratio co-variation);
[symbolic-regression](symbolic-regression.md) open ideas; failure analysis in [IDEAS-WAVE4](IDEAS-WAVE4.md).
