# The use cases and the models they must yield

A use case is a system we can run, whose structure we know, and the model Orchestra must discover
from its metrics alone. Each one is an acceptance test for discovery and for the metrics the
machines write. The workflow `.claude/workflows/model-acceptance.js` runs a case, discovers,
judges against the expectations below, and has three skeptics try to refute every pass.

What "meaningful" means here comes from the owner's judgement of earlier models
(`docs/HANDOFF-2026-10-25.md`, `docs/analysis-method.md` §6, `docs/proposals/system-dynamics-core.md` §3):

- Stocks are conserved levels that are sensed, not reported; each is paired with where its
  contents go (its opposite or its sink).
- Flows are rates that move stocks; a flow measured twice (by the machine that did it and by the
  event counter) is one flow; six instances of one machine are one flow.
- Noise is left out, with the reason recorded.
- Every equation records its origin (fitted, discovered, declared) and the data it was fitted on.
- The structure can carry the feedback loops the system is known to have; a conveyor belt of
  states with no loop is not a model of a system.
- Where the rules are ours, the fitted rates agree with the rules within the noise the window
  allows (the bakery: balances exact, main rates within ~10%).

## UC-0: the curious observer (the north-star story, the owner, 2026-10-26)

Someone is curious about a thing or a place. They point a handful of measurement scripts at it
(weather, tides, a river, power, flights, their own machine, anything with numbers) and Orchestra
gives them a system dynamics model of how it works now: what accumulates, what flows, what drives
what. Then they act on it:

1. **Observe.** Collectors only ([[collect]] scripts and [[scrape]] endpoints; no library to
   import). Discovery proposes stocks, flows and drivers, every equation with its origin.
2. **Find causes, not correlations.** Most of what they collect will be noise that happens to move
   together. Discovery must say so, and the causal claims it does make should be tested by
   **impulse injection**: a machine nudges one quantity on purpose, at known times, and the model
   checks whether what it claims depends on that quantity responds (the intended-effect, null and
   unexplained-change tests of `docs/rationale/lifted-models.md` §3).
3. **Change the system.** They add machines that act on the environment. The first is a recurring
   AI agent loop with a prompt that says what to change; it reads the metrics and the model and
   decides what work to do or what program to write (an AI agent as a universal machine: natural
   language turned into automation).
4. **Verify.** The fitted equations show whether the machine's flow has the effect intended, era
   by era; a machine whose effect does not show is a hypothesis that failed.

The live sample's telemetry (58 series from 23 sources: local machine, Boulder weather and air,
tides, space weather, earthquakes, river flow, flights, Wikipedia, Hacker News, bitcoin, power
grids, the London Tube) is the first instance of step 1; almost all of it is noise on purpose,
which makes it a test of whether discovery is fooled.

Its second half, influencing and replacing (the environment as an actor, ghost machines inferred
from fitted rates, leverage points, shadow-and-swap, distilling an agent into a program, and how
many flows one machine should own), is `docs/proposals/environment-and-ghost-machines.md`.

Built for it on 2026-10-27: each series' real resolution respected by discovery, and levels no
counters balance taken for stocks when the other series explain their net flow and the form
survives its refutations (`sd/netflow.py`: it must beat a steady trend in time as well as a
constant, predict the held-out half of the window, explain at least 40% of the level's changes,
and lose most of its fit when its driver is read a quarter of the window earlier or later). On the
live telemetry, replayed over 4 h and 6 h at 5 s, **no level survives as a stock by its net
flow**; every one stays an input with its reason. The first version took five for stocks, and
each was refuted:

- the San Francisco tide, "driven" by California's power demand (R² 0.81 over 4 h, 0.87 over
  6 h): a steady trend in time explains its changes as well (R² 0.79, 0.87); the demand stands in
  for the clock, and read two hours off it fits about as well;
- Claude's processes, "driven" by the host's processes: they may be a part of that total (counts
  in one unit, never above it, swinging no wider), so neither may drive the other; its best other
  form (CPU use, R² 0.19) predicted the held-out half no better than a simpler one;
- the machine's load relaxing toward its CPU use: it explains only 12% of the load's changes;
- a repository's disk use relaxing toward a level (R² 0.43 over 6 h): read at its real
  resolution (it changes about every five minutes, though polled every minute), nothing explains
  its changes better than a constant;
- in the bakery, the shelf's mean age, "driven" by demand (R² 0.48) or by the Yelp rating
  (R² 0.38): an average summarises what is on the shelf and holds nothing.

A net-flow stock that does survive is still only a correlation: its driver is what fitted the
level's changes, and nothing has moved the driver to see the level answer. The Dynamics page says
so on every such flow ("fitted from correlation; untested"); the impulse tests of H1 are what
would test it. What it needs that is not built: an impulse-injection machine and the tests that read it
(H1–H2), the recurring agent loop as a machine any user can declare (H2), the model readable by
agents (H2).

## UC-1: the bakery (`~/orchestra-bakery`)

Run: clear the bakery's runtime state (`run/board.json`, `run/yelp.json`, `run/shelf`, `run/pass`),
`bin/bakery-ctl start`, 60 minutes, then `uv run orchestra sd discover --minutes 60`.
(With the default two takers the customers' line empties within a second and never becomes a
stock; a run with `TAKERS=1` is a separate case for the line.)

Expected stocks: orders waiting, baking, inspecting, on the shelf, accepting; customers waiting.
Expected inputs: the Yelp rating, read by the arrivals flow (it is a mean of recent reviews, not
a conserved quantity, so it is an input until the model has auxiliaries).
Expected flows: placed, assigned, baked (baking → inspecting), inspection passed (inspecting →
on shelf) and failed, picked up, accepted, rejected (accepting → waiting, the board's own
counter), refunded, lease expired, cancelled by state, once each has at least five events in the
window.
Expected loops: rework (failed inspections and returns remake orders) and leases (a baker who
wanders off returns the order to the queue) representable in the structure; demand and service
representable only as far as "rating drives arrivals" (closing it through waits and reviews is
an SD Lab strategy's job, not conservation's).
Forbidden: the weather series; `*_busy` flags as inputs or drivers; takers or bakers free as a
stock in the orders network; one flow per instance; an unmeasured flow on an exactly balanced
stock; duplicate flow ids; the same level as two stocks.

Not expected after the 2026-10-26 runs (judged "expectation wrong" or "the bakery's own"):
the expo's bake and pass queues (the board's states seen again from the dispatcher, with no
outflow counter of their own); shelf expired (unreachable under the bakery's rules); reviews
posted as a flow (it moves no measured level). The bakery's own measurement gaps, for the owner
(decisions D15): one `bakery_offers_total` for both phases; no `customers_called_total`, so the
line's outflow is only Orchestra's event count; `customer_demand_per_min` publishes the model's
own demand formula as a gauge.

Results so far: baseline 4/10 (2026-10-26 08:00, invented flows, flag inputs, duplicate ids,
a twin stock); after the first discovery fixes 6/10 (10:30; the five board states exact, nine
transitions right, remaining: a spurious takers-free stock from a stuck balance search, the
rating not read by any flow, the rejected flow split through outside, stale values before a
restart losing stocks in the host's scheduled runs). Reports under the session scratchpad
`split/model-acceptance/`. On 2026-10-27 (levels with no counters, series resolution) the round-6
export keeps its nine counted stocks and gains one by its fitted net flow, the shelf's mean age
(an average of ages, read off the demand or the rating): not expected, and to be judged; the
weather stays an input (its fit does not carry from one half of the hour to the other).

## UC-2: the task system with programs (`~/orchestra-tasking/demo`)

Run: the demo's one command with tickets created on a cadence (one every 1–2 minutes for 20
minutes), the shell worker and the program reviewer serving.

Expected stocks: tickets OPEN, IN_PROGRESS, READY_FOR_REVIEW, IN_REVIEW, REJECTED, BLOCKED,
DONE (`tasks_tickets{state}`).
Expected flows: one per transition (`tasks_ticket_transitions_total{from,to}`), created
(`tasks_tickets_created_total`); merged across the scheduler's and the machines' sources.
Expected loops: rejection returning work to the worker; capacity (workers, reviewers) limiting
the in-progress and in-review levels (a capacity-limited form, H1).
Forbidden: a flow per machine instance; the operator's capacity setting as a stock.

## UC-3: the task system with agents and a program (`~/orchestra-agents/demo`, the sample project)

Run: the demo's one command with real Haiku as reviewer, Supervisor and Coordinator resident, the
shell worker as worker; a dozen tickets over 20–30 minutes including one rejection and one
BLOCKED ticket.

Expected: everything in UC-2, plus stocks of agents at work by role (`agents_working{role}`) and
flows of turns started and finished (`agent_turns_*_total{role}`); the reviewer's turns move
IN_REVIEW to APPROVED/REJECTED; the Coordinator's attention turns follow BLOCKED.
Expected event map: `task_scheduler` publishes `task.assigned`/`task.released` and listens for
`task.accepted`/`task.working`/`task.reported` and the requests; `worker/1` (package tasks' demo
program) and `reviewer/1` (package agents) answer; `agents` (the host) listens for
`task.assigned`, `task.released`, `task.attention_needed`; supervisor and coordinator are
continuous/scheduled machines of package agents.
Forbidden: agent sessions as stocks of tickets; the host's heartbeat as a flow.

## UC-3b: a sample with a domain stock of its own (not yet built; the next case to score)

The sample's stocks are ticket states and the reviewer's sessions: the pipeline measured by
itself. Orchestra's aim is the loops between a project's own domain and the process that
develops it, and no such loop can appear until a sample's tickets accumulate something the
project measures. The next sample writes one domain series of its own (a count of files, tests
or records the tickets' work adds to), so a domain stock is filled by the pipeline's flows.

Run: UC-3's command on a target whose tickets each add to that series, with the series written
by the target's own program (a machine of the sample, not of either plugin).

Expected: UC-3's stocks and flows, plus one domain stock balanced by a counter the tickets'
work moves, with the flow from DONE (or from the worker's reports) into it; the model's
machine table names the sample's own program on that flow.
Expected loops: the first between the domain and the process: the domain stock read by a flow
of the pipeline (a planner creating tickets while the count is below a goal), once a planner
is written to do that.
Forbidden: the domain series as a tally of ticket events (it must measure the project, not the
pipeline).

This is the next use case the model-acceptance workflow should score.

## UC-4: code mode (`~/orchestra-tasking` in-process e2e, extended to a run)

Run: the task system with `work = "code"`, the fake machine (or the agents' fakes), a repository
with a unit command; tickets including one the gate rejects.

Expected stocks: UC-2's plus APPROVED and MERGING; gate runs in flight.
Expected flows: the gate's landed and rejected; MERGING back to REJECTED.
Expected loops: the gate's rejection re-engaging the worker.

## UC-5 onward: the user stories

`docs/user-stories.md` and `docs/user-story-equations.md` hold stories 1–4 with their stocks,
flows and loops, and stories 5–21 with the structure each is expected to have. They become use
cases here when a story runs against fakes of the company systems (H3). Their expected
structures are already written; what is missing is the running system that produces the metrics.

## Adding a case

A case needs: a start command, a stop, a duration, the repository that writes its metrics, and
the expectations in the four lists above. Expectations are structure, not numbers: a case that
only passes with a tuned rate is reported as a gap, not fixed to pass.
