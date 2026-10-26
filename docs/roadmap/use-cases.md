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

## UC-1: the bakery (`~/orchestra-bakery`)

Run: `bin/bakery-ctl start`, 30 minutes, then `uv run orchestra sd discover --minutes 30`.

Expected stocks: orders waiting, baking, inspecting, on the shelf, accepting; customers in line,
customers waiting; bake queue, pass queue; the Yelp rating as a slow stock (or an auxiliary once
auxiliaries exist).
Expected flows: placed, assigned, baked, inspection passed and failed, picked up, accepted,
rejected, refunded, shelf expired, lease expired, cancelled by state; customers in and out of the
line; reviews posted.
Expected loops: demand and service (balancing, through the rating), rework (reinforcing while it
lasts, through remakes), leases returning work to the queue.
Forbidden: the weather series; `*_busy` flags as flows; takers/bakers free as stocks of orders.

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
