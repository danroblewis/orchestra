# Demo 4: capacity projection

Tab "4. Capacity projection" on `/demos`. Code: `sdlab/demos/capacity.py`, `sdlab/static/demos-capacity.js`,
tests `tests/test_demos_capacity.py`. Ideas 23 and 24 of `OPERATIONALIZATION.md`.

## What it shows

How much more traffic the service on ladder case `311-k8s-node-pool` can take, and which limit hits first. The
case's week of traffic is scaled from 0.5x to 2.5x (21 steps of 0.1) and run through a stored found model and
through the true model. Three limits are tracked:

- **serving**: each ready pod serves at most 40 requests a step (`min(0.6 x queue, 40 x ready)`);
- **node room**: a pending pod starts only while a node has room, 4 pods a node (`min(0.5 x pending, 4 x nodes - ready)`);
- **autoscaler maximum**: at most 16 pods wanted (`min(16, ceil(cpu / 192.5))`).

A limit *binds* when it, not the demand, decides the flow. Where each limit binds is judged with the true limits
on each model's simulated levels, so both models are judged alike. **Headroom** is the largest scale where a limit
binds in under 1% of the week's steps. The page also shows peak queue, most pods wanted and ready, and the share
of requests that give up, found beside true, and one week at a chosen scale.

It also checks whether the found model **has** each limit (a `min` form on the flow between the same stocks), and
how often the training data (the case's none-long run, 2000 steps) reached it. A limit the data never reached may
be missing from the found model. The found model then fits the data, but its projection past that limit is not
proven, and the page says so.

## How it works

- The true model is an in-memory copy of the case's model with its traffic given as an explicit series (the case's
  formula, scaled), the node count set and the injections chosen; it runs in the truth engine without noise.
- The found model is the strategy's stored passing result on 311 none-long (`engine.stored_model`), run free from
  the case's start levels with the same traffic series and the same injections (each applied before its step).
- Controls: found model (milp, combined2, kalman_lna, structures, engine_forms), nodes (3 = the case, 4, 5, 6),
  and whether the case's node failures (Mon, Wed, Fri 10:50, the node back 30 steps later) are included.
- Endpoints: `GET /api/demos/capacity/projection?strategy=milp&nodes=3&failures=true` (the sweep, the headroom,
  the limits table) and `GET /api/demos/capacity/week?strategy=milp&scale=2.0&nodes=3&failures=true`.
- A sweep takes about 11 s the first time (21 truth runs + 21 found runs of 2016 steps) and is cached in
  `~/.cache/sdlab/demos/capacity/` (keyed by the case hash, the result id and the settings).
  Warm every setting: `uv run python -m sdlab.demos.capacity` (about 5 CPU-minutes, single-threaded).

## What it found (2026-10-22, `capacity.projection(strategy, nodes, failures=True)`)

Results used: milp #386951 (ec2164b), combined2 #386967, kalman_lna #386962, structures #386957,
engine_forms #386942, all passing on 311 none-long.

- **Limits in the found models.** All five have the serving limit and the node-room limit, which the data reached
  in 32% and 55% of its steps. **None has the autoscaler maximum of 16**: the data never reached it (desired peaks
  at 15 in the data), so discovery could not see it. Verdict on screen: "fits, not proven past it".
- **With 3 nodes (the case)** every found model matches the truth: same headroom for every limit, peak queue
  within 6% at every scale (at 2.0x: true 22,450, milp 22,497). Today (1.0x) the pool is already past its
  headroom: pods wait for node room in 54% of the week's steps (found 55%) and the serving limit binds in 31%
  (found 31%). Headroom: serving 0.5x, node room below 0.5x with the failures; without them, serving 0.8x and
  node room 0.6x, found and true alike. The autoscaler maximum never binds with 3 nodes (cpu is held down by the
  12 pods that fit), so the missing limit does not matter there.
- **With more nodes the missing limit matters.** With 6 nodes the truth stops at 16 pods; every found model keeps
  scaling to 29 pods wanted and 24 ready. At 2.0x the found models predict a peak queue of 8,433 to 8,551 against
  the truth's 16,635 (about half), and a serving headroom of 1.3x against the truth's 1.0x. They also predict pods
  waiting for node room from 1.1x, which in the truth never happens. Same for all five strategies. This is the
  honest result: a projection past what the data showed is only as good as the form the model guessed there.

## Limits

- One week, noise-free, from the case's start levels; not a forecast of real traffic.
- "Binds" uses the true limits' conditions on each model's levels; a found model with a differently written limit
  is judged by the same conditions.
- The queue never grows without bound in this model (8% of waiting requests time out each step and 40% of
  those give up), so the demo reports peak queue and requests given up instead of a blow-up point.
- The 1% headroom tolerance is a choice (the case's node failures make limits bind briefly even at 0.5x).
