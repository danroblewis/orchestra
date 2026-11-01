# Design a system backwards

Status: draft for the owner's review, 2026-10-31. Nothing built. The north star for everything
after the task system; the owner's decisions of the same day are D21 in
`docs/roadmap/decisions.md`.

Written from the owner's thinking of 2026-10-31, after a week of trying to use Orchestra at work.
It builds on the curious observer (`docs/roadmap/use-cases.md` UC-0: observe, then influence,
then replace), the environment and ghost machines (`environment-and-ghost-machines.md`), the
agent-first machines (`agent-first-machines.md`), the work charter (`docs/work-charter.md`) and
the user stories (`docs/user-stories.md`, placed by layer in `docs/roadmap/story-placement.md`).
It supersedes the task-system half of `empty-orchestra.md`: the task package was the first
machines, and it has done its job.

## 1. The problem

The owner tried Orchestra at work and hit one hurdle after another. Each hurdle was the same
hurdle: the task system has one workflow built into it (a ticket, a worker, a reviewer, a merge
gate, a staging deploy), and the owner's work is not that workflow. Delivering a change at work
means keeping a Jira ticket current, opening a pull request with a good description, watching its
tests, asking people to review it, addressing their feedback until there are enough approvals,
sending it to the company's merge gate with a label, and watching that gate for a failure. That
is one workflow of many: reviewing the team's pull requests is another, an alert from PagerDuty is
a third, and the user stories hold twenty more. Release candidates and their verification, several
releases out at once, staged production rollouts, customer-owned deployments, concurrent release
branches that all need hotfixes: every company has its own, and none of them is the one we built.

Orchestra has two descriptions of what happens in a system. The event map shows the machines and
who talks to whom. The system dynamics model shows how the quantities we care about move over
time. Both are observed: they say what the system does. Nothing says what it *should* do. The
only "should" in the whole system is the task system's loop, hard-coded, and that is why
everything at work had to be bent toward it (external review mode, stacking, labels) and still did
not fit.

The owner's words: "I think we assumed our 'tasks' workflow and 'merge' would mesh more naturally
with that of my company's." And: "What I need to integrate this workflow into my work life is
something that helps me build out machines, events, and metrics so that we actually cover all of
the processes I need to integrate in work."

## 2. The dream

"Design a system backwards. Start by declaring what you want, then declare what effects you expect
to see emergently, then declare what machines you want, then declare how they are related and
communicate, then implement them implicitly with Universal Machines, and eventually refactor away
the Universal Machines to Programmatic Machines with AI-fixers, then reduce the amount of AI-fixing
it needs. This is the dream. Monitor the system at all of those levels, add Universal Machines to
improve efficiency."

As a ladder, each rung declared before the next and every rung monitored:

1. **Declare what you want.** A system dynamics model with no measurements behind it yet: the
   stocks the owner cares about and the targets on them. Pull requests wait under a day for a
   first review. A hotfix reaches every release branch within four hours. An alert is disqualified
   or escalated within fifteen minutes. The owner may also name the basic stocks they expect to
   see.
2. **Declare the effects you expect.** The measurable consequences of the system that no machine
   produces and no machine owns: latency, error budget, the age of the review backlog, on-call
   load, customer trust, technical debt. They are not the environment as we have used that word
   (`environment-and-ghost-machines.md` §1: the unnamed actor behind flows nobody sets). They are
   what happens to the system at large as a result of its machines working. Nebulous, sometimes
   ephemeral, measurable. We call them **effects** here; the name is provisional (§8).
3. **Declare the machines, by name.** The owner has some idea of what machines they want, and
   places them on the map by name only. A name declares a kind; how many instances there are is
   learned from the labels of what is later measured or heard ("postgres database": if they have
   one, they have more than one). Existing machines go on the map too: a Jenkins job pipeline, a
   database cluster, a company's merge gate.
4. **Declare how they communicate.** The events each machine publishes and listens for: the
   intended event graph. As machines are added they get more detailed and more specific, and the
   map rerenders and reorients itself as the Event Map does today.
5. **Implement each machine as a Universal Machine.** An AI agent with a prompt, tools and the
   events it publishes and subscribes to is a complete implementation of a declared machine, and
   the fastest one. The agents refine themselves from the semantic information in the event graph.
6. **Observe at every level.** The bus shows which machines really talk to which; the metrics and
   discovery show which stocks, flows and effects really exist and how they move; the targets say
   whether what the owner wanted is happening.
7. **Replace Universal Machines with programs plus AI fixers.** When an agent's transcripts
   repeat, a program does the job and an agent is kept only for the cases the program does not
   know (the ghost-machine path: observe, fit, write, shadow, swap, verify).
8. **Reduce the fixing.** The cases the fixer handles become the program's, one by one.

Monitoring happens at every rung, and wherever a rung is inefficient the remedy is the same: add a
Universal Machine there, then walk it down the ladder.

## 3. Three layers on one map

Everything declared is a hypothesis. That is already Orchestra's rule for equations (a declared
equation is an assumption until it is fitted; `AGENTS.md` rule 6) and for the priors a human hands
discovery (D4). This proposal extends it to machines, events, stocks and effects: all of them may
be declared, and declaring none of them makes anything true.

So the map has three layers, drawn on one page:

| Layer | Who puts it there | What it means |
|---|---|---|
| **Proposed** | the AI (§4) | an option, drawn as a slightly darker variant; a click solidifies it into the declared layer |
| **Declared** | the owner, through the Supervisor | what the owner intends: a machine, an event, a stock, an effect, a target |
| **Observed** | the bus and the metrics | what is actually there: machines known by their events, stocks found by discovery, series measured by instruments |

The design map and the Event Map are the same page. A declared machine that has never published
shows as declared and unheard. An observed machine no one declared shows as unexpected. A declared
event with no observed publisher, a declared stock discovery never finds, a target that is missed:
each difference between the declared layer and the observed one is a piece of work, or a
correction to the declaration. The comparison is the work list, and it replaces the coverage
tables we would otherwise keep by hand.

## 4. The AI's part

An agent helps draw the map, and everything it draws is proposed, never declared:

- **Naming.** Given a machine's name, it fills in a first prompt, tools and events for it, as an
  option. Not official until solidified.
- **Events.** It suggests event names for a new machine, considering the existing event names and
  the descriptions of the other machines, so that one purpose gets one name across the map.
- **Refinement as the graph grows.** As more machines are added and the map gets more specific, it
  revisits earlier machines: their prompts, their tools, what they publish and subscribe to.
- **Refinement passes**, run a few times over the whole map: events with a publisher but no
  subscriber; two events serving one purpose; one event serving several distinct purposes
  (deduplicated too far); and the rest of that family.
- **The Universal Machines refine themselves** from the semantic information in the graph: what
  they publish, what they listen for, what their neighbours say of themselves. With a feedback loop
  from the observed layer (what they actually did, how long it took, what it cost), that
  refinement is where the automated benefit is.

The Supervisor is still the only one the owner talks to (`AGENTS.md` rule 9). Whether this agent is
the Supervisor's duty or a machine of its own is the kind of question D20 answers by watching it
grow.

## 5. The integration step

The machines a company already has (a Jenkins pipeline, a Postgres cluster, a deploy system, the
company's merge gate) will never publish an event on Orchestra's bus, and they are the ones that
matter most at work. They are declared as placeholders on the map, and **instruments are attached
to them**: the owner says which collected series measure which declared machine. The instrument
measures; the declared machine is where the measurement is hung on the map; the labels on the
series say how many instances there are. This is the integration step, and it is where the design
map meets the systems that exist.

This amends two invariants on purpose, and the commit that builds it must say so:

- **Rule 2** already allows placeholders: machines a plugin declares that only fill in machines
  not yet seen and never override what is observed. Declared machines are placeholders of the same
  kind, from the owner instead of a plugin, with the same limit: they never make a machine exist
  in the observed layer.
- **Rule 7** says measurements are not machines and a flow is never associated with a machine
  from a measurement's label. That stands. Attaching an instrument to a declared machine is
  declared provenance, the same as the `instrument=<name>` label today: it says what was measured,
  never that the machine exists, and never which flow the machine drives. The link between a
  machine and a flow stays an inferred hypothesis (rule 6).

## 6. What this makes of the task system

The task system was a prototype. It will be replaced by a Workflows plugin that is "capable of
handling any existing workflow, from any company", and very little of it, including its data
storage, will remain. It can be left out simply by not installing it. Later, a task system is
written again as a naive implementation of Workflows, for demos, and people are expected to
customise it into the workflows they actually have. The details belong to the later proposals
(§7); here is only the shape.

**Items have no status.** An item is its facts: the events about it, each recorded in that item's
own log, folded into a snapshot when needed. "Which step is it at" is a function from the facts,
computed by a workflow, and several workflows can read the same item differently (a pull request
is in the owner's delivery workflow and in the team's review workflow at once). There is no
`status` field, no transitions table, no version bump. The record is a per-item event log, kept by
the plugin in the state directory (rule 5), not on the bus, whose retention is the broker's.
Snapshots and checkpoints keep long-lived items cheap; a closed item's log is archived and then
dropped, its final snapshot kept.

**Piles are the stocks.** A pile is a named query over the items' facts ("has a Jira key, no pull
request, nobody holds it"). The size of each pile is written to the metrics store every tick, so
the piles are exactly what discovery finds as stocks, and the moves between piles are its flows.
The workflow does not declare the model; it is made of it.

**The floor engages machines.** The most important thing the task system did was the one thing
nothing else does: launch and set up machine instances to do actual work. That part stays, as the
floor: for each pile a workflow marks as somebody's, it offers an item to the role, claims the
resources the step needs, records the claim, keeps the lease, takes silent work back, and
escalates when a guard is passed. It does not know what a machine is made of; the agents' host
answers its offers by starting sessions, a program answers them by running.

**Resources** are the scarce things a step needs: a worktree, a staging environment, a customer
sandbox, an API budget. A kind is a name, a capacity, and commands the repository provides to
make one, reset one between uses and release one. A Jira ticket or a pull request is not a
resource; it is a fact on the item.

**A repository's `.orchestra/` and a plugin have the same shape.** Both hold workflows, machines,
resources, instruments and settings. A workflow starts in the repository, specific and private;
gets parameters when a second repository wants it; moves into a package; and is shared. Nothing in
it changes between those steps except where it is loaded from. The Supervisor writes all of it,
the pages draw it, and no human ever reads the files: "If TOML is the interface for setting this
up, it will be a miserable experience."

## 7. Checkpoints and build order

Each document settles one thing and gets the full review before anything is built on it.

| # | Document | What it settles |
|---|---|---|
| 1 | `docs/proposals/design-backwards.md` (this one) | The dream as one page: the ladder, the three layers on the map, the levels of monitoring. |
| 2 | `docs/proposals/intended-model.md` (core) | Declared stocks, effects and targets; declared machines, instances and events; proposed, declared and observed; the comparison; what the Dynamics and Machines pages gain; which invariants change and how. |
| 3 | `docs/proposals/workflows.md` (new plugin) | The record (facts, folds, snapshots, lifecycle), piles, the floor, the workflow vocabulary and nothing beyond it, resources, relations between items, metric conditions, the `.orchestra/` layout, promotion to a plugin. |
| 4 | `docs/proposals/machine-design.md` (agents) | The AI that helps draw the map: naming machines, proposing events from existing names, refining prompts from the graph's semantics, the refinement passes, proposals as options; the loop that improves Universal Machines; the path to programs with AI fixers. |
| 5 | `docs/proposals/instruments-on-machines.md` (core) | The integration step: attaching instruments to declared machines, instances from labels, what it means for rules 2 and 7. |
| 6 | `docs/roadmap/use-cases.md` and `goals.md` | Seven example workflows as acceptance cases (the owner's delivery through the company gate, team review, on-call, release-candidate verification, hotfixes across release branches, a staged rollout, customer-owned deployments), each a tiny repository with scripted machines; the milestones in build order. |
| 7 | `docs/roadmap/decisions.md` | The decisions of 2026-10-31 (D21). |

Build order, after the reviews: the intended model and the map (2, 5); then the record and the
floor, with the task system's loop as the first example (3); then the design assistant (4); then
the examples one by one, the owner's delivery workflow the first real one.

## 8. Open questions

1. **The name "effects."** A machine does, an instrument measures, an effect is what happens to
   the system as a result. "Conditions" and "outcomes" are taken (the desk's true-or-false
   responsibilities; what the owner wants). The owner has not named them: "I don't know what to
   call them."
2. **The floor before the map?** The order in §7 builds the declared layer first because
   everything else is checked against it. The owner needs to be running at work sooner than that
   suggests; the record and the floor (3) could come first, with the map following.
