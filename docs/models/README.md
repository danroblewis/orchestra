# User-story models

System dynamics models of the user stories in `../user-stories.md`. They are written in SD Lab's
editor format (`~/orchestra/sdlab/MODEL.md`), checked with SD Lab's own validator, and simulated
with SD Lab's own simulator. They are planning estimates, not measurements: every number is an
assumption (listed below) until it's fitted from history.

```
python3 docs/models/build.py      # regenerate the model files (build.py is their source)
node docs/models/check.mjs        # SD Lab at ~/orchestra/sdlab, or SDLAB=<path>
node docs/models/render.mjs       # diagrams and charts: docs/user-story-diagrams.md
```

**To see the diagrams in SD Lab's editor** without touching your own SD Lab models:

```
mkdir -p /tmp/sdlab-stories/models
EXPORT=/tmp/sdlab-stories/models node docs/models/check.mjs
cd ~/orchestra/sdlab && SDLAB_HOME=/tmp/sdlab-stories uv run sdlab --port 8031
# open http://127.0.0.1:8031/?model=story-1-simple-task-designed
```

`EXPORT` writes every model and variant as its own model file: `story-1-simple-task-designed`,
`story-1-simple-task-manual`, `desk-designed`, and so on. Stocks are laid out in three bands: ours on
top, the interface in the middle, the company at the bottom (a second company row holds the stocks
work returns from).

The check validates every model and variant, simulates each one, assembles the desk model, and runs
the model-level acceptance checks. It writes `results.json`. It exits non-zero only if a **validity**
check fails. **Design gaps** (requirements the design doesn't yet meet) are reported, not hidden.

## Files

| File | What it is |
|---|---|
| `story-1-simple-task.json` | A simple task asked for by another team, from request to landed and announced. 22 stocks across our side, the interface, and the company. |
| `story-2-prod-command.json` | A request to run a production command: understanding, authority, context, decision, logging, follow-ups, and the prevention loop that makes such requests rarer. |
| `story-3-status-request.json` | A manager asks for status; a status page kept current, or research from scratch. |
| `story-4-reviews-given.json` | Teammates' review requests, and the goodwill that comes back. |
| `*.variants.json` | Other machine assignments for the same model: `manual` (today: everything on me), plus what-ifs (`rising` demand, `better-first-pass`, `manual-thorough`). A variant overrides fields of named flows. |
| `desk.couplings.json` | The declared effects one story's stocks have on another story's flows. The desk model is the four stories together, sharing my time, the agents, and the budget, plus these couplings. |
| `build.py` | The source of the model files: stocks, flows, machines, layout, variants, couplings. |
| `*.charts.json` | What each story's charts plot, as data: named **measures** (a stock, a sum of stocks, a flow's rate per week, a share of flows, a machine's hours, the agents' spend), and charts that pick a measure per variant. Written by `build.py`. |
| `../user-story-equations.md` | Generated: every stock's starting value and every flow's equation, effects, machine time and cost, per story. |
| `render.mjs` | Draws every story with SD Lab's own diagram renderer (`diagram.js`) into `svg/`, with the three sides as bands. Writes `../user-story-diagrams.md`: each story's diagram, Mermaid charts of the simulation (manual against designed), a Mermaid flowchart, its machines, crossings and checks. Also writes `diagrams.html`. |
| `lib.mjs` | Shared by `check.mjs` and `render.mjs`: loading, variants, the desk, the validator, the simulator, measures. |
| `check.mjs` | The model-level acceptance checks; with `EXPORT=<dir>`, also writes every variant as a model file. |
| `results.json` | The last run's results, leverage rankings, and every boundary crossing by story. |

## Conventions

- **Time unit:** a working hour (40 a week). Horizon: 26 weeks (1,040 hours), long enough for slow
  loops (learning, decay, trust, reputation) to show.
- **Feedback first.** Every model lists its named loops in a `loops` key:
  - an id;
  - reinforcing or balancing;
  - the stocks it runs through;
  - what it does.

  `render.mjs` prints them on the diagrams page. A chain of stocks with no loop through it isn't
  a model of anything dynamic.
- **Rates depend on stocks.** The success rate, how much I check, how fast reviewers respond, how
  often managers ask, how fast runbooks rot: each is a table effect of another stock's level. Those
  effects are the loops.
- **How effects bite in SD Lab.**
  - On a flow with machine time (`work` above 0), an effect changes the machine's speed.
  - On a flow with none (environment, or a program with `work: 0`), it changes the rate itself.
  - So outcomes and routing decisions (success or flaw, check or pass, catch or miss) are
    parallel environment or program flows whose rates carry opposite effects. The split moves
    with the system's state. Work that takes time (attempts, checks, reviews) runs on machines.
- **Machines are shared by every story:**

  | Machine | Kind | Capacity | Notes |
  |---|---|---|---|
  | `me` | person | 0.6 | About 60% of my working hours free for this work |
  | `analyst` | agent | 1 | |
  | `drafter` | agent | 1 | Everything it writes goes to my outbox |
  | `implementer` | agent | 2 | Two slots |
  | `orchestra` | code | 5 | Programs, no model calls |
  | `environment` | — | — | The company and its people. They aren't ours to schedule. |
- **The budget** is a stock refilled at $3 an hour (about $120 a week of the $190). Agent flows draw
  on it through co-flows (`uses`) and stop when it's empty.
- **Annotations.** Stocks and flows carry:
  - `side`: `ours`, `interface`, or `company`;
  - `crosses`, on flows that touch a company system;
  - `note`, the long description.

  SD Lab ignores keys it doesn't know.
- **Inputs.** Story 2 uses a measured input (`company_growth`, a ramp) to grow demand over 26 weeks.

## The models

| Model | Stocks | Flows | Loops | What it's about |
|---|---|---|---|---|
| Story 1, simple tasks | 30 | 41 | 8 | Agents that learn (or don't). Playbook against decay and overload; the capability trap; trust deciding how much I check; reviewer fatigue; debt; reputation bringing more asks. |
| Story 2, production commands | 24 | 31 | 7 | Prevention against rising demand; evidence and crises speeding adoption; runbooks learning and decaying; requesters learning the process; repeats coming back. |
| Story 3, status | 18 | 27 | 6 | Freshness; source hygiene and nudges; nagging that backfires; manager confidence against the micromanagement spiral; early warning of blocked projects. |
| Story 4, reviews given | 16 | 23 | 7 | Reciprocity; fatigue; coaching raising the team's skill; reviewer reputation; the agent's map of the code; comment quotas (Goodhart); escaped defects. |
| Desk | all of them | | | Shared time, agents and budget, plus declared couplings: my goodwill speeds reviews of my PRs; the team's skill raises how many flaws reviewers catch. |

## Where the numbers come from, and what is repeatable

The method for producing analyses like `user-story-diagrams.md` from a model, for any ask, is in
`../analysis-method.md`.

- **Authored, not derived.** Claude wrote by hand, in `build.py`, from what you described of your
  work:
  - every equation, starting value and input;
  - every variant;
  - every chart, and every measure behind a chart.

  None of it was fitted to data or discovered.
- **Running it is repeatable.** The simulation is deterministic (SD Lab's simulator, no noise), so
  `build.py` → `check.mjs` → `render.mjs` gives the same files every time. The diagrams page prints:
  - for every chart, the measure it plots and that measure's formula;
  - for every story, its starting values, the drivers from outside, and what each variant
    changes.

  `user-story-equations.md` lists every flow.
- **Authoring it again would not be.** Asked again, an AI would write different numbers and choose
  different charts. To make authoring repeatable, each number needs a recorded origin:
  - an assumption, with its reason;
  - a value from you;
  - a value fitted from history by a named method and data window.

  Fitting should be done by code (SD Lab's fit, or discovery), not by an agent. The agent's job
  becomes proposing structure, which you review. That is the next step, not done yet.

## Assumptions

All are estimates for planning. The structure (which stocks affect which rates, and with what
sign) is the claim. The numbers are placeholders to be fitted from GitHub, Jira and Slack history.

- **Demand:**
  - simple tasks start near 5 a week and rise with requesters' confidence;
  - command requests start at 2.4 a week and rise toward 7 as the company grows, less any adopted
    prevention;
  - managers ask about 4 times a week, scaled by their confidence and recent surprises;
  - review requests run 6–8 a week, scaled by my reputation as a reviewer.
- **Agent outcomes:**
  - at a 20-entry playbook, attempts are 55% sound, 20% hidden flaw, and 25% visible failure;
  - a good playbook moves that toward about 75/10/15, and an oversized one partly back;
  - debt pushes toward flaws.
- **Learning and decay:**
  - each failure, late finding or bug leaves lessons, and successes leave patterns;
  - the playbook halves in about six weeks without upkeep, faster when much is landing;
  - runbooks and the agent's code map decay more slowly.
- **Company side:**
  - checks plus AI review catch about 40% of flaws;
  - reviewers respond in about 24 working hours at one recent ping, slower with long queues;
  - reviewers catch 70% of flaws when fresh, much less when overloaded;
  - SAIL takes about 4 hours, and a quarter of runs fail as flakes.
- **Trust and confidence** move slowly up with good outcomes, and sharply down with late findings,
  bugs and surprises.

## Results (last run)

`node docs/models/check.mjs`: 26 validity checks pass, 7 design gaps. The full table is in
`results.json` and on the diagrams page. The behaviour the models produce:

| Story | Behaviour |
|---|---|
| 1 | **Learning beats decay.** Playbook 20 → 89 entries, and attempts going wrong 33% → 24%. Without learning: playbook rots to 1, 68% go wrong, debt doubles, the budget runs out 9 weeks sooner. |
| 1 | **Capability trap (gap).** Under a surge, the playbook peaks at 61 and falls to 29. With lesson capture protected it reaches 98. |
| 1 | **Limits to growth.** Requesters' confidence 20 → 77, and asks 5 → 12 a week, until the budget binds in week 23 and the backlog grows to 15 (gap). |
| 1 | **Trust.** From 30 to 87. Starting from blind trust dips to 68 and recovers. Escaped flaws stay under 0.4 per 100. |
| 2 | **Prevention bends the curve.** 2.8 requests a week at week 26, against 7.2 without prevention, with about 9 preventions in force. Runbooks 20 → 32, against 2.5 without updates. |
| 2 | **Incidents (gap).** 5% of commands cause one, against 11% today. |
| 2 | **Repeats.** 21 surprise repeats today; none designed. |
| 3 | **The spiral.** Without a status page: confidence 50 → 15, questions 4 → 25 a week, me 96% busy. With one: confidence 50 → 76, questions 4 → 3.3, and 95% of blocked projects noticed by me first. |
| 3 | **Nudging.** None or too many both leave sources rotten (hygiene 0, against 38 with moderate nudging). |
| 4 | **The code map.** Grows 30 → 71 and halves missed defects (12% against 29%). |
| 4 | **Comment quota.** Triples comments and cuts goodwill 43 → 24. Review volume is under my 8-a-week target (gap). |
| Desk | **Budget, not my time, is the limit:** about $125 a week wanted against $120 (gap). Reciprocity shortens my PRs' wait in review from 3.1 to 2.2 days. |

## What this says about the design

1. **Agents that learn are worth more than faster agents.** The playbook, runbooks, and code map
   are the stocks that move outcomes, and they decay. Their upkeep has to be a protected flow,
   especially under pressure. Otherwise the capability trap takes it.
2. **The binding constraints are outside my time:** the budget, the company's reviewers, and the
   company's adoption of prevention. The design's leverage is in what reaches them (fewer flaws,
   better evidence, timely reviews of others' work), not in raw agent speed.
3. **Trust and confidence are stocks with slow inflows and fast outflows.** Late findings and
   surprises are the expensive events. Early detection (my checks, the status page, early warning)
   pays for itself through those loops.
4. **Several "obvious" policies backfire through feedback:** nagging, comment quotas, and blind
   trust at high load. The models make that visible before trying them on real people.

## Proposed SD Lab extensions (found while writing these)

- **Named loops as a first-class part of a model** (`loops`), drawn on the diagram as polarity
  markers, and checked: does each listed loop actually close through the flows and effects?
- **`side` and `crosses` as first-class fields,** so the editor draws the boundary and lists
  crossings.
- **Variants** (machine assignments, initial values, what-ifs) as a model feature, not a separate
  file applied by `check.mjs`.
- **Declared couplings between models,** so several small models run as one.
- **Auxiliaries in the editor format.** Several effects here want a ratio or a sum (reviewer load
  across two queues, a share of stale items). The editor's effects read one stock, so the models
  use the closest single stock.
- **Leverage over parameters, splits and effect tables,** not only flow speed: the strongest levers
  here are effect strengths and decay rates.
