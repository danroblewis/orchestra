# Proposal: Systems and Roles, in four stages

Status: Stage 1 decided and being built, 2026-10-11. Stages 2 to 4 remain proposals.

## Decisions taken

- **Only Stage 1 is in scope now.** Roles and custom agents. Teams, jobs,
  catalogs, channels, and the library are not built until Stage 1 has earned
  them.
- **Roles are authored in conversation.** Creating a role is a brainstorming
  and requirements-gathering exercise between the human and the Supervisor:
  what the agent is for, what should wake it, what it may do, how it reports.
  When the human agrees to the plan, the Supervisor writes the role and its
  prompt. There is no form and no template picker in the UI.
- **Role storage is an interface, like tickets.** A `RoleStore` with one
  implementation to start: the project repository, under `.orchestra/roles/`,
  versioned with the code. Not `~/.orchestrator`. Later stores (an external git
  repository, GCS, Artifactory) implement the same interface, because roles are
  valuable and people will want them outside any one machine or repo.
- **The knowledge catalog is deferred, deliberately.** A catalog without a
  curation policy is a text dump. Its value comes from the coordinated
  behaviour of agents around it, scheduled curation and strongly worded
  directives, not from storage or tools. It returns when a team exists to
  curate it.

## Why stages

The full idea, teams of agents with leads, members, catalogs, permissions, and
cross-team channels, could absorb weeks and still miss the mark. The honest
answer to "what if this is a windmill" is to build it in stages where each stage
is useful on its own, each has a checkpoint that says whether it earned the
next one, and the first stage covers the one thing we are certain people want:
**their own long-running monitoring agents that receive events.**

| Stage | What it adds | Who needs it | Stop here if |
|---|---|---|---|
| 1. Custom agents | Roles defined as data: prompt, tools, events, schedule. Create, pause, restart, delete. | Everyone. "I want a Product Owner" or "I want a nightly auditor". | Nobody creates a second role, or created roles are ignored. |
| 2. Teams and jobs | A lead with members; non-code work as job tickets reviewed by the lead. | Anyone whose agent needs helpers: PO with a designer, PI with researchers. | Jobs produce results nobody reads. |
| 3. Catalogs, access, channels | Owned knowledge with read/write/decide permissions; role library shared across projects; cross-team channels. | Teams that make decisions other teams must trust. | Decisions do not change what gets built. |
| 4. Self-organizing teams | Leads request members; templates; rotation; reference teams (Pipeline, Product, Lab); impact metrics. | A project that runs for months. | The metrics say agents' decisions are not better than the human's. |

The vocabulary, fixed now so it stays stable across stages:

- **Role**: one kind of agent, with a prompt, tools, a wake policy, and a session policy.
- **Team**: a group of roles with one **lead**. The lead decides, delegates, owns the team's catalogs, and is the only member that talks outside the team.
- **Member**: a role in a team that is not the lead.
- **Job**: a unit of non-code work, executed by a member, reviewed by the lead.
- **Catalog**: a named, owned collection of documents.
- **Channel**: an explicit permission for two teams to exchange messages.
- **Supervisor**: the human's interface, above every lead.

What exists today in these terms: an Engineering team whose lead is the
Coordinator and whose members are the per-ticket worker and reviewer, a
Pipeline team whose lead is the Pipeline Manager with no members yet, and the
Supervisor. All three are defined in Python.

---

## Stage 1: Custom agents

**Goal.** Anyone can add a long-running agent like the Coordinator or Pipeline
Manager without writing Python, and control it from the UI.

**A role is a record.** Stored in the project state as `roles.json` plus a
prompt file per role; built-in roles stay in code and can be overridden by a
record of the same name.

```json
{
  "name": "product_owner",
  "session_id": "product-owner",
  "description": "Keeps value propositions and user stories current; asks the Coordinator for tickets.",
  "prompt": "prompts/product_owner.md",
  "tools": ["tickets", "escalate"],
  "session": "resident",
  "wake_on": ["milestone_closed", "ticket_done"],
  "every": "24h",
  "at": "09:00",
  "paused": false,
  "source": "project"
}
```

**Wake policy.** `wake_on` is a list of event types from the existing event
log, so any event the loop already emits can wake a role: ticket created,
landed, blocked, gate failed, staging deployed, and so on. `every` and `at`
schedule wake-ups. A woken role gets the same wake-up prompt the Coordinator
gets today: why it was woken, the execution-health section, and the project
snapshot.

**Session policy.** `resident` keeps one Pi process alive for the life of
`orchestra run`; `ephemeral` starts a fresh session per wake-up and closes it,
which suits daily roles that need no memory and keeps context from growing.

**Tools.** Granted by the existing groups: `tickets`, `context`, `pipeline`,
`capacity`, `escalate`. Stage 1 adds one group, `events`, which lets a role
read the event log so a monitor can look back over what happened.

**Supervisor tools.** `create_role`, `update_role`, `delete_role`,
`restart_role`, `pause_role`, `resume_role`. The Supervisor writes the prompt
from a short template: who the role is, what it watches, what it may do, how
it reports. Deleting a role archives its sessions like a finished ticket.

**UI.** An **Agents** page listing every role, built-in or custom, with status,
last activity, next scheduled wake-up, and pause, restart, and delete controls.
Pause queues wake-ups instead of dropping them, so a resumed role catches up.
The dashboard's left column shows custom resident roles beneath the three
built-in ones.

**Done when.** A user creates a Product Owner from chat, it wakes daily and on
landings, it asks the Coordinator for tickets through `escalate`-style
messages, and the user pauses and deletes it from the UI.

**Checkpoint.** Does anyone create a second role, and does it change what gets
built? If created roles are ignored, stop here; the mechanism is cheap and
already covers the certain need.

---

## Stage 2: Teams and jobs

**Goal.** A role can have helpers, and helpers can do work that is not code.

**Teams.** `teams.json` names a lead and its members, and the team's capacity:
how many member sessions may run at once, separate from the engineering worker
pool so a lab survey cannot starve code work of the local model.

**Jobs are tickets.** Tickets gain `kind`: `code` is today's path through
worker, review, and the merge gate; `job` names the member role that executes
it. A job runs `OPEN → IN_PROGRESS → READY_FOR_REVIEW → IN_REVIEW → DONE` and
skips `APPROVED` and `MERGING`. Its reviewer is the team's lead unless the team
names a reviewer role. Its result is written where the job's brief says, at
this stage a plain document directory per team (`<state>/teams/<team>/docs/`),
which Stage 3 turns into catalogs.

Why tickets rather than a second queue: one task graph, one dependency model,
one burndown, and "the spectrum survey must finish before the decoder ticket
starts" is an ordinary dependency. The loop, slots, pause, stop, crash retry,
effective priority, and the drawers apply unchanged. The cost is that
`REJECTED` means "redo the research" for a job, which the prompts explain.

**Communication, the tree.** A member talks only to its lead; a lead talks to
its members and to the Supervisor. `send_to(role, note)` queues a wake-up and
the store rejects calls outside the tree with a message saying why. Leads do
not talk to each other yet; that is Stage 3.

**Done when.** A Lab team with a Principal Investigator lead and an ephemeral
researcher member runs a research job created by the PI, the PI reviews and
accepts the result, and a code ticket that depends on the job becomes ready.

**Checkpoint.** Do job results get read? Measure how often a job's document is
referenced by a later ticket or decision. If jobs are produced and never
consumed, stop before catalogs.

---

## Stage 3: Catalogs, access control, channels, and a role library

**Goal.** Teams own knowledge that other teams can trust, decisions are
explicit, and roles are reusable across projects.

### Catalogs

A catalog is a named collection of markdown documents with frontmatter (id,
title, author role, status, tags, created, updated). Catalogs are grouped by
purpose under the team that owns them:

```
<state>/catalogs/
  product/            owned by the Product team
    value-propositions/
    user-stories/
    user-studies/
  design/             owned by the Product team, written by the designer
    decisions/
    components/
  research/           owned by the Lab
    findings/
    reference-surveys/
  pipeline/           owned by the Pipeline team
    gate-runs/  flaky-tests/
```

Each top-level catalog is its own git repository, so every change has a diff
and an author. Documents have a status: `draft`, `proposed`, `decided`,
`rejected`, `superseded`.

### Access control

Permissions are a matrix of role × catalog × action, stored in `teams.json`
and enforced in one place, the `orchestra api` layer that every tool goes
through, keyed by the `ORCHESTRA_ROLE` the loop set when it launched the agent.
Agents never see the matrix; a disallowed call fails and says who may do it.

| Action | Meaning | Default grant |
|---|---|---|
| read | list and read documents | every role, every catalog |
| write | create and edit `draft` documents | members of the owning team |
| propose | move a document to `proposed` | members of the owning team |
| decide | set `decided`, `rejected`, or `superseded` | the owning team's lead |
| grant | change the matrix for the team's catalogs | the owning team's lead |

A lead grants access to its members: "the designer may write to `design/`",
"the explorer may write to `product/user-studies/` but not read `design/`".
`decided` documents are the contract between teams: Engineering reads decided
design documents; the Lab reads decided user stories to know what to research.
Two catalogs are also code, acceptance tests and reference tests, and those
enter the merge gate only as code tickets through Engineering.

### Channels

Sometimes leads must talk to each other: the Product Owner to the Pipeline
Manager about a flaky acceptance test, the PI to the Coordinator about a survey
that changes a ticket's brief. A **channel** is an explicit grant between two
teams, created by the Supervisor or requested by a lead, that allows
`send_to` between their leads, and optionally between named members. The
default remains the tree; channels are the exceptions, and each one is listed
on the Teams page so the communication pattern is visible. Everything else
crosses teams through `decided` documents.

### Role library

Roles and teams should not be rebuilt per project. The library has three
sources, resolved in order:

1. **Project**: `<repo>/.orchestra/roles/` and `.orchestra/teams/`, versioned
   with the code, for roles specific to that codebase.
2. **User**: `~/.orchestrator/library/`, shared by every project on the machine.
3. **Built-in**: the roles shipped with Orchestra.

A role definition is portable because it names tool groups and event types
rather than project details; project specifics live in the role's prompt
template slots (product name, domain, catalogs). `orchestra role install
<name>` copies a library role into a project; `orchestra role export <name>`
does the reverse. Teams are packaged the same way, so a "Product team" or "Lab
team" can be installed into a new project in one step.

**Done when.** The Product Owner decides a user story, QA files acceptance-test
tickets that cite it, the gate runs them, and the same Product team installs
into a second project from the library.

**Checkpoint.** Do decided documents change tickets? Measure how many tickets
cite a decided document and how often a decision is superseded. If decisions
pile up without affecting work, do not build Stage 4.

---

## Stage 4: Self-organizing teams

**Goal.** Teams run for months with little human attention, and we can tell
whether they help.

- **Leads request members.** A lead may ask the Supervisor for a role to be
  added to its team, with a justification. The Supervisor decides, informed by
  the human. Leads grant their members access themselves.
- **Templates.** Role templates with slots, so the Supervisor instantiates a
  lead, specialist, job worker, reviewer, or explorer rather than writing a
  prompt from nothing.
- **Session rotation.** Resident roles rotate to a fresh session every N turns
  or days, writing a handover document to their catalog first, so memory
  survives but context does not grow without bound.
- **Reference teams.** Pipeline (gate events: a run over 2.5 times the median,
  bisection, flaky tests; a daily test run member that files tickets on
  failure), Product (owner, designer, explorer, user-study coordinator, QA),
  and Lab (PI, researchers, reference surveys turned into tests). Shipped as
  library teams.
- **Impact metrics.** On the Teams page: jobs completed, decisions made and
  cited, tickets that trace to a decision, time from decision to landing, and
  the human's overrides of agent decisions. These are the numbers that answer
  the windmill question.

**Checkpoint.** If the metrics say agent decisions are overridden more often
than they are kept, the right move is to scale back to Stages 1 to 3, which
remain useful on their own.

---

## Open questions

1. **Stage 1 prompt authoring.** Free-form prompt from the Supervisor, or a
   template with slots from day one?
2. **Job results in Stage 2.** A plain document directory per team, or catalogs
   immediately with permissions deferred?
3. **Catalog location.** Under the project state, invisible to the code repo,
   or inside the repo under `.orchestra/catalogs/` where the gate's
   dirty-checkout rule applies?
4. **Decide semantics.** A status the lead sets, or a propose-then-decide flow
   with feedback, like code review?
5. **Channels.** Lead-to-lead only, or may a channel name specific members?
6. **Ephemeral versus resident for daily roles.** Memory versus context growth;
   Stage 4's rotation makes resident safe, but Stage 1 must pick a default.
7. **Library format.** A directory of JSON and markdown, or a Pi package so it
   can be published and versioned?

## Build order

Stage 1 first, as one piece of work. Then the Pipeline team's events and daily
run as the first Stage 2 use, since they are already required. Stages 3 and 4
only after their checkpoints.
