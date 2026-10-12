# Proposal: Teams and Roles, in four stages

Status: Stage 1 built and checkpointed, 2026-10-11. Stage 2 decided and next.
Stages 3 and 4 remain proposals.

## Decisions taken

- **Stage 1 is built.** Roles as data, created in conversation with the
  Supervisor, paused and deleted from the UI. The first project to use it
  (the automata game) got a Product Owner, a QA engineer, and the start of a
  developer-experience role from chat.
- **Stage 1 checkpoint, evaluated 2026-10-11: single agents do not accomplish
  much on their own.** A lone scheduled role can observe and file tickets, but
  it cannot delegate, it has nowhere to keep what it learns, and every piece of
  work it wants done has to go through the engineering pipeline as a code
  ticket. The Product Owner mostly reported "board healthy, nothing to do";
  the developer-experience role needs a reader of transcripts, a keeper of
  docs, and a builder of tools, which is three jobs. That is the case for
  teams, so Stage 2 is in scope.
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
- **No catalog. A team owns a space in the repository instead.** The earlier
  plan had curated catalogs with document statuses, a permission matrix, and a
  separate data store. That is a content-management system, and the value we
  want comes from somewhere simpler: a team needs a place that is its own,
  where it keeps its notes, its documents, and the tools it builds for itself,
  and that it is responsible for keeping accurate and small. In other settings
  that place is a wiki, or a chat channel where resident agents meet. Ours is
  a directory in the project repository, managed by the team, possibly kept
  out of git. Access is by directory, read-only or read-write, granted by the
  lead. Decision statuses, proposals, and the matrix are gone.

## Why stages

The full idea, teams of agents with leads, members, resources, permissions, and
cross-team channels, could absorb weeks and still miss the mark. The honest
answer to "what if this is a windmill" is to build it in stages where each stage
is useful on its own, each has a checkpoint that says whether it earned the
next one, and the first stage covers the one thing we are certain people want:
**their own long-running monitoring agents that receive events.**

| Stage | What it adds | Who needs it | Stop here if |
|---|---|---|---|
| 1. Custom agents | Roles defined as data: prompt, tools, events, schedule. Create, pause, restart, delete. | Everyone. "I want a Product Owner" or "I want a nightly auditor". | Nobody creates a second role, or created roles are ignored. *Passed: roles were created; they were limited, not ignored.* |
| 2. Teams, jobs, and team spaces | A lead with members; non-code work as job tickets reviewed by the lead; a directory per team that the team manages, with its own docs and tools. | Anyone whose agent needs helpers: a developer-experience lead with a retrospective reader and a tool builder; a PO with a designer. | Jobs produce results nobody reads, or team spaces rot. |
| 3. Access, channels, and a role library | Directory grants between teams; cross-team channels; roles and teams shared across projects. | Teams whose output other teams must trust. | Grants are never used beyond the defaults. |
| 4. Self-organizing teams | Leads request members; templates; rotation; reference teams (Pipeline, Product, DevEx, Lab); impact metrics. | A project that runs for months. | The metrics say agents' decisions are not better than the human's. |

The vocabulary, fixed now so it stays stable across stages:

- **Role**: one kind of agent. Every role has two independent dials:
  - *session policy*: `resident` (one long-lived process that keeps memory and
    can be talked to) or `ephemeral` (a fresh session per wake-up);
  - *wake policy*: events, an interval, a daily time, or messages from its
    lead, in any combination.
  "Scheduled" and "long-lived" are not two kinds of agent; they are settings
  every agent has. A Product Owner is resident and woken daily and on
  landings; a researcher is ephemeral and woken only by a job; a monitor is
  resident and woken by events.
- **Team**: a group of roles with exactly one **lead**. The lead decides,
  delegates, owns the team's space, grants its members access to it, and is
  the only member that talks outside the team.
- **Member**: a role in a team that is not the lead.
- **Job**: a unit of non-code work, executed by a member, reviewed by the lead.
- **Team space**: the directory a team owns. It holds whatever the team needs
  to do its work: documents, notes, handovers, generated reports, and the
  tools the team builds for itself. The lead decides its layout and keeps it
  accurate and bounded. Other roles see it read-only unless the lead grants
  more.
- **Grant**: a directory, a role, and `read` or `write`. Grants are what a
  lead hands out, inside its own space to its members, and to other teams on
  request.
- **Channel**: an explicit, visible permission for two teams' leads to exchange
  messages. The default is the tree: members to their lead, leads to the
  Supervisor, the Supervisor to the human.
- **Supervisor**: the human's interface, above every lead.

Stage 1, which exists, is the degenerate case: single roles with the two dials,
no lead above them but the Supervisor, and no resources beyond tickets and the
event log. Teams add the lead, the members, the jobs, and the space.

What exists today in these terms: an Engineering team whose lead is the
Coordinator and whose members are the per-ticket worker and reviewer, a
Pipeline team whose lead is the Pipeline Manager with no members yet, and the
Supervisor. All three are defined in Python.

---

## Stage 1: Custom agents (built)

**Goal.** Anyone can add a long-running agent like the Coordinator or Pipeline
Manager without writing Python, and control it from the UI.

**A role is a record.** `.orchestra/roles/<name>.json` plus `<name>.md` for the
prompt, in the project repository; built-in roles stay in code.

```json
{
  "name": "product_owner",
  "description": "Keeps value propositions and user stories current; asks the Coordinator for tickets.",
  "tools": ["tickets", "events", "escalate"],
  "session": "resident",
  "wake_on": ["milestone_closed", "ticket_transition:DONE"],
  "every": "45m",
  "created_by": "supervisor"
}
```

**Wake policy.** `wake_on` is a list of event types from the existing event
log, so any event the loop already emits can wake a role. `every` and `at`
schedule wake-ups. A woken role gets the same wake-up prompt the Coordinator
gets: why it was woken, the execution-health section, and the project snapshot.

**Session policy.** `resident` keeps one harness process alive for the life of
`orchestra run`; `ephemeral` starts a fresh session per wake-up and closes it.

**Tools.** Granted by group: `tickets`, `context`, `pipeline`, `capacity`,
`escalate`, `events`, `roles`.

**UI.** The Agents page shows what each role is: purpose, triggers, next
wake-up, session policy, tool names, who defined it, the prompt file, and the
full prompt. The Dashboard shows only live processes.

**What the checkpoint taught.**

- A role without helpers can only observe and file tickets. When its job needs
  reading long transcripts and also keeping a small set of documents current,
  one resident session cannot do both well: the transcripts crowd out the
  context the documentation work needs. The fix is two roles with one owner,
  which is a team.
- A role has nowhere to keep what it learns. The project context document is
  the Supervisor's, the workers do not read it, and agents may not write into
  the checkout. So a role that wants to maintain documentation for workers has
  to file a code ticket for every line, which nobody will do twice.
- Long design turns hit the wall-clock turn timeout. That is a loop problem,
  not a role problem, and is tracked separately: time out on silence, not
  duration.

---

## Stage 2: Teams, jobs, and team spaces

**Goal.** A role can have helpers, helpers can do work that is not code, and a
team has a place of its own to keep its work and its tools.

**Teams.** `.orchestra/teams/<team>.json` names the lead, the members, the
team's space, the grants the lead has made, and the team's capacity: how many
member sessions may run at once, separate from the engineering worker pool so a
documentation sweep cannot starve code work of the model.

```json
{
  "name": "devex",
  "description": "Keeps the implementation workers effective: accurate docs, good tools, lessons from rejections.",
  "lead": "environment_keeper",
  "members": ["retrospective", "toolsmith"],
  "space": ".orchestra/teams/devex",
  "tracked": false,
  "grants": [
    {"path": ".orchestra/teams/devex", "role": "retrospective", "access": "write"},
    {"path": ".orchestra/teams/devex/tools", "role": "toolsmith", "access": "write"},
    {"path": "automata", "role": "toolsmith", "access": "read"}
  ],
  "capacity": 2
}
```

**The team space.** A directory in the repository, by default
`.orchestra/teams/<team>/`. What goes in it is the lead's decision; a typical
layout is `docs/` for what the team maintains for others to read, `notes/` for
its own working memory and handovers, `reports/` for what it produces per
wake-up, and `tools/` for scripts and small command-line programs the team
writes for itself. The space is the team's wiki and its workbench in one
place, and the team is responsible for it the way a human team is responsible
for its Confluence space: accurate, current, and not too long.

- **Tracked or not.** A team decides whether its space is committed with the
  code (`tracked: true`, which makes it part of the product's history and
  visible to every worktree) or kept out of git (`tracked: false`, which adds
  the directory to `.gitignore` and keeps the space local to the machine). The
  default is untracked: a team's notes and half-built tools are not product
  code and should not pass through the merge gate. Documents a team wants
  workers to read go the other way, through a code ticket, which is the one
  path that lands in every worktree. A later store can sync an untracked space
  to a cloud bucket so it survives the machine; that is the same interface as
  the role store and is not built now.
- **Tools.** A team may write its own tools into `tools/` and they go on the
  `PATH` of every member session, so a team can grow a small command line of
  its own: a transcript summariser, a doc-budget checker, a conflict-overlap
  report. The toolsmith member exists to build these when the lead asks. Tools
  are the team's, not Orchestra's: Orchestra never depends on them and never
  ships them.
- **Budgets.** The lead sets a size budget on the documents it maintains for
  others, and Orchestra enforces it in the write path: a write that takes a
  file over its budget is refused with the current count, so adding a line
  means cutting one. This is the one piece of curation policy that is code.

**Grants and enforcement.** Every member runs with its working directory set
to the team space and `ORCHESTRA_ROLE` set, as workers run in their worktree.
Orchestra's own file tools (the `space` tool group: list, read, write, append)
check the grants before acting and refuse with a message saying who may. The
harness's built-in file tools cannot be fenced the same way, so the second line
is the one that already exists: the checkout's dirty-tree check. A member that
writes outside its grants leaves the checkout dirty, Orchestra reverts the
change, notes it on the lead's next wake-up, and the lead is expected to fix
the member's brief. Reads outside the space are allowed by default: a team
that cannot read the code it is supporting is useless.

**Jobs are tickets.** Tickets gain `kind`: `code` is today's path through
worker, review, and the merge gate; `job` names the member role that executes
it and the team it belongs to. A job runs `OPEN → IN_PROGRESS →
READY_FOR_REVIEW → IN_REVIEW → DONE` and skips `APPROVED` and `MERGING`. Its
reviewer is the team's lead unless the team names a reviewer role. Its result
is written into the team space where the job's brief says.

Why tickets rather than a second queue: one task graph, one dependency model,
one burndown, and "the transcript analysis must finish before the docs ticket
is filed" is an ordinary dependency. The loop, capacity, pause, stop, crash
retry, effective priority, and the drawers apply unchanged. The cost is that
`REJECTED` means "redo the work" for a job, which the prompts explain.

**Communication, the tree.** A member talks only to its lead; a lead talks to
its members and to the Supervisor. `send_to(role, note)` queues a wake-up and
the store rejects calls outside the tree with a message saying why. Leads do
not talk to each other yet; that is Stage 3. The team space is the other
channel: a member's report lands in `reports/`, the lead reads it on its next
wake-up, and nothing needs to be said.

**The first team.** Developer Experience, on the automata project, because the
need is measured. Of the re-engagements on that project, 38 were timeouts, 15
were merge conflicts, and 4 were reviewer rejections, and all four rejections
were decisions a worker made early with too little context. The team:

- *environment_keeper*, lead, resident, daily. Reads the day's commits and
  landed tickets, keeps the worker-facing docs accurate and under budget,
  folds in lesson candidates, files at most two docs tickets a day, reports to
  the Supervisor in a paragraph.
- *retrospective*, member, ephemeral, woken by reviewer rejections and gate
  conflicts. Reads one transcript, classifies the cause (brief gap, knowledge
  gap, discipline gap, one-off), writes a two-line lesson candidate into the
  space or nothing.
- *toolsmith*, member, ephemeral, woken by jobs from the lead. Builds the
  team's tools: a doc-budget check, a file-overlap report across in-flight
  branches, a transcript digest.

**Done when.** The DevEx team runs for a week on the automata project: the
retrospective produces lesson candidates, the keeper turns them into docs
tickets that land, the toolsmith ships at least one tool the keeper uses, and
the re-engagement counts on the Dashboard go down.

**Checkpoint.** Do job results get read, and does the space stay healthy?
Measure how often a report in the space is referenced by a later ticket or a
lead's note, and whether the docs stay under budget without the human
touching them. If jobs are produced and never consumed, or the space fills
with stale notes, stop before Stage 3.

---

## Stage 3: Access between teams, channels, and a role library

**Goal.** Teams can rely on each other's spaces, decisions between leads are
explicit, and roles are reusable across projects.

### Grants between teams

Stage 2 grants are inside a team. Stage 3 lets a lead grant another team's
role read or write access to a directory in its space: "Engineering's workers
may read `devex/docs`", "the Product Owner may write to `devex/notes/requests`".
Grants are stored on the owning team and listed on the Teams page, so who can
touch what is visible without reading JSON. Enforcement is the same as Stage 2:
Orchestra's file tools check; the dirty-tree check catches the rest.

There are no document statuses. If a team wants a decision to be final, it
writes it down in its space and says so; other teams read it because they were
told to in their prompts. If that turns out to be too loose, the fix is a
convention in the lead's prompt, not a workflow engine.

### Channels

Sometimes leads must talk to each other: the DevEx lead to the Coordinator
about two tickets that will conflict, the Product Owner to the Pipeline
Manager about a flaky acceptance test. A **channel** is an explicit grant
between two teams, created by the Supervisor or requested by a lead, that
allows `send_to` between their leads, and optionally between named members.
The default remains the tree; channels are the exceptions, and each one is
listed on the Teams page so the communication pattern is visible.

### Role library

Roles and teams should not be rebuilt per project. The library has three
sources, resolved in order:

1. **Project**: `<repo>/.orchestra/roles/` and `.orchestra/teams/`, versioned
   with the code, for roles specific to that codebase.
2. **User**: `~/.orchestrator/library/`, shared by every project on the machine.
3. **Built-in**: the roles shipped with Orchestra.

A role definition is portable because it names tool groups and event types
rather than project details; project specifics live in the role's prompt
template slots (product name, domain, the team's space). `orchestra role
install <name>` copies a library role into a project; `orchestra role export
<name>` does the reverse. Teams are packaged the same way, with their space
layout and tools, so a "DevEx team" can be installed into a new project in one
step and arrives with its tools.

**Done when.** The DevEx team installs into a second project from the library,
its lead grants Engineering read access to its docs, and the Coordinator acts
on a channel message from the DevEx lead.

**Checkpoint.** Are grants and channels used beyond the defaults, and does
anything cross teams that would not have crossed as a ticket? If not, Stage 4
is not needed.

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
  or days, writing a handover note into their space first, so memory survives
  but context does not grow without bound.
- **Space sync.** An untracked team space can be synced to a cloud store so it
  survives the machine and follows the team into another project. The same
  interface as the role store.
- **Reference teams.** Pipeline (gate events, bisection, flaky tests, a daily
  test run member), Product (owner, designer, explorer, QA), DevEx (keeper,
  retrospective, toolsmith), and Lab (PI, researchers). Shipped as library
  teams with their spaces and tools.
- **Impact metrics.** On the Teams page: jobs completed, reports read, tickets
  that trace to a team's note, re-engagements per landed ticket over time,
  and the human's overrides of agent decisions. These are the numbers that
  answer the windmill question.

**Checkpoint.** If the metrics say agent decisions are overridden more often
than they are kept, the right move is to scale back to Stages 1 to 3, which
remain useful on their own.

---

## Open topic: how a team shows its work

This is unresolved and is recorded here so it is not forgotten. It belongs to
Stage 2 or later, but it shapes what a team is for.

**The need.** A team that produces something other than code needs a place to
show it. The R&D lab in an earlier project built its own page: waterfall
diagrams of radio spectrum, a viewer for its analyses and discoveries. It was
dynamic and it was good. A Product team would want user stories, study
results, and design decisions laid out, not a directory listing. The
dashboard, ticket graph, and Agents page are Orchestra's views of Orchestra;
a team's output needs the team's own view.

**Two things not to do.**

- Not a page assembled from a fixed palette of pre-defined widgets. The work is
  too variable; a waterfall diagram is not a bar chart with different data.
- Not teams defined by custom HTML and JavaScript as a matter of course. That
  makes a team definition a web project, and makes the Supervisor or lead a
  front-end developer. Sometimes a team genuinely needs a custom page, and
  that must stay possible, but it should be the exception a team earns.

**Directions worth exploring.**

1. *The space, rendered.* The cheapest default: Orchestra serves a team's
   space read-only at `/teams/<team>/`, markdown rendered, reports listed by
   date, tools listed with their help text. Most teams would never need more.
2. *Pages as a job output.* A lead can request a page as a job: a member
   writes a self-contained page into the space, served by Orchestra under the
   team's path with read access to the space, reviewed by the lead like any
   job. The page is team code, not Orchestra code and not product code.
3. *Pages built against an API, not a database.* Whatever a team page is, it
   reads through Orchestra's API, so grants are respected and a page cannot
   bypass a lead.

**Data that is not the space.** The lab recorded several gigabytes of radio
captures. That does not belong in a repository directory, tracked or not. A
team that produces bulk data needs a store outside the repo, referenced from
its space by URI. Which backends, how retention works, and how a team page
reads large data for display are all open, and the Stage 4 space sync is the
natural place for it to appear.

---

## Open questions

1. **Space default.** Untracked by default is the proposal; is there a kind of
   team whose space should be tracked from the start (a Product team whose
   decisions should be in the product's history)?
2. **Writing docs for workers.** A team's untracked space is invisible to
   worktrees, so worker-facing docs must land through a code ticket. Is that
   friction acceptable, or should the keeper have a narrow write grant on a
   tracked directory such as `docs/agents/` that commits on the base branch
   when the checkout is clean, as the role store does today?
3. **Enforcement.** Grants are enforced by Orchestra's own file tools plus the
   dirty-tree check. Is that enough, or does a member need a sandboxed
   working directory with only its granted paths visible?
4. **Tools on PATH.** A team's tools are on the PATH of its member sessions.
   Should a team be able to offer a tool to another team, and is that a grant
   or a copy?
5. **Channels.** Lead-to-lead only, or may a channel name specific members?
6. **Library format.** A directory of JSON and markdown, or a package so it
   can be published and versioned, now that a team ships with tools?
7. **Team pages and team data.** See the open topic above.

## Spec changes Stage 2 requires

Recorded here so the commit that builds Stage 2 updates `AGENTS.md` and
`SPEC.md` deliberately rather than by accident.

- Invariant 3 ("nothing is ever written inside the user's checkout except
  `orchestra.toml`") already has one exception in practice, `.orchestra/roles/`.
  Stage 2 widens it to `.orchestra/`: roles, teams, and team spaces, written
  only through Orchestra's stores and tools, never by the merge gate, and
  never by an agent's own file tools outside its grants.
- A new tool group, `space`, and a new store, `TeamStore`, with the same
  shape as `RoleStore`.
- Tickets gain `kind` and, for jobs, `team` and `executor`. The transition
  table gains the job path.
- Member sessions get the team's `tools/` on `PATH` and their working
  directory set to the space.

## Build order

Stage 2 as the next piece of work, driven by the DevEx team on the automata
project, because that team's need is measured and its first week is the
checkpoint. Stage 3 only after a second team wants to read the first team's
space. Stage 4 after a project has run for a month.
