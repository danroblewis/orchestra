# The bakery: a toy system for Orchestra to discover

Three machines, each its own process. They use Orchestra only as a library, for the event bus
and the metrics store. Orchestra is never told what bread is; the point is to see it find the
bakery's dynamics on its own.

| Machine | Listens for | Publishes | Writes |
|---|---|---|---|
| **oven** | `bread.ordered` | `bread.baked` | `bakery_loaves_baked_total`, `bakery_orders_filled_total`, `bakery_oven_orders_pending` |
| **shop** | `bread.baked` | `bread.sold`, `bread.discarded`, `bread.ordered` | `bakery_shelf_loaves`, `bakery_loaves_sold_total`, `bakery_loaves_discarded_total`, `bakery_loaves_ordered_total` |
| **weather** | nothing | `weather.reported` | `weather_temperature_celsius` |

The rules, per minute:
- the oven bakes 6 loaves on its day shift and 1.5 on its night shift (alternating every 10
  minutes), plus 0.5 more per loaf it has been ordered and not yet baked;
- customers buy 20% of the shelf, and 5% of it goes stale and is thrown out;
- when the shelf is below 10 loaves, the shop orders 20 more (at most once a minute);
- the weather drifts and has nothing to do with bread, so discovery should leave it out.

That makes a **balancing loop**: a low shelf leads to orders, orders make the oven bake faster,
and faster baking fills the shelf.

## Run it

Needs a project whose `orchestra.toml` points at a shared bus and metrics store (the demo stack:
`docker compose -f deploy/dev/compose.yaml up -d`, then `[events] url = "redis://127.0.0.1:6379/0"`
and `[metrics] url = "http://127.0.0.1:8428"`).

```bash
export ORCHESTRA_REPO=~/my-project
for m in oven shop weather; do uv run --project ~/orchestra_2 python examples/bakery/bakery.py $m & done
orchestra run &                          # the host: counts every event by type and source
orchestra web                            # Machines shows the three and their events
# after 20 minutes or more (two shift changes):
orchestra sd discover --minutes 20       # Dynamics shows what it found
```

## What discovery should find

- two stocks: the shelf (baked − sold − discarded) and the oven's order backlog (ordered −
  filled), each balanced exactly;
- sold and discarded proportional to the shelf (about 0.2 and 0.05 per minute);
- baking linear in the order backlog (about c + 0.5 × backlog, where c averages the shifts), with
  high dispersion, because the shifts are a driver the model lacks;
- ordering falling as the shelf grows: the influence that closes the loop;
- weather left out.

`tests/unit/test_discover.py` checks exactly this on a simulated bakery.
