# The ladder: discovery tested on tiny true models

The ladder is SD Lab's primary test bench for discovery. It is a list of tiny ground-truth models,
simplest first, each adding one new feature to a simpler one. Every discovery strategy runs on
every case on its own. The ladder asks whether discovery recovered the **true equations**, flow by
flow and number by number, not only whether it predicts well. Behaviour (skill@H) is reported next
to that.

Everything is fast: the whole ladder with `matrix` (25 cases x 4 variants, 100 items) runs in about 2.5 seconds from a cold cache
on 27 workers (20 seconds on one). Results are kept in a store, so only what changed runs again:

- a new or changed case runs every strategy on it;
- a new or changed strategy, or any change to `sdlab/discovery`, runs that strategy on every case;
- a change to the scoring re-scores the stored found models without running discovery again.

A failure found anywhere (an example, the generator, the page) becomes a new case: the smallest
model that shows it. The 31 examples (`sdlab/examples/sd-*`) and the generated models
(`tests/bench/generator.py`) are secondary benchmarks
([DISCOVERY-LOOP.md](DISCOVERY-LOOP.md)).

## Commands

```
uv run sdlab-ladder sync                               # run everything stale (all strategies, all cases)
uv run sdlab-ladder sync --strategies matrix           # only matrix
uv run sdlab-ladder run --strategies matrix --cases 003,tag:loop --variants counts   # run these now, current or not
uv run sdlab-ladder status                             # the strategy x case matrix, per-tag summaries
uv run sdlab-ladder status --strategies matrix --variant counts-short   # one strategy, one variant in detail
uv run sdlab-ladder show 011 --strategy matrix         # true vs found equations, part by part, with scores
uv run sdlab-ladder watch                              # sync now, then whenever a case or strategy changes
uv run sdlab-ladder check                              # every case file compiles, and the cases' sanity checks
uv run sdlab-ladder new my-slug                        # write the next case, NNN-my-slug.yaml, from a template
uv run sdlab-ladder freeze 042#5                       # write draw 5 of parametric case 042 as an ordinary case
```

`python -m sdlab.ladder ...` works too. Cases are chosen by id or number prefix (`003`,
`003-chain-2`), tag (`tag:loop`) or level (`level:6`); a parametric case's prefix (`042`) is all its
draws, and `042#5` is one. Variants are chosen by name (`counts-short`),
noise (`none`, `counts`) or length (`short`, `long`). Common options: `--jobs N` (default: CPU cores
minus 1; each worker uses one numpy thread) and `--timeout S` (per item, default 120 s). A strategy
that raises is recorded as `error` and one that runs out of time as `timeout`; the run carries on.

Data and results live outside the repository, in `$SDLAB_LADDER_CACHE` (default
`~/.cache/sdlab/ladder`): `data/` holds each case's runs, and `results.sqlite` holds the results.

## Cases

One file per case in `sdlab/sdlab/ladder/cases/`, named `NNN-slug.yaml` (the number sets the order;
the id is the file name without `.yaml`). A case is a few lines of YAML, written by hand:

```yaml
title: Chain of three
level: 3                        # the rung: 1 is the simplest
tags: [chain, move]             # motifs, for the per-tag summary
tests: two moves in a row are recovered, each at its own rate     # one sentence
seed: 4                         # optional (default 1)
stocks: {A: 0, B: 0, C: 0}      # each stock's initial level, in order
flows:
  outside -> A: 20              # constant                       id: in
  A -> B: 0.5 * A               # proportional                   id: ab
  B -> C: 0.25 * B              #                                id: bc
  C -> outside: 0.1 * C         #                                id: c_out
```

### Add a case in a minute

1. `uv run sdlab-ladder new my-slug` writes the next case (`NNN-my-slug.yaml`, a chain of two) and
   prints its path. Edit it: the smallest model that shows the feature or the failure, one change
   relative to a simpler case. Pick numbers that keep it bounded and moving: start stocks away from
   equilibrium, and drive slow parts with a schedule (a square wave in an inflow) if they would
   otherwise settle.
2. `uv run sdlab-ladder check --cases NNN` must say `ok`. It compiles every case file (a mistake is
   reported as `file:line: ...`), then checks that, over 5x the long length, levels stay finite,
   non-negative and bounded, that flows add up, that every flow moves, and that the stocks keep
   moving. `tests/test_ladder.py` runs the same check on every case, and also checks that the true
   model passes its own scoring.
3. `uv run sdlab-ladder sync` runs every strategy on the new case.

Do not change what an existing case means: its history would no longer compare. Add a new case
instead. Changing a case's model makes all its results stale; rewriting how it is written does not
(see the hash, below).

### The format

**Top level.** `title`, `level`, `tags`, `tests`, `stocks` and `flows`; optional `seed`, `schedule`,
`injections`, `variants` and `tolerance`. Any other key is an error.

**Stocks** map an id (letters, digits, `_`; not `outside`) to its initial level. Words after the
level mark it, or give the long form for anything else (`unit`, ...; extra keys are passed through):

```yaml
stocks: {A: 0, H: 0 hidden, Done: 0 final, R: {initial: 60, unit: cups, hidden: true}}
```

`hidden` is an unmeasured stock (`"measured": false`: discovery never sees it); `final` is a stock
nothing ever leaves.

**Flows** map `FROM -> TO` to a rate; either end may be `outside`. The flow's id comes from its ends:

| flow | id |
|---|---|
| `outside -> X` | `in` for the case's first flow from outside (named or not), `x_in` for later ones |
| `X -> outside` | `x_out` |
| `X -> Y` | `xy` when both ids are one letter (`ab`), else `x_y` (`work_done`) |

`A -> B as rework: ...` names a flow. Two flows with the same ends need a name for one of them
(`A -> B as fast`); a repeated key is an error, never silently dropped. `flows:` may also be a list
of one-key items (`- A -> B: 0.5 * A`), which reads the same.

**Rates** are arithmetic on numbers and stock ids, parsed by a small parser (no eval). Every rate is
floored at 0 by the engine, so `max(0, ...)` around a rate is allowed and changes nothing.

| written | form (MODEL.md) | JSON |
|---|---|---|
| `20` | constant | `{"form": "constant", "value": 20}` |
| `0.5 * A` (or `A * 0.5`, `A / 2`, `A`) | proportional | `{"form": "proportional", "stock": "A", "k": 0.5}` |
| `(300 - I) / 5` | gap: (goal - stock) / time | `{"form": "gap", "stock": "I", "goal": 300, "time": 5}` |
| `30 - 0.25 * A + 0.1 * B` | linear: c + terms | `{"form": "linear", "c": 30, "terms": [{"stock": "A", "k": -0.25}, {"stock": "B", "k": 0.1}]}` |
| `0.01 * A + 0.02 * B` | linear without c | `{"form": "linear", "terms": [...]}` |
| `max(0, 0.2 * A - 30)` | linear (the floor binds below A = 150) | `{"form": "linear", "c": -30, "terms": [...]}` |
| `available`, `available(A)` | available | `{"form": "available"}` (`"stock": "A"`) |

A rate times one or more **effects** multiplies it by a stock's level (several multiply, in order):

```yaml
  A -> B: 0.3 * A * effect(C, linear, normal=50, max=2)          # x clamp(C / 50, min, max); min, max optional (0, 1)
  A -> B: 0.3 * A * effect(C, table, [[0, 0.2], [50, 1], [100, 1.4]])   # a curve through (level, multiplier) points
```

A **co-flow** follows the rate: `A -> B: 0.3 * A uses(R, 0.5)` uses up 0.5 of `R` per unit moved
(`"uses": [{"stock": "R", "per": 0.5}]`); several `uses(...)` may follow.

**The long form** of a flow is a mapping with `rate` and any other flow keys (`ratio`, `name`,
`outputs`, `split`, ...; passed through). Its `rate` may also be the JSON rate itself:

```yaml
  A -> B:
    rate: 0.5 * A
    ratio: 2
  B -> outside:
    rate: {form: constant, value: 3}
```

**Schedule**: every `every` steps (one period; leave it out for once only), each change sets new
rates at step `t` of the period. A change is `at T [label] [announced]: {flow: rate, ...}`; a flow is
named by its id or, when only one flow has them, its ends. `announced` makes the change an era the
data announces; without it the change happens unannounced.

```yaml
schedule:
  every: 200
  at 1 low: {outside -> C: 3}
  at 101 high: {outside -> C: 7}
  at 50 "second machine" announced:
    ab: 0.6 * A
```

The JSON form (`changes: [{t, label, set, announce}]`) is accepted as is.

**Injections** (announced additions to a stock at the start of step `t`):

```yaml
injections:
  - {t: 50, stock: A, amount: 400}
  - {t: 150, stock: A, amount: 400}
```

**Variants** default to both noises (`none`, `counts`) at both lengths (`short` 300 and `long` 2000
steps); `variants: {noise: [counts], lengths: {short: 300}}` overrides that (`variants: default` is
the same as leaving it out). **Tolerance** overrides the scorer's (Scoring, below), e.g.
`tolerance: {rel: 0.1}`.

**YAML traps.** Inside `{...}` (flow style) a comma ends the value, so a rate with commas
(`effect(...)`, `max(0, ...)`, `uses(...)`) goes on its own line (block style). A value that starts
with `- ` or `[` reads as a list: quote it. Strings with `: ` or ` #` (a title,
a test sentence) need quotes.

### Parametric cases: random numbers

A hand-written case has one set of numbers (three chains with inflows 20, 12 and 6), so a strategy
can pass it by the luck of those numbers. In a **parametric** case any number may be a range, and
the case runs on several draws of its numbers (`sdlab/sdlab/ladder/draws.py`). Real use never
varies a model like this. It is a diagnostic for the analyser: it shows what happens when unrelated
stocks happen to get similar inflows, or a rate lands small.

```yaml
title: Two independent chains of two, random numbers
level: 4
tags: [independent, chain, move, parametric]
tests: 029 with every number drawn at random (8 draws); each chain is recovered with no flow between them
seed: 42
draws: 8                                  # how many draws (default 8)
stocks: {A1: draw(0, 300, int), B1: 0, A2: 0, B2: 0}
flows:
  outside -> A1: draw(5, 40)              # uniform on [5, 40]
  A1 -> B1: draw(0.05, 0.6, log) * A1     # log-uniform
  B1 -> outside: draw(0.03, 0.5, log) * B1
```

- `draw(lo, hi)` takes `0 <= lo < hi`, then optionally `log` (log-uniform, `lo > 0`) and `int` (a
  whole number). Other draws are rounded to three significant figures, so a value reads as written.
  For a negative coefficient, write `- draw(...)`. `{draw: [lo, hi]}` is the same number as
  `draw(lo, hi)`, written as a YAML mapping.
- A draw may stand for any number: a rate's numbers (a constant, `k`, a gap's goal and time, a linear
  rate's terms), an initial level, a schedule's values, or an injection's amount. Draws are replaced in
  the text before the YAML is read, so the comma trap does not apply to them. A `draw(...)` in a
  comment is left alone.
- **Draw i** (1..N) is the case `NNN-slug#i`. It is scored, stored and shown like any case, with its
  own hash: for every strategy and variant. Its numbers come from a generator seeded by the case's
  `seed`, `i` and an attempt number. So draws are reproducible, and raising `draws` keeps the first
  ones. The simulation seed is the case's `seed` for every draw.
- Each draw must pass the case checks (bounded, moving, every flow moves). A draw that fails them
  is drawn again with the next attempt, up to 12 attempts. `sdlab-ladder check` and `show` report
  the rejected attempts and why they were rejected. The accepted attempt is remembered in
  `$SDLAB_LADDER_CACHE/draws`, so the checks run once per draw.
- **Reporting.** `status` lists each draw as a row and adds a **Parametric cases** table. Each
  strategy gets its pass rate over draws x variants, then how many draws pass in every variant
  (`62.5% 3/8`). `show NNN#i` prints the drawn numbers with their ranges. In the read API, a draw's
  case has `draw: {base, i, of, seed, attempt, values: [{label, value, lo, hi, log, int, line}],
  rejected, problems}`. `summary()` adds `draw` (`{base, i, of, lines, values}`) to each draw's case
  and `parametric: {case: {title, level, tags, draws, strategies: {name: {pass, ..., total, rate,
  draws_passing, draws_run}}}}`. The Now page and the Cases view show a draw's numbers as the lines
  they went into. In the leaderboard, a parametric case counts as its draws, and a **Kind** filter
  separates fixed cases from random draws. The editor does not list draws as basic models.
- **Freezing.** `sdlab-ladder freeze NNN#i [--slug S]` writes draw i as the next ordinary case:
  `NNN-slug-draw-i.yaml`, with the drawn numbers in place and comments kept. Its title and `tests`
  sentence say where it came from, and the `parametric` tag becomes `frozen-draw`. It compiles to
  exactly the draw's model. This is how a failing draw becomes a fixed regression case.

| case | numbers drawn |
|---|---|
| 039-random-inflow-outflow | 002: inflow 5-40, drain 0.03-0.5 (log) |
| 040-random-chain-2 | 003: inflow, move 0.05-0.6 (log), exit |
| 041-random-chain-3 | 004: inflow, two moves, exit |
| 042-random-two-chains-of-two | 029: both chains' inflows, moves and exits |
| 043-random-three-chains-of-two | 031: all three chains |
| 044-random-three-stocks | 034-036: three unrelated stocks' inflows, drains and starts (0-300) |
| 045-random-link | 007: A's inflow and drain, the link 0.03-0.3, B's drain |
| 046-random-link-loop | 008: inflow 5-30, move 0.1-0.6, drain 0.1-0.4, births 0.01-0.09 (below the drain: bounded) |
| 047-random-goal-gap | 011: goal 150-450, time 2-10, arrival 0.1-0.5, demand 0.05-0.2 |
| 048-random-stepping-inflow-drain | 027: the two inflow levels (1-10, 5-25) and the drain 0.03-0.3 |

Failing draws frozen as fixed cases (October 2026, from the first run of the leading strategies):
057-three-chains-equal-moves (043#2), 058-move-equals-other-chains-drain (043#7),
059-small-inflow-step (048#1), 060-close-slow-drains-at-equilibrium (044#3) and
061-small-inflow-counts (039#2).

### Parametric cases: random numbers

A hand-written case has one set of numbers (three chains with inflows 20, 12 and 6), so a strategy
can pass it by the luck of those numbers. In a **parametric** case any number may be a range, and
the case runs on several draws of its numbers (`sdlab/sdlab/ladder/draws.py`). Real use never
varies a model like this. It is a diagnostic for the analyser: it shows what happens when unrelated
stocks happen to get similar inflows, or a rate lands small.

```yaml
title: Two independent chains of two, random numbers
level: 4
tags: [independent, chain, move, parametric]
tests: 029 with every number drawn at random (8 draws); each chain is recovered with no flow between them
seed: 42
draws: 8                                  # how many draws (default 8)
stocks: {A1: draw(0, 300, int), B1: 0, A2: 0, B2: 0}
flows:
  outside -> A1: draw(5, 40)              # uniform on [5, 40]
  A1 -> B1: draw(0.05, 0.6, log) * A1     # log-uniform
  B1 -> outside: draw(0.03, 0.5, log) * B1
```

- `draw(lo, hi)` takes `0 <= lo < hi`, then optionally `log` (log-uniform, `lo > 0`) and `int` (a
  whole number). Other draws are rounded to three significant figures, so a value reads as written.
  For a negative coefficient, write `- draw(...)`. `{draw: [lo, hi]}` is the same number as
  `draw(lo, hi)`, written as a YAML mapping.
- A draw may stand for any number: a rate's numbers (a constant, `k`, a gap's goal and time, a linear
  rate's terms), an initial level, a schedule's values, or an injection's amount. Draws are replaced in
  the text before the YAML is read, so the comma trap does not apply to them. A `draw(...)` in a
  comment is left alone.
- **Draw i** (1..N) is the case `NNN-slug#i`. It is scored, stored and shown like any case, with its
  own hash: for every strategy and variant. Its numbers come from a generator seeded by the case's
  `seed`, `i` and an attempt number. So draws are reproducible, and raising `draws` keeps the first
  ones. The simulation seed is the case's `seed` for every draw.
- Each draw must pass the case checks (bounded, moving, every flow moves). A draw that fails them
  is drawn again with the next attempt, up to 12 attempts. `sdlab-ladder check` and `show` report
  the rejected attempts and why they were rejected. The accepted attempt is remembered in
  `$SDLAB_LADDER_CACHE/draws`, so the checks run once per draw.
- **Reporting.** `status` lists each draw as a row and adds a **Parametric cases** table. Each
  strategy gets its pass rate over draws x variants, then how many draws pass in every variant
  (`62.5% 3/8`). `show NNN#i` prints the drawn numbers with their ranges. In the read API, a draw's
  case has `draw: {base, i, of, seed, attempt, values: [{label, value, lo, hi, log, int, line}],
  rejected, problems}`. `summary()` adds `draw` (`{base, i, of, lines, values}`) to each draw's case
  and `parametric: {case: {title, level, tags, draws, strategies: {name: {pass, ..., total, rate,
  draws_passing, draws_run}}}}`. The Now page and the Cases view show a draw's numbers as the lines
  they went into. In the leaderboard, a parametric case counts as its draws, and a **Kind** filter
  separates fixed cases from random draws. The editor does not list draws as basic models.
- **Freezing.** `sdlab-ladder freeze NNN#i [--slug S]` writes draw i as the next ordinary case:
  `NNN-slug-draw-i.yaml`, with the drawn numbers in place and comments kept. Its title and `tests`
  sentence say where it came from, and the `parametric` tag becomes `frozen-draw`. It compiles to
  exactly the draw's model. This is how a failing draw becomes a fixed regression case.

| case | numbers drawn |
|---|---|
| 039-random-inflow-outflow | 002: inflow 5-40, drain 0.03-0.5 (log) |
| 040-random-chain-2 | 003: inflow, move 0.05-0.6 (log), exit |
| 041-random-chain-3 | 004: inflow, two moves, exit |
| 042-random-two-chains-of-two | 029: both chains' inflows, moves and exits |
| 043-random-three-chains-of-two | 031: all three chains |
| 044-random-three-stocks | 034-036: three unrelated stocks' inflows, drains and starts (0-300) |
| 045-random-link | 007: A's inflow and drain, the link 0.03-0.3, B's drain |
| 046-random-link-loop | 008: inflow 5-30, move 0.1-0.6, drain 0.1-0.4, births 0.01-0.09 (below the drain: bounded) |
| 047-random-goal-gap | 011: goal 150-450, time 2-10, arrival 0.1-0.5, demand 0.05-0.2 |
| 048-random-stepping-inflow-drain | 027: the two inflow levels (1-10, 5-25) and the drain 0.03-0.3 |

### What a case compiles to

The loader (`cases.py`) compiles a YAML case (`caseformat.py`) to the case dict the ladder has always
used; a `NNN-slug.json` file holding that dict directly still loads (one id in both formats is an
error). `cases.spec(id)` gives the dict:

```jsonc
{
  "title": "Chain of two", "level": 2, "tags": ["chain", "move"], "tests": "...",
  "tolerance": {"rel": 0.1},                    // optional
  "variants": {"noise": ["none", "counts"], "lengths": {"short": 300, "long": 2000}},   // optional
  "model": {                                    // the truth.model.json format (sdlab/sdtruth.py)
    "seed": 3,
    "stocks": [{"id": "A", "initial": 0}, {"id": "B", "initial": 0}],
    "flows": [
      {"id": "in", "from": null, "to": "A", "rate": {"form": "constant", "value": 20}},
      {"id": "ab", "from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.5}},
      {"id": "b_out", "from": "B", "to": null, "rate": {"form": "proportional", "stock": "B", "k": 0.2}}
    ],
    "schedule": {"every": 200, "changes": [{"t": 1, "label": "low", "set": {"in": {...}}, "announce": true}]},
    "injections": [{"t": 50, "stock": "A", "amount": 400}]
  }
}
```

**The case hash** (which decides whether a result is stale) covers what a run is made from and
scored against, not the file: the compiled model, variants and tolerance as canonical JSON, the
truth model of every variant (without its id and name), the engine (`sdtruth.py` and the equations
it uses from `runner.py`) and `data.py`. A comment, a reordered term (`A * 0.5` for `0.5 * A`),
moving a case between YAML and JSON, or rewording its title, level, tags or `tests` sentence leaves
its results current. (Until 19 October 2026 the hash also covered the title and `tests` sentence;
the stored results, including those of earlier wordings of 035, were moved to the new hashes
then.)
(Until October 2026 the hash covered the case file's bytes and `cases.py`; the results stored then
were moved to the new hashes when the 25 cases became YAML, and
`tests/test_ladder_caseformat.py` checks each converted case compiles to exactly the JSON it
replaced.)

Every case runs in each **variant**: `none` (the engine's exact flows, where the equations should be
recovered essentially exactly) and `counts` (whole things moved, drawn Poisson around the rate), each
at `short` (300 steps) and `long` (2000 steps). The data comes from the ground-truth engine
(`sdlab/sdtruth.py`, which is never edited; the case's model is simply handed to it). Data is cached
under the case's hash. Each variant also has a **fresh run** (the next seed), used to grade
generalisation; without noise it is the same run.

Discovery gets only what the page would give it: the measured stocks (id, name, unit, final, group),
their levels, the announced eras and the announced injections.

### The first ladder

| case | tests |
|---|---|
| 001-inflow-only | a constant outside inflow into a stock nothing leaves |
| 002-inflow-outflow | a constant inflow and a proportional outflow of one stock |
| 003-chain-2 | a move between two measured stocks, with the chain's inflow and exit |
| 004-chain-3 | two moves in a row, each at its own rate |
| 005-chain-4 | three moves in a row |
| 006-chain-exit-middle | a stock's drain split between a measured receiver and outside |
| 007-link | an inflow that follows another stock's level (a link, not a move) |
| 008-link-loop | a reinforcing loop closed by a link (B's level drives A's inflow, A feeds B) |
| 009-births-and-deaths | births and deaths in proportion to one stock: only the difference is identifiable (best answer: equivalent) |
| 010-loop-branch | a link loop with a move leaving it to a third stock |
| 011-goal-gap | a balancing loop: orders into a supply line follow the gap between a goal and the inventory |
| 012-rework | a back-flow (B -> A) beside the forward move |
| 013-merge | two stocks fed from outside drain into one |
| 014-split | one stock drains into two at different rates |
| 015-hidden-stock | an unmeasured stock between two measured ones (an inferred stock with the right delay) |
| 016-coflow | a move that uses up a third stock as it goes |
| 017-linear-effect | a move multiplied by a linear effect of a third stock's level |
| 018-table-effect | a move multiplied by a table effect of a third stock's level |
| 019-announced-era | a move's rate that changes at announced eras |
| 020-unannounced-step | an outside inflow that steps without announcement |
| 021-daily-inflow | an outside inflow with a daily cycle |
| 022-pulse | a one-step burst into a chain every 100 steps |
| 023-injection | announced injections into a chain |
| 024-floor-binds | a link with a negative coefficient that stops at zero |
| 025-runs-empty | a constant demand that empties its stock and is then capped |

## Cases as mathematical probes (`analysis.py`, `fisher.py`, `sweep.py`)

The cases are not meant to reproduce real-world outcomes. They are for debugging methods: each one
probes one mathematical property. For every case and variant we work out from the mathematics what
the data can and cannot deliver. A failure can then be put down to one of two things: (a) the
method's fault, where the data allowed a pass, or (b) the data's limit, where it did not. The
analysis is on the scorer's side. It uses the true model and the run; discovery never sees it.

```
uv run sdlab-ladder analyse 038 --variant none-short     # one case: label, design, bound, parts, equivalences
uv run sdlab-ladder analyse --all --jobs 6               # every case and variant into the cache; counts by label
uv run sdlab-ladder analyse --validate 003 --variant counts-long --seeds 30   # the bound against ML refits
```

`sdlab-ladder show CASE` prints each variant's label first. The matrix marks every cell's square
with its label (amber underline: data-limited, grey: unidentifiable) and gives the reason on hover.
`status` and the leaderboard ("pass (achievable)") give each strategy's **pass rate over the
achievable cells only**. The labels never change pass or fail: the user decides about scoring.

### What is computed

**1. Is the structure identifiable from levels?** (`design`) Each measured stock's change is
regressed on everything a method could put in its row: a constant (one per window where the
truth's constant changes) and every measured level. Each step is weighted by the true variance of
that change. For each stock the analysis reports:

- the rank and condition number of the column-normalised design;
- the (near-)collinear columns, as an eigenvector with its relative size;
- for each true term, its SE in this full regression and z = |true| / SE.

A term with z < sqrt(log n) (the BIC price of a column) cannot be told from the alternatives. Its
chance of being detected is P(|z_hat| > sqrt(log n)). Without noise, the only noise left is the
data's rounding to 4 decimals. A true term that falls below the threshold there is collinear to
the data's precision, which makes the cell *unidentifiable*. Examples are identical stocks (034,
038), different starts of identical stocks (035: the levels stay in a fixed ratio), and two drawn
chains that share a rate (043#2).

**2. Same-size alternative structures** (`alternatives`). The levels identify the linear system
(B, u). They do not identify how it splits into non-negative flows. Each of the following is
another structure with no more numbers than the truth, built from it, that has the same mean
change of every stock on the run (checked on the run's own rates, so a floor that binds rules it
out):

| truth | the same levels | example |
|---|---|---|
| a link outside -> i reading j at k, where j drains at d | the move j -> i at min(k, d), the rest as a link, j's drain d - min(k, d) | 007, 008, 045, 054, 055 |
| a move j -> i at k, where j also drains at d | a link at k and j's drain at d + k | 006, 029-033 |
| an inflow c - k j (a gap) | the inflow c and an outflow i -> outside reading j at k | 011, 047 |
| a constant inflow c and an outflow k j of the same stock | one inflow c - k j | 002, 036, 049, 056 |
| a co-flow using `per` of R | an outflow R -> outside at per x the flow's rate | 016 |

The two structures differ only in the noise's covariance. A move's count leaves one stock and
arrives in the other; a link's does not. Without noise they cannot be told apart, so the cell is
unidentifiable. With counting noise, the chance that the likelihood prefers the truth is
Phi(sqrt(D / 2)), where D is the summed KL divergence between the two Gaussians step by step. It
enters the cell's p. A move whose source has no drain has an alternative with one number more
(parsimony picks the move), which is only listed. A hidden stock between A and B has its
**mirror**: the delay and B's drain swapped, with k_in rescaled. Without noise it gives the same
measured levels, so 015 and 026 are unidentifiable on their noise-free variants.

**3. The best achievable accuracy** (`fisher.py`). Every number in the true equations becomes a
parameter. A rate that a schedule changes gets one parameter per segment. Each step's change of
the measured stocks, given the levels at its start, is then dy = S q with S the stoichiometry and q
the flows' amounts. q is Poisson around the rates (floored at 0, outflows capped at what the stock
holds, as in the engine). Taken as Gaussian, dy ~ N(S r, S diag(r) S'). The Fisher information is

    I = sum_k J_k' Sigma_k^-1 J_k  +  1/2 tr(Sigma_k^-1 dSigma_i Sigma_k^-1 dSigma_j)

The first term is the mean (what least squares uses). The second is the variance: counting noise
grows with the rate, which is what separates births from deaths (009) when the mean cannot. The
Cramér–Rao bound I^-1 is the best SE any unbiased method can reach on that run. A direction the
information is blind to is *not identified*: births + deaths without noise, and an effect's
`max` that the run never reaches (harmless, because a flow with effects is scored as a whole).
Without noise the bound comes from rounding alone ("exact if identifiable").

The bound is mapped to the scorer's parts per window. For a flow with effects it is mapped to the
flow's amount over the run. Each part is compared with the scorer's own allowance, max(rel x |true|,
floor, z x oracle SE). A part is reached within tolerance with p = 2 Phi(allowed / SE) - 1. The
cell's p is the joint chance from 4000 Monte Carlo draws of the bound's normal, multiplied by the
chance that every true term and the truth over its alternatives are detected.

**Labels:** `unidentifiable` means only an equivalent model is possible (p is set to 0; a pass
there comes from a prior such as parsimony or a tiebreak, not from the data). `data-limited` means
identifiable, but p < 0.5. `achievable` means p >= 0.5. For a hidden stock the SEs are the hidden
oracle's ML SEs in place of the bound. A cell where a stock is at 2 or below on more than 5% of
steps is marked `approximate` (see 056 below).

**The bound checked by Monte Carlo.** The true structure was refitted by ML on fresh seeds and the
spread of the estimates compared with the mean bound (`analyse --validate`, 30 seeds; sd / bound
per number):

| case, variant | sd / bound |
|---|---|
| 003 counts-long | 0.99, 1.02, 0.95 (40 seeds in `tests/test_ladder_analysis.py`: within 25%) |
| 003 counts-short | 1.29, 1.37, 1.33 (300 steps: the asymptotic bound is about 30% optimistic) |
| 007 counts-short | 1.06, 1.02, 0.83, 0.79 |
| 049#1 counts-short | 1.11, 1.16, 1.04, 0.99 |
| 054#4 counts-long | 0.84, 0.94, 1.16, 1.13, 0.80 |
| 009 counts-long | 0.89, 0.78, 0.86 |
| 056#5 counts-long (equilibrium 1) | 1.12, 1.02, but the ML estimates are biased: drain 0.38 for 0.5 |
| 056#7 counts-long (equilibrium 0.2) | 1.69, 0.72, biased: drain 0.29 for 0.5, inflow 0.036 for 0.1 |

Near the zero floor the Gaussian picture fails. Counts there are 0, 1 and 2, and a drain is cut
short by an empty stock. A method with Gaussian noise, the truth's own structure included, is then
biased. An exact count likelihood would not be, so these cells stay "achievable" but are marked
`approximate`.

**On the ladder** (`sdlab-ladder analyse --all`, 18 October 2026): of the 492 cells of the ladder
without the sweeps, 353 are achievable, 29 data-limited and 110 unidentifiable. Cells by the
reason they are unidentifiable (a cell can have several): 62 inflow + drain = one gap inflow, 42
link <-> move, 12 collinear levels, 10 negative inflow term = outflow, 4 hidden mirror, 2
births/deaths, 2 co-flow. Almost all of these are noise-free variants. With counting noise, the
cells that remain short of achievable are data-limited, not unidentifiable: a weak link or loop
(046, 054, 055 at low gain, 008 and 010 on short runs), 044's
random three stocks on short runs, the effects cases' per-window inflow constants (017, 018: 10%
of 3 is the SE of a 100-step window, and there is no oracle allowance for effects), 016 short, and
022 long.

### Sweeps

A sweep is a parametric case that varies one quantity along a grid instead of at random:
`grid(v1, ..., vN)` stands for v_i in draw i (draws.py). Several grids in one case move together.
A `# axis: ...` comment names the axis, and `# axis values: ...` gives its values when the grid's
numbers are not the axis itself.

| case | axis | grid |
|---|---|---|
| 049-sweep-drain-ratio | drain ratio of two unrelated stocks d_B / d_A | 1, 1.02, 1.05, 1.1, 1.2, 1.35, 1.5, 2 |
| 050-sweep-timescale | fast / slow rate in a chain (A -> B over B's drain) | 1, 2, 5, 10, 20, 50, 100 |
| 051-sweep-level-scale | signal to noise: inflow (levels scale with it) | 2, 5, 20, 50, 200, 500, 2000 |
| 052-sweep-run-length | run length (short; long is twice) | 50, 100, 250, 500, 1000, 2500 |
| 053-sweep-excitation | unannounced inflow steps per 300 steps | 0, 1, 2, 4, 5, 9, 14 |
| 054-sweep-link-strength | link k over the receiver's drain | 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2 |
| 055-sweep-loop-gain | loop gain (link over B's drain; unstable at 1) | 0.1, 0.3, 0.5, 0.7, 0.85, 0.95, 0.98 |
| 056-sweep-zero-floor | equilibrium level near zero | 40, 10, 4, 2, 1, 0.4, 0.2 |

**Phase diagrams** (`/ladder/probes`, `GET /api/ladder/sweeps/{base}/{variant}[.svg]`,
`sweep.findings`) plot each leading strategy's relative error on every true number against the
axis. Beside them are the bound (dashed) and the scorer's tolerance (dotted). The background is
shaded where the cell is data-limited or unidentifiable. Where a method's error leaves the
tolerance while the bound is still far inside it, the method breaks first; where the band is
shaded, the data does. Strategies that return the same model draw on top of each other (matrix and
hidden_transit, earned_pieces and common_cause, on most points). Below: counts-long, then
counts-short for 049, 054 and 055.

![049](probes/049-counts-short.svg)
![050](probes/050-counts-short.svg)
![051](probes/051-counts-long.svg)
![052](probes/052-counts-short.svg)
![053](probes/053-counts-long.svg)
![054](probes/054-counts-long.svg)
![055](probes/055-counts-long.svg)
![056](probes/056-counts-long.svg)

Findings (lna, earned_pieces, held_out, common_cause, hidden_transit, matrix; results of 18
October 2026, `python -c "from sdlab.ladder import sweep; print('\n'.join(sweep.findings('049')))"`):

- **049 drain ratio.** Without noise every point is unidentifiable: the inflow + drain = gap
  equivalence everywhere, and at r = 1 the levels are identical too. All methods pass for r > 1 by
  their convention, and only common_cause (its tiebreak) passes r = 1. With counts the data allow
  every point, even r = 1 (noise separates the stocks, z of each own drain about 6 in 300 steps).
  lna, earned_pieces, held_out and common_cause pass everywhere. matrix and hidden_transit fail
  all 8 short points and 4 of 8 long ones, with errors of 40-150% against a bound of about 7%.
  That is the method's fault, at every ratio.
- **050 time-scale ratio.** The data allow every point up to 100. Four methods pass everywhere.
  matrix and hidden_transit fail at r = 2 and at r >= 20 on short runs (a slow B still far from
  equilibrium) and at r = 2 on long runs. That is the method's fault.
- **051 level scale.** The data allow every point; the bound shrinks from 2.2% at inflow 2 to 0.9%
  at 2000. matrix and hidden_transit fail at inflow 2 and 20 on short runs. lna fails at 2000 on the
  long run with 2 spurious parts. Both are the method's fault.
- **052 run length.** Achievable from 50 steps (p 0.97) to 5000. All six methods pass every point:
  nothing breaks on length alone in this range.
- **053 excitation.** The data allow every point; more steps help the bound. held_out fails as soon
  as there is one step (without noise from 4 steps per 300). lna fails at 4 and 14 steps on short
  runs and at 14 on long ones; matrix and hidden_transit fail sporadically. All are the method's
  fault (finding the pieces).
- **054 link strength.** Without noise it is unidentifiable everywhere (the link is a move with a
  smaller drain), and every method gives the best possible answer, equivalent. With counts it is
  data-limited below k / d = 0.25 (0.5 on short runs) and achievable above, where only the noise's
  covariance separates link from move. lna passes there (0.25-2 long, 0.25-1 short). earned_pieces,
  held_out and common_cause return the equivalent move. matrix and hidden_transit fail. The break
  is the method's: they do not use the covariance.
- **055 loop gain.** Without noise it is unidentifiable (link <-> move). With counts it is
  data-limited only at gain 0.1 (p 0.04 short, 0.13 long) and achievable from 0.3 (p 0.56 on short runs) up to 0.98. lna passes 0.1-0.85
  long and 0.5-0.95 short, and gives the equivalent move at 0.95 and 0.98 long, near instability.
  The others return equivalent or fail at every gain. That is the method's fault in both places.
- **056 zero floor.** With counts the bound says achievable at every point (marked approximate
  below equilibrium 4). earned_pieces, held_out and common_cause pass down to equilibrium 1 and
  fail at 0.4 and 0.2. lna, matrix and hidden_transit fail from 2 (long). The truth's own Gaussian
  ML is biased by 24-42% there. These methods break where counting noise stops being Gaussian,
  which is a modelling limit; an exact count likelihood would be needed.

## Strategies

Every module in `sdlab/discovery/strategies/` with `identify(stocks, run, opts)` is a strategy. The
folder is listed again on every sync, so a new module is picked up with no registration. A
strategy's **hash** covers:

- its own module (a file, or a package folder);
- any sibling strategy it imports (`from .other import ...`);
- the rest of `sdlab/discovery`.

Any change to discovery's shared code therefore re-runs every strategy, but adding a strategy does
not re-run the others. A strategy whose import fails (for example, an optional package that is
missing) is listed as unavailable with the reason and skipped. It does not crash the run.

To add one, follow [DISCOVERY-LOOP.md](DISCOVERY-LOOP.md). Write the module, then run
`uv run sdlab-ladder sync --strategies <name>` and read its column next to `matrix`'s in
`sdlab-ladder status`.

## Scoring (`sdlab/sdlab/ladder/score.py`)

**Parts.** Each flow is cut into parts, one per number in its equation. A rate in a linear form
(`constant`, `proportional`, `gap`, `linear`) is `c + sum k_j x level_j`. Its parts are:

- `(from, to, const) = c`;
- `(from, to, j) = k_j` for each stock j it reads.

Here from and to are measured stocks, or outside. The part's **kind** follows from the key:

| kind | key |
|---|---|
| move | measured to measured |
| outside inflow | from outside, reading nothing |
| link | from outside, reading a stock (also a gap's own-stock term) |
| outside outflow | to outside |
| co-flow | `(uses, from, to, stock) = per` |
| effect | `(effect, from, to, stock)` |
| hidden | measured A to unmeasured H to measured B: `(hidden, A, B) = {k_in, delay}` |

On the found side, a hidden stock is a flow with `via: {delay}`, or a chain through a stock that is
not measured, such as an inferred stock. Parts with the same key are summed on each side, because
two flows that are one number in the data are scored as that one number.

**Windows.** Each number is compared in every window of the run where the truth's equations hold
still (between announced eras and unannounced schedule changes). In each window, the found number
is averaged over the window: its `byTime` segments, or its outside inflow pieces. A part is right
only if it is right in every window.

**Tolerance.** A found number k is right when `|k - true| <= max(rel x |true|, floor / mean level it
reads, z x SE)`:

| term | default |
|---|---|
| rel | 10% with noise, 2% without |
| floor | 1% of the median true part size (0.2% without noise); size = flow amount per step, \|k\| x the mean level it reads |
| SE | the oracle's standard error for that number, with z = 3 |

The **oracle** (`oracle.py`) is the truth's own structure fitted by least squares on the run. A
short noisy run cannot pin a rate to 10%, even for someone who knows the structure. The oracle
allowance keeps a strategy from failing for what the data cannot say. Without noise the oracle's
SE is about 0, so 2% is all that is allowed. The oracle applies only when the truth is a linear
system of the measured stocks (no effects, no hidden stocks). A flow with effects is compared as a
whole: its amount on the run's states (rate x effects) against the found flows between the same
stocks, by relative rms error within `rel`. Hidden stocks are compared by `k_in` and delay: `k_in`
like any number, the delay within `max(rel x delay, z x SE)`. Per-case overrides go in
`"tolerance": {"rel", "rel_exact", "floor", "floor_exact", "spurious", "z"}`.

The **hidden-stock oracle** (`hidden_oracle.py`) does the same for a truth with one unmeasured
stock H between measured A and B (A -> H reading A, H -> B reading H; the other flows linear, A's
reading only A and B's only B; 015, 026). It fits the truth's own structure by maximum likelihood
on the measured data only: H is followed by a one-state Kalman filter with the counts' shared noise
(the filter of `strategies/hidden_transit/kalman.py`, copied so the scorer does not move with a
strategy), H's start is a free number, A's (and B's) outside constant gets one number per window
when it changes, and the fit starts at the truth's numbers (the mirror, delay and B's drain
swapped, is another optimum and is not wanted). The SEs come from the inverse Hessian of
-log L; the delay's is d's by the delta method (SE(d) / d^2). They apply to the outside inflow,
B's drain, `k_in` and the delay, only on noisy variants (whole-number data are counts, scale 1;
without noise there is no oracle). Spurious parts get no allowance from it, and `equivalent` is
still not checked. A fit takes about 0.01-0.2 s and is cached per truth and data. Why: the delay
is carried only by the counting noise at equilibrium, so its SE is about one step (10%) at any
length; on 40 fresh seeds of 015 counts the truth's own ML fit had all four numbers within a bare
10% in only 47.5% (300 steps) and 60% (2000 steps) of runs
([research/hidden_transit.md](research/hidden_transit.md)). The SEs on the ladder's runs:

| case, variant | outside -> A | k_in | delay (steps) | B -> outside |
|---|---|---|---|---|
| 015 counts-short | 1.12 | 0.0113 | 1.25 | 0.0116 |
| 015 counts-long | 0.42 | 0.0042 | 1.05 | 0.0043 |
| 026 counts-short | 0.61 / 1.65 (low / high) | 0.0105 | 1.04 | 0.0106 |
| 026 counts-long | 0.42 / 0.88 (low / high) | 0.0039 | 0.42 | 0.0039 |

They are honest: over 30 fresh seeds per variant, the mean SE against the spread of the truth's own
fit (k_in, delay, drain) was 015 short 0.0107 / 1.31 / 0.0108 against 0.0099 / 1.52 / 0.0089, 015
long 0.0042 / 1.15 / 0.0042 against 0.0041 / 1.18 / 0.0037, 026 short 0.0101 / 0.94 / 0.0102
against 0.0134 / 1.14 / 0.0121 (slightly small there: the delay was within 3 SE in 25 of 30), 026
long 0.0038 / 0.41 / 0.0038 against 0.0038 / 0.51 / 0.0039.

**Status.**

- **pass**: every true part is found and right, and no part is spurious. A spurious part is a found
  part the truth lacks that is larger than 5% of the median true part size. With an oracle, it must
  also be larger than 3 SE of that term added to the truth's fit.
- **equivalent** (not a pass): the found flows make the same linear system as the truth. Every
  measured stock's change is the same function of the levels and the outside, within the same
  tolerances, in every window. So the data cannot tell the two apart while no floor binds. Examples:
  births and deaths seen as their difference, a gap seen as an inflow plus a drain, a link seen as
  a move. It is reported apart from pass. It is not checked for cases with effects or hidden stocks.
- **fail**: anything else. **error** / **timeout**: the strategy raised or ran out of time.

**recall** is the share of true parts whose key the found model has (right kind and ends,
whatever the number). **precision** is the share of found parts, at least as large as the spurious
threshold, that are true.

**Behaviour.** Behaviour is skill@20 and skill@100, computed by `sdlab/skill.py`, the same grading
as the examples' bench: the found and true models are run from about 150 moments, fed the truth's
outside inflows. It is reported on the run discovery saw and on the fresh run. Each comes with a
**95% bootstrap interval** that resamples the start moments: how much the number depends on which
moments were graded. It is a diagnostic next to the equations. A pass usually behaves well, but good
behaviour does not make a pass.

## Complexity (`sdlab/sdlab/ladder/complexity.py`)

How much more complicated a found model is than the truth. A noisy strategy can add flows, pieces
and terms that the scorer lets through (too small to be spurious, or in a run that fails anyway); a
simpler, slightly less correct model may be preferable. One count, applied identically to the true
model and to the found one:

**complexity = flows + numbers**, where the numbers are what it takes to write each flow's rate over
the run:

| part | counts |
|---|---|
| flows | 1 per flow (a found hidden stock written as one `via` flow is 2: into it and out of it) |
| terms | the rate's numbers in its first piece: constant 1, proportional 1, gap 2 (goal, time), linear 1 per stock read + 1 for a non-zero constant (zero terms are not written), available 0; a `via` delay 1 |
| pieces | for a rate that changes over the run (a found flow's outside inflow pieces or `byTime` segments; the truth's schedule), the numbers of every piece after the first; consecutive equal pieces are one. A found inflow in 9 pieces is 9 numbers |
| other | effects (linear 3: normal, min, max; table 2 per point), 1 per co-flow use, 1 for a ratio other than 1, 1 per stock that is not measured (hidden or inferred) |

The truth is counted **on the run** (its schedule laid out over steps 2..N, where found pieces
start), as a found model would have to write it: a found model that writes the true equations
counts exactly as much (extra 0). So a schedule counts once per change in the run: 020 is 8 on the
short runs and 25 on the long ones, and the daily cycle (021) 43 and 255. Examples: 003 (chain of
two) 6, 011 (goal gap) 7, 015 (hidden stock) 9, 016 (co-flow) 11, 017 (linear effect) 15.

Per result: **extra** = found - true, broken out by part (flows, terms, pieces, other), and
**ratio** = found / true. Not counted for an error or timeout (nothing found).

The **Occam score** of a result discounts accuracy by excess complexity, the way an information
criterion charges for parameters:

    occam = fit x parsimony,    parsimony = min(1, true / found)

where fit is 1 for a pass or an equivalent model, else the share of true numbers right (right / of),
and 0 for an error or timeout. Parsimony is the share of the found model's complexity that the truth
needs: a model twice as complicated as the truth keeps half its fit, one 10% over keeps 91%. A model
simpler than the truth is not rewarded for it (its fit already pays for what it misses). Multiplying
rather than subtracting keeps the score between 0 and 1 and does not zero a right model of a tiny
case for one extra piece.

Complexity is computed from the stored found flows when they are read (no re-run, and the scorer's
hash does not change): the summary counts each stored result once and keeps the count by result
id, so only new results are counted when it is recomputed.

## Long run: far horizons and constant-time jumps (`longrun.py`, `jump.py`)

skill@20 and skill@100 re-anchor both models on the true levels at ~150 moments and run them H
steps: they grade short and medium-horizon dynamics, and a model can score 100% there and still
break down after 10,000 steps (a mode that grows by 0.001% a step is invisible at H = 100 and
dominant at t = 100,000). The long run grades what is left.

**Free run.** The true and the found model start from the run's first levels (a found model's own
unmeasured stocks from 0) and run with nothing re-anchored, fed the truth's outside inflows exactly
as skill@H feeds them, to t = 100,000. Past the recorded run the truth's schedule repeats (`every`),
and a found model's own changing rates (byTime segments, outside-inflow pieces it keeps) repeat
their last period of the run; without a schedule, a found rate's last piece of at least 10 steps
holds (a one-step piece at the very end of a fit is an end effect: held for ever it would set the
equilibrium; it did for 34 results on 007-link before the rule).

**Constant time.** After the run, both models are periodic in time with the schedule's period P (or
autonomous). They are stepped in chunks (a multiple of P, at least 64 steps), and stepping stops as
soon as the future is known:

- **settled**: the last chunk equals the one before (to 1e-9 of the scale): every later step is read
  off that chunk, any t in O(1);
- **drift**: every chunk adds the same amount, only to stocks that no flow reads, drains or uses up
  (a final stock that only accumulates): exact for any model, linear or not, so x(t) = chunk + k x drift;
- **jump**: an affine model still moving after 20,000 steps (a very slow or marginal mode) whose last
  chunk agrees with its linear jump-ahead (below) is jumped;
- otherwise it is stepped to the end, and a run that passes 1e12 x the truth's scale stops (runaway).

The whole ladder (14,000 results) takes ~5 minutes of CPU: almost every model settles within a few
hundred steps of the end of the run.

**The jump-ahead** (`jump.py`). When every rate is a linear form (constant, proportional, gap,
linear) with no effects, co-flows or hidden delays, a step is affine, x(t+1) = M_t x(t) + b_t with
M_t = I + B_t. Composing the P steps of one period gives (M_P, b_P), and k periods are the power of
the augmented matrix [[M_P, b_P], [0, 1]] by squaring, in O(log k): x(t0 + kP) = M_P^k (x(t0) - x*)
+ x*, x* = (I - M_P)^-1 b_P (the augmented power also covers a stock that only grows, where I - M_P
is singular). **It is exact only while no floor binds**: every rate stays >= 0, no stock is asked for
more than it holds (the engine shares a stock among its outflows), no level goes below 0. A stable
model whose rates stay positive near its fixed point (chains, links, loops) is exact to float
precision; a floor that binds (024, 025), effects or co-flows (017, 018, 016), or a found model that
runs away or empties a stock are not covered, and there stepping (with the settled/drift read-off,
exact for any model) is the reference. `tests/test_ladder_longrun.py` checks the jump against
stepping on linear cases (with a periodic schedule, eras and injections), the read-off against
stepping to t = 8,000 on a nonlinear and a floor-binding case, and the true equilibria against the
analytic ones (002: A* = c / k; 003: A* = in / k_ab, B* = k_ab A* / k_b).

**Metrics**, per result (per measured stock normalised by the truth's scale: its range over the
recorded run, or its largest level in the graded window if larger; rms over stocks):

| | |
|---|---|
| `err` | at t = 1k, 10k, 100k and at 10 and 100 x the truth's slowest time constant: rms of (found - true) / scale over one chunk ending there |
| `far` | `err` at 100k, the headline |
| `eq_err` | the settled behaviour: mean level over the settled chunk, found vs true (a stock that only accumulates: its drift per step, relative); none when the found model never settles or grows where the truth settles |
| `tau_true`, `tau_found`, `tau_err` | slowest time constant, tau = -1 / ln\|lambda\| steps per mode, from the period map's eigenvalues (exact, the linear part) for an affine model, else from the Jacobian of the chunk map at the settled levels (finite differences); `tau_err` = \|tau_found / tau_true - 1\| |
| `rho_true`, `rho_found`, `unstable` | spectral radius per step; unstable: the found model's is above 1 by enough to grow 2x within the graded horizon (rho^100,000 > 2, i.e. rho > 1 + 6.9e-6), where the truth's is not (a mode at 1 + 1e-7 is a fitting rounding that doubles only after millions of steps) |
| `flag` | `runaway` (grows without bound, or 100x the truth's scale), `dies` (a stock goes to ~0 where the truth stays above 1% of its scale), `unstable`, or none; `hard_fail`: runaway or unstable |

They are computed from the stored found flows, once per result id, by `sdlab-ladder longrun
[--strategies ...] [--cases ...] [--jobs N]` (worker processes, niced) into
`$SDLAB_LADDER_CACHE/longrun.sqlite` under the long-run code's hash (`longrun_cache.py`). The server
never computes them for the summary: it reads the file (new rows only, at most every 10 s), and a
result not graded yet is "not computed yet". The summary carries them as one compact aggregate,
`longrun: {strategy: {variant: {level: [n, sum err@100k, sum eq err, n eq, sum tau err, n tau,
diverging]}}}` (each error capped at 1; a run that runs away or is unstable counts 1), which the
leaderboard turns into the columns **err@100k**, **eq err**, **tau err** and **diverges**.
`sdlab-ladder show` prints a result's long-run line (computing it if missing) and its graph link.

**The run page** (`/ladder/run?id=<result id>&at=250000&window=500`, linked from every case card on
the Now page and from `show`): per measured stock, the true model (blue) vs the found model's
prediction (orange) with the gap shaded, over the recorded run (with the recorded, noisy data as
dots), over the whole horizon on a log-time axis, and in windows ending at 10 and 100 tau, 1k, 10k,
100k and any `at` (any t when the run settled or drifts: constant time). Inline SVG, no library.
`GET /api/ladder/longrun/{id}?at=&window=` (`longrun_series.py`) gives its data.

**What it showed** (October 2026, `sdlab-ladder longrun` then the store): of 9,581 results with
in-sample skill@100 >= 90%, 185 have err@100k or eq err >= 10% or are flagged. The worst are models
with a nearly neutral mode that skill@100 cannot see: output_error on 034 and 038 (skill@100 100%;
two stocks draining each other at almost equal rates, rho 1.000004-1.000016: at 1k the gap is 7x the
truth's range and a stock dies out), effect_hats on 043#2 (rho 1.0147, unstable, eq err 54%),
earned_pieces on 043#2 none-long (1.8% at 1k, 190% at 100k), sindy on 032 none-long (tau 11,724
steps vs 9.5); and 055-sweep-loop-gain#7 (a truth with tau 348) where matrix, held_out and
hidden_transit run away (skill@100 97%, err@100k 191x). Most of the rest settle 10-15% off (gaps
in equilibrium from noisy rates: 048 draws, 020, 017, 018 effects, 033).

## Reading the matrix

```
case                             matrix
003-chain-2                PPPP  100.0%
007-link                   EEFF   68.8%
```

Each cell has one letter per variant, in the order `none-short, none-long, counts-short,
counts-long`:

- P pass, E equivalent, F fail, X error, T timeout, . not run;
- `*` after the letters means the result is stale (a sync would run it again).

The number is the mean recall over the variants. Read the letters left to right. A strategy should
pass the noise-free variants of a rung before its noisy ones mean much. Failing only with noise
points at estimation; failing without noise points at structure, a representation the strategy
lacks.

After the matrix, `status` prints each strategy's totals. With one strategy (or `--detail`), it
prints a per-variant table with recall, parts right, skill@20 with its interval, and fresh skill@20.
Then come the **per-tag** counts (pass + equivalent of total) across strategies, which show which
motifs a strategy handles. `show CASE` prints the true equations, the found ones, and every part
with its true and found numbers, error and verdict, plus the spurious parts.

## The read API (for a page)

`sdlab/sdlab/ladder/api.py`. Every function is read only and returns JSON-safe values:

| function | returns |
|---|---|
| `cases()` | every case: `id, title, level, tags, tests, hash, tolerance, variants [{name, noise, length, steps}], model` (the truth model) |
| `case(id)` | one case, or None |
| `strategies()` | `[{name, hash, available, reason}]` |
| `results(case?, variant?, strategy?)` | the latest result per (case, variant, strategy), filtered |
| `result(case, variant, strategy)` | the latest one with `found` (the found flows), or None |
| `history(case, variant, strategy)` | every result for it, newest first |
| `result_by_id(id)` | one stored result (any, not only the latest) with `found`, or None |
| `case_data(case, variant, fresh?)` | `{case, variant, fresh, t, levels (measured stocks), all_levels (every stock, hidden ones too), measured, eras, injections}`: what discovery sees, and what it does not |
| `timeline(strategy)` | one point per version (strategy hash and scorer hash, in the order they first ran): `{strategy_hash, score_hash, first, last, ran, totals: {status: n}, of}`, the totals being the ladder's state just after that version (each case and variant's newest result up to then) |
| `board(strategy, variant?)` | `{strategy, variant, best, cases, results}`: every case and one strategy's latest results (found flows included) in a variant, or all four |
| `best_strategy()` | the available strategy with the highest pass rate |
| `progress(recent?)` | `{run: {id, command, started, finished, total, done, running}, items: [{case, variant, strategy, state (queued, running, done), reason, started, finished, status}]}`; with `recent`, a light copy for polling: only the running items and the `recent` latest finished, plus `counts` (finished items by status) and `queued` |
| `summary(strategies?)` | `{strategies, cases, cells: [{case, variant, strategy, status, stale, recall, precision, right, of, spurious, skill20, skill20_ci, skill100, skill100_ci, fresh20, fresh20_ci, fresh100, fresh100_ci, seconds, at, error, occam, cx_true, cx_found, cx_extra, cx_ratio, cx_by: [flows, terms, pieces, other]}], by_tag: {tag: {strategy: counts}}, totals: {strategy: counts}, score_hash, longrun (the long-run aggregate, below)}` |
| `run_graph(id, at?, window?)` | one result's true vs found levels run free, far ahead: `{result, stocks, run, overview, windows, metrics, how}` (Long run, below) |

A result is `{id, case, variant, strategy, case_hash, strategy_hash, score_hash, at, latest, status,
seconds, error, scores, code_commit, code_dirty}`. Its `strategy_hash` is that of the code the
worker actually imported (`provenance.py`). It is computed when the process first imports the
strategy, not when the run was planned, so a file edited during a long run cannot put newer code
under an older hash. `code_commit` is the git commit then. `code_dirty` is empty when the imported
code is that commit's; otherwise it is the hash of a patch saved as
`$SDLAB_LADDER_CACHE/code/<code_dirty>.patch`, and `git checkout <commit> && git apply <patch>`
gives back the exact code. `show` prints both. `scores` holds:

- the equation scores: `status, recall, precision, right, of, parts [{key, kind, found, true, found_value, ok, error, se}], spurious, negligible, windows, tolerance, notes`;
- `behaviour: {in_sample, fresh: {"20", "100": {skill, ci, moved}}}`.

A result read with its found flows (`result`, `result_by_id`, `board`) also has `complexity: {true,
found, extra, ratio, by: {flows, terms, pieces, other}}` (None for an error or timeout).

A parametric case's draws (`NNN-slug#i`) are cases like any other here, and a draw's case carries
`draw` (Parametric cases, above). In a URL the `#` is written `%23`
(`/api/ladder/cases/042-random-two-chains-of-two%235`).

The server serves these endpoints, read only:

```
GET /api/ladder/cases
GET /api/ladder/cases/{case}
GET /api/ladder/strategies
GET /api/ladder/results?case=&variant=&strategy=
GET /api/ladder/results/{case}/{variant}/{strategy}
GET /api/ladder/results/{case}/{variant}/{strategy}/history
GET /api/ladder/cases/{case}/data/{variant}?fresh=
GET /api/ladder/result/{id}
GET /api/ladder/strategies/{strategy}/timeline
GET /api/ladder/board?strategy=&variant=
GET /api/ladder/progress?recent=
GET /api/ladder/summary?strategies=a,b
GET /api/ladder/longrun/{id}?at=&window=
```

A case, variant or strategy must be one the listings name, and a result id an integer that is stored;
anything else is a 404 (422 for an id that is not a number). No path comes from the client.

## The page

`/ladder` (the 🪜 button in the editor and the research view) shows all of this, read only
(`sdlab/static/ladder.html`, `ladder.js`, `ladder-compare.js`, drawing with `diagram.js`; SPEC.md
4.13):

- **Now** (default: every case on one page for one strategy and variant, `GET /api/ladder/board?strategy=&variant=`): per case the true model, the found model and their differences (✓ matched, ~ off, − missed, + invented, ≈ equivalent) as a diagram and a diff list, a plain-language explanation, and the error measures, headed by the **equation error** = (true numbers missing + off + invented numbers) ÷ true numbers. Click a case for the single result: what is running (polled every second) and, following the run as it finishes items or
  for any case, variant and strategy picked, the true model's diagram beside the found one, laid
  out identically, flows coloured green (right), amber (a number off: true vs found shown), red
  dashed (missing), red (spurious), blue (equivalent), grey (too small); then the equations side
  by side, every part's numbers, and the scores with their intervals.
- **Matrix**: strategies x cases, four squares a cell (P E F X T ·, hatched when stale), per-strategy
  totals and per-tag summaries; a filter and an order for the columns when there are many
  strategies; click a square to open it in Now.
- **History**: a case and strategy's results over time (when it started passing or failing,
  recall or skill per variant, every result clickable into Now) and each strategy's totals per
  version.
- **Cases**: every case with its "tests" sentence, true diagram and equations, and a plot of its
  data in any variant.

The **leaderboard** (`/ladder/leaderboard`, 🏆 from the ladder and research pages) ranks every
strategy by pass rate, recall, precision and skill, sortable, with variant and level filters. It
also shows each strategy's **Occam score** (mean over all runs; not run, error and timeout count 0),
mean **extra** complexity (over the runs that found a model; hover for the mean true and found and
the extra by part) and **× truth** (the geometric mean of found / true), and can rank by the Occam
score or by least extra complexity (Rank by, or click a column). The Now page and `sdlab-ladder
show` give each result's true and found complexity and where the extra comes from.

In the **editor**, every case is also a read-only **basic model** (`ladder-<case>`, listed first in
the model picker; SPEC.md 4.14): its true model, laid out the same way, playing back the case's
recorded data in a variant (`counts-long` by default), so Discover can be run on it there and its
flows compared with the truth.

Run `uv run sdlab` and open `http://127.0.0.1:8020/ladder`; run `uv run sdlab-ladder sync` (or
`watch`) in another terminal to see it live.

## Where things are

| | |
|---|---|
| Cases | `sdlab/sdlab/ladder/cases/*.yaml`; the YAML format in `caseformat.py`; parametric cases (draws) in `draws.py`; loading, variants and hashes in `cases.py`; checks in `checks.py` |
| Data | `data.py` (engine runs, cached in `$SDLAB_LADDER_CACHE/data`) |
| Scoring | `score.py` (equations and behaviour), `parts.py` (equations as numbers), `oracle.py` (standard errors) |
| Long run | `longrun.py` (free runs, settled / drift read-off, metrics), `jump.py` (affine jump-ahead, equilibria, spectra), `longrun_cache.py` (by result id, the CLI fill, the summary aggregate), `longrun_series.py` (the run page's data), `sdlab/static/ladder-run.html` |
| Complexity | `complexity.py` (true and found complexity, extra, the Occam score; cached by result id) |
| Strategies | `catalog.py` (listing, hashes, availability) |
| Store | `store.py` (`results.sqlite`: results with history, runs and progress) |
| Running | `runner.py` (what is stale, the process pool, timeouts), `cli.py` |
| Read API | `api.py`, endpoints in `routes.py` |
| Page | `sdlab/static/ladder.html`, `ladder.js` (views), `ladder-compare.js` (true vs found, flow by flow), `diagram.js` (drawing, shared with the editor) |
| Probes | `analysis.py` (identifiability, alternatives, labels; cached), `fisher.py` (the truth's numbers, Fisher information, ML refit), `sweep.py` (phase diagrams), `analysis_report.py` (`analyse`), `analysis_routes.py`; page `sdlab/static/probes.html` |
| Tests | `tests/test_ladder.py`, `tests/test_ladder_analysis.py`, `tests/test_ladder_caseformat.py`, `tests/test_ladder_complexity.py`, `tests/test_ladder_longrun.py`, `tests/ladder_compare.test.mjs` |
