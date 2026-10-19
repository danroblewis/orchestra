# Realistic cases: what goes wrong (triage, 19 October 2026)

**Status:** triage done; distilled cases 152-161 added (commit 52cd6d1); strategy `realistic_hats`
built on it (docs/research/realistic-hats.md). **Question (the user):** "our realistic example checks
are absolutely trashed. I don't know if any of them actually passed." Why, case by case, and what
would fix it?

## The short answer

- **Equations:** of the 66 realistic cells (31 sd-* examples + sd-k8s-small + sd-k8s-platform, two
  lengths each), at most one passes for any strategy (combined, structures, kalman_lna,
  earned_pieces, common_cause each pass 1; effect_hats, censored and matrix pass none). On models
  with 8-17 flows, hidden stocks, co-flows and effects, an exact pass is not expected yet;
  behaviour is the headline (LADDER.md "Realistic cases").
- **Behaviour** (mean in-sample skill@20, clipped at -100%, over the runs graded; `api.summary()`
  at 19 Oct 2026 ~07:00, board versions mixed): effect_hats 49.9% (54 graded, 9 timeouts), censored
  41.3%, structures 40.5%, combined 40.4%, kalman_lna 36.8%, earned_pieces 35.0%, matrix 30.6%, the
  lna family 17.5-30.4%. Goals met (skill@20 >= 90% and skill@100 >= 80%): 10-16 of 66.
- **Is it the grading?** Partly, in about a sixth of the runs; see the next section. Most of the gap
  is discovery: a hidden stage, a co-flow or a flow driven by another stock is missed, and an outside
  inflow (pieces) stands in for it.

## Is it the grader? (`tests/study_realistic_grading.py`, commit 0dc412d)

The grader (sdlab/skill.py `same_behaviour`) runs the found model and the truth from the same
levels, both fed the truth's outside inflows: in every stock the truth feeds with a constant
outside inflow, the found model's driverless constant outside inflows are dropped and the truth's
put in their place. The study re-grades every stored latest realistic model of 7 strategies four
ways, in-sample skill@20, without changing the scorer:

- **graded**, as the ladder grades it (recomputed);
- **own**, the found model with its own inflows and pieces, nothing swapped;
- **full**, as graded, but the truth's constant inflows keep every schedule segment (a non-constant
  segment is not set to 0);
- **replay**, a model with no dynamics at all: each stock's mean change per step over the found
  model's own piece cuts, graded as "own". It is what the piece budget buys by replaying the run.

Command: `JOBS=2 uv run python tests/study_realistic_grading.py OUT.jsonl` (431 runs, ~10 min).

| strategy | runs | graded | own | full | replay | @20 >= 0.9: graded / own / replay |
|---|---|---|---|---|---|---|
| effect_hats | 54 | 0.499 | 0.817 | 0.503 | 0.355 | 16 / 29 / 5 |
| censored | 61 | 0.413 | 0.798 | 0.414 | 0.387 | 18 / 33 / 6 |
| combined | 64 | 0.398 | 0.768 | 0.403 | 0.399 | 17 / 34 / 8 |
| structures | 64 | 0.399 | 0.769 | 0.404 | 0.396 | 17 / 34 / 8 |
| kalman_lna | 64 | 0.340 | 0.728 | 0.345 | 0.399 | 15 / 31 / 8 |
| earned_pieces | 61 | 0.350 | 0.708 | 0.352 | 0.366 | 16 / 28 / 7 |
| matrix | 63 | 0.306 | 0.710 | 0.308 | 0.356 | 14 / 25 / 6 |

What it says:

1. **Zeroing the non-constant schedule segments does not matter** (full = graded within 0.01).
2. **"Own inflows" is not a fair grade either.** A model with no dynamics, given the same pieces,
   already scores 0.36-0.40, about what the strategies score graded. Own-inflow skill (~0.8) is
   mostly replay.
3. **About half the runs are not touched by the swap** (own within 0.1 of graded: 32-37 of ~62 per
   strategy). Their failures are discovery's alone: sd-brewery, sd-ci, sd-fishery, sd-orders,
   sd-supply, sd-university, sd-moderation and others.
4. **The swap costs a model whose own dynamics are sound** (own >= graded + 0.1 and own >= replay +
   0.3) in 9-15 runs per strategy: sd-sawmill (14 strategy-runs), sd-learning-curve (14),
   sd-webshop-stock (9), sd-emergency (8), sd-cloud-credits (6), sd-eras long (6), sd-clinic-doses
   (5), sd-housing long (5), sd-bakery (4). In each, the found model puts endogenous behaviour
   into its outside inflow. Either the inflow is several times the truth's and a drain balances
   it (sd-learning-curve backlog 60.8 against 28; sd-sawmill sharpness 24.5 against 6 x f(own
   level)), or a link carries part of it (sd-cloud-credits' queued; sd-housing's 0.001 x occupied
   read as 20 more of constant inflow). Fed the truth's inflow, such a model breaks. This is mostly
   a real structural error that the swap exposes (mechanism B below). sd-sawmill is the arguable
   one: the truth's "constant" sharpening inflow carries an effect of its own stock, so it is not
   exogenous. The user has been asked about a narrow change (swap only constants with no effect).
   The scorer is unchanged.

## Triage table (33 cases)

Per case: the best strategy's in-sample skill@20 (short / long) from the store, and the mechanisms
that cost the most behaviour. Read with `uv run sdlab-ladder show sd-<x> --strategy <s> --variant
counts-short` and the per-case dumps behind this document (truth, found flows, wrong parts, the
grading study). "T/O" = a timeout.

| case | best @20 short / long | main mechanisms (letters below) |
|---|---|---|
| sd-bakery | 0.80 effect_hats / 0.72 censored | B (orders inflow + constant drain stand in for bake), C (flour co-flow as an effect plus drain), D |
| sd-brewery | 0.81 combined / 0.82 censored | A (malt -> wort -> fermenting), C (pitch uses yeast on the hidden flow), G (unannounced drain-rate step) |
| sd-ci | 0.89 censored / 0.90 structures (effect_hats T/O) | A (review), C (approve uses minutes on the hidden flow), K |
| sd-clinic-doses | -0.07 combined / -0.38 combined (effect_hats, censored T/O) | B (walk-in co-flow folded into the doses inflow, 205 pieces), C (128, 129), G (450 delivered 1 day in 7) |
| sd-cloud-credits | -0.10 effect_hats / -0.16 matrix | B (submit 1.56 against 4.25 plus a link from credits), C (129: credits run out), A (postproc) |
| sd-emergency | 0.64 combined / 0.82 effect_hats | E (treat = waiting x staff x table(waiting) read as additive links), F (fatigue), G (12-step staff cycle) |
| sd-eras | 0.99 / 0.49 combined (effect_hats T/O) | G (announced eras on two moves read as one rate), B (spurious loop and pieces compensate) |
| sd-ev-fleet | 0.65 effect_hats / 0.61 censored (effect_hats T/O) | A on a closed loop (road -> returning -> queue as a shortcut), D (capacity-fill move), E (dispatch read off parcels) |
| sd-farm-soil | 0.95 effect_hats / 0.98 combined | F (effect on an outside inflow: 510 pieces), C (harvest uses nitrogen), A (ripe) |
| sd-fishery | 0.42 effect_hats / 0.43 combined | E (catch = 4 x at_sea found from in_port, wrong sign), C (launch uses fuel), A (cold store) |
| sd-hidden-chain | 1.00 / 1.00 combined | A (two hidden stages as one); behaviour fine |
| sd-hospital | 0.97 matrix / 1.00 combined (effect_hats T/O) | A, C; data near stationary (replay 0.97): skill says little |
| sd-housing | 0.97 censored / 0.94 effect_hats | B (link 0.001 x occupied ~ 20 a step absorbed into a constant), E (flows of a slow stock read as constants), A (permits) |
| sd-k8s-platform | none (only lna_products ran, no skill) | K (227 measured stocks, 1,130 flows: scale) |
| sd-k8s-small | none short / 0.87 matrix | K (combined and structures empty; effect_hats and censored T/O) |
| sd-kanban | 0.85 censored / 0.76 combined | G (fortnightly pulse of work and capacity top-up), A (hidden rework), C |
| sd-learning-curve | 0.57 combined / 0.45 combined | F (131: solve and learn x table(experience)), B (backlog inflow 60.7 against 33.6), G (forget eras) |
| sd-manufacturing | 0.81 effect_hats / 0.87 matrix | A + C (packing uses cartons on the hidden stage's exit), A (supply line, 133), E (cross-driven start/ship), B |
| sd-moderation | -0.40 combined / -0.99 matrix (effect_hats T/O) | B (screening inflow 353 against 10.6, cancelled by drains), runaway (negative intercepts), A + C (vendor stage uses credits) |
| sd-orders | 0.76 effect_hats / 0.88 censored | D (order gap over stock and pending, unequal weights: 124), C (order uses budget), G (steps in a constant outflow) |
| sd-pipeline | 1.00 combined / 0.99 censored | B (one inflow piece, a move cut to a third plus a link), runaway (self-link in combined long) |
| sd-population | 0.68 effect_hats / 0.50 effect_hats | B (immigration absorbs the ageing move), H (elderly -> adults reversed), replay 1.0 short |
| sd-print-shop | 0.40 effect_hats / -0.96 combined | B (queue inflow 373 with a constant drain 333; move 0.008 for 0.5), C (paper and toner) |
| sd-recycling | 0.75 effect_hats / 0.94 effect_hats | A on a loop (rail), C (sell uses wagons, with a threshold), H |
| sd-reservoirs | 0.98 structures / 0.95 effect_hats | H (affine releases -6 + 0.02 x upper read as proportional) |
| sd-restaurant | 0.77 censored / 0.65 censored (effect_hats T/O) | H (net affine move read as two moves), A (plating), C + G (fire uses prep, announced eras) |
| sd-saas | 1.00 / 1.00 | A (lapsed: 0.001, negligible); behaviour fine |
| sd-sawmill | -2.61 censored / -2.07 matrix (all -1 clipped) | B (sharpening: 123), C + F (cut x table(sharpness) uses sharpness: 130), A (kiln) |
| sd-services | 0.98 effect_hats / 0.97 censored (effect_hats T/O; combined empty) | K (combined returned no model: fixed, beab53e), C (co-flow on a link-driven inflow) |
| sd-supply | 0.97 / 0.93 effect_hats | D (ship = (250 - shop) / 3, the destination's gap, found reversed), C (fuel), A (trucks) |
| sd-support-tiers | -5.15 effect_hats / 0.95 combined | B (customers' inflow: a link on a gap-pinned stock stands in), E (tier2 solved split into drain + link), C, A |
| sd-university | 0.75 effect_hats / 0.76 censored | G (enrolment rate rises in 4-step windows every 52), D (rooms refill read as self-growth plus a constant drain) |
| sd-webshop-stock | 0.74 effect_hats / 0.86 effect_hats | B + runaway (combined short: self-growth of backlog, 130), A (in transit), F (reorder x table(backlog)) |

## Mechanisms, counted

A case counts under every mechanism among its main costs (so the counts overlap).

| | mechanism | cases | covered by | new distilled case | what would fix it |
|---|---|---|---|---|---|
| A | **a hidden stage missed**: a delay between measured stocks read as a drain of A plus outside pieces into B, or a shortcut | 19 (brewery, ci, cloud-credits, ev-fleet, farm-soil, fishery, hidden-chain, hospital, housing, kanban, manufacturing, moderation, recycling, restaurant, saas, sawmill, supply, support-tiers, webshop-stock) | 015, 063, 133, 135 (every leader but structures and hidden_transit fails them) | **156** (on a closed loop), **161** (its exit uses a stock) | hidden transit stocks on the leader's model (realistic_hats does this), hidden stages fed from a co-flowed exit, loops |
| B | **an outside inflow stands in for a flow** (inflow plus a cancelling drain, a link absorbed into a constant, a move folded into the inflow); the grader's swap breaks it | 15 (bakery, clinic-doses, cloud-credits, eras, housing, learning-curve, manufacturing, moderation, pipeline, population, print-shop, recycling, sawmill, support-tiers, webshop-stock) | 123, 131 (their forms) | **153** (a link from a large slow stock), **154** (a slow move into a stock with its own stepping inflow) | a judge that does not replay pieces (combined.md); prefer the flow over the constant when both explain the row; pieces priced against links |
| C | **co-flows missed**, read as a drain following another stock, as links, or folded into an inflow | 17 (bakery, brewery, ci, clinic-doses, cloud-credits, farm-soil, fishery, hospital, kanban, manufacturing, moderation, orders, print-shop, recycling, restaurant, sawmill, services) | 016, 128, 129, 130 | **161** (on a hidden stage's exit); a plain co-flow on a gap-restocked stock was tried and is recovered as equivalent, so it is not the mechanism | co-flows on hidden flows; a co-flow whose used stock is restocked by a gap |
| D | **a gap misread**: the gap of the destination drives a move, gaps over two stocks with unequal weights, capacity fills | 6 (bakery, ev-fleet, orders, supply, university, services) | 011, 124, 125 | **155** (a move set by the gap of the stock it fills) | a gap column of the destination in the move's rows |
| E | **a flow driven by a stock it does not join** (a move set by a third stock, cross-driven drains, products) | 6 (emergency, ev-fleet, fishery, housing, manufacturing, support-tiers) | 126, 127 (products) | **152** (a move driven by a third stock) | moves (not link + drain pairs) with any stock as driver, conserving the pair |
| F | **an effect missed or put on the wrong flow** | 6 (emergency, farm-soil, learning-curve, sawmill, webshop-stock, bakery) | 017, 018, 123, 130, 131 | **160** (an effect on an outside inflow) | effect_hats' screen on outside inflows (base 1 x f(C)) |
| G | **rates or inflows on a schedule** (announced eras on several moves, unannounced rate steps, periodic windows and pulses) | 10 (brewery, clinic-doses, emergency, eras, kanban, learning-curve, orders, restaurant, saas, university) | 019, 020, 021, 022, 132 | **157** (eras on two moves and an inflow step), **159** (a fortnightly pulse and top-up) | era-aware rates on every move; a periodic schedule found as such |
| H | **affine flows and two-way ambiguity** (a release with a threshold, a net move read as two) | 4 (population, recycling, reservoirs, restaurant) | 009 (net rates) | **158** (an affine release) | a constant term on moves |
| K | **time and scale**: timeouts, empty models | 3 cases + 9 effect_hats runs (ci, clinic-doses, eras, ev-fleet, hospital, k8s-small, moderation, restaurant, services) | none (not a property) | none | an anytime strategy (realistic_hats); combined's fallback (beab53e); a scalable base for k8s |
| - | data-limited or behaviour already near 1 | sd-saas, sd-hidden-chain, sd-hospital | | | nothing: their skill is right, their equations miss tiny flows |

## The new distilled cases (152-161)

Written as invariant 4 asks: the smallest model that makes the leaders make the hard case's mistake.
Checked with `sdlab-ladder check` (all ok), the truth passing its own scoring
(`tests/test_ladder.py -k "...and (sane or own_equation)"`, 30 passed), and a run of effect_hats,
censored and matrix (`sdlab-ladder run --strategies effect_hats,matrix,censored --cases 152,...,161
--jobs 2`, 19 Oct 2026). Letters: none-short, none-long, counts-short, counts-long. P pass, E
equivalent, F fail; then the mean fresh skill@20 over the four (each clipped at -100%).

| case | from | effect_hats | censored | matrix | the same mistake? (effect_hats, unless named) |
|---|---|---|---|---|---|
| 152-move-driven-by-third-stock | sd-fishery, sd-manufacturing | EEFE, 89% | EEFF, 57% | EEFF, 58% | yes, on counts: the move as two links reading S (A -> out 3.96 S, out -> B 3.91 S) plus a stray S -> B; matrix and censored counts-short -0.47 |
| 153-link-from-large-slow-stock | sd-housing, sd-support-tiers | FFEF, -100% | FFFF, -100% | FFFF, -100% | yes: H's inflow a constant 58.96 (32 + the link's ~20), no link; graded with the true 32 it runs off (skill -13 to -42) |
| 154-move-into-stepping-fed-stock | sd-population | FFEF, 39% | FFFF, 37% | FFFF, 37% | yes: B -> A reversed (0.021 B, the births read as a move back), immigration halved on counts-long (406 against 795) |
| 155-gap-of-downstream-drives-move | sd-supply | FFFF, 99% | FFFF, 94% | FFFF, 96% | yes: the move reversed (S -> W 0.37 S), W drained by a constant and inflow pieces into S |
| 156-hidden-stage-on-closed-loop | sd-ev-fleet, sd-recycling | FFFF, 62% | FFFF, 62% | FFFF, 62% | yes: a shortcut A -> B 0.075-0.12 A, A -> out and an inflow piece into B (counts-long skill 0.08) |
| 157-two-chained-eras | sd-eras | FPFF, 0% | FPFF, 0% | FPFF, 0% | yes on counts: one rate per move, a doubled inflow and drains of A and B (skill -5 to -10) |
| 158-affine-release | sd-reservoirs, sd-recycling | EEFE, 13% | EEFE, 10% | EEFE, 10% | yes: proportional release, the intercept moved into A's inflow (28.4 against 20.7) and a constant drain of B; counts-short skill -2.2 |
| 159-periodic-pulse-and-top-up | sd-kanban | FFFF, -38% | FFFF, -74% | FFFF, -39% | yes: constant inflows of A and K with drains following B and K |
| 160-effect-on-outside-inflow | sd-farm-soil | FFFF, -100% | FFFF, -100% | FFFF, -100% | yes: no effect; the inflow as pieces, or N drained into A |
| 161-hidden-stage-exit-coflow | sd-manufacturing, sd-brewery, sd-ci | FFFF, 77% | FFFF, 60% | FFFF, 56% | yes: no hidden stage (A -> out, inflow pieces into B), K drained by links from A and B |

Tried and dropped (they did not reproduce the mistake, so they are not on the ladder): a fast queue
under a stepping inflow (sd-print-shop, sd-moderation: all three pass it, so the fast stage alone is
not what fails there), and a co-flow on a gap-restocked stock (sd-hospital: recovered as an
equivalent drain of K reading A).

## Grading questions for the user (not changed)

- **The swap of "constant" inflows that carry an effect** (sd-sawmill's sharpening, 160's growth): the
  truth's inflow is endogenous there, but it is fed to the found model as if exogenous.
- **sd-restaurant**: graded 0.65-0.77 against 0.94 own with nothing swapped; the triage agent
  suspects the truth's arrivals are added on top of a found reverse move that supplies the same
  stock. Not checked further.
