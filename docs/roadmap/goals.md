# Goals (the owner, 2026-10-27)

What the owner asked for next, grouped by when it can be built. Each goal has an acceptance test,
which is how it is known to be done. Goals that were already on the roadmap are enhanced here and
linked from their horizon in [README.md](README.md).

**The relationship goes both ways** (the owner, 2026-10-27).

- **From machines to model.** We learn how the system dynamics model arises from the machines in
  the software factory. That gives capacity planning and project verification.
- **From model to machines.** Machines get visibility into the model, so they can improve. A
  machine doesn't define the model, but it can guess how its change relates to it. If the change
  would cause a bad outcome elsewhere in the system, the machine can drop it, or use the
  simulated outcomes to choose between options.

This is closed-loop use of a model of the system being run: Forrester's industrial dynamics
started inside a real factory, and the same idea underlies model-predictive control, model-based
reinforcement learning and "digital twins". G5 is its first step; G10 is the first machine whose
own job depends on it. Each machine's guesses are themselves hypotheses, checked against later
model versions.

**Run the tests with dummy agents.** Acceptance tests run on dummy agents: scripted machines
that cost nothing. Claude on Haiku is used only where a test needs judgement, and such tests are
marked as such. This is goal G1, and every other goal's tests depend on it.

## Now

### G1. Dummy agents that cost nothing
- **What:** a harness in `orchestra-agents` (next to `pi`, `claude_code`, `codex`) that runs a
  scripted agent: it accepts work, edits files, runs commands, calls tools and reports as a
  script says, with no model behind it. Scripts are per role, so a demo or a test can run a
  whole team for free.
- **Acceptance:** the agents demo runs end to end with `harness = "dummy"`: a ticket is offered,
  worked, reviewed, gated and landed, and the Supervisor answers a chat turn, with no API calls
  and no network. Every later goal's acceptance test can use it.

### G2. Reusing git worktrees (optional)
- **Why:** the owner's work repository is 7 GB per worktree.
- **What:** a task-system setting that keeps a small pool of worktrees and resets one for the
  next ticket, instead of creating and deleting one per ticket. The default stays as it is.
- **Acceptance:**
  - with the option on, five tickets in a row use at most N worktrees;
  - each worktree starts clean, on the ticket's branch from the base;
  - nothing from a previous ticket leaks in: untracked files are removed and ignored files are
    kept or removed as configured;
  - with the option off, behaviour is unchanged.

### G3. Custom worker types
- **Why:** specialised workers (frontend, backend, operations, Slack messaging) with their own
  tools and prompts.
- **What:**
  - **Task system:** a ticket can ask for a kind of worker, and the scheduler offers it only to
    that role.
  - **Agents:** roles with their own prompt and tool groups (custom roles exist; make them
    fillable as task-system workers).
  - **Configuration:** it lives in `orchestra.toml` and the agents' role files, is viewable on
    the web, and is not editable there. The Supervisor changes it with its config tools.
- **Acceptance (dummy agents):**
  - a `frontend` ticket and a `backend` ticket are each offered only to their role, and each is
    worked by an agent with that role's prompt and tools;
  - the web shows each worker type's configuration read-only;
  - the Supervisor, asked to add an `ops` worker, does it through its tools and the change is
    committed and announced.

### G4. A Supervisor and Coordinator who know how to change Orchestra's settings
- **What:** they know the integration contract: [USING_ORCHESTRA.md](../../USING_ORCHESTRA.md)
  (metrics, machines, configuration), [PLUGINS.md](../../PLUGINS.md), and the task system's
  worker contract. They can read these docs through their tools, and their prompts say when to.
- **Acceptance:**
  - **Dummy:** the docs are reachable through their tools.
  - **Haiku, marked:** given "add a collector for X", "connect my service's /metrics" or "add a
    backend worker", the Supervisor picks the right mechanism and the result runs.

### G5. Agents use the system dynamics model (phase 1)
- **What:**
  - **Tools:** agents can read the model and simulate a change: "if this flow's rate changed
    so, what do these stocks do?". A worker can state, before its work, which flows it expects
    to change, and a later version of the model checks the guess.
  - **Guidance:** agents learn what good stock and flow metrics look like and how to add an
    emitter (`docs/machines.md`, USING_ORCHESTRA.md §3–4), since agents implement new metrics.
  - **Focus:** domain stocks the target repository emits come first; the task system's own
    stocks matter mostly to a pipeline manager (G9).
- **Acceptance:**
  - the simulate tool's output matches `orchestra sd` on a known model (the bakery);
  - a dummy worker records an expected-effect note, and the note is compared with the next
    model version.

## Next

### G6. Pull requests tracked to resolution, and external review
- **What:**
  - **External review:** a path the task system can take instead of its own merge gate. The
    ticket's work becomes a pull request, and the ticket follows it until it is merged or
    closed.
  - **Who opens it:** the owner submits to the company's CI/CD by hand; nothing pushes to it
    without the owner.
  - **Watching:** a poller follows the pull request's state: reviews, review comments, change
    requests, labels (e.g. SAIL passed or failed), checks and merge.
  - **Acting:** it publishes these as events, and re-engages the worker that wrote the change
    (resuming its previous Claude or Codex session where possible) when comments, change
    requests or a failing label arrive. Review comments are handled on the ticket, not as new
    tickets, unless a rule says so.
  - **States:** this may add states such as `IN_EXTERNAL_REVIEW`, or it may be an alternative
    to the gate. The design decides, written down before building.
- **Acceptance:** in a private sandbox repository on GitHub (an e2e project made for this),
  with dummy agents:
  - a ticket's pull request receives a "changes requested" review with comments; the same
    worker addresses them on the same branch, and the pull request is updated;
  - a label set by hand re-engages the worker;
  - an approval and a merge close the ticket.

### G7. Pull-request trees with git-spice
- **What:** stacked and diverging branches, rebased often (decision D8, memory "PR trees"),
  so dependent tickets build on each other's branches.
- **Acceptance (sandbox repository):**
  - a ticket that depends on another branches from it;
  - when the first changes, the second is restacked;
  - both pull requests show the right base.

## Horizon (to be planned)

### G8. The owner's work loop, end to end (use case UC-6)
- **Why:** the biggest value for the owner's work. Each step below is first tracked (who asked,
  where, which ticket, which pull request, who reviewed, what is waiting on whom), then
  automated where it can be. Steps that speak as the owner go through an outbox with the owner's
  approval (H3).
- **The loop:**
  1. A request arrives on Slack and is expected within about 2 hours.
  2. A Jira ticket is made from a template: type, label, reporter, assignee, points, project,
     the current sprint, and links.
  3. The Jira link is posted in the Slack thread.
  4. The ticket moves to In Progress, and a branch is made with `arc feature`.
  5. The change is made and tested.
  6. A pull request description is written from the template, with the test output and within
     the length limit.
  7. The AI review agent reviews it, and the pull request is opened.
  8. Reviewers are chosen, and "RR: <link> cc: @person" is posted in the right channels and in
     the requesting thread.
  9. If no review comes within a day, the request is posted again.
  10. Comments are addressed, in a loop until enough approvals.
  11. A final risk review decides whether to stake the owner's reputation on it, what the risks
      are and who must be told.
  12. The SAIL label is added, and the result is awaited. A failure loops back.
  13. On merge, the requesting threads are told.
- **Needs:** G6 and G7, the Slack bridge (built; branch `slack-bridge`), a Jira bridge (event
  sources phase 3), the outbox, and a template and identity configuration (D10: the owner's,
  never core).
- **Acceptance:**
  - against fakes of Slack, Jira and GitHub that speak the real protocols, a request on the fake
    Slack becomes a merged pull request with every message and transition above, each waiting
    on the right person, and the model carries the "2 hours" promise as a stock;
  - a real run is then done with the owner's approval of every outward message.

### G9. A notification and communication plugin; ad-hoc request tracking
- **What:** keeps the chains of communication (requests, replies, who is waiting on whom) even
  where nothing is automated.
- **Builds on:** the Slack bridge's pings and the 15-minute (here, 2-hour) promise.
- **Acceptance:** to be written when planned.

### G10. A pipeline-manager agent
- **What:** one of the few agents that cares about the task system's own model. It uses the
  model to check whether its fixes to the pipeline work, and to find what drives, say, a long
  merge-gate time.
- **Needs:** G5 and the model's version comparisons.
- **Acceptance:** to be written when planned.

## Status

| Goal | Status |
|---|---|
| G1–G5 | In progress from 2026-10-27 |
| G6–G7 | After G1 and G3 |
| G8–G10 | To be planned |

Related work already in flight (2026-10-27):
- agent tool permissions enforced;
- the task system's sharp edges;
- events over HTTP without the library;
- `[[scrape]]` machine and instance labels, and plugin-declared scrapes.
