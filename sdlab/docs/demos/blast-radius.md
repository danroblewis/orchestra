# Demo 12: blast radius across services

Ideas 22 (blast-radius map) and 33 (dependency risk) in `OPERATIONALIZATION.md`. Page: `/demos`, tab
"12. Blast radius". Code: `sdlab/demos/blast_radius.py`, `sdlab/static/demos-blast-radius.js`, tests in
`tests/test_demos_blast_radius.py`.

## What it shows

One service of a multi-service system slows down. Which other services feel it, how much, and how soon? The demo
answers with a found model and, beside it, with the true model of the same simulated system, so you can see where the
found model is right and where it is wrong.

- **Systems:** ladder case 315 (fan-out: frontend calls catalog and cart, catalog calls pricing) and 314 (a chain:
  frontend → catalog → pricing). Each service has a queue, requests in flight, and a counter of responses. Case 316
  (the shared database) has no passing result yet, so it is not offered.
- **Found models:** the stored passing results of kalman_lna, engine_forms, milp, structures, sindy, z3robust and
  lna_stack on none-long and counts-long, where they exist (the picker shows the result id; the page shows strategy,
  result id, status and commit).
- **The fault:** from step T (default 1000), one service's dispatch rate (pods pick up waiting requests) or
  completion rate (requests finish) is set to 75%, 50%, 25% or 0% of normal.
- **The picture:** two diagrams (found, true) of the services as boxes with arrows for calls. Each box is coloured by
  the service's largest move and labelled with when it first moved past 5%. Links the found model has but the truth
  lacks are drawn red and dashed; true links the found model misses are drawn orange and dotted. Then a table of every
  stock (largest move, and when it first moved, found and true), and charts of the stocks that moved.
- **Dependency risk:** each service is slowed in turn. Its *spread* is the sum of the other services' largest moves.
  The services are ranked by spread, found model beside true model, with the services each slowdown reaches.

## How it works

- The true model is the case's (`cases.truth_model`), run noise-free by the truth engine. The fault is a schedule
  change on an in-memory copy (`engine.run_truth(change=...)`), using the true flow between the two stocks
  (`engine.true_flow_between`) with its rate scaled (`engine.scale_true_rate`).
- The found model is run free by the scorer's simulator for found models (`engine.free_run`), starting from the true
  levels at the first step. It runs to step T−1 as found, then from there with every found flow between the same two
  stocks scaled by the same factor. If the found model has no such flow, the page says so (a missed flow) and does
  not compare.
- Each model is compared with **its own** run without the fault, so the found model's small fitting errors do not
  count as impact. A stock's move is (with fault − without) divided by its typical level after T without the fault.
  A counter is read as its increase per step (responses per step). A stock has *moved* once that is more than 5%.
  A service's move is its largest stock's move, and its arrival time is the first time any of its stocks moved.
- The call graph of a model: service X → Y when a flow into (or out of) one of Y's stocks reads, or moves from, one
  of X's stocks. That gives the true and found graphs and their differences.
- Each request takes well under a second (a spread runs four simulations of 2000 steps; the ranking runs one spread
  per service, about 1 s), and results are cached in memory. No precomputed cache or new discovery run was needed.

## What it found (2026-10-22)

Produced by `B.setup()`, `B.spread(...)` and `B.ranking(...)` over every offered model, every service, both kinds of
fault, at 50% and at 0%, from step 1000 (the endpoints `/api/demos/blast-radius/setup`, `/spread`, `/ranking`):

- **Noise-free fits (none-long), all 12 models on 314 and 315:** the blast radius is exactly the truth's. Same
  services, same arrival steps, peaks within 1%. Example (315, kalman_lna #386697, catalog completion at 50% from
  step 1000): catalog moves at once (in-flight +177% of its typical level), pricing moves 1 step (5 min) later
  (+177%); frontend and cart do not move, in both models. The dependency ranking is the same for every model:
  frontend first (its slowdown reaches cart, catalog and pricing), catalog second (reaches pricing), cart and pricing
  spread nothing.
- **Counted fits (counts-long) with a false link:** some found models have a small flow the truth lacks, and the demo
  shows it as a false spread.
  - 315, kalman_lna #384532, engine_forms #384553, lna_stack #384543: a flow `cart_queue → frontend_queue`
    (k ≈ 0.008–0.010). With cart stopped (dispatch at 0%), the true model moves only cart. The found models say
    frontend, catalog and pricing all move about 50% (55% for engine_forms), frontend about 15 steps (75 min) after
    the fault. They also say cart's queue grows far less (+10,907% vs +50,106% for kalman_lna), because the false
    flow drains it into frontend. At 50% slowdowns the false link stays under the 5% line (frontend moves about 1%).
  - 314, kalman_lna #384517, engine_forms #384515, z3robust #384530: frontend's completions read catalog's requests
    in flight (a false catalog → frontend link). A catalog slowdown at 50% moves frontend 7% in the found model and
    not at all in the truth; at 0% the found model says 89%. In the ranking, catalog's slowdown "reaches" frontend in
    these found models, not in the truth (same order, different reach).
  - The other counted fits (structures, sindy, z3robust on 315; milp, structures, sindy, lna_stack on 314) have the
    true call graph and the true reach. With a service stopped (0%), where its queue grows without limit, their peak
    sizes can differ from the truth's by more than 20% (marked "size").
- No found model in this set misses a true link.

## Limits

- The true models of 314 and 315 have no backpressure: a caller does not wait on its callee, so a slowdown only
  spreads downstream, to the services a service calls. Real services often push trouble upstream too (callers' requests
  pile up while they wait, and retries add load). This demo cannot show that until a case with it passes. 316 (a
  shared database whose pool caps both callers) is the obvious next system, but no strategy passes it yet.
- The 5% line and "typical level" are simple choices. They are not calibrated on noise, and the runs are noise-free.
  Peaks of a stopped service's queue (unbounded growth) depend on the run length.
- The fault scales the whole flow between two stocks. A found model that writes that flow differently (two flows,
  an expression) is scaled as a whole too; one with no flow there cannot be compared.
- Services are named by the stock prefix (`catalog_queue` → catalog).

## Shared-code notes (not changed by this demo)

- `engine.stored_model`'s fallback (newest passing result when the latest is not one) calls `store.connect()`
  without `with`, which raises `AttributeError`; this demo does its own lookup (`blast_radius._stored`).
- `demos.js` rewrites the URL to `?demo=residual` before the extra demos' scripts load, so `?demo=blast-radius`
  (any extra demo) does not open that tab; the tab must be clicked.
