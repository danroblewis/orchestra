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
     "max": 500,                                    // optional: a ceiling; flows into it share the room left (see below)
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
     "exact": true,                                 // ground truth only: no counting noise (an information flow, e.g. a SMOOTH)
     "delay": {"id": "ab", "stage": 1, "of": 3, "time": 6},   // ground truth only: one stage of a compiled DELAY3
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

  "inputs": {"pump": {"values": [3, 3, 5], "repeat": false,          // optional: measured inputs (see below)
                      "terms": [{"fn": "step", "height": 2, "start": 100}]}},
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
| `expr` | an expression (ground truth only, 2026-10-19; below) |

A rate (`stock` of proportional, gap or a linear term) and an effect may read a **measured input**
by its name instead of a stock.

## Measured inputs, sub-steps, ceilings, delays

Added on 2026-10-18 for ground-truth models (`sdlab/sdtruth.py`) and the ladder's cases
(`docs/LADDER.md`, "Inputs, sub-steps, ceilings, delays"); the editor (`static/sim.js`) runs them
too. Each is additive: a model without it runs exactly as before.

- **`inputs`**: outside drivers given as data. `values` is one value per time unit (step t uses
  `values[t - 1]`, held over the step; after the end the last value, or the series again with
  `repeat`), plus `terms` evaluated at time t + j x dt in sub-step j of step t: `constant {value}`,
  `step {height, start}`, `pulse {height, start, width = 1}`, `ramp {slope, start, end?}`,
  `pulse_train {height, first, width, every, last?}`, `sin {amplitude, period, phase = 0}`. A
  ground-truth run reports each input's mean per step (`"inputs"`), which discovery may be given
  (`"inputs"` in a discovery request) as it is given eras: data, never the truth.
- **`dt`** in a ground-truth model: each recorded step is 1/dt sub-steps (1/dt a whole number); a
  rate moves rate x dt per sub-step, counting noise is Poisson(rate x dt) per sub-step (the same
  variance per recorded step), levels and counters are recorded once per step. (In the editor, `dt`
  has always been its simulation step.)
- **`max`** on a stock: a ceiling. The flows into the stock share the room left (max - level) as its
  outflows share what it holds; the room is taken before the step's outflows (as the floor ignores
  the step's inflows), so at dt = 1 a full stock drained at k sits at max / (1 + k dt).
- **Delays and smoothing** are not new equation forms: they are written as stocks and flows.
  DELAY1(rate, T) is one hidden stock drained at 1/T; DELAY3(rate, T) is three hidden stocks in a
  chain, each drained at 3/T (marked `"delay"` so the answer key reads the chain as one hidden path
  of delay T); SMOOTH(X, T) is a hidden stock filled at X/T from outside (reading X, not draining it)
  and drained at its own level/T, with `"exact"` flows; SMOOTH3 is three such stages at 3/T. STEP,
  PULSE, RAMP and PULSE TRAIN in a rate are schedule changes (unannounced); an announced PULSE of
  material is an injection; as data an outside driver is an input (above).

## Expressions, auxiliaries, switches, signed stocks, two-way flows, fixed delays

Added on 2026-10-19 (queue item 2d) for ground-truth models (`sdlab/sdtruth.py`,
`sdlab/sdtruth_expr.py`) and the ladder's cases (`docs/LADDER.md`, "Expressions, signed stocks,
two-way flows, switches, fixed delays"). Each is opt-in and additive: a model that uses none of them
runs through the engine exactly as before (`tests/test_engine_additive.py`); one that uses any runs
through `Truth._run_ext`, the same loop with these added (`tests/test_engine_2d.py` checks it gives
every existing case the same numbers too). The editor (`static/sim.js`) does not run them yet.

- **`{"form": "expr", "expr": "0.3 * sqrt(T) + min(A, B / max(1, C))"}`**: a rate as an expression of
  stocks, inputs and auxiliaries: `+ - * / ^`, comparisons (`<`, `<=`, `>`, `>=`, `==`, `!=`, 1 or 0),
  `min`, `max`, `abs`, `sqrt`, `exp`, `ln`, `log(x, base)`, `power`, `ceil`, `floor`, `integer`,
  `modulo`, `quantum`, trigonometry, `if_then_else(c, a, b)`, `and`, `or`, `not`, `xidz`, `zidz`,
  `lookup(x, [[x0, y0], ...])` (linear, held at the ends) and `flow(id)` (another flow's amount in this
  sub-step, after its noise and the floor and ceiling, as a rate; it may not itself read a flow).
  Floored at 0 like every rate, unless the flow is two-way. Division by zero is an error (use `zidz`).
- **`"auxiliaries": {"util": "cpu / max(1, ready)"}`**: algebraic variables (no stock), computed in
  every sub-step from the levels and inputs (and each other, in dependency order; a loop is an error),
  read by name by a rate, an expression, an effect or a switch. A run reports each one's mean per
  step (`"auxiliaries"`).
- **`"switch": {"of": "T", "on_below": 19, "off_above": 21}`** (on a stock, level 0 or 1): a switch with
  memory (hysteresis), set at the start of every sub-step from its expression: 1 below `on_below`, 0
  above `off_above`, held in between (or `on_above` / `off_below`). No flow may move it.
- **`"signed": true`** (on a stock): it may go negative: no floor on its outflows, and an injection may
  take it below 0.
- **`"two_way": true`** (on a flow): its rate is not floored at 0; a negative rate moves material back
  (from `to` to `from`). Counting noise is the signed Poisson of its size. The floor of an unsigned
  stock and a ceiling apply to whichever stock it takes from or fills.
- **`"max_net": true`** (on a stock with `max`): the room under the ceiling counts the step's
  outflows, so a full stock holds at `max` at dt = 1 (rather than `max / (1 + k dt)`).
- **`"delay": {..., "shape": "pipe"}`**: a stage of a compiled DELAY FIXED (`delay_fixed(rate, T)` in
  the case format): time / dt hidden stages, each passed on whole in one sub-step (exact flows at
  k = 1 / dt), so what leaves arrives exactly T later; the answer key reports a pipe. A DELAYn whose
  `time` is an expression (its stages `{"form": "expr", "expr": "3 * H / (time)"}`) reports
  `delay_expr` and no number.

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
