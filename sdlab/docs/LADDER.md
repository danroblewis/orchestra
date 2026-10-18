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
```

`python -m sdlab.ladder ...` works too. Cases are chosen by id or number prefix (`003`,
`003-chain-2`), tag (`tag:loop`) or level (`level:6`). Variants are chosen by name (`counts-short`),
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

**The case hash** (which decides whether a result is stale) covers what a run is made from, not the
file: the compiled case as canonical JSON, the truth model of every variant, the engine
(`sdtruth.py` and the equations it uses from `runner.py`) and `data.py`. A comment, a reordered
term (`A * 0.5` for `0.5 * A`) or moving a case between YAML and JSON leaves its results current.
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
stocks, by relative rms error within `rel`. Hidden stocks are compared by `k_in` and delay, each
within `rel`. Per-case overrides go in `"tolerance": {"rel", "rel_exact", "floor", "floor_exact",
"spurious", "z"}`.

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
| `progress(recent?)` | `{run: {id, command, started, finished, total, done, running}, items: [{case, variant, strategy, state (queued, running, done), reason, started, finished, status}]}`; with `recent`, a light copy for polling: only the running items and the `recent` latest finished, plus `counts` (finished items by status) and `queued` |
| `summary(strategies?)` | `{strategies, cases, cells: [{case, variant, strategy, status, stale, recall, precision, right, of, spurious, skill20, skill20_ci, skill100, skill100_ci, fresh20, fresh20_ci, fresh100, fresh100_ci, seconds, at, error}], by_tag: {tag: {strategy: counts}}, totals: {strategy: counts}, score_hash}` |

A result is `{id, case, variant, strategy, case_hash, strategy_hash, score_hash, at, latest, status,
seconds, error, scores}`. `scores` holds:

- the equation scores: `status, recall, precision, right, of, parts [{key, kind, found, true, found_value, ok, error, se}], spurious, negligible, windows, tolerance, notes`;
- `behaviour: {in_sample, fresh: {"20", "100": {skill, ci, moved}}}`.

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
GET /api/ladder/progress?recent=
GET /api/ladder/summary?strategies=a,b
```

A case, variant or strategy must be one the listings name, and a result id an integer that is stored;
anything else is a 404 (422 for an id that is not a number). No path comes from the client.

## The page

`/ladder` (the 🪜 button in the editor and the research view) shows all of this, read only
(`sdlab/static/ladder.html`, `ladder.js`, `ladder-compare.js`, drawing with `diagram.js`; SPEC.md
4.13):

- **Now**: what is running (polled every second) and, following the run as it finishes items or
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
strategy by pass rate, recall, precision and skill, sortable, with variant and level filters.

In the **editor**, every case is also a read-only **basic model** (`ladder-<case>`, listed first in
the model picker; SPEC.md 4.14): its true model, laid out the same way, playing back the case's
recorded data in a variant (`counts-long` by default), so Discover can be run on it there and its
flows compared with the truth.

Run `uv run sdlab` and open `http://127.0.0.1:8020/ladder`; run `uv run sdlab-ladder sync` (or
`watch`) in another terminal to see it live.

## Where things are

| | |
|---|---|
| Cases | `sdlab/sdlab/ladder/cases/*.yaml`; the YAML format in `caseformat.py`; loading, variants and hashes in `cases.py`; checks in `checks.py` |
| Data | `data.py` (engine runs, cached in `$SDLAB_LADDER_CACHE/data`) |
| Scoring | `score.py` (equations and behaviour), `parts.py` (equations as numbers), `oracle.py` (standard errors) |
| Strategies | `catalog.py` (listing, hashes, availability) |
| Store | `store.py` (`results.sqlite`: results with history, runs and progress) |
| Running | `runner.py` (what is stale, the process pool, timeouts), `cli.py` |
| Read API | `api.py`, endpoints in `routes.py` |
| Page | `sdlab/static/ladder.html`, `ladder.js` (views), `ladder-compare.js` (true vs found, flow by flow), `diagram.js` (drawing, shared with the editor) |
| Tests | `tests/test_ladder.py`, `tests/test_ladder_caseformat.py`, `tests/ladder_compare.test.mjs` |
