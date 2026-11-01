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

**That result does not hold at the live demo's 12 h window.** Two minutes after this was deployed
(2026-10-27 05:12), the live discovery took the San Francisco tide for a stock again, "driven" by
California's power demand, and kept it for 32 minutes (model versions 2–8) until its collector
stopped; replayed on the same code at 12 h, it survives every refutation above (R² 0.92 ending
05:12, 0.93 ending 05:32). The refutations were measured at 4 h and 6 h only. In production the
layer is active and wrong, and it is a candidate for removal.

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
Expected inputs: the Yelp rating, read by the arrivals flow directly or through
`customer_demand_per_min` (it is a mean of recent reviews, not a conserved quantity, so it is an
input until the model has auxiliaries; the bakery publishes its own demand formula, the rating
squared, as that gauge (D15), and discovery rightly reads the nearer input: U1, 2026-11-01).
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
The busy flags are never stocks either: the head chef's `bakery_chef_busy` is balanced exactly by
inspections started less inspections done when the head chef's writes line up with the board's
on the grid (97.5% of steps on 2026-11-01 09:11, 100% in U1's run, under 97% in rerun 2: the
grid's flag check, at its edge), but its items are the orders inspecting. A level of 0 to k that
reads what its counters imply, holds no more than another stock, whose items leave by that
stock's outflows, and whose start the stock's own writer counts (and no other stock's flow) is
that stock's capacity of k (`sd/capacity.py`), judged on the series' own writes so the outcome
is the same at every step: left out, and shown in the orders inspecting's drawer as capacity k
with the share of time busy. The servers are a parameter of the one stock, not a second stock
(U5). A count of servers stays a stock when another machine's instrument counts its starts
(UC-3's `agents_working{role}`: the agents' turns beside the tickets in review are the agents'
stock, and who serves which flow is a hypothesis), and when the server reports later than a
write interval after the stock's writer (not resolved).

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
Expected event map: no `task_scheduler` (the task system's scheduler is no machine and publishes
nothing as itself, D17); the worker's queue publishes `task.assigned`/`task.released` as `worker`;
hand-offs read planner → worker → reviewer → worker → reviewer → merge_gate; `worker/1` (package
tasks' demo program) and `reviewer/1` (package agents) answer; `agents` (the host) listens for
`gate.landed`, `review.approved`, `request.done`, `ticket.created`; supervisor and coordinator are
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

## UC-6: the owner's work loop (planned; [goals.md](goals.md) G8)

A Slack request becomes a merged pull request: Jira ticket from a template, the link posted back,
a branch, the change and its tests, a templated description, AI review, review requests (repeated
after a day), comments addressed until enough approvals, a final risk review, the SAIL label and
its result, and the requesting threads told. Run first against fakes of Slack, Jira and GitHub.

Expected stocks: requests waiting for a first answer (the 2-hour promise), tickets in progress,
pull requests awaiting review, comments awaiting an answer, pull requests awaiting SAIL. Expected
loops: an unanswered review request re-posted after a day; comments re-engaging the worker until
approvals suffice; a SAIL failure looping back to the work.

## UC-7 onward: the example workflows (`~/orchestra-workflows/examples/<name>/`)

The seven example workflows of `docs/proposals/workflows.md` §9 (from
`design-backwards-notes.md` §10), written 2026-11-01 for milestone M5 of
[GOAL-2026-11-01-workflows.md](GOAL-2026-11-01-workflows.md), where they are X1–X7 in this order.
The owner: "We want some examples of how people would actually use this, and we want them
tested." X1 and X2 are built (2026-11-01, `examples/delivery_sail`, `examples/team_review`; each
case's status line says what discovery found); the rest are planned for M5 of this run, which is the
first milestone sacrificed if the run is short, so each case below says what it waits on. The task loop
(workflows.md §9 example 1, task W6, acceptance test 22) is the plugin's first example and the
successor of UC-2 once the task system is not installed; it is not a case of its own here.

**What every example shares.** Each is a tiny target repository with its own `.orchestra/`
(definitions, programs, resource kinds, a `[[collect]]` for its domain series), scripted machines
(programs, and agents on the dummy harness: no model, no network), and fake bridges that publish
the outside events on a script as the relayed actors (`bot.github`, `person.owner`), never as the
bridge (D19). One command runs it (proposed: `uv run python -m orchestra_workflows demo <name>`,
as example 1's `demo task-loop`), for its test and for the UX review. The run lasts until every
expected move has been seen at least five times (UC-1's threshold for a flow).

The three checks, the same for every example (workflows.md §9):

1. **Piles over time** match the script: at named moments of the script, each step pile's
   `workflow_pile_items{workflow, pile}` in the metrics store has the count the script implies.
2. **The model** (`model-acceptance`): every step pile is recorded `by_construction` (until the
   core's two discovery inputs exist, a level balanced exactly by its moves); the R² of 1.000 of a
   pile's balance is no evidence and is not scored as one. The expected loops and the domain
   series below are what is scored.
3. **The event map** shows the declared machines and hand-offs; no node, edge or `source` names
   the recorder, the floor or the program host, and dispatch appears as `<planner>/dispatch`
   (D17).

Forbidden in every example: a stock from `workflow_pile_oldest_seconds` or from a declared pile
(they carry the `age` and `aggregate` views); holds by role, or a role's capacity setting, as a
stock; a flow per machine instance; the domain series as a tally of the workflow's own events;
a `<step>.held` pile of a step nothing is offered for (an outside wait), which stays empty, taken
for a stock; a machine node for a metric condition (`metric:<series>` is a recorder fact, never a
source, rule 7).

## UC-7: the owner's delivery through the company gate (M5's X1; `examples/delivery_sail`)

workflows.md §7's SAIL table, the one example that uses every word of the vocabulary. Set aside
by the owner as the generic problem's first target ("we ignore SAIL for now", notes §11); it is
built here as an example on fakes, never against the company's systems. It is the workflow form
of UC-6 and of G8's loop from step 4 onward; the Jira half (`jira-hygiene`) is a second workflow
on the same item, not a step.

Item: a Jira ticket. Starts: `jira.issue.assigned` to the owner. Planner: `supervisor` (so
dispatch is `supervisor/dispatch`). Steps: write (role `worker`, needs a worktree), open the PR
(`person: owner`; the worker drafted the text), ci (outside: GitHub, `head_sha` equal to the item's
`commit`), review (outside: people, `github.pr.approved` count ≥ 2), nudge (role `nudger` drafts,
the outbox sends), sail (the outbox adds the label after approval), sail-check (outside: SAIL's
action), triage-failure (program `sail_triage`).

Script: ten tickets; two CI failures; one "changes requested"; one review left a day (scaled) so
the nudge runs; one company-wide SAIL failure retried; one SAIL failure sent back to write. The
outbox's approvals come from a scripted approver.

Expected stocks: `write.waiting`, `write.held`, `open_pr.waiting`, `ci.waiting`, `review.waiting`,
`nudge.waiting`, `sail.waiting`, `sail_check.waiting`, `triage_failure.waiting` (each
`by_construction`); `jira-hygiene`'s piles apart.
Expected flows: the moves `<start>` → write; write waiting ↔ held; write → open_pr (ready);
open_pr → ci; ci → review (success) and ci → write (failure, rework); review → write (`on`
changes requested); review → nudge (the `within` guard) and nudge → review; review → sail; sail →
sail_check; sail_check → `<end>` (success) and → triage_failure; triage_failure → sail_check
(company-wide, rounds 3) and → write.
Expected loops: rework to the same worker instance (CI failure, changes requested, a SAIL failure
not company-wide); the nudge loop on a stale review; the retry loop through triage; the worker
role's capacity and the worktree pool limiting `write.held`.
The domain series: commits on the example repository's `main` (a `[[collect]]`), whose inflow is
the sail_check → `<end>` move.
Forbidden (beyond the shared list): the approvals counted toward `count ≥ 2` as a stock; the two
workflows' piles summed; a node or `source` for the bridge itself (D19).
Needs beyond W5: person offers, `count ≥ n`, a field equality, the outbox as a `who` (all §12.1,
"built with the examples that need them").
The test: the example's one test runs the script and passes the three checks; the item's page
names, for a ticket after rework, the CI failure fact that sent it back.

**Status (2026-11-01, X1 built as `examples/delivery_sail`, orchestra-workflows branch X12).** Built
on eight tickets in the e2e (one CI failure, not the two planned, its rework preceded by a stale check result for the old
commit that does not count; one changes requested; one review past its `within`; one company-wide
SAIL failure retried; one sent back to write) and judged in process on three simulated hours.
Discovery found: the step piles of write and triage (waiting, held) and the waiting piles of
open_pr, ci, review, sail and sail_check as stocks `by_construction`; the waits' held piles left out
as never changing (no stock, as the shared forbidden list asks); all fourteen moves as fitted flows,
the three rework moves back to write among them; the **SAIL retry (sail → sail_check → triage →
sail) as a feedback loop the core's loop finder names**; the worker capacity as the claim's form
reading `write.held` (on seed 1; on seed 7 it is fitted on `floor_offers`, an input); the domain
series `git_branch_commits{branch="main"}` (SAIL's merges, from git) a stock whose one inflow is
`sail_check → <end>`; nothing forbidden. Short of the bar: the rework cycles through write are
cycles of flows, not loops of influence (a write turn's end is fitted on the oldest item's age, as
in the task loop); the worktree pool is held during write only (the floor lets units go at a wait),
so it never limits `write.held` below the role's capacity here. Left out: the nudge step (the
review's `within` raises attention instead) and `jira-hygiene`; the PR events carry the ticket's
key as subject (no `item.related` linking, so no `of: children`). Vocabulary findings: an outside
step counted only its system's own machine, never a person's act (fixed: the actors relayed under
the system's namespace, `person.github.<login>`, `bot.<system>`, count); a start cannot filter on a
field ("assigned to the owner"); `count ≥ 2` counts events, not distinct reviewers; person and
outbox steps accept any source (person offers later); "wait, then retry" has no word (triage
sleeps); a step that two machines do (nudger drafts, outbox sends) is two steps.

**Gaps since S3 (2026-11-01, orchestra-workflows branch vocabulary; its SPEC §7.3).** The item
starts only on tickets assigned to the owner (the start filters on the event's data, `{"assignee":
{"setting": "owner"}}`: a ticket assigned to anyone else makes no item); review needs two distinct
reviewers (`count: 2, distinct: "source"`: one reviewer approving twice counts once); open_pr, sail
and ping are `person: owner`, counted only from the owner and never offered. Nudge then ping is
built, as two steps (no new word): a role writes the reminder's text into an item field (`nudge`),
and an outbox step drafts from that field for the Outbox plugin, which sends it after the owner's
approval (in this fake example the owner's act is played as `ping`, `person: owner`, done when
`github.pr.commented`; the review's `within` guard enters nudge). Triage → retry uses `after`
(`retry`, no who, `{"after": "2s"}`, then sail): triage answers at once and nothing sleeps. Still
left out: `jira-hygiene` and the PR's `item.related` link to its ticket. **The model acceptance
uses seed 5**, not seed 1 (`tests/unit/test_example_delivery_sail_model.py`): the nudge and retry
steps changed the script's draws, and since S3 seed 1 sees the changes-requested move only 4 times,
below the 5 the acceptance asks of each move. The capacity form is seed-dependent and was not
tuned: S3 re-ran seeds 1–8, and the claim into `write.held` reads `write.held` on seeds 5 and 6,
the open offers (`floor_offers`, an input) on 2, 3, 4, 7 and 8, and `write.waiting` on 1.

## UC-8: team pull-request review (M5's X2; `examples/team_review`)

The owner: "check for pull requests from my team; read them, understand them, contextualize
them, give feedback as comments; approve the pull requests if warranted; make sure the pull
requests get merged; if they have test failures, remind them to attempt to sail again. if there
are failures, check if there are company-wide issues that are affecting them." User stories 4
and 14.

Item: a pull request. Starts: `github.pr.review_requested` naming the owner. Steps: read (role
`pr_reader`, an agent on the dummy harness: reads and drafts comments), comment (the outbox posts
them, after approval), approve (`person: owner`, within a day), merge-watch (outside: GitHub,
done when `github.pr.merged`; `on` failing checks → remind; within two days → stale), remind
(role `nudger` drafts, a program checks for company-wide failures, the outbox sends; → merge-watch),
stale (attention to the planner). New commits (`github.pr.synchronize`) move it back to read.
**One pull request in two workflows:** the same pull requests also enter a second, one-step
workflow over the same subjects (for example a team-wide merge watch starting on
`github.pr.opened`), so each item has two positions.

Expected stocks: the piles of read, comment, approve, merge-watch and remind, per workflow, never
summed across workflows (the Piles page never sums them either).
Expected flows: each workflow's `<start>` counter (`workflow_item_moves_total{from="<start>"}`)
stays its own flow, though both are filled by events about the same subjects; read → comment →
approve → merge-watch → `<end>`; merge-watch → remind → merge-watch; merge-watch → stale;
`on` synchronize back to read.
Expected loops: the reminder loop on failing checks; re-reading after new commits.
The domain series: review comments posted on the fake GitHub, read from its API by a
`[[collect]]`, whose inflow is the comment step's move.
Forbidden: the two workflows' `<start>` counters merged into one flow, or their piles into one
stock; a flow between piles of different workflows.
Needs beyond W5: person offers; the outbox as a `who`.
The test: the three checks, and at a named moment one pull request is in both workflows with a
position in each.

**Status (2026-11-01, X2 built as `examples/team_review`, orchestra-workflows branch X12).** The
second workflow is UC-8's own suggestion, `merge_watch` (one step, started by `github.pr.opened`,
done at `github.pr.merged`); the remind step is the nudger alone (no company-wide check program);
approve is the owner's wait. Built on eight pull requests in the e2e (one failing check reminded,
one re-read after new commits, one moved to stale by the guard); at pr-101's approval it has a
position in each workflow, and the record held items in both during the run. Discovery, in process
on three simulated hours: each workflow's step piles as stocks of their own, never summed; the waits'
held piles left out; the two `<start>` counters two flows, and no flow joins piles of different
workflows; every move a fitted flow; **the reminder loop (merge → remind → merge) and the re-read
after new commits (merge → read → comment → approve → merge) both named as feedback loops** by the
core's loop finder; the domain series `github_review_comments` (read from the fake GitHub's log by a
`[[collect]]`) a stock whose one inflow is the comment step's move; nothing forbidden. Limit: the
re-read loop is named only when its move is seen often enough to be fitted on its source (on seed 1,
four re-reads in three hours, it is fitted constant). Vocabulary finding: a start cannot filter on a
field ("review requested **of me**"). **Since S3** (orchestra-workflows branch vocabulary): built,
`team_review` starts only on reviews requested of the owner (`{"event":
"github.pr.review_requested", "data": {"reviewer": {"setting": "owner"}}}`); a review asked of
anyone else makes the pull request an item of `merge_watch` alone. The comment step is the owner's
act in the fake (`person: owner`); on real systems it is an outbox step's draft.

## UC-9: on-call (M5's X3; `examples/on-call`)

The owner: "get an alert from pagerduty; do a quick impact analysis, search for correlated
signals, check SLO's for worrying numbers; check logs for error rate change in any services, for
evidence of an outage; disqualify an outage if possible; then wait for a triage-agent comment to
be added to the pagerduty alert's jira ticket, review it, determine a course of action; perform
the steps to fix the issue; consider updating a runbook." User story 5.

Item: an alert. Starts: the fake PagerDuty's alert event. Steps: analyse (program
`impact_analysis`: correlated signals, SLOs, log error rates; `no outage` → `<end>`, disqualified),
await-triage (outside: the triage agent's comment on the alert's Jira ticket, from the fake Jira as
the relayed `bot.triage`; within 15 minutes → attention), decide (role `responder`, an agent:
the course of action), fix (role `fixer`, or `person: owner`; done when a **metric condition**
holds: the fake service's error-rate gauge under its threshold for D), runbook (role `responder`:
consider updating it). A metric `on` (the error rate back under threshold, with an exit threshold)
ends an item from any step before fix as resolved.

Expected stocks: the piles of analyse, await-triage, decide, fix and runbook.
Expected inputs: the fake service's error-rate gauge, read by the metric conditions (and by the
resolved move's rate, if discovery relates them), never a stock.
Expected flows: `<start>` → analyse; analyse → `<end>` (disqualified) and → await-triage;
await-triage → decide; decide → fix; fix → runbook; runbook → `<end>`; the metric `on` → `<end>`;
fix → decide (a fix whose condition is not met within its guard).
Expected loops: a failed fix returning to decide; alerts that disqualify themselves.
The domain series: runbooks in the example repository (a `[[collect]]` counting the files under
`runbooks/`), whose inflow is the runbook step's `updated` move.
Forbidden: the error-rate gauge as a stock; the metric condition's facts as a flow or an edge of
their own (they are recorder facts, on no bus); a gap in the error-rate series counted as "below".
The test: the three checks; a scripted gap in the error-rate series resets the condition's
duration, and the item's page names the `metric:<series>` fact that moved it.

Status (2026-11-01, X3, orchestra-workflows branch X34, `examples/on_call`): built; e2e (six alerts relayed as `bot.pagerduty` from a scripted fake Prometheus world: two disqualified by the `impact_analysis` program, one recovered by the metric `on`, three confirmed by a gauge done-when, above 0.05 for 30 s with exit 0.03, whose run a 7 s gap in the series restarts; the triage comment as `bot.triage` with a `within` guard raising attention once; fixer; `runbook_check` writing `runbooks/<alert>.md`) and model acceptance pass. Discovery finds the eight piles that hold alerts by construction (the two waits' held piles never hold and are left out), all eleven moves as flows, analysed's two ways out (the metric-gated branch), the error ratio only as an input (it fits the alerts' arrival, not the metric moves), no flow or stock of the metric facts, and `runbook_entries` fed by runbook → end. Differences: steps are analyse, analysed (the metric gate), awaiting_triage, decide, fixing, runbook (no fix → decide loop, so no loop is expected); since S3 (orchestra-workflows branch vocabulary) `decide` is `person: owner`, done when `pagerduty.incident.acknowledged` counted only from the owner (a teammate's acknowledgement is listed as not counted, with why) and never offered; durations scaled to seconds; the triage comment's subject is the alert itself (no relation to its Jira ticket). Needed in the plugin: an outside `who` naming a relayed source (`bot.triage`).

## UC-10: release-candidate verification (M5's X4; `examples/rc-verification`)

Some companies "have Release Candidates and Release Candidate verification steps" (the owner, D21).

Item: a release candidate. Starts: `every` an interval (the cut is scheduled), or a request.
Steps: cut (program `rc_cutter`), verify (role `verifier`, programs and an agent on the dummy
harness; needs a `staging` unit, a resource kind of capacity 2 with make, reset and release
scripts), release (`person: release_manager`, within a day). Outcomes: verify `verified` →
release, `rejected` → `<end>` (rejected), and the cutter cuts the next candidate on a rejection.

Expected stocks: the piles of cut, verify and release.
Expected flows: `<start>` → cut; cut → verify; verify waiting ↔ held; verify → release; verify →
`<end>` (rejected); release → `<end>` (released).
Expected loops: the staging pool limiting `verify.held` (a capacity-limited form, H1; "no unit" as
the wait reason when the pool is full); rejections raising the rate of new candidates.
The domain series: release tags in the example repository (a `[[collect]]` counting `v*` tags),
whose inflow is release → `<end>`.
Forbidden: the staging pool's capacity as a stock; `floor_resources{kind="staging"}` as a stock of
the candidates' network (it may be read as the limit, never balance the piles).
Needs beyond W5: person offers.
The test: the three checks; with three candidates in verify at once, one waits with "no unit" and
is offered when a unit is reset and freed.

Status (2026-11-01, X4, orchestra-workflows branch X34, `examples/rc_verification`): built; e2e (six candidates asked for at once; cut, checks in a `staging` unit of capacity 1 (not 2) whose make/reset/release scripts manage a directory, verifying by a scripted verifier in the same unit, rejected or failed → cut with a `rounds` guard raising attention once, release as an outside wait on `release.approved` from `person.release_manager`, scripted, who tags `v1.0.<n>`) and model acceptance pass; the queue waits in `checks.waiting` with "no unit" and the held piles never hold more than one. Discovery finds the seven piles that hold candidates by construction, all ten moves as flows, the rework cycle back to cut in the flows, the staging pool by state never a stock, and `git_release_tags` fed by release → end. No loop is named: the claim into `checks.held` is fitted on the floor's open offers (an input), so no chain of influences closes and the staging limit is not what the form reads (W6's limit). Differences: a rejection is rework to cut, not an end; started by request, not `every`.

## UC-11: hotfixes across release branches (M5's X5; `examples/hotfixes`)

Status (2026-11-01, X5, orchestra-workflows branch X567, `examples/hotfix_branches`): built; e2e (three release branches, fan-out by a `fanout` program, fan-in `all landed`, a dropped child leaves its parent `partial` with attention) and model acceptance pass. Discovery finds both workflows' piles by construction, every move as a flow within its workflow, and the one loop resolve → review → rejected → resolve. Gaps: the per-branch commit series are stocks whose inflows are fitted rates, not the single land counter (only their sum matches it). Since S3 (orchestra-workflows branch vocabulary; its SPEC §7.3): `ported` is a fan-in with no who (nobody acts there, no machine drawn); `partial` is left unnamed, so a hotfix with a dropped port stays at `ported` and the planner is told once (attention, no `partial` step); the dependency between two hotfixes is built with `depends: {"at": "end"}` on cherry_pick and `item.related {kind: depends_on}` from `fanout` (hotfix-3's ports wait for hotfix-2's); following the slowest child is the fan-in itself (no word), and that the model shows no flow across the two workflows is the core's rule that piles are never joined across workflows.

"We might see multiple concurrent release branches that all need hotfixes" (the owner, D21). User
story 16.

Items: a hotfix (workflow `hotfix`) and one child per release branch (workflow `port`, children by
`item.requested` with `parent`). Hotfix steps: fan-out (program `porter` requests a child per
branch), wait (fan-in: `all` children ended `landed`, else the named outcome `partial` →
attention). Port steps: port (program `porter`: a clean cherry-pick → review, a conflict →
resolve), resolve (role `conflict_resolver`, an agent; needs a worktree), review (role
`reviewer`; `rejected` → resolve as rework), land (program `landing`) → `<end>`.

Expected stocks: the hotfix's fan-out and wait piles; the port piles, each child counted once, in
its own workflow.
Expected flows: the moves of both workflows; the hotfix wait → `<end>` when the last child lands.
Expected loops: conflict → resolve → review → rejected → resolve; the parent's completion following
the slowest child (representable as the wait pile's outflow tracking the port's land moves).
The domain series: hotfix commits on the `release/*` branches of the example repository (a
`[[collect]]`, one series per branch), whose inflow is the port workflow's land move.
Forbidden: a child counted in the parent's piles; a stock per branch (per-branch views are
declared piles, `aggregate`, shown on the Piles page only); a flow per branch.
The test: the three checks; with three branches, the parent is done when the third child lands and
takes `partial` when one does not; a dependency between two hotfixes holds the second's port.

## UC-12: staged rollout (M5's X6; `examples/staged-rollout`)

Status (2026-11-01, X6, orchestra-workflows branch X567, `examples/staged_rollout`): built; e2e (four releases, 30 s stages, r3 rolled back once by the metric `on` at fifty) and model acceptance pass. Needed in the plugin: a metric label from the item's field (`{item: release}`) and an offered step's metric done-when read from its turn's end. Since S3 (orchestra-workflows branch vocabulary): the program is told its step (`ORCHESTRA_WORKFLOW`, `ORCHESTRA_STEP`, `ORCHESTRA_FIELDS` in its environment, and nothing else but the basics and its `spec.env`), so `fleet_set.py` reads the stage it sets from `ORCHESTRA_STEP`. Discovery finds the four stage piles and rollback by construction, each stage → rollback and rollback → end, and the domain series fed by hundred → end; the error ratio and traffic share are never stocks, though for incidental reasons (`*_ratio` read as utilisation; the share changes too rarely). The rollback loop is not found: no move's form reads the error ratio.

"We might see a staged production rollout" (the owner, D21). User story 7 is its feature-flag
form.

Item: a release. Steps: canary, ten, fifty, hundred (each: program `rollout` sets the stage on the
fake fleet; done when a **metric condition** holds, "the canary's error rate under 0.1% for 30
minutes", scaled; a `within` guard per stage → attention), rollback (program `rollback`) →
`<end>` (rolled back). A metric `on` (the error rate above its threshold, with an exit threshold
for hysteresis) moves the item from any stage to rollback.

Expected stocks: the piles of the four stages and of rollback.
Expected inputs: the fake fleet's error-rate gauge (and the share of traffic on the new version,
which the rollout program sets), never stocks.
Expected flows: `<start>` → canary; each stage → the next; hundred → `<end>`; any stage →
rollback; rollback → `<end>`.
Expected loops: the rollback loop (a high error rate moving releases out of their stages, as far as
"the error rate drives the rollback move" is representable).
The domain series: releases fully rolled out on the fake fleet (its own count), whose inflow is
hundred → `<end>`.
Forbidden: the error rate or the traffic share as a stock; a machine node or `source` for the
metric (rule 7); the condition's facts as bus events.
The test: the three checks; a condition met only after holding for D; a missing series never
meets it; one release scripted to fail at fifty is rolled back by the metric `on`, once.

## UC-13: customer-owned deployments (M5's X7; `examples/customer-deployments`)

Status (2026-11-01, X7, orchestra-workflows branch X567, `examples/customer_deployments`): built with 4 customers × 3 releases (not forty × two); e2e (outbox after an approval, `customer.scheduled`, deployed with the version equal to the item's `release`, a `within` guard → overdue with attention, late deploy through overdue to verify) and model acceptance pass. Discovery finds the piles per workflow by construction, never joined across workflows, deploy → overdue → verify, nothing per customer, the oldest-age series never a stock, the registry count fed by verify → end; deploy → overdue is fitted on the oldest age (the guard's clock). Not built: the chase step and loop; the release's `partial` ends it rather than raising attention. No loop is named. Since S3 and O1 (orchestra-workflows branches vocabulary and outbox-writes): no word is needed; its outbox step is a draft (`who: {"outbox": "owner"}` with a `draft` the floor hands to the Outbox plugin, awaiting the owner's approval, ending `sent`, `rejected` or `failed`); the fake example still waits on a fake outbox as an outside system.

"We might see customer-owned deployments" (the owner, D21).

Item: a customer × release pair (subject `<customer>@<release>`), many per release: a program
`fanout` requests one per customer when a release is published. Steps: notify (the outbox sends,
after a scripted approval), schedule (outside: the customer, the fake bridge's `customer.scheduled`;
within N days → chase), chase (role `account_agent` drafts, the outbox sends; → schedule), deploy
(outside: the fake bridge sees the deployment, its version equal to the item's `release` field),
verify (program `verify_deploy`) → `<end>`; overdue (a guard's named step past the release's
deadline: attention to the planner).

Expected stocks: the piles of notify, schedule, chase, deploy, verify and overdue.
Expected flows: the moves between them; schedule → chase → schedule; any wait → overdue.
Expected loops: the chase loop on a silent customer; overdue escalation.
The domain series: customers on the latest release (the fake registry's count), whose inflow is
verify → `<end>`.
Forbidden: a stock or flow per customer; `workflow_pile_oldest_seconds` (long waits make it
tempting) as a stock.
Needs beyond W5: a field equality; the outbox as a `who`.
The test: the three checks with forty customers over two releases (eighty items); the Piles page's
oldest item and wait reasons match the script.

## Adding a case

A case needs: a start command, a stop, a duration, the repository that writes its metrics, and
the expectations in the four lists above; an example workflow (UC-7 onward) also names its
domain series, the test that runs its three checks, and what it needs beyond the vocabulary
already built. Expectations are structure, not numbers: a case that
only passes with a tuned rate is reported as a gap, not fixed to pass. Every run records what
discovery read: `orchestra sd discover --snapshot <out>/<case>/snapshot` writes each series it read
(one JSON file per series, with its labels, kind and points) and a `manifest.json` naming the window,
the step, the method and the commits, beside the case's `model.json`. A fix to discovery is then
checked against recorded runs with `orchestra sd discover --from <dir>` (`sd.snapshot.replay`),
which gives the same model from the same data and writes to no store.

Two lessons from the 2026-11-01 re-scores. Run a case from a detached clone, never a linked
worktree: `find_repo_root` resolves a linked worktree to the main checkout, so the case shares the
main checkout's project key and state. Sample as fast as the states move: UC-2's tickets leave
OPEN in under a second, so a 5 s sample sees OPEN non-zero in one step of 421 and the stock is
lost by chance; a case whose states last less than the sample interval states its interval (1 s
for UC-2 and UC-3) or is scored as a sampling gap, not a discovery miss.
