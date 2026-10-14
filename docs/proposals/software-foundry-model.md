# The software foundry model: stocks, flows, and what Orchestra shows

Status: proposal, 2026-10-14. Replaces the ticket-state "stocks and flows" map on the Agents
page. Sources: `docs/research/sd-software-models.md` (the published structures),
`docs/research/foundry-sd-claude.md` and `docs/research/foundry-sd-gemini.md` (two
independent answers to the same question).

## 1. What the foundry produces

Orchestra is a software foundry: AI agents are the machines, and the product is good
software. The ticket tracker is the work-order system of the foundry, not its output. A
ticket can reach DONE and the software still be worse. The map therefore shows what the
foundry holds and produces, with tickets appearing only as demand and as the owners of
work in progress.

Every published system-dynamics model of software development (Cooper's rework cycle,
Abdel-Hamid and Madnick, Madachy's defect flows, Ford and Sterman's phase model, the DORA
keys, Reinertsen's queues) reduces to one structure:

```
Work to do ──progress──▶ Work done
                           ├── really done                       (fraction correct and complete, FCC)
                           └── undiscovered rework ──discovery──▶ Known rework ──rework──▶ Work to do
```

Three parameters govern everything: productivity (work per unit effort), FCC (the share of
work that is right the first time), and the discovery delay (how long a defect stays hidden).
Every named loop in the literature changes one of those three. Orchestra's job on this page
is to measure those three and the stocks around them, and to show which agent sits on which
flow, so the operator can see where to add an agent or a binding.

## 2. The stocks

A stock is a quantity the foundry holds that accumulates and drains. Each has a unit, an
inflow, an outflow, and one or more estimators (section 4). The built-in stocks are the
software foundry's defaults; a project in another domain declares its own (section 5).

| # | Stock | Unit | What it is | Inflow | Outflow |
|---|-------|------|------------|--------|---------|
| D | **Demand** | tickets | Work ordered and not started: OPEN tickets in open milestones, plus BLOCKED. | ticket_created, send-backs that reopen | start (OPEN → IN_PROGRESS), cancel |
| W | **Work in progress** | changes | Ticket branches with commits ahead of main. Sub-readings: being worked, awaiting review, awaiting the gate. | start | land, send back, restart |
| K | **Known rework** | changes | Changes a reviewer or the gate sent back, with the classified cause. | review rejection, gate rejection, gate conflict, regression on main | fixed (next READY_FOR_REVIEW) |
| U | **Undiscovered rework** | changes | Defects in W and L not yet found. Hidden; inferred (section 4). | injection = progress × (1 − FCC) | discovery |
| L | **Landed software** | commits | Commits the gate put on main, with diff size. The product. | gate_landed | fix commits that touch recent lines (churn) count as rework, not new product |
| B | **Working build** | builds | The staging build the acceptance suite ran against, and whether it is up. | staging_deployed | staging_failed, superseded |
| T | **Verified behaviour** | tests | Tests on main: unit and acceptance, passing, failing, skipped, from the last gate run. Test capital. | tests added per landed change | tests removed or skipped |
| R | **Environment resources** | documents | What the worker and reviewer read before working: AGENTS.md, README, team docs, roles, decided lessons, team tools. Measured by count, line budget, and freshness. | lessons decided, docs changed | pruned, over budget |
| C | **Agent capacity** | agent-hours/day | Time agents spend, by activity: implement, review, fix (rework), improve (devex), plan. From sessions. Restarts are lost capacity. | the capacity ceiling | turns |

U is the stock the whole literature says matters most and the one no log records. The
foundry shows it as an estimate with its uncertainty, never as a count.

## 3. The flows, the machines on them, and the loops

Flows are rates per day over the window. A machine (an agent or Orchestra itself) is a valve
on a flow: its in-use/capacity and cycle time set the flow's rate.

| Flow | From → To | Machine | Measured by |
|------|-----------|---------|-------------|
| start | D → W | orchestra (pickup) | OPEN → IN_PROGRESS |
| implement | effort → W | worker | commits on the ticket branch; READY_FOR_REVIEW arrivals |
| discover in review | U → K | reviewer | IN_REVIEW → REJECTED, with cause |
| discover at the gate | U → K | merge gate | gate_rejected, gate_conflict, gate_base_broken, with stage |
| discover after landing | U → K | acceptance run, smoke test, humans | a failing test on main that passed before; a bug ticket citing a landed commit |
| fix | K → W | worker | REJECTED → IN_PROGRESS … READY_FOR_REVIEW |
| land | W → L | merge gate | gate_landed |
| deploy | L → B | orchestra | staging_deployed |
| add tests | effort → T | worker, qa agents | tests on main after vs before each landing |
| improve | K → R | environment keeper, devex | lessons decided; doc commits in `.orchestra/` and agent-facing files |
| restart | W → D | orchestra (turn limits) | IN_PROGRESS → OPEN; lost capacity in C |

The parameters, each a reading on the page:

- **FCC, first pass.** Changes that reach READY_FOR_REVIEW and land without a send-back, over
  changes that reach READY_FOR_REVIEW. (Cooper and Mullen's survey: 0.68 commercial average.)
- **FCC, landed.** Landed commits not later touched by a fix within the discovery window, over
  landed commits. A lower bound on the true FCC until the cohort is older than several τ.
- **Discovery delay τ.** Median time from the commit that introduced a defect to the event that
  found it. First estimate: READY_FOR_REVIEW to the rejection; better: `git blame` of fix
  commits on main back to the introducing commit.
- **Discovery split.** Where defects are found: worktree tests, review, gate, staging, after.
  The histogram shifting left is the signal that verification is working earlier.
- **Rework share.** Fix capacity over total capacity in C. Repenning's firefighting threshold
  is roughly a third.
- **DORA keys** as readings of the same model: landing frequency (land flow), lead time
  (commit to deploy), change failure (gate rejections + staging failures over gate runs), time
  to restore (staging_failed to the next staging_deployed).

The loops, with polarity from the literature and the signal that shows each one working:

| Loop | Structure | Signal |
|------|-----------|--------|
| B1 defect removal | K → fix → K falls | fix round trip short and stable |
| B2 discovery pull-forward | T ↑ → defects found at the worktree or review, not the gate | discovery split moving left; τ falling |
| B3 capacity limit | W ↑ → pickup paused / capacity lowered | W bounded; queue ages not rising |
| B4 capability | K (by cause) → improve → R → FCC ↑ → K ↓ | FCC first pass rising after lessons land; same cause not recurring |
| R1 firefighting | rework share ↑ → less improve and add-tests → U ↑ → K ↑ | rework share rising week on week |
| R2 debt drag | churn ↑ → productivity ↓ → pressure → FCC ↓ | landed per agent-hour falling while diff size is constant |

B4 is the devex loop. It closes through the world: a lesson becomes a doc, a doc becomes a
worker's context, and the effect appears as a lower send-back rate for that cause, delayed
by however long it takes a lesson to land. Orchestra draws it as a loop only when the
devex agents' edges are observed (`eventgraph` latent/observed rule), and measures it by the
cause-specific send-back rate before and after each lesson.

## 4. Estimators: how a stock gets a number

Finding measurable stocks is the hard part of every system-dynamics model. Orchestra uses
three kinds of estimator and shows them side by side when more than one exists.

1. **Inside the model.** Integrate the flows the log already records: level = Σ inflow −
   Σ outflow, which is how U is estimated (U ≈ τ × discovery rate, Lyneis and Ford's
   first-order discovery; the discovered rate is a lower bound on injection). This needs
   nothing but events and is exact for D, W, K.
2. **Outside the model, deterministic.** A probe: a command that prints a number, run on an
   interval, in the team's space or the repo (the existing `Prober`). Also event counts and
   git queries. Used for L, B, T, R, C.
3. **Outside the model, by judgement.** An AI judge with a pinned model and rubric. To contain
   volatility: the rubric asks for a class from a fixed list, never a magnitude; the judge
   runs N samples at low temperature and the reading is the mode (or median for ordinal
   classes) with the agreement recorded; comparisons ("is this better than last week's")
   are preferred over absolute ratings; a change of model, prompt or rubric starts a new
   series and the chart shows the break. Used for cause classification of send-backs
   (already done by devex), lesson applicability, and doc accuracy.

Every reading is an event, `stock_measured` {stock, estimator, value, samples, agreement,
window}, so the series is in the log like everything else, and a stock's "perceived" value
is the smoothed series (Sterman's perceived-vs-actual pair), not the last sample.

## 5. Declared stocks

The stocks above are the software foundry's defaults. A Lab produces research a Product
Owner consumes; a devex team produces resources the workers consume; a non-software project
produces something else entirely. So stocks are data, like roles, agents, and teams.

```jsonc
// .orchestra/stocks/<name>.json
{
  "name": "lessons",                     // snake_case, unique
  "unit": "documents",
  "team": "devex",                       // owner; null for built-ins
  "description": "Decided lessons the worker and reviewer read before a ticket.",
  "inflows":  ["lesson_decided"],        // event types (declared by the team) or built-in types
  "outflows": ["lesson_retired"],
  "estimators": [
    {"kind": "probe", "command": "ls .orchestra/spaces/devex/lessons/decided | wc -l", "every": "1h"},
    {"kind": "events", "level": true},   // Σ inflows − Σ outflows since the stock was declared
    {"kind": "judge", "rubric": "...", "classes": ["accurate", "stale", "wrong"], "samples": 5, "model": "..."}
  ],
  "consumers": ["worker", "reviewer"],   // agents that read it; drawn as an input to their valve
  "producers": ["environment_keeper"]    // agents that fill it; drawn as a flow into it
}
```

Rules, enforced by the store like the rest of the org model:

- Built-in stocks live in `orchestra/foundry.py` (data, like `roles.py`) and cannot be
  deleted or renamed; a project may add estimators to them.
- Only the Supervisor creates, changes, or deletes a declared stock (`create_stock`,
  `update_stock`, `delete_stock`, `list_stocks` in `api_org`), in conversation, exactly as
  teams and agents are made. The org guide gets a section on when to declare one: when a
  team produces something another agent consumes, or when a loop's purpose names a quantity
  the map cannot otherwise show.
- A declared stock's inflow and outflow event types must be declared (by a team's `emits`)
  or built in. Its probes run under the owning team's space like team probes.
- Deleting a stock does not delete its measurements; the series stays in the log.

Discovery of candidate stocks is a Supervisor task, not code: the loop detector already
reports loops the Supervisor has not named, and the same wake-up can list event types and
team spaces that no stock names, so the Supervisor can propose one.

## 6. What the page shows

The "Stocks and flows" section of the Agents page becomes the foundry map:

1. **Headline readings.** FCC first pass, discovery split (a five-bar strip: worktree,
   review, gate, staging, after), τ, rework share, landed per day, lead time, change failure,
   time to restore. Each with its window and a tooltip stating the exact estimator.
2. **The map.** One aging chain left to right: Demand → Work in progress → Landed → Working
   build, with Known rework beneath feeding back into Work in progress, and Undiscovered
   rework drawn dashed between Work in progress and Landed with its estimate and range.
   Verified behaviour and Environment resources sit above as capability stocks with arrows
   into the valves they strengthen (T into the reviewer and gate valves, R into the worker and
   reviewer valves). Agent capacity is a strip showing the split by activity. Machines are
   valves on flows with in-use/capacity and cycle time. Declared stocks appear where their
   producers and consumers put them. Hovering a stock, valve, or loop isolates it; clicking an
   agent opens it.
3. **The loop table.** B1 to R2 plus every loop the Supervisor named, each with its signal's
   current reading and direction over the window, and the literature's "what to add" hint
   when the signal is adverse (most defects caught at the gate → add verification before it;
   rework share above a third → reduce intake before adding producers; a cause recurring
   after its lesson → the lesson is not reaching the worker).
4. **Drill-down.** The ticket-state pipeline with its transition rates, behind a disclosure,
   for reconciling the numbers against the tracker.

The ticket counts per state no longer appear on the map; they are the drill-down.

## 7. Data Orchestra already has, and what it must add

Already in the log or store: every ticket transition with from/to; gate runs with outcome
and tickets; staging deploys and failures; sessions with kind, duration, and turn outcomes;
the classified causes the devex team files as notes; team probes.

To add, in order:

1. `loopmetrics` computes the stocks D, W, K, C, the flows, FCC first pass, τ (first
   estimate), discovery split, rework share, and the DORA keys from the log. `foundry.py`
   holds the built-in stock definitions.
2. The gate records, per run, the test counts (collected, passed, failed, skipped) per stage,
   and the landed diff size, so T and L have readings without re-running anything.
3. A `git` estimator (commits ahead of main per worktree for W; fix-commit blame for FCC
   landed and τ) run by the Prober with the repo as cwd.
4. Declared stocks in `RepoOrgStore`, the four Supervisor tools, `stock_measured` events,
   and the judge estimator (model pinned, N samples, mode and agreement).
5. The page, as in section 6, with the ticket pipeline as the drill-down.

## 8. Open questions

- Whether U should be shown at all before τ has a git-based estimate; a wrong number in the
  most important box is worse than a dashed box saying "not yet estimable".
- The window: 24 hours is right for flows in the demo project, but FCC landed and τ need the
  age of the cohort, so they are reported for the cohort older than 2τ with the cutoff shown.
- Whether the judge estimator runs under the Prober (a command that calls a harness) or as an
  ad hoc agent with the `stocks` tool; the latter keeps "Pi's session file is the only
  transcript" true.
