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
  - **Tools:** agents can read the model and simulate a change. The owner (2026-10-27): the
    "what if" is not "scale this flow"; the agent looks at the model, guesses the impact of its
    change, and writes it as flow equations removed, rewritten whole or added, over any stocks and
    variables, one edit at a time or as a whole diagram, until the outcomes it expects follow from
    equations that semantically justify them. Not only agents: any machine may. A worker can
    state, before its work, which flows it expects to change, and a later version of the model
    checks the guess.
  - **Guidance:** agents learn what good stock and flow metrics look like and how to add an
    emitter (`docs/machines.md`, USING_ORCHESTRA.md §3–4), since agents implement new metrics.
  - **Focus:** domain stocks the target repository emits come first; the task system's own
    stocks matter mostly to a pipeline manager (G9).
- **Acceptance:**
  - the simulate tool's output matches the model's own simulation on a known model (the bakery);
  - a dummy worker records an expected-effect note, and the note is compared with the next
    model version.
- **Phase 1 built (2026-10-27) in Orchestra's core: experiments** (SPEC §4.5,
  `orchestra/sd/experiments/`). An equation language every flow's rate is read and written in
  (every equation discovery writes renders in it and round-trips); a staged draft of the model a
  machine edits in checked, atomic batches (add, rewrite or remove flows; hidden stocks;
  parameters; input scenarios; a whole model) with each equation's origin recorded; three runs:
  **forward** (base and draft from now, with the band, limits and trust flags of the former what-if,
  whose run matches `sd.simulate` on the bakery), **replay** (a past window on its measured
  inputs, each equation scored against its counter: the backtest and the counterfactual replay)
  and **inverse** (G16); and **commit**, which makes the experiment a G13 prediction. Served to
  any machine by the HTTP API beside the events endpoint and the Python API, and read-only on the
  web. `orchestra sd whatif` and `POST /api/dynamics/whatif` are gone. **Next:** phase 2, the
  agents' tools (pi or MCP) and a skill explaining them, in `~/orchestra-agents`; phase 3, the
  web pages that show experiments and their runs.
  **Superseded 2026-11-01 (the owner): the declared layer and predictions.** The owner's way to say what a change should do
  is the declared layer's expected effects and `orchestra.prediction.made`; the Experiments page
  (phase 3) was removed, and then, the same day, the rest of the experiments with their APIs and
  the agents' tools (D41's stage 2): the equation language and the forward run stay in
  `orchestra/sd/equations/` for prediction judging.

**The Workflows run (2026-11-01): G17–G22.** Written by the coordinator's run from the four reviewed proposals and the task table of
[GOAL-2026-11-01-workflows.md](GOAL-2026-11-01-workflows.md) (milestones M2–M5), following D21;
for the owner to confirm. Each acceptance list names the proposal's test numbers, which hold the
exact wording. The run's defaults behind them are D22–D40 in [decisions.md](decisions.md).

### G17. The intended model in the core, and the two pages (M2: C1–C3, C5)
- **Why:** the owner: "Right now, both of those show only what truly exists. It doesn't have the
  concept of a tentative or proposed change. There are two types of tentative changes - user
  created and AI inferred. The user created one has precedence, but it's not real until the user
  confirms it."
- **What** (`docs/proposals/intended-model.md`):
  - **C1, the store and API:** the declared layer in the model store as `dN` versions beside the
    discovered `vN` (`ModelStore.intended()`, `project.intended`): declared stocks, effects,
    flows, targets, expected marks, machines (the envelope only; `spec` stored unread) and event
    types; proposed, declared and observed states; parts matched by key; the expected set;
    "changes since vN"; provenance on every element and an id on every change; `apply`, `read`,
    `diff`, `design`; the page's observations and requests; `orchestra.intent.changed` and
    `orchestra.intent.requested`; simulated parts marked in `vN`. It runs nothing.
  - **C2, the Dynamics page:** D1 (the ghost stock, the Expected group, "How to measure it" from
    what the plugin recorded), D2 (the changes-since switch, new and removed marks, the Changes
    panel, the legend), D3 (the expected switch, the pin).
  - **C3, the Machines page:** E1 (the unconfirmed machine, the highlight and its two shades, the
    details panel with the Universal and Programmatic forms), E2 (the live diff marks), E3 (ad hoc,
    continuous, external; the kind row apart from the engagement tabs).
  - **C5:** the existing cases still hold, and SPEC and AGENTS.md carry the amended rules 2, 4,
    5, 6, 7 and 9 and rule 3's list (intended-model.md §8), each stated in the commit.
- **Acceptance:**
  - intended-model.md §10 tests 1–31: one journal line and one `dN` per call, all ops or none
    (422 with the index); past versions unchanged and numbered without gaps; provenance kept; the
    envelope checked and `spec` stored as sent; a declared stock with no series is an absent,
    unmeasured expectation and changes no discovered stock; discovery's body identical with and
    without a declared layer; new, removed, settled, came-and-went and ignored by key, including a
    renamed collector and an era's prior; candidates never matched automatically, `link` alone
    sets `found_as`; the control endpoint accepts exactly the observations and the request
    endpoint publishes one request and writes no `dN`; simulated parts marked, skipped by
    verdicts and targets, gone after expiry; each call announced once; derived fields refused;
    `rises`/`falls` judged by slope; flow and stock targets on their means; the E1 highlight
    opacities; the Core page answers with `intended/` broken (rule 8);
  - test 32: the real pages, fed C1's answers for the fixtures in `mockups/fixtures/`, render
    each frame of intended-model.md §7, compared with `mockups/out/D*.png` and `E*.png` (with
    §7's corrections), and pass `ux-review` on the demo;
  - C5: `model-acceptance` on UC-1–UC-3 scores no lower than before; `subtraction-audit` on the
    core.

### G18. Instruments attached to declared machines (M2: C4)
- **Why:** the owner: "Because the Machines aren't likely to emit their actual metrics, and
  because we would want to incorporate and model existing machines, we need to attach our
  measurement instruments to Machines."
- **What** (`docs/proposals/instruments-on-machines.md`): an attachment (a declared machine, an
  instrument, an optional match and instance label) recorded in the declared layer; measured
  instances per attachment within a cadence window; the metrics store's new `recent()` (a backend
  contract change); "Measured by" in the machine's panel and "hung on" on the Instruments page.
  Being measured never makes a machine seen or active, never binds a flow, and changes no point
  or model (rules 2 and 7 amended in wording).
- **Acceptance:** instruments-on-machines.md §6:
  - unit, tests 1–14: an attachment recorded in a new `dN` with the store and `orchestra.toml`
    unchanged; refusals with reasons; discovery equal with and without attachments, and
    `sd.attribute` importing nothing of the intended model; `recent()` conformance on every
    backend; measured, never heard, never active; instances, the window, the cap, two spellings of
    one replica, one scrape on two machines, aliases; the store down answered in time; no page
    control writes an attachment;
  - end to end, tests 15–17, on the agents' demo with a declared external `postgres` and a
    `[[collect]]` of `pg_connections{server}`: measured with two instances, then three; hung on
    `postgres` on the Instruments page; no flow hypothesis names it after discovery.

### G19. The Supervisor declares, measures and drafts (M3: A1–A3)
- **Why:** the owner: "These configurations are complicated and annoying. I don't want to do
  them. I want the Supervisor to set up my environment."
- **What** (`docs/proposals/machine-design.md`, in `~/orchestra-agents`): the Supervisor's `design`
  tools (`declare_stock`, `declare_effect`, `set_target`, `propose_measurements`,
  `add_instrument`, `keep_instrument`, `match`, `mark_expected`/`ignore`, `rediscover`,
  `declare_machine`, `refine_machine`, `declare_event`, `declare_expected_effect`,
  `confirm`/`discard`, and `read_design`); writes to the state directory and the overlay, never
  the base branch; the draft namespace; the clearance check for company systems; answering the
  owner's page requests; the refinement passes (`refine_map`); prompts and the guide (A2): never
  ask the owner to edit a file; the owner's scenario live (A3).
- **Acceptance:** machine-design.md §7, with the fake Claude unless marked:
  - tests 1–17: each tool refuses a missing reason, an invented quote and any caller but the
    Supervisor; against a real empty Orchestra, one turn leaves the script at the state path, its
    entry in the overlay, a stored point in the draft namespace and no commit on the base branch;
    choosing an option changes nothing else; refusals before anything is written; the simulated
    and draft lifecycles; `needs approval` and no credential anywhere; `match` with origin
    `declared`; every field of each kind recorded, no AI terms in a Universal declaration;
    six-edit refinements all or none; the expected effect published only at confirm, as
    `supervisor`, tied to the `system.changed` of the agent's first turn; a page request confirmed
    by the Supervisor with nothing committed; one refinement proposal with three findings; no
    prompt or reply asks the owner to edit configuration;
  - test 18: the six turns of machine-design.md §2.6 with the fake Claude on the agents' demo
    with `--dummy`, after which P2's API answers the D1, D2, D3 and E2 shapes; again with
    `[agents] tools_via = "bash"`;
  - test 19, **live, marked** (A3): turns 1, 3, 4 and 5 to a Supervisor on Haiku (Sonnet on
    failure) with the narrowed tool set; Features declared with at least one point, the
    improver's receives and its 00:00 schedule as the owner said, its expected effect present;
    transcripts saved, D1 and E2 screenshots kept, under $10.

### G20. AI workers cannot push or merge (M3: A5)
- **Why:** AI workers run with the user's credentials, and only the prompt said "do not push"
  (notes §12); at work the base branch is protected.
- **What:** the harness gives worker and reviewer sessions a git environment in which `git push`
  to any remote fails and `gh pr merge` and `gh pr create` are disallowed: a configuration-level
  block, not only the prompt; configurable off per project for machines that are allowed to; the
  Supervisor's guide says so.
- **Acceptance:** an end-to-end test where a worker session runs `git push` and `gh pr merge`,
  sees both refused, and the refusals are in its transcript.

### G21. The Workflows plugin: the record, piles, the floor, definitions, the task loop (M4: W1–W7)
- **Why:** D21: the task system was a prototype, replaced by "a Workflows system" that handles any
  company's workflows; "the ability to actually launch and setup Machine instances" is what must
  remain.
- **What** (`docs/proposals/workflows.md`, the new private repository `~/orchestra-workflows`):
  - **W1** the repository and its rules (no `task.*` names, the import boundary), the machine
    contract; **W2** the record: per-item logs of facts, recorded exactly once by event id, folds
    order-independent per field, snapshots and the index, closing and deleting, the bus's gaps;
    **W3** piles: step piles and their moves by construction, declared piles, wait reasons, the
    `workflows.piles` instrument; **W4** the floor without workflows: requests and `every` items,
    offers, claims, leases, capacity with preparations, take-backs, attention, resources with the
    worktree kind, the program host, the reference machines; **W5** definitions: the loader, the
    vocabulary as §7 scopes it, the position view, `all` fan-in, dependencies, metric conditions,
    access; **W6** the task loop as example 1 with its one-command demo; **W7** the Items, Piles and
    Workflows pages (read-only) and the Supervisor's `declare_workflow`.
  - **Asked of the core** (not in this run's table): file-bus rotation with `EventBus.start()`;
    provenance from plugin collectors; `pile` as a place of construction. The plugin works without
    them.
- **Acceptance:** workflows.md §12.2 tests 1–23:
  - W1 (1): the suite exits 0, `GET /api/plugins` lists `workflows`, the import boundary is tested;
  - W2 (2–6): exactly the non-excluded facts of the measured run's fixture recorded; 200
    permutations fold equal; a crash at every point of a tick gives the uninterrupted logs; a gap
    reported, nothing invented; closing and deleting; the measured budgets (a year under 10 MB,
    the index rewrite under 100 ms, the 9,118-event run under 5 s, a 2,000-fact fold under 50 ms);
  - W3 (7–9): each pile gauge equals the index and its change equals moves in minus out; discovery
    records step piles `by_construction` (until then, exactly balanced levels) and no stock from
    declared piles or ages; each wait reason from a scripted case;
  - W4 (10–16): one claim wins; take-backs within lease plus a tick; capacity never exceeded
    across 100 items; the worktree held across a pass-on and freed on a take-back; no half-claimed
    unit after a crash; role-only and `every` items; offers as `coordinator/dispatch`, no source of
    the plugin's own; a machine written only from `docs/machine-contract.md` completes ten offers;
  - W5 (17–21): the loader's refusals, one sentence each; a two-step workflow with rework to the
    same instance; `all` fan-in, a dependency, a cycle raising attention; metric conditions with
    the duration, the gap and the recorder fact; access, and the drift test;
  - W6 (22): ten items through the task loop on the reference machines with one rejection and one
    gate conflict; the three checks of use-cases.md (UC-7 onward) pass; the Machines page shows
    worker, reviewer, merge_gate and coordinator with the hand-offs worker → reviewer →
    merge_gate;
  - W7 (23): every `POST`, `PUT` and `DELETE` under `/api/plugins/workflows` answers 405;
    `ux-review` on the demo.

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

### G22. The example workflows (M5: X1–X7; use cases UC-7–UC-13)
- **Why:** the owner: "We want some examples of how people would actually use this, and we want
  them tested." The examples are the Workflows plugin's suite and its documentation at once.
- **What:** one tiny target repository per example under `~/orchestra-workflows/examples/`, each
  with its own `.orchestra/`, scripted machines on the dummy harness and fake bridges, in this
  order: X1 the owner's delivery through the company gate (UC-7), X2 team review (UC-8), X3
  on-call (UC-9), X4 release-candidate verification (UC-10), X5 hotfixes across release branches
  (UC-11), X6 staged rollout (UC-12), X7 customer-owned deployments (UC-13). The vocabulary words
  left for later (`any`, `count ≥ n`, field equalities, person offers; workflows.md §12.1) are
  built with the example that first needs them.
- **Needs:** G21 through W6.
- **Acceptance:** each example's one test passes its three checks (piles over time match the
  script; `model-acceptance` finds its stocks, flows, loops and domain series and nothing on its
  forbidden list; the event map shows its declared machines and hand-offs and nothing of the
  plugin's infrastructure), plus the case's own check in use-cases.md; `layered-review` once on
  the set. In the run's order of sacrifice M5 goes first: an example not built is reported, not
  dropped from this list.

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

## Leverage: machines improving the system through its model (the owner, 2026-10-27)

The control-engineering half of "both ways": machines change the system, and the model says whether
the change did what was intended.

### G11. Eras: a new era when a machine changes the system
- **What:** when a machine changes how the system works, a new era begins. Examples: a prompt or
  role edited, a configuration changed, a worker kind added, a deploy. The model is fitted per
  era, so the eras can be compared.
- **An era is the analysis window** (the owner): both the event map and the model's equations are
  determined from the era's own data. The previous era's model is the prior for the new one (D4):
  early in an era, discovery starts from it and the era's own evidence takes over as it accumulates.
  Where they disagree is what the change did.
- **Who marks it:** the change is announced by the machine that made it, as an event on the bus.
  Orchestra knows no domain (rule 1), so which event types start an era is configuration, plus
  the generic events Orchestra already sees, such as `config.changed`.
- **Acceptance:** a change event starts an era. Discovery fits the eras separately, and the
  Dynamics page shows them on a timeline. A rate that changed at an era boundary is reported as
  changed, with before and after values.
- **Decided (the owner, 2026-10-27):** an era is the analysis window. Within it the event map and
  the model are determined from its data only; the previous era's model is its prior (D4), and the
  era's own evidence takes over as it accumulates. Parts in only one era are reported as appeared
  or disappeared at the boundary.
- **Built (2026-10-27):** `system.changed` always begins an era, and `[discovery] eras_from`
  names more by envelope (default `config.changed`); the host records and announces them
  (`orchestra.era.started`); discovery reads only the current era, merges it with its prior and
  compares the two (SPEC §4.3, `sd/eras.py`, `sd/prior.py`, `sd/compare.py`); the Dynamics page has
  the timeline and each flow's change, the Machines page's map is per era, and `GET /eras` on the
  events endpoint lists them for machines (the `orchestra sd eras` command was removed on
  2026-10-27).

### G12. The model says when it changes, and when reality leaves its predictions
- **What:** Orchestra publishes events of its own:
  - **a structure change:** a stock, flow or loop appeared or disappeared;
  - **a divergence:** observed levels left the predicted band for longer than a set time.
  
  Other machines can listen. The pipeline manager (G10) and the Desk would. While the model
  still churns, the events are rate-limited, so they don't fire on every flip.
- **Acceptance:** a scripted change to a dummy-run system produces exactly one structure-change
  event. A system pushed off its prediction produces a divergence event naming the stocks and
  the size of the gap.
- **Built (2026-10-27):** `orchestra.model.changed` (held over `[discovery] announce_hold`
  discoveries, at most one per `announce_gap`), `orchestra.model.diverged` and `.returned` (a
  stock out of its predicted band for `diverge_after`, the gap in half-widths of the band); SPEC
  §4.3, `sd/announce.py`, `sd/diverge.py`.

### G13. The intended-effect test: "better than evals"
- **What:** a change states its predicted effect before it is made, as a "what if" (G5) on the
  current model, and the prediction is recorded with its horizon. When the horizon passes, the
  system is rediscovered for the new era and judged by `docs/rationale/lifted-models.md` §3.1:
  - **passed:** the predicted edit appears and the stocks move as simulated;
  - **model wrong elsewhere:** the edit appears but the stocks don't move as simulated;
  - **no effect:** no edit appears;
  - **side effect:** a different edit appears.
  
  The null test (§3.2) covers changes that should not change behaviour.
- **Acceptance:** with dummy agents, a scripted change that really improves a rate is judged
  passed; one that changes nothing, no effect; one that moves another stock, side effect.
- **Built (2026-10-27)** in Orchestra's core. A machine publishes `orchestra.prediction.made`
  (an Orchestra type whose `data` Orchestra reads, as with `orchestra.machine.started`) naming the
  id its change will carry, the expected edits (a flow's factor, unchanged, a part appearing or
  disappearing, a stock's level; `[]` is the null test), the horizon and optionally its own
  forward run; `sd.predictions.Predictions` and the Supervisor's `confirm` publish it (the
  `orchestra sd predict` command was removed on 2026-10-27). The host
  matches it to the era its change begins, judges it after the horizon against the boundary
  comparison (a form change by whether the old law still predicts the count) and the stocks'
  run from the previous era's model with the edits, and publishes `orchestra.prediction.judged`:
  passed, no effect, side effect (naming what), model wrong elsewhere, interrupted or undecided,
  with the threshold and the false-change rate measured between the previous era's halves. The
  Dynamics page shows the verdicts under each era; `orchestra sd predictions` lists them (SPEC
  §4.3, `sd/predictions.py`, `sd/verdict.py`, `sd/judge.py`). Accepted on a synthetic pipeline with
  known rates (`tests/unit/test_predictions.py`: each outcome, the null test, an interrupted
  era) and end to end on a real `orchestra run` with a scripted machine that predicts over the
  events endpoint (`tests/e2e/test_predictions_e2e.py`, opt in). Not yet on the dummy agents
  themselves: that test belongs in `orchestra-agents`, beside its eras e2e.
- **Extended (2026-10-27): equations as predictions.** A prediction may expect a flow's whole
  equation (`{"flow", "equation", "params"}`), judged by its law: the predicted equation, run over
  the era's measured levels and inputs, must predict what the era counted. On the
  synthetic pipeline, a doubled rate written as new numbers or as a new equation passes, and a
  wrong equation is a side effect (`tests/unit/test_predictions.py`). (Committing an experiment
  stated its edits this way until experiments were removed on 2026-11-01.)

### G14. Test health as instruments
- **What:** counts of tests by kind (unit, acceptance, e2e) and by outcome (passing, failing,
  skipped, flaky), confirmed acceptance and e2e tests, and the merge gate's reruns of flaky tests.
  - **Instruments:** a script reading the test runner's report (JUnit XML or pytest's), supplied
    for the target repo; the task system adds gate reruns to its own instrument.
  - **What the model shows:** growth in tests is a stock, and a regression shows as a drop or a
    rise in failures.
- **Acceptance:** on the sample, adding e2e tests raises the e2e stock, breaking one shows a
  regression, and a flaky test that the gate reruns is counted.
- **Built (2026-10-27).**
  - **The instrument** (`orchestra/instruments/test_reports.py`, USING_ORCHESTRA.md §3.4), one
    `[[collect]]` entry, standard library only. It reads JUnit XML and pytest's report log and prints
    `tests{kind}`, `test_outcomes{kind,outcome}`, `tests_flaky{kind}`, `tests_confirmed{kind}`,
    `tests_duration_seconds{kind}` and `test_report_files{state}`. With `--history` it also prints
    the counters `tests_added_total{kind}` and `tests_removed_total{kind}`, which balance the test
    count. Kinds are told by path glob, `path::name` or marker.
    - **Flaky:** failed and passed within the stream's last `--window` runs, or passed on a rerun.
    - **Confirmed:** passed in each of its last `--confirm` runs, none flaky.
  - **The gate** (`orchestra-tasking`). `[gate] rerun_failures = N` reruns a failed stage spec, and
    a pass on a rerun lands, marked flaky. Each run's reports are kept, with `gate.xml` for its
    stages. The record counts `tasks_gate_runs_total`, `tasks_gate_reruns_total` and
    `tasks_gate_flaky_stages_total` through `tasks.tickets`. A second plugin instrument,
    `tasks.tests`, runs the test-report instrument over the gate's reports.
  - **Accepted** end to end in `orchestra-tasking` (`tests/e2e/test_test_health_e2e.py`), through a
    real `orchestra run` with the demo's shell worker:
    - three e2e tests landed raise the e2e count from 1 to 4;
    - a broken test shows a failure;
    - a test failing on its first run lands on the rerun, counted flaky by the record and the
      instrument.
  - **Run mode and absent kinds (2026-10-28).** `--run CMD` runs the tests itself and reads the
    fresh report (pytest's markers recorded by an injected plugin), printing the run's result and
    no test series when it wrote none; `--max-age` for `--reports`. A kind a current run does not
    have prints nothing, never zeros (absent is not zero).
  - **Discovery:** a replay (`tests/unit/test_test_reports_discovery.py`) finds the e2e count a
    stock balanced by tests added and removed (R² 1.0).
  - **Not yet:** the run on the dummy agents themselves. That test belongs in `orchestra-agents`,
    as G13's does.

### G15. A self-improving worker kind
- **What:** story 1's R-learning loop made real.
  - **The curator:** a configured agent maintains a worker kind's prompt and playbook (G3), e.g.
    the "frontend" worker's. It learns from rejected and reworked tickets.
  - **Each edit:** starts an era (G11) and carries a prediction (G13).
  - **The outcome:** the worker kind's first-try pass rate. Its stock is the playbook, measured by
    its size and its freshness against the code.
  - **The model** shows the learning, decay and overload loops, and whether each edit helped.
- **Needs:** G3, G11 and G13, and the agents' "what if" tool (G5).
- **Acceptance:** with dummy agents whose success depends on a playbook file, the curator's edits
  raise the first-try rate. The intended-effect test passes for a helpful edit and fails for a
  useless one.

## Causality

### G16. Exploring causality
- **Why:** a model fitted to what happened says what moves together; acting on it needs what
  causes what. The owner (2026-10-27): "if we did last month again but our profits were 50%
  higher, what else would have needed to be true?", with the warning that such a search
  optimises isolated changes, and data faked to fit them may not be faked fully, especially where
  there are unintended but acceptable side effects.
- **What:**
  - **Inverse experiments** (built, the first part; removed 2026-11-01, superseded by the declared layer
    and predictions): targets over a past window and what must
    hold; the smallest set of changes to the model under which a replay meets them; the side
    effects, the near-optimal alternatives, and a fabricate-and-rediscover check of whether the
    data would tell the solution from another.
  - **Counterfactual replay** (built; removed 2026-11-01 with the experiments): a past window run again with other equations, on its own
    measured inputs, scored against what happened.
  - **Era boundaries as natural experiments:** every announced change is an intervention; the
    boundary comparison (G11) and the verdicts (G13) are its readout, and the false-change rate
    measured between an era's halves is the noise floor any claimed effect must clear.
  - **Probes:** designed perturbations (persistent excitation in control terms): a machine varies
    something on purpose, within safe bounds, so that the flows it touches can be identified
    rather than inferred from whatever happened to vary. A probe is a change predicted with its
    own horizon and a planned return.
- **Acceptance:**
  - (built) on synthetic data from a known model, an inverse run asked for a target the true
    change produced recovers that change as the sparsest solution and reports its side effects;
    an impossible target is reported unreachable with the best approach; an ambiguous one is
    flagged; the solver keeps its deadline (its tests went with it on 2026-11-01);
  - (built) the true equation scores better in replay than a wrong one on data it made
    (likewise removed on 2026-11-01);
  - (to come) a probe on the dummy-agents system identifies a flow's rate that ordinary operation
    leaves unidentified (the observability report says undetermined before, determined after);
  - (to come) the effect of each era boundary on the dummy-agents system is reported with the
    measured false-change rate, and an effect below it is said to be indistinguishable from noise.

## Status

| Goal | Status |
|---|---|
| G1–G5 | In progress from 2026-10-27; G5's phase 1 (experiments in the core) built 2026-10-27, phase 2 (agents' tools and skill) built; phase 3 (web pages) built; all three removed 2026-11-01, superseded by the declared layer and predictions |
| G6–G7 | After G1 and G3. Written for the task system, which D21 replaces with the Workflows plugin (G21); to be restated against the floor once it runs, for the owner to confirm |
| G8–G10 | To be planned; G8's loop is written as a workflow in UC-7 (G22's X1), on fakes |
| G11–G12 | Built 2026-10-27 in Orchestra's core: eras with the previous era as the prior, the boundary comparison, the model's own events |
| G13 | Built 2026-10-27 in Orchestra's core: predictions recorded on the bus, judged per era by lifted-models §3.1, `orchestra.prediction.judged`; equation expectations added the same day (committed experiments too, removed 2026-11-01); the dummy-agent e2e is still to be written in `orchestra-agents` |
| G14 | Built 2026-10-27: the test-report instrument in Orchestra, the gate's reruns and test reports in the task system; the dummy-agent e2e is still to be written in `orchestra-agents` |
| G15 | After G3, G11 and G13 |
| G16 | Inverse experiments and counterfactual replay built 2026-10-27 (with G5's phase 1); removed 2026-11-01, superseded by the declared layer and predictions; natural experiments and probes to come |
| G17–G18 | Planned 2026-11-01 (M2 of the Workflows run); proposals 2 and 5 reviewed and merged; C1 dispatched |
| G19–G20 | Planned 2026-11-01 (M3); proposal 4 (G19) reviewed and merged; A1 and A5 dispatched |
| G21 | Planned 2026-11-01 (M4); proposal 3 reviewed and merged; W1 running |
| G22 | Planned 2026-11-01 (M5, after W6); the first milestone given up if the run is short |

Related work already in flight (2026-10-27):
- agent tool permissions enforced;
- the task system's sharp edges;
- events over HTTP without the library;
- `[[scrape]]` machine and instance labels, and plugin-declared scrapes.
