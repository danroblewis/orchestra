# SD Lab model format

A model is one JSON file. Examples live in `sdlab/examples/<id>.json`, with their programs in
`sdlab/examples/<id>/machines/*.py` and sensors in `sdlab/examples/<id>/machines/*.py`
(programs and sensors are both named `<id>/<file stem>`).

```jsonc
{
  "id": "socks", "name": "Sock drawer", "description": "…",
  "time_unit": "minute",          // one step of the simulation and one tick of a live run
  "horizon": 120,                 // how far to project
  "dt": 0.25,                     // simulation step (fractions of a time unit)

  "stocks": [
    {"id": "basket", "name": "Laundry basket", "unit": "socks", "initial": 0, "x": 150, "y": 200,
     "target": {"value": 120, "by": 120},          // optional goal
     "final": true,                                 // optional: nothing ever leaves it (discovery never proposes a flow out of it)
     "inferred": {"shape": "exp", "delay": 5},       // optional: found by discovery from timing, never measured; its level is what its flows imply
     "group": "orders/checkout",                    // optional: discovery only proposes flows between stocks of the same group
     "hide": true,                                  // optional: not drawn on the canvas (still in the model and the simulation)
     "keep": true,                                  // optional: Simplify never suggests hiding it (flows can have "keep" too)
     "query": "sum(kafka_consumergroup_lag{topic=\"orders\"})"}   // optional: how a sensor measures it (PromQL for prometheus/promql)
  ],

  "flows": [
    {"id": "unload", "name": "Unload", "from": "basket", "to": "loose",   // null = outside the model
     "outputs": ["other_stock"],                    // optional: other stocks it may fill
     "split": {"loose": 0.6, "other_stock": 0.4},   // simulation only: how it divides between them
     "ratio": 2,                                    // units taken from `from` per unit put in `to` (default 1)
     "rate": {"form": "constant", "value": 4},      // the equation (see below)
     "machine": "worker",                           // a machine id, "environment" (happens on its own), or null (never runs)
     "work": 0.2,                                   // machine time per unit moved
     "rule": true,                                  // live runs: the machine follows the equation (fires no more often than it says);
                                                    // without it, a machine runs its flows whenever it can and the equation only describes them
     "args": ["unload"],                            // arguments the machine's program gets for this flow
     "program": "socks/socks",                      // environment flows only: the program that does it in a live run
     "take": [{"as": "a", "from": "loose"},         // live run: what one run takes (default: one item from `from`)
              {"as": "b", "from": "loose", "where": {"colour": "a.colour"}, "order": "any|oldest|newest"}],
     "effects": [{"stock": "bits", "shape": "linear", "normal": 10, "max": 1},          // speed x clamp(level/normal, 0, max)
                 {"stock": "fatigue", "shape": "table", "points": [[0, 1], [5, 0.6], [10, 0.2]]}],
     "uses": [{"stock": "bits", "per": 0.01}],      // co-flow: each unit moved uses up 0.01 of `bits`
     "hidden": true,                                // runs in live runs, never reaches the page
     "query": "sum(rate(x_total[5m]))"              // optional: its measured rate per second (PromQL), for prometheus/promql
    }
  ],

  "machines": [
    {"id": "worker", "name": "Worker", "kind": "code|person|agent", "color": "#0f766e",
     "capacity": 1,                                 // time units of work per time unit
     "capacity_stock": "staff",                     // optional: capacity is per unit of this stock
     "program": "socks/socks", "args": [],          // the program a live run starts for each of its flows
     "prompt": "…", "timeout": 180}                 // AI agents (program "agents/llm"): what to do; how long to wait
  ],

  "sensors": [{"program": "factory/tickets", "args": []}],   // optional: measured stocks (prints {"stock": level})
  "history": {"program": "factory/history", "args": []}      // optional: prints past levels, one {"t": n, "levels": {…}} per line
}
```

## Equations (`rate.form`)

| form | rate per time unit |
|---|---|
| `constant` | `value` |
| `proportional` | `k` × level of `stock` |
| `gap` | (`goal` − level of `stock`) / `time`, never below 0 |
| `available` | everything in the source (the machine sets the pace) |
| `linear` | `c` + Σ `k` × level of `stock` over `terms` |

## Programs

A program is a Python file run as `python <file> <flow args> <machine args>`. On stdin it gets
`{"flow", "flow_name", "inputs": {name: item}, "to": [allowed stocks], "context": {stock: {"name", "level", "sample"}}, "prompt"?}`.
It prints one `{"to": <stock id or null>, "item": {…}}` per line. A non-zero exit puts the items back.

A sensor prints one JSON object `{stock id: level}`. A history program prints one
`{"t": <step>, "levels": {stock id: level}}` per line, steps counting up from 1.

## Stocks nobody measures

Discover flows also looks for things that wait somewhere unmeasured. A flow can take from one
stock and deliver to another some time later, so that what arrives is a delayed copy of what left.
Discovery tries three shapes for that delay:

- **exp**: the hidden stock drains in proportion to what it holds.
- **erlang**: arrivals bunch around the mean delay.
- **pipe**: everything waits the same time.

It fits the delay and how much was waiting when measuring began. It keeps such a flow only when it
pays for itself under the same price as any other flow. When added to the model, it becomes an
`inferred` stock with a flow in and a proportional flow out (one over the delay). Charts show its
level as its flows imply it.

What has to be measured: a hidden stock is identifiable when its source's or its target's other
traffic is counted. Two waits in a row (the hidden one and the target's own drain) look the same in
either order if neither end is counted.
