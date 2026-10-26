# Orchestra: the long haul

This folder is the plan for the program as a whole: Orchestra (this repository) and the packages
that use it. It is written to be executed by someone who was not in the room: each horizon says
what is built, how it is judged, and what stops it. The other files here are the parts a plan
refers to again and again: the use cases and the models they must yield ([use-cases.md](use-cases.md)),
how work is reviewed ([reviews.md](reviews.md)), and the decisions only the owner can make
([decisions.md](decisions.md)).

The design itself is `SPEC.md`; the rules are `AGENTS.md`; the reasons are `docs/rationale/`;
the proposals, built and unbuilt, are `docs/proposals/`. This plan does not repeat them.

## The goal, in the owner's words

"There is one system, and one system dynamics model of it." Orchestra is "system-dynamics-first,
now and permanently. It isn't a task manager." Its main use is "to find the feedback loops between
the target's domain and the processes used to develop it." The job it serves is the owner's: to
"meet the expectations of the people who judge my work" while automation "never quietly takes
over the part that makes up my identity." What persuades their managers is "the simulation
charts": a model whose numbers show where they came from.

## What exists (2026-10-26)

| Repository | What it is | State |
|---|---|---|
| `~/orchestra_2` (GitHub `danroblewis/orchestra`, public) | The platform: event bus (CloudEvents), metrics store, one versioned system dynamics model discovered from metrics (`orchestra/sd`, strategies from SD Lab in `orchestra/sdlab`), bootstrap host, web UI (Core, Dashboard, Machines, Dynamics), plugin interface | Empty of machines since 2026-10-25. Unit tests plus the bus and metrics conformance suites; discovery reworked in four rounds on 2026-10-26 (see use-cases.md) |
| `~/orchestra-tasking` (private) | Task management as a plugin: tickets, milestones, a scheduler that offers work on the bus, leases, the merge gate and worktrees for code, staging, probes, requests from planners, the Tickets page and Tasks panel | Split from Orchestra 2026-10-25; the agents left it 2026-10-26 |
| `~/orchestra-agents` (private GitHub `danroblewis/orchestra-agents`) | AI agents as machines: Supervisor, Coordinator, worker and reviewer roles, teams, the harnesses for Pi, Claude Code and Codex, transcripts, the Agents page | New 2026-10-26 |
| `~/orchestra-bakery` (local) | A bakery built like a ticket system, to test discovery from the outside | Discovery finds its balances and main rates |

The split follows one rule, from `AGENTS.md`: Orchestra knows no tickets, tasks or AI; machines
are outside it and known by observation; packages label, they never separate the one model.

## Horizons

Each horizon has a definition of done that a program or a reviewer can check, and a stop rule.
Horizons overlap only where the text says so.

### H0: the split is finished (this week)

Done when:
- The three repositories are clean under the subtraction audit ([reviews.md](reviews.md) §4):
  no concept lives where it does not belong; every file is justified.
- Each plugin has a demo in its repository that one command starts, and an end-to-end test that
  starts a real `orchestra web` with the plugin installed and drives it over HTTP.
- The task system's demo runs with programs only. The agents' demo runs a Haiku reviewer and a
  program worker on one queue.
- The sample project (the agents' demo, run for real) yields the model in
  [use-cases.md](use-cases.md) §UC-3 and an event map a person can read.
- Each repository's SPEC, AGENTS and README describe what exists, point at each other, and the
  bus contract is documented once per repository (`tasking/assignments.py` and
  `orchestra_agents/protocol.py`).
- `main` is fast-forwarded to the work; the private repositories are pushed.

Stop rule: anything not needed for the above waits. In particular, no launcher, no ingestion
layer, no new ticket states, no change to rule 9.

### H1: the model is trustworthy on known systems (next two weeks)

The owner rejected earlier models as "conveyor belts without dynamics" and for "hiding where
numbers came from." This horizon makes discovery earn trust on systems whose structure we know.

- The model-acceptance suite ([use-cases.md](use-cases.md) §UC-1 to §UC-4) runs as a workflow
  and passes: every expected stock a stock, every expected flow one flow, instances merged,
  noise left out, origins recorded.
- Discovery follow-ups in the owner's order (`docs/HANDOFF-2026-10-25.md`): eras; auxiliaries;
  explicit counter/gauge typing; one stock measured by two series; a flow-aware layout; then
  capacity-limited forms.
- The Dynamics page shows, for every stock, measured against simulated against projected, and for
  every equation its origin and the data it was fitted on. "No chart without a check behind it."
- The analysis rubric (`docs/analysis-method.md` §6) is applied to the sample's model by a second,
  independent run before it is called meaningful.
- Version churn is bounded: a rediscovery that changes nothing of substance makes no new version.

Stop rule: if discovery cannot pass UC-1 (the bakery) and UC-2 (the task system with programs)
after the listed follow-ups, the owner decides between a designed skeleton and discovery-first
([decisions.md](decisions.md) D4) before anything else is built on the model.

### H2: the agents are ordinary, measured machines (weeks 3–4)

- Agent usage and cost are events and series (tokens, dollars, turns, wall time per role), so the
  model can carry the "Agent budget" stock the user stories need.
- A verifying agent is separate from the agent that did the work ("an agent's word counts only
  when a separate agent verifies it").
- A machine that is a person is decided ([decisions.md](decisions.md) D1); until then humans act
  only through the Supervisor.
- Team probes, schedules and wake-ups are observable as machines' modes on the Machines page.
- The Supervisor can read the model (the model tools proposed in `docs/proposals/empty-orchestra.md`
  §10) and nothing else changes it.

### H3: the first real user story (weeks 5–8)

Story 1 (`docs/user-stories.md`: a simple task for another team) runs end to end against fakes
that speak each company system's real protocol, with the task system and the agents as the
machines. The model carries the stocks in `docs/user-story-equations.md`; the gaps the stories
record (1.4, 1.8, 1.11) are reproduced or refuted on the measured system, never tuned away.
The company boundary is crossed only through connectors and the outbox; nothing speaks as the
owner without an unedited-approval run behind it.

### H4: the coupled model (after H3)

The target system's model (from Prometheus or the equivalent) and the work system's model are
coupled by declared equations that are hypotheses until fitted; the intended-effect, null and
unexplained-change tests run at their own horizons; "policy design, deployment and verification
are one loop." Scope and order per `docs/proposals/system-dynamics-core.md` §12.

## How work moves

1. A horizon's items become tickets in the task system that runs this program (the tasking
   demo is also our own tracker once H0 lands; until then, `~/orchestra-tasking`'s own project).
2. Implementation happens in the repository that owns the concept, never across the boundary.
3. Every implementation phase is followed by the reviews in [reviews.md](reviews.md), which
   re-engage the implementor until the triage judge says clean. Reviews that only find taste are
   a sign the phase was too small to need them; reviews that find the brief violated stop the
   phase.
4. The model-acceptance suite runs after any change to discovery or to a package's metrics.
5. An hourly critic reads the goals and the evidence and names the one thing to do next, while
   the owner is away.
6. Nothing is pushed by an agent; the owner's assistant pushes after a secret scan.

## What this plan does not decide

Everything in [decisions.md](decisions.md). The plan proceeds around those questions, never
through them.
