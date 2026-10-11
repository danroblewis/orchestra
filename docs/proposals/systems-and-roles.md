# Proposal: Systems and Roles

Status: draft for discussion, 2026-10-11. Nothing here is implemented yet.

Orchestra needs a generic way to create agent roles and arrange them into working
groups: a Product Owner with a designer, an explorer, and a QA function under it;
an R&D lab with a Principal Investigator and researchers; a Pipeline Manager with
a daily test run. Today only one such arrangement exists, Coordinator to worker,
and it is hard-coded. This document proposes the general mechanism, the options
where there is a real choice, and the questions to settle before building.

---

## 1. What exists today

The role registry (`orchestra/agents/roles.py`) gives a role a prompt file, tool
groups, a resident flag, wake events, and an optional schedule. The loop keeps
resident roles alive, delivers queued wake-ups, and queues scheduled ones. The
Pi extension grants tools by group. Operator controls can pause pickup and stop
an agent.

That covers "a role exists and gets woken". It does not cover:

1. **Hierarchy.** Who reports to whom, and who may send what to whom.
2. **Jobs that are not code.** A researcher surveying a spectrum or an explorer
   running a user study is not a worker on a branch, but it is a unit of work
   with a lifecycle and a result.
3. **Catalogs.** Structured, owned knowledge such as product metadata, design
   decisions, research findings, and user-study results, with read, write, and
   decide permissions.
4. **Runtime definition.** Roles are Python. The Supervisor needs to create,
   rework, restart, and delete them as data, and the human needs to pause,
   resume, or delete them from the web UI.

---

## 2. The core idea: Systems

A **System** is a group of roles with exactly one **lead**. The lead is the only
member that communicates outside the system. Members do the work; the lead
decides and owns the system's catalogs. The Supervisor sits above every lead and
remains the only human interface.

Every arrangement in the requirements fits this shape, including the one we
already have:

| System | Lead | Members | Jobs | Catalogs |
|---|---|---|---|---|
| Engineering | Coordinator | worker, reviewer (per ticket) | code tickets | tickets |
| Pipeline | Pipeline Manager | daily test runner (scheduled) | gate fixes, flaky-test triage | gate runs, flaky tests |
| Product | Product Owner | UI/UX designer, explorer, user-study coordinator, QA | design jobs, user studies, acceptance-test tickets | product, design, user studies |
| Lab | Principal Investigator | researcher (per job) | research jobs | research catalog, reference tests |

The pattern is the same in each row: **the lead decides, members do, results land
in a catalog the lead owns.** Coordinator to worker is the first instance of it.

A System is defined by:

- its lead role and member roles,
- the job kinds its members execute and which role executes each,
- the catalogs it owns and the permissions it grants other systems,
- what wakes the lead: events, a schedule, or messages from the Supervisor,
- its capacity: how many member sessions may run at once.

---

## 3. Jobs: two options

### Option A: jobs are tickets

Add a `kind` field to tickets: `code` (today's path through worker, review, and
the merge gate) or `job`, with a `role` naming the member that executes it. A job
ticket runs `OPEN → IN_PROGRESS → READY_FOR_REVIEW → IN_REVIEW → DONE`, skipping
`APPROVED` and `MERGING`. Its reviewer is the system's lead or a designated
reviewer role. Its result is one or more catalog entries rather than a branch.

For:
- One task graph, one dependency model, one burndown, and milestones that mix
  research, design, and code. "The spectrum survey must finish before the
  decoder ticket starts" is a plain dependency.
- The loop, slots, pause, stop, crash retry, and the drawers all apply unchanged.
- Effective priority and aging apply to jobs too.

Against:
- `REJECTED` means "redo the research" rather than "fix the code", which the
  prompts must explain.
- The graph gets busier; a kind filter will be needed.

### Option B: a separate job queue per system

Jobs live in their own store with a smaller lifecycle and their own page.

For: cleaner semantics; nothing in the engineering graph changes.
Against: a second scheduler, a second UI, and no dependencies between research
and code.

**Recommendation: A.** The survey-guides-implementation example is exactly a
research job that code tickets depend on.

---

## 4. Catalogs

A catalog is a named collection of documents. Each document is a markdown file
with a small frontmatter record (id, title, author role, status, created,
updated, tags). Catalogs live under the project state, each catalog its own git
repository, so every change has a diff and an author.

Tools, granted by permission:

| Tool | Permission | Meaning |
|---|---|---|
| `catalog_list`, `catalog_read` | read | Browse and read documents. |
| `catalog_write` | write | Create or update a document as a draft or finding. |
| `catalog_propose` | write | Submit a document for the lead's decision. |
| `catalog_decide` | decide | Mark a document `decided` or `rejected`, with a note. |

Permissions are per role per catalog. Typical shape: every role reads most
catalogs; members write to their own system's catalogs; only the lead decides.
Other systems treat `decided` documents as settled input. A design decision is a
decided document in the design catalog; a product value proposition is a
decided document in the product catalog.

Two catalogs are special because they are also code:

- **Acceptance tests.** QA's output enters the merge gate the only way code
  does: QA creates *code tickets* carrying the tests, which are reviewed and
  gated like any change.
- **Reference and performance tests.** The Lab's reference survey becomes tests
  the same way, through code tickets, so the gate owns them.

---

## 5. Communication

A strict tree:

- A member talks only to its lead.
- A lead talks to its members and to the Supervisor.
- Leads talk to each other only through the Supervisor, or through decided
  catalog documents.

Implemented as a `send_to(role, note)` tool that queues a wake-up, with the tree
enforced in the store so a tool call outside it fails and says why. The explorer
story is the argument for the tree: moving user studies under the Product Owner
improved outcomes because the decision-maker received the raw input.

---

## 6. Scheduling and sessions

Each role declares:

- `resident` (one long-lived session, kept alive by the loop) or `ephemeral`
  (a fresh session per job or per wake-up, closed afterwards),
- `every` (interval) or `at` (daily time), or neither for purely event-driven
  roles.

A Product Owner at one session per day should be resident and woken once daily
so it keeps its memory. Researchers are ephemeral per job. Resident sessions
grow without bound, so a rotation policy is needed: Pi's compaction, or a fresh
session every N turns seeded from a summary document the role writes to its
catalog before rotating.

---

## 7. Definition and control

Roles and systems become data:

```
<state>/
  systems.json          # systems, members, catalogs, permissions, schedules, capacity
  prompts/<role>.md     # role prompts, editable
  catalogs/<name>/      # one git repository per catalog
```

Built-in roles (supervisor, coordinator, pipeline manager, worker, reviewer)
stay in code but can be overridden by the same data.

Supervisor tools: `create_system`, `update_system`, `delete_system`,
`create_role`, `update_role`, `restart_role`, `delete_role`, `set_permissions`.
Deleting a role archives its sessions the way finished tickets are archived.

Web UI: a **Systems** page showing a tree of systems and roles, each with its
status, last activity, next scheduled wake-up, and pause, restart, and delete
controls. Pause means wake-ups queue rather than drop, so a resumed role catches
up. These are operator controls, like the existing pause and stop.

Prompt quality is the main risk in letting the Supervisor author roles. The
proposal is role **templates** with slots to fill rather than free-form prompts,
at least initially:

| Template | Shape |
|---|---|
| lead | Owns catalogs, decides, delegates jobs, reports upward. |
| specialist | Resident member with domain tools; writes findings; proposes decisions. |
| job worker | Ephemeral per job; produces a catalog entry; reports READY_FOR_REVIEW. |
| reviewer | Judges a job's output against its brief. |
| explorer | Simulates a user against staging; files observations and bugs. |

---

## 8. The Pipeline Manager as the first real System

The Pipeline Manager's requirements fit this design directly and would be the
first build:

- Events: a merge gate run taking more than 2.5 times the recent median, a run
  that entered bisection, a test flaky across N runs.
- A scheduled **daily test run** member: runs the specs quarantined as daily,
  records results in the gate-runs catalog, and the lead files tickets for
  failures.
- Tools: `quarantine_test`, `unquarantine_test`, `get_gate_run`,
  `list_gate_runs`, `resume_pipeline`, `restart_staging`.

---

## 9. Open questions

1. **Jobs as tickets (A) or a separate queue (B)?** Recommendation: A.
2. **Catalog storage.** A git repository under the project state, invisible to
   the code repo? Or inside the code repo under `.orchestra/catalogs/`,
   versioned with the code but then subject to the gate's dirty-checkout rule?
3. **Decision semantics.** Is `decide` a status the lead sets, or an approval
   flow where members propose and the lead accepts or rejects with feedback?
4. **Strict tree, or may leads talk to leads directly?** For example, Product
   Owner to Pipeline Manager about a flaky acceptance test.
5. **Daily roles.** Resident with a once-a-day wake, or fresh ephemeral sessions
   seeded from a catalog summary? This decides how context growth is handled.
6. **Prompts.** Templates with parameters, or free-form text the Supervisor
   writes?
7. **Capacity.** One global pool, or per-system capacity so a lab survey cannot
   starve engineering of the local model?
8. **Reference and performance tests.** May the Lab add tests to the merge gate
   directly, or always through code tickets?
9. **Where the Pipeline Manager's new events live.** Part of this work, as the
   first non-trivial System with a scheduled member, or a separate change?

---

## 10. Suggested build order, once decided

1. Ticket `kind` and job lifecycle; the loop routes jobs to their role.
2. Catalogs: storage, tools, permissions.
3. Systems data model, `send_to` with the tree enforced, per-system capacity.
4. Supervisor tools and role templates; the Systems page with pause, restart,
   and delete.
5. Pipeline System: gate events, daily test run, flaky quarantine.
6. A Product System and a Lab System as the proof that the mechanism is generic.
