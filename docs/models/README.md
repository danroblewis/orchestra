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
| `render.mjs` | Draws every story with SD Lab's own diagram renderer (`diagram.js`) into `svg/`, with the three sides as bands. Writes `../user-story-diagrams.md`: each story's diagram, Mermaid charts of the simulation (manual against designed), a Mermaid flowchart, its machines, crossings and checks. Also writes `diagrams.html`. |
| `lib.mjs` | Shared by `check.mjs` and `render.mjs`: loading, variants, the desk, the validator, the simulator, measures. |
| `check.mjs` | The model-level acceptance checks; with `EXPORT=<dir>`, also writes every variant as a model file. |
| `results.json` | The last run's results, leverage rankings, and every boundary crossing by story. |

## Conventions

- **Time unit:** a working hour. 40 a week. Horizons are 160 (four weeks), or 480 (twelve weeks)
  for story 2's prevention loop.
- **Machines are shared by every story:**

  | Machine | Kind | Capacity | Notes |
  |---|---|---|---|
  | `me` | person | 0.6 | About 60% of my working hours free for this work |
  | `analyst` | agent | 1 | |
  | `drafter` | agent | 1 | Everything it writes goes to my outbox |
  | `implementer` | agent | 2 | Two slots |
  | `orchestra` | code | 5 | Programs; no model calls |
  | `environment` | — | — | The company and its people. They aren't ours to schedule. |

  A flow's `work` is machine-hours per item. A machine with too much work shares its capacity
  across its flows, so everything it runs slows down.
- **The budget is a stock.** It is refilled at $3 per working hour, about $120 of the $190 weekly
  total. Agent flows draw on it through co-flows (`uses`), so they stop when it's empty.
- **Annotations.** Stocks and flows carry `side` (`ours`, `interface`, `company`). Flows that
  touch a company system carry `crosses` (which system, read or write, and whether it goes
  through my outbox). Some carry a `note`. SD Lab ignores keys it doesn't know. These are proposed
  extensions (below).
- **Information stocks.** `t_nudges` (recent pings) and `r_recent` (recent reviews given, standing
  in for goodwill) aren't work. They act on flows through table effects.

## Assumptions

All are estimates for planning, to be replaced by fitted values from GitHub, Jira and Slack
history.

| Assumption | Value | Where |
|---|---|---|
| Simple-task requests | 6 a week (0.15/h); 10 a week in `rising` | `t_arrive` |
| My time per simple task, designed | 0.25 h collecting requirements + about 0.5 h of approvals | `t_collect`, approvals |
| My time per simple task, manual | About 10 h across research, ticket, code, tests, PR, fixes, pings, replies, SAIL, Jira, Slack | `manual` variant |
| Agent hours and cost per task | Research 0.5 h/$1.50; ticket 0.2 h/$0.50; implementation 2 h/$6; verification 0.5 h/$1.50; each fix round 0.5–1 h/$1.50–3 | `work`, `uses` |
| Internal rework | 25% sent back by internal verification | `t_verify` split |
| Company PR checks | 1 h; 15% fail | `t_checks` |
| Company AI review | 0.5 h; comments on 50% | `t_bot` |
| Human review | 16 working hours mean first response with one recent ping, 0.6× speed with none; 40% request changes | `t_review` |
| SAIL | 4 h; 30% fail; two thirds of failures are known flakes | `t_sail`, `t_triage` |
| Production command requests | 2 a week, falling as prevention is adopted | `p_arrive` |
| Prevention adoption | About two working weeks in company review | `p_adopt` |
| Status | 60 tracked items; 5% go stale each hour; managers ask 4 times a week; 1.5 h to answer from scratch, under 10 minutes when current | story 3 |
| Review requests to me | 8 a week; 0.4 h each with a brief, 0.75 h without | story 4 |
| Reciprocity | Reviews given recently speed my PRs' reviews by up to 1.4× | `desk.couplings.json` |

## Results (last run)

18 validity checks pass. 3 design gaps.

| Check | Result |
|---|---|
| **Manual reproduces today** (1.1, D.1) | I'm 100% busy, work waiting for me grows from 9 to 55 items in four weeks, and 4 of 24 simple tasks are delivered. This matches what you described, which is the face-validity test. |
| **Designed, story 1** | 22 of 24 delivered, 0.94 h of my time each, 22% of my free time. |
| **Designed, story 2** | Full due diligence at 0.70 h of my time per request, against 5.26 h doing it all myself and 2.87 h for today's shortcut (which skips root cause and prevention). Three preventions adopted in twelve weeks; requests fall from 2.0 to 1.4 a week. |
| **Designed, story 3** | 0.21 h per answer against 1.72 h. |
| **Designed, desk** | Everything together uses 46% of my free time, with nothing piling up. |
| **Gap 1.5: cost** | $22 per simple task against a $20 target. |
| **Gap 1.6: turnaround** | 5.2 working days against 4. 90% of work in progress sits in company stocks (review, checks, SAIL). |
| **Gap D.4: budget** | The four stories want $150 a week against a $120 share. The budget becomes the binding constraint by week four. |
| **Info 1.6b: better first pass** | Fewer rounds at each boundary (internal rework 10%, AI review comments 35%, change requests 25%) gives $16 per task and 4.3 days. This is the largest lever on both gaps. |
| **Info: leverage** | Making agent flows 10% faster changes nothing: they aren't the bottleneck. Human review is the largest lever, then SAIL and checks. In the desk, the budget comes first. (Leverage also ranks more demand as "more delivered", which is true and useless.) |
| **Info D.5: reciprocity** | Reviews given lift delivered simple tasks from 21 to 22: real but small at these assumptions. |

## What this says about the design

1. **Agents remove the overload, not the wait.** My time per task falls tenfold, but turnaround is
   set by the company's side. The four-day expectation can't be met by faster agents, only by fewer
   round trips across the boundary and faster human review.
2. **Iterate inside, cross once.** Every crossing back from the company (a failed check, an AI
   review comment, a change request, a SAIL failure) costs a company delay plus agent money. First-
   pass quality at our side is worth more than agent speed.
3. **The budget binds before my time does.** With agents carrying the work, dollars are the
   constraint. Cheaper steps (programs instead of agents), fewer rounds, and choosing which
   requests get the full treatment are the levers.

## Proposed SD Lab extensions (found while writing these)

- **`side` and `crosses` as first-class fields,** so the editor can draw the boundary and list the
  crossings.
- **Variants as a model feature:** named machine assignments and what-ifs of one model. Today they
  live in a separate file, applied by `check.mjs`.
- **Declared couplings between models,** so several small models can run as one without being
  merged by hand.
- **A busy-based overload measure.** The editor's machine "load" (asked ÷ capacity) is very large
  for flows whose rate is `available`, so it doesn't indicate overload. Busy share plus the levels
  of stocks a machine drains does.
- **Leverage over parameters and splits,** not just flow speed: the strongest levers here
  (the share of PRs needing changes, SAIL failure rate) are splits, which the 10%-faster test can't
  vary.
