# Web shop: the answer key

For graders. The model (`../shop.json`) is told only what a Prometheus dashboard shows at the end
of every second: requests in flight per service, messages waiting per queue (consumer lag), and
jobs in progress per worker pool, 42 stocks in one group, no flows. This is what the simulation
(`machines/sim.py`, seed 20261016, 7200 one-second steps, 6,017,561 requests,
96,014 messages) really does. `python truth.py` regenerates `truth.json`: the graph,
every parameter, and the SD structure with the coefficients a perfect discovery would report.
`tests/fixtures/shop-run.json` holds the imported run plus the simulator's per-second counters
(requests handled, calls per edge, messages produced and consumed, jobs done), which the model
never sees.

## How the simulation works

- **External traffic** arrives at three edge services (web-frontend 30/s, mobile-api 20/s,
  partners at the api-gateway 4/s, on average) as a non-homogeneous Poisson process: a day
  compressed into two hours (quiet at the start and end, busiest at t = 3600, x0.5 to x1.6), a
  **flash sale** (web and mobile traffic x2 from t = 3600 to 4200, ramping over a minute) and a
  **partner burst** (api-gateway external traffic x5 from t = 5000 to 5100).
- **A service** serves `capacity` requests at once; beyond that, requests wait FIFO inside it.
  In flight = being served + waiting. Each request takes a lognormal time (mean latency, cv).
  While serving it, the service makes `fan-out` calls on average to each callee (floor(f) plus
  one more with probability frac(f)), each at a uniformly random moment of its service time.
  Calls do not hold the caller up (a caller's latency already includes its usual wait; there is
  no backpressure up the graph). A finished request may publish one message into a queue.
- **A queue** holds messages until a worker of its one consumer pool is free (FIFO).
- **A worker pool** has N workers (N changes in eras). A worker takes the oldest message, works
  on it for a lognormal time (cv 0.4 to 0.5), calls services while working, as a service does, and
  may publish a message when done. A worker told to stop finishes its job first.

Every request and message is accounted for: each stock's change in every step equals what
arrived minus what left (tested in `tests/test_example_shop.py`).

## The true structure

Dashed arrows are **information links**: the source's level drives the target's arrivals and
nothing leaves the source (labels: fan-out, or the probability of a message). Thick arrows are
**real flows**: a message leaves the queue and becomes a job. Not drawn: every service and
every pool also drains to outside (requests finish, jobs finish).

```mermaid
flowchart LR
    OUT(("outside"))
    web_frontend["web-frontend"]
    mobile_api["mobile-api"]
    api_gateway["api-gateway"]
    auth["auth"]
    session["session"]
    feature_flags["feature-flags"]
    user_profile["user-profile"]
    catalog["catalog"]
    search["search"]
    pricing["pricing"]
    currency["currency"]
    inventory["inventory"]
    recommendations["recommendations"]
    reviews["reviews"]
    image_service["image-service"]
    cart["cart"]
    checkout["checkout"]
    payment["payment"]
    fraud_check["fraud-check"]
    tax["tax"]
    shipping_quote["shipping-quote"]
    address_validation["address-validation"]
    promotions["promotions"]
    order_service["order-service"]
    loyalty["loyalty"]
    notification["notification"]
    email_gateway["email-gateway"]
    sms_gateway["sms-gateway"]
    analytics_ingest["analytics-ingest"]
    merchant_api["merchant-api"]
    order_placed[/"order-placed"/]
    payment_captured[/"payment-captured"/]
    email_requested[/"email-requested"/]
    product_changed[/"product-changed"/]
    profile_updated[/"profile-updated"/]
    clickstream[/"clickstream"/]
    fulfillment_workers[["fulfillment-workers"]]
    loyalty_workers[["loyalty-workers"]]
    email_workers[["email-workers"]]
    search_indexer[["search-indexer"]]
    profile_sync_workers[["profile-sync-workers"]]
    analytics_workers[["analytics-workers"]]
    OUT -. external .-> web_frontend
    OUT -. external .-> mobile_api
    OUT -. external .-> api_gateway
    web_frontend -. 1 .-> api_gateway
    web_frontend -. 1 .-> session
    web_frontend -. 0.5 .-> feature_flags
    web_frontend -. 2 .-> image_service
    web_frontend -. 1 .-> analytics_ingest
    mobile_api -. 1 .-> api_gateway
    mobile_api -. 1 .-> session
    mobile_api -. 1 .-> feature_flags
    mobile_api -. 0.5 .-> analytics_ingest
    api_gateway -. 0.8 .-> auth
    api_gateway -. 0.6 .-> catalog
    api_gateway -. 0.3 .-> search
    api_gateway -. 0.3 .-> recommendations
    api_gateway -. 0.25 .-> cart
    api_gateway -. 0.2 .-> user_profile
    api_gateway -. 0.04 .-> checkout
    api_gateway -. 0.012 .-> merchant_api
    auth -. 0.5 .-> session
    auth -. 0.3 .-> user_profile
    search -. 0.5 .-> catalog
    search -. 0.5 .-> pricing
    recommendations -. 0.8 .-> catalog
    recommendations -. 0.5 .-> user_profile
    merchant_api -. 1 .-> catalog
    catalog -. 1 .-> pricing
    catalog -. 0.5 .-> inventory
    catalog -. 0.5 .-> image_service
    catalog -. 0.3 .-> reviews
    reviews -. 0.2 .-> user_profile
    cart -. 1 .-> pricing
    cart -. 1 .-> inventory
    cart -. 0.5 .-> promotions
    checkout -. 1 .-> cart
    checkout -. 1 .-> payment
    checkout -. 1 .-> tax
    checkout -. 1 .-> shipping_quote
    checkout -. 0.8 .-> address_validation
    checkout -. 1 .-> promotions
    checkout -. 0.9 .-> order_service
    payment -. 1 .-> fraud_check
    payment -. 0.5 .-> currency
    pricing -. 0.4 .-> currency
    pricing -. 0.3 .-> promotions
    shipping_quote -. 0.5 .-> address_validation
    order_service -. 1 .-> inventory
    order_service -. 0.5 .-> notification
    order_service -. 0.5 .-> loyalty
    notification -. 0.5 .-> sms_gateway
    fulfillment_workers -. 1 .-> inventory
    fulfillment_workers -. 1 .-> shipping_quote
    loyalty_workers -. 1 .-> loyalty
    email_workers -. 1 .-> email_gateway
    search_indexer -. 1 .-> catalog
    search_indexer -. 1 .-> image_service
    search_indexer -. 1 .-> search
    profile_sync_workers -. 1 .-> loyalty
    checkout -. p 0.85 .-> order_placed
    payment -. p 0.8 .-> payment_captured
    order_service -. p 1 .-> email_requested
    merchant_api -. p 0.9 .-> product_changed
    user_profile -. p 0.015 .-> profile_updated
    analytics_ingest -. p 0.08 .-> clickstream
    fulfillment_workers -. p 1 .-> email_requested
    loyalty_workers -. p 0.2 .-> email_requested
    profile_sync_workers -. p 0.3 .-> email_requested
    order_placed ==> fulfillment_workers
    payment_captured ==> loyalty_workers
    email_requested ==> email_workers
    product_changed ==> search_indexer
    profile_updated ==> profile_sync_workers
    clickstream ==> analytics_workers
```

## Services

Depth is the longest path from the edge, through queues and pools. In flight is the measured
stock (mean and max over the 7200 seconds).

| service | depth | mean latency (s) | cv | capacity | mean in flight | max | external req/s (avg) |
|---|---|---|---|---|---|---|---|
| web-frontend | 0 | 0.3 | 0.5 | 36 | 9.91 | 46 | 30.0 |
| mobile-api | 0 | 0.25 | 0.5 | 20 | 5.546 | 33 | 20.0 |
| api-gateway | 1 | 0.08 | 0.4 | 17 | 4.784 | 23 | 4.0 |
| auth | 2 | 0.06 | 0.5 | 10 | 2.866 | 18 |  |
| session | 3 | 0.03 | 0.4 | 9 | 2.397 | 19 |  |
| feature-flags | 1 | 0.02 | 0.3 | 4 | 0.764 | 8 |  |
| user-profile | 8 | 0.12 | 0.5 | 16 | 4.688 | 38 |  |
| catalog | 6 | 0.15 | 0.5 | 32 | 9.111 | 39 |  |
| search | 5 | 0.35 | 0.6 | 23 | 6.484 | 37 |  |
| pricing | 7 | 0.08 | 0.4 | 25 | 6.958 | 34 |  |
| currency | 8 | 0.03 | 0.3 | 5 | 1.088 | 12 |  |
| inventory | 7 | 0.1 | 0.5 | 18 | 5.184 | 28 |  |
| recommendations | 2 | 0.45 | 0.6 | 21 | 8.693 | 91 |  |
| reviews | 7 | 0.2 | 0.5 | 13 | 3.679 | 20 |  |
| image-service | 7 | 0.25 | 0.7 | 66 | 25.713 | 301 |  |
| cart | 3 | 0.2 | 0.5 | 13 | 3.458 | 18 |  |
| checkout | 2 | 2.0 | 0.4 | 18 | 4.724 | 23 |  |
| payment | 3 | 1.5 | 0.5 | 9 | 7.214 | 99 |  |
| fraud-check | 4 | 1.0 | 0.6 | 9 | 2.38 | 11 |  |
| tax | 3 | 0.8 | 0.4 | 8 | 1.907 | 12 |  |
| shipping-quote | 5 | 0.8 | 0.5 | 12 | 3.507 | 18 |  |
| address-validation | 6 | 0.6 | 0.5 | 10 | 2.458 | 14 |  |
| promotions | 8 | 0.06 | 0.4 | 8 | 2.235 | 17 |  |
| order-service | 3 | 1.5 | 0.5 | 13 | 3.204 | 16 |  |
| loyalty | 11 | 0.6 | 0.5 | 9 | 2.12 | 11 |  |
| notification | 4 | 1.0 | 0.5 | 5 | 1.093 | 11 |  |
| email-gateway | 13 | 0.6 | 0.5 | 10 | 2.832 | 16 |  |
| sms-gateway | 5 | 2.0 | 0.5 | 5 | 1.104 | 10 |  |
| analytics-ingest | 1 | 0.05 | 0.4 | 8 | 2.259 | 17 |  |
| merchant-api | 2 | 1.5 | 0.5 | 5 | 1.085 | 12 |  |

## Calls (service to service)

k is the coefficient in *arrivals into the callee per second = k x requests in flight at the
caller*: k nominal = fan-out / caller's mean latency (Little's law); k realised = total calls on
the edge / Σ the caller's in-flight level in the step before. They agree except where the caller
queued (payment, image-service and recommendations in the flash sale): a queued request is in
flight but has not started, so it calls nobody yet, and the realised k is lower (payment's is
half the nominal one).

| caller | callee | fan-out | k nominal (/s) | k realised (/s) |
|---|---|---|---|---|
| web-frontend | api-gateway | 1.0 | 3.3333 | 3.3546 |
| web-frontend | session | 1.0 | 3.3333 | 3.3546 |
| web-frontend | feature-flags | 0.5 | 1.6667 | 1.6779 |
| web-frontend | image-service | 2.0 | 6.6667 | 6.7091 |
| web-frontend | analytics-ingest | 1.0 | 3.3333 | 3.3545 |
| mobile-api | api-gateway | 1.0 | 4.0 | 3.9664 |
| mobile-api | session | 1.0 | 4.0 | 3.9664 |
| mobile-api | feature-flags | 1.0 | 4.0 | 3.9664 |
| mobile-api | analytics-ingest | 0.5 | 2.0 | 1.9791 |
| api-gateway | auth | 0.8 | 10.0 | 9.9544 |
| api-gateway | catalog | 0.6 | 7.5 | 7.4627 |
| api-gateway | search | 0.3 | 3.75 | 3.7425 |
| api-gateway | recommendations | 0.3 | 3.75 | 3.7203 |
| api-gateway | cart | 0.25 | 3.125 | 3.108 |
| api-gateway | user-profile | 0.2 | 2.5 | 2.4949 |
| api-gateway | checkout | 0.04 | 0.5 | 0.497 |
| api-gateway | merchant-api | 0.012 | 0.15 | 0.1479 |
| auth | session | 0.5 | 8.3333 | 8.314 |
| auth | user-profile | 0.3 | 5.0 | 4.9898 |
| search | catalog | 0.5 | 1.4286 | 1.4386 |
| search | pricing | 0.5 | 1.4286 | 1.4337 |
| recommendations | catalog | 0.8 | 1.7778 | 1.637 |
| recommendations | user-profile | 0.5 | 1.1111 | 1.0199 |
| merchant-api | catalog | 1.0 | 0.6667 | 0.6522 |
| catalog | pricing | 1.0 | 6.6667 | 6.6522 |
| catalog | inventory | 0.5 | 3.3333 | 3.3331 |
| catalog | image-service | 0.5 | 3.3333 | 3.3312 |
| catalog | reviews | 0.3 | 2.0 | 1.9949 |
| reviews | user-profile | 0.2 | 1.0 | 0.9865 |
| cart | pricing | 1.0 | 5.0 | 4.9871 |
| cart | inventory | 1.0 | 5.0 | 4.9871 |
| cart | promotions | 0.5 | 2.5 | 2.4892 |
| checkout | cart | 1.0 | 0.5 | 0.5034 |
| checkout | payment | 1.0 | 0.5 | 0.5034 |
| checkout | tax | 1.0 | 0.5 | 0.5034 |
| checkout | shipping-quote | 1.0 | 0.5 | 0.5034 |
| checkout | address-validation | 0.8 | 0.4 | 0.4043 |
| checkout | promotions | 1.0 | 0.5 | 0.5034 |
| checkout | order-service | 0.9 | 0.45 | 0.4528 |
| payment | fraud-check | 1.0 | 0.6667 | 0.3296 |
| payment | currency | 0.5 | 0.3333 | 0.1667 |
| pricing | currency | 0.4 | 5.0 | 5.021 |
| pricing | promotions | 0.3 | 3.75 | 3.7587 |
| shipping-quote | address-validation | 0.5 | 0.625 | 0.625 |
| order-service | inventory | 1.0 | 0.6667 | 0.6677 |
| order-service | notification | 0.5 | 0.3333 | 0.3353 |
| order-service | loyalty | 0.5 | 0.3333 | 0.3338 |
| notification | sms-gateway | 0.5 | 0.5 | 0.4943 |

## Worker calls (pool to service)

k: arrivals per second = k x jobs in progress (calls per job / mean job time).

| pool | service | calls per job | k nominal (/s) | k realised (/s) |
|---|---|---|---|---|
| fulfillment-workers | inventory | 1.0 | 0.25 | 0.2499 |
| fulfillment-workers | shipping-quote | 1.0 | 0.25 | 0.2499 |
| loyalty-workers | loyalty | 1.0 | 1.0 | 1.0077 |
| email-workers | email-gateway | 1.0 | 1.0 | 0.9965 |
| search-indexer | catalog | 1.0 | 0.3333 | 0.3353 |
| search-indexer | image-service | 1.0 | 0.3333 | 0.3353 |
| search-indexer | search | 1.0 | 0.3333 | 0.3353 |
| profile-sync-workers | loyalty | 1.0 | 0.5 | 0.4939 |

## Produce edges (service or pool to queue)

One message per finished request or job with the given probability; k = probability / mean
latency or job time.

| producer | queue | P(message) per request/job | k nominal (/s) | k realised (/s) |
|---|---|---|---|---|
| checkout | order-placed | 0.85 | 0.425 | 0.4262 |
| payment | payment-captured | 0.8 | 0.5333 | 0.2641 |
| order-service | email-requested | 1.0 | 0.6667 | 0.6675 |
| merchant-api | product-changed | 0.9 | 0.6 | 0.5856 |
| user-profile | profile-updated | 0.015 | 0.125 | 0.1195 |
| analytics-ingest | clickstream | 0.08 | 1.6 | 1.5579 |
| fulfillment-workers | email-requested | 1.0 | 0.25 | 0.2498 |
| loyalty-workers | email-requested | 0.2 | 0.2 | 0.2005 |
| profile-sync-workers | email-requested | 0.3 | 0.15 | 0.1514 |

## Queues and their consumer pools

| queue | pool | mean job (s) | workers by era | mean lag | max lag | mean jobs | 
|---|---|---|---|---|---|---|
| order-placed | fulfillment-workers | 4.0 | 10 from t=1, 16 from t=2401 | 39.523 | 586 | 8.056 |
| payment-captured | loyalty-workers | 1.0 | 3 from t=1 | 136.841 | 1051 | 1.89 |
| email-requested | email-workers | 1.0 | 12 from t=1, 0 from t=4801, 12 from t=5701 | 470.423 | 4542 | 4.718 |
| product-changed | search-indexer | 3.0 | 3 from t=1, 1 from t=6001 | 50.76 | 334 | 1.895 |
| profile-updated | profile-sync-workers | 2.0 | 2 from t=1 | 25.271 | 284 | 1.135 |
| clickstream | analytics-workers | 1.0 | 6 from t=1, 9 from t=1201 | 7.204 | 141 | 3.527 |

## Eras and incidents

| t (first second) | change |
|---|---|
| 1 | Start |
| 1201 | analytics-workers scaled up to 9 |
| 2401 | fulfillment-workers scaled up to 16 for the flash sale |
| 4801 | email-workers outage (0 workers) |
| 5701 | email-workers restored (12 workers) |
| 6001 | search-indexer scaled down to 1 |
| 3600 to 4200 | flash sale: web and mobile traffic x2 (not an era: the world, not the shop, changed) |
| 5000 to 5100 | partner burst at the api-gateway x5 (not an era) |

What the incidents look like in the levels:

- **Flash sale.** Payment (capacity 9, 1.5 s) saturates: in flight climbs from ~5 to ~90 and
  falls back below 10 by t = 4191. Image-service (up to ~300) and recommendations (up to ~90) queue too.
  Every queue builds a backlog, peaking around t = 4000 to 4200 and draining afterwards:
  order-placed 586 (fulfillment at 16 workers handles 4/s; empty again at t = 4546),
  payment-captured 1051 (3 loyalty workers handle 3/s; empty at t = 5445), product-changed 334
  (empty at 5509), profile-updated 284 (empty at 4850), clickstream 141 (empty at 4192).
- **email-workers outage, t = 4801 to 5700.** email-requested climbs almost linearly from 0 to
  ~4540 (about 5 messages a second keep arriving); email-workers drop to 0 jobs and
  email-gateway to 0 in flight. When 12 workers come back they run flat out (12 jobs in
  progress, ~12 messages a second consumed, against ~3 a second arriving) and the lag reaches
  0 about ten minutes later (t ~ 6300). This is the capacity-limited drain no linear equation
  in the lag expresses.
- **search-indexer scaled down to 1, t = 6001.** One worker at 3 s a job (0.33/s) against
  ~0.3 to 0.4 messages a second in a quieter evening: product-changed only wobbles (at most ~12
  waiting). An era that changes little.

## Long runs

`sim.run(seed, steps)` and `sim.measured(seed, steps)` run any number of seconds (`sim.LONG_STEPS`
= 43,200, six compressed days, for the discovery test bed: about 38 s, 4 MB of JSON; every request
is simulated, about 3 million a compressed hour). The two hours are a day, and the day recurs: at
every multiple of 7200 s an era "A new day: every pool back to its starting size", then the
analytics scale-up (t 900-1500 of the day), the fulfillment scale-up 20 minutes before the flash
sale (sale at 3000-4200, 10 minutes), the email-workers outage (from 4500-5100, 10-20 minutes),
the restore, the search-indexer scale-down (5-10 minutes after it), and the partner burst
(4000-6400). The times come from a generator of each day's own. A long run is simulated a day at
a time (in-flight requests, waiting messages and busy workers carry over to the next day), with
each later day drawing from its own seeded generator, so the first day is always exactly the run
described here. Six eras every day; the graph and every parameter are the same at any length.
`measured()` is what `history.py` prints for the example model: the 42 levels and the eras.

## The SD structure a perfect discovery would report

In SD Lab terms (all of it is in `truth.json` under `sd_structure`):

1. **Real flows between stocks: 6.** *queue -> its pool* (a message is taken and becomes a job):
   order-placed -> fulfillment-workers, payment-captured -> loyalty-workers, email-requested ->
   email-workers, product-changed -> search-indexer, profile-updated -> profile-sync-workers,
   clickstream -> analytics-workers, one message per job (ratio 1). Queues and pools both count
   messages (a job is the message a worker took), so discovery can propose this one-for-one flow. The rate is capacity-limited: min(free workers, messages waiting) per mean job time, at most
   workers / job time per second; with an empty queue it equals the queue's inflow.
2. **Flows to outside: 36.** Every service (requests finish, proportional, k = 1 / mean time in
   the service) and every pool (jobs finish, k = 1 / mean job time):

| stock | to | what | k nominal | k realised |
|---|---|---|---|---|
| web-frontend | outside | requests finish | 3.3333 | 3.3545 |
| mobile-api | outside | requests finish | 4.0 | 3.9664 |
| api-gateway | outside | requests finish | 12.5 | 12.4398 |
| auth | outside | requests finish | 16.6667 | 16.6176 |
| session | outside | requests finish | 33.3333 | 32.9937 |
| feature-flags | outside | requests finish | 50.0 | 50.5548 |
| user-profile | outside | requests finish | 8.3333 | 8.2621 |
| catalog | outside | requests finish | 6.6667 | 6.6522 |
| search | outside | requests finish | 2.8571 | 2.8596 |
| pricing | outside | requests finish | 12.5 | 12.5249 |
| currency | outside | requests finish | 33.3333 | 33.2259 |
| inventory | outside | requests finish | 10.0 | 9.9856 |
| recommendations | outside | requests finish | 2.2222 | 2.0476 |
| reviews | outside | requests finish | 5.0 | 4.9408 |
| image-service | outside | requests finish | 4.0 | 3.7908 |
| cart | outside | requests finish | 5.0 | 4.9871 |
| checkout | outside | requests finish | 0.5 | 0.5034 |
| payment | outside | requests finish | 0.6667 | 0.3296 |
| fraud-check | outside | requests finish | 1.0 | 0.9991 |
| tax | outside | requests finish | 1.25 | 1.2469 |
| shipping-quote | outside | requests finish | 1.25 | 1.2522 |
| address-validation | outside | requests finish | 1.6667 | 1.6686 |
| promotions | outside | requests finish | 16.6667 | 16.6159 |
| order-service | outside | requests finish | 0.6667 | 0.6675 |
| loyalty | outside | requests finish | 1.6667 | 1.6673 |
| notification | outside | requests finish | 1.0 | 0.9825 |
| email-gateway | outside | requests finish | 1.6667 | 1.6603 |
| sms-gateway | outside | requests finish | 0.5 | 0.4895 |
| analytics-ingest | outside | requests finish | 20.0 | 19.576 |
| merchant-api | outside | requests finish | 0.6667 | 0.652 |
| fulfillment-workers | outside | jobs finish | 0.25 | 0.2498 |
| loyalty-workers | outside | jobs finish | 1.0 | 1.0077 |
| email-workers | outside | jobs finish | 1.0 | 0.9965 |
| search-indexer | outside | jobs finish | 0.3333 | 0.3353 |
| profile-sync-workers | outside | jobs finish | 0.5 | 0.4938 |
| analytics-workers | outside | jobs finish | 1.0 | 0.9978 |

3. **Driven inflows (information links, nothing moves from the driver): 65.** Each is a flow
   *outside -> target* whose rate is k x the driver's level: 48 calls, 8 worker calls, 9 produce
   edges (tables above). A stock with several drivers has one linear inflow,
   external + Σ k x driver level (`sd_structure.inflow_equations`); e.g. *catalog* is driven by
   api-gateway (7.5), search (1.43), recommendations (1.78), merchant-api (0.67) and
   search-indexer (0.33).
4. **External inflows: 3** (outside -> web-frontend, mobile-api, api-gateway), time-varying.

A perfect discovery reports no flow between two services, none from a service into a queue,
and none from a pool into a service or queue: those are links, not flows. Today's discovery
only has flows (see docs/DISCOVERY.md section 9, "Flows only, no information links"), so the
closest it can come is a flow from outside into the target with a `linear` equation in the
driver's level, which its `c + a x source` form does not express when the driver is not the
source: expect it to report constant or proportional inflows from outside instead, and to
mistake strongly co-moving stocks for stock-to-stock flows.

## What should be visible at 1-second steps, and what should not

Measured on the fixture (`detr` = after removing a 5-minute moving average, so the shared
daily cycle and the flash sale do not count):

| link | driver level (t-1) vs arrivals on that edge (t), detr | driver level vs target level, same step, detr |
|---|---|---|
| order-service -> email-requested (produce) | 0.77 | ~0 |
| checkout -> order-placed (produce) | 0.65 | ~0 |
| email-workers -> email-gateway | 0.55 | 0.50 |
| checkout -> payment | 0.50 | 0.25 |
| catalog -> pricing | 0.32 | 0.50 |
| web-frontend -> api-gateway | 0.34 | 0.35 |
| api-gateway -> checkout | 0.06 | 0.05 |
| non-edges (search -> checkout, tax -> merchant-api, sms-gateway -> search) | 0.02 to 0.05 | |

- **Visible:** calls from a busy caller into a callee whose in-flight level is mostly driven by
  that caller and that holds requests for a good fraction of a second or more: catalog ->
  pricing, checkout -> tax / order-service / address-validation / shipping-quote, email-workers
  -> email-gateway, web-frontend -> image-service / api-gateway / analytics-ingest, cart ->
  inventory / pricing. The queue -> pool flows are plain during the backlogs (flash sale, the
  outage) because the queue falls exactly as fast as the pool takes in.
- **Hard:** links into callees with many drivers (catalog, user-profile, inventory, session,
  promotions): each driver explains a small share. Low-rate edges such as api-gateway ->
  checkout (fan-out 0.04: the gateway's level is dominated by everything else) and api-gateway ->
  merchant-api.
- **Probably invisible:** callees with very short latencies, whose in-flight is near zero and
  mostly 0/1 noise: feature-flags (0.02 s, mean 0.76 in flight), currency (0.03 s, 1.1),
  session (0.03 s, 2.4), promotions (0.06 s, 2.2), analytics-ingest (0.05 s, 2.3). Their
  arrivals are almost entirely served inside the same second, so their level barely shows how
  many came. **Produce edges into a queue its pool keeps up with** (clickstream,
  product-changed, profile-updated, order-placed and payment-captured outside the flash sale):
  the lag stays at 0, a message published is taken within the second, and the queue's level
  carries nothing. The producer -> queue correlation of levels is ~0 for every produce edge;
  only the backlogs show anything, and then the queue's level is driven mostly by its
  consumers. Messages that pass through a queue straight into a pool show up instead as the
  producer driving the *pool's* jobs (a link that skips the unmeasured flow: the queue holds
  ~nothing). Pool-to-service links where the pool is small (search-indexer, profile-sync-
  workers: 0.6/s into a busy service) are swamped by the service's other traffic.
- **Reversed or mixed signals:** a service that queues (payment in the flash sale) has a level
  that grows while it calls nobody new, so its link to fraud-check and currency looks weaker
  than its nominal k (realised k is half); the backlog then drains at capacity, not in
  proportion to the level.
