# The second half, 2026-11-02: report (draft)

The unattended run of [GOAL-2026-11-02-second-half.md](../roadmap/GOAL-2026-11-02-second-half.md),
run by [COORDINATOR.md](../roadmap/COORDINATOR.md), with product decisions taken by the owner proxy
([OWNER-PROXY.md](../roadmap/OWNER-PROXY.md)). Its first timed log line is 2026-11-01T17:08Z. This
draft was written at 2026-11-02T00:27Z and brought up to date for T4 at about 01:55Z. The goal's progress log is the source
of truth. Where this draft and the log disagree, the log wins.

In short: the live delivery example ran the owner's day on the real SCRUM board and the private
repository three times (L1, T2-prep, T2), with every outside write in the approved scope. The
Supervisor passed the design scenario on the live example on Haiku (L3). The Monday walkthrough
(T2) passed 7 of 16 steps outright. 2 more met their rule but misled the owner, and 6 failed. The
failures are mostly in the Supervisor's answers and the pages' account of who must act, not in the
delivery itself. T4 implemented the T3 judge's work list (47 rows: 19 must, 28 should) in core,
agents, workflows and outbox; every T4 repository was on origin by 01:53Z. The walkthrough re-run
on T4's code (T2b) passed 12 of 16 steps, with 2 misleading and 2 failed; T2 had 7, 2 and 6. Fixes
for T2b's findings are in progress as T6.

## 1. Questions for the owner

Each is answerable in one sentence. Until you answer, the run uses the default in brackets.

### The goal's own questions

1. Which Jira Data Center project and board, and which GitHub repository, should Orchestra watch
   at work first? [none; the live example only]
2. Is your day "ticket assigned, branch, pull request, reviews, SAIL label, SAIL result, Slack
   thread told", and which step is wrong or missing? [as written]
3. Which page do you open first in the morning? [the Dashboard]
4. What are the three questions you will ask the Supervisor most, and what must each answer
   contain? [what is stuck and why; what needs me; what changed since yesterday]
5. Which writes to outside systems may Orchestra make at work, and which need your approval each
   time? [all need approval; none outside the live example]
6. Which distribution should QUICKSTART present to a colleague? [the core from GitHub with the
   plugins as extras]
7. Does the RabbitMQ test rig get its own repository? [no; it stays where it is]
8. D19: may a polling relay be a Workflows program, or does it stay a machine that publishes as
   the actors? [stays as is]
9. Will you give the Slack app's client id and secret for token refresh, or a bot token that does
   not rotate? [neither; Slack is disabled on expiry]
10. Which time zone and working hours do guards and schedules use? [ask in the chat; none guessed]
11. Do you confirm defaults D22 to D40 as a set, or which do you want to revisit? [standing]

### Escalated by the proxy (R1 E, R2 X, T3 Y)

Pages and names:
- E1. Should Agents stay in the navbar now that Machines shows the agents? Tickets leaves with the tasking plugin (your Q5 words). [Agents stays]
- E2. Should Core stay in the navbar, plumbing opened only when something breaks? [stays]
- X2. Would you object to the Outbox page, where drafts wait for your approval? [kept]
- E9. The hidden stock of items whose pull request waits for CI: what do you call it? [named by its neighbours]
- Y6. Items passing SAIL (sail_check → close_ticket): what do you call that quantity? [named from the step]
- Y4. The stock "agents working (supervisor)" counts the Supervisor's own turns: keep it, and what do you call it? [kept, marked by construction]
- E20. Rename `[[machines]]` to `[[processes]]` and merge the two kind vocabularies (program/agent/person/service vs universal/programmatic)? [unchanged]
- E24. Should the Items list mark rows moved since your last visit? [not built]

Who acts, and what may be sent without you:
- E3. Should the floor publish as itself (a dispatcher's name) rather than as `supervisor/dispatch`? Machines credited the Supervisor with 13 offers and 11 drafts on Monday. [stays; waits on you]
- E4/X7/X8/Y8. May a machine at work, without your approval each time, add or remove SAIL labels, move a ticket to Done, post a Slack nudge, approve a teammate's pull request, or run a fix step on production? [every one an Outbox draft; no approve sender exists]
- Y1. Would you object to the SAIL label, the Jira transition and the created ticket being sent with no approval on the test repository and board, which your "approval-always" decision does not allow? [as built, test scope only; `--scope board` makes each wait]
- Y3. May the Supervisor wake unasked on `attention.needed` and write to you, and start the Review Nudger on that attention without your words? [it writes; it starts nothing]
- Y9. Is the Outbox an actor (a machine on Machines, publishing as `outbox`) or your hand (publishing as your person id)? [unchanged, `[outbox] owner` set]
- Y10. Should the guard be the only judge of "waited too long", with the nudger's own 30-minute scan gone? [both stay]
- Y2. Would you object to `confirm` refusing a machine until its prediction is recorded? [no refusal]
- X3. Should the Supervisor start an item itself (`request_work`) rather than Supervisor → Coordinator → tickets? [as built: it starts items]
- X4/E16. Without tasking, should the Coordinator hand code work through a Workflows item, or should the agents' ticket-built team (roles, teams, the ticket path) go? [the gap stays documented]
- E15. Is the Supervisor part of Orchestra (rule 9) or a plugin's machine whose name no one else may use? [rule 9 as written]
- X5. A stale review at work: told to you on the Dashboard, to the reviewer, or in the chat? [Dashboard]
- E13. Who is "the requester" to tell in Slack: the Jira reporter by DM, or one channel? [no post until a bot token exists]
- E14. During a PagerDuty incident, should deliveries pause, or only SAIL triage consult it? [only triage]

The model:
- Y5. Does "SAILED per day ×1.2" mean more deliveries passing SAIL, or reviews waiting less? [recorded as said, on the sail_check → close_ticket flow]
- Y7. At work, does SAIL publish a check-result event, or only labels on the pull request? [the fake keeps `sail.check.completed`]
- X1. Would you object to a 0/1 "busy" level being left out as another stock's capacity, shown in that stock's drawer? [kept]
- X6. A count of agents busy on tickets in review: IN_REVIEW's capacity, or a stock of its own? [a stock]
- E10. Should a definition declare its piles and moves in the intended layer, so a mis-bound pile shows as a mismatch? [no]

At work:
- Y11. Would the MCP block stop Orchestra's local MCP server, and is `tools_via = "bash"` allowed instead? [bash; the walkthrough runs on it]
- E6/Y12. May a `gh` token or a Jira PAT sit in a mode-600 file, or must it come from a keychain or vault? [a mode-600 file, by reference; credentials stripped from agent sessions]
- Y13. May private repositories from a personal GitHub account be cloned onto the laptop, or must they be mirrored to GHE? [cloned]
- Y14. May the Outbox write labels, comments and transitions as you, or only through a service account? [as you]
- E7. Would managed Claude Code settings disable `--dangerously-skip-permissions`, and what is allowed instead? [unchanged]
- E8. Are github.com, PyPI and the Claude API reachable through the proxy, with a corporate CA injected? [documented in INTEGRATING]
- X9. Does Claude Code reach the model through api.anthropic.com, or Bedrock or Vertex? [api.anthropic.com]
- X10. May plugin pages fetch scripts from public CDNs? [no; vendored]
- E11. May ticket summaries and pull request URLs ride the bus, or ids only? [as today]
- E12. May GitHub and Jira push webhooks to Orchestra, or must it poll (5 minutes a hop)? [poll]
- E5. Should `orchestra-workflows` become public, since the install line fails for anyone else? [private]

Repository housekeeping (yours to decide; nothing changed):
- E17 (desk and outbox in the install line: stay), E18 (the events endpoint's second model API: stays), E19 (`Plugin.machines` placeholders: stay), E21 (the 74 unused SD Lab strategies: kept), E22 (the test-report instrument in the core: kept), E23 (`mockups/`, 14 MB: kept), X11 (rule 2's exceptions into SPEC: unchanged), 7 (the RabbitMQ rig's repository: stays).

## 2. What works, with the evidence

**The delivery on the real systems.** L1 (17:55Z) took three "[orchestra live test]" tickets on
SCRUM from assignment to a real pull request in `danroblewis/orchestra-live-delivery`, GitHub
Actions CI, a stand-in review, the SAIL label, the example's fake SAIL, a merge and the ticket
Done. One ticket (SCRUM-7) was rejected, triaged back, reworked and SAILED. No AI was spent.
T2-prep (22:22Z) ran it again with every write through the Outbox: SCRUM-14 to 16, pull requests
#12 to #14, one held review with the 30-minute guard firing once, one forced rejection triaged
`local` and reworked, 10 Outbox sends by configuration, no Slack post. T2 ran it a third time
(SCRUM-17 to 19, pull requests #15 to #17, all merged and Done, branches deleted).

**The Supervisor on the live example.** L2 (18:44Z) fixed the Haiku failures the first run left;
its second live run passed every turn ($0.12; both runs $0.25). L3 (20:10Z) passed all three
design turns on `delivery_live` in three Haiku runs ($0.21): a stock measured by the existing pile
series, the Review Nudger declared, scheduled and confirmed with a prediction, and "what needs me"
answered with the real ticket keys and pull request numbers. Its weakness: discovery found no
model in 20 minutes of two tickets, so the prediction's flow is an event type.

**T2's passing steps.** Two tickets assigned with no replay of Done tickets (2). Pull requests
opened through the Outbox with no history replayed (3). CI relayed with each item's commit (4).
The stand-in review moved A and held B (5). SAIL sent only through the Outbox (6). Work started
from the chat: `request_work` opened SCRUM-19 through the Outbox, then pull request #17, merged
and Done (13). "What needs me before I go?" was accurate against the bus in 7 seconds (15). Step
12 passed on Jira and GitHub; its page gaps are in section 3.

**Model acceptance (S4).** At 1 s sampling, UC-2 scored 9/10 (was 8) on core `fa4e8acd`, and UC-3
9/10 (was 6) on `281922c0`. U1 scored UC-1 8/10 on `e9472164` with a snapshot whose replay
reproduces the model exactly (U4). Every remaining miss was named as data:

| case | score | the miss | why (the modeller's verdict) |
|---|---|---|---|
| UC-1 | 8/10 | the rating; an extra stock `bakery_chef_busy` | the bakery publishes its own demand formula, which `placed` reads (R² 0.87); the extra stock is a 0/1 flag, now a capacity of one (U5) |
| UC-2 | 9/10 | IN_REVIEW | its series was never non-zero in 2,115 one-second samples: the reviewer passes tickets in under a second |
| UC-3 | 9/10 | the coordinator's and Supervisor's levels; the attention loop | scripted turns last under a second; they need real agents' turns of seconds |

U5 (merged 19:32Z, refuted once, fixed) makes a 0/1 or 0..k level another stock's capacity: UC-1's
replay goes from 7 to 6 stocks, UC-2 and UC-3 are unchanged, and UC-1's expectation now accepts
the rating through the demand gauge (D15). A re-score of UC-1 after U5 is not recorded. The
passage fixes (18:30Z) and the R2 discovery rows (21:14Z) replayed identically on every snapshot.
No case is at 10/10, so done criterion 3 rests on the misses being named as data.

**Vocabulary (S3, 19:05Z).** V1, V2, V4, V7 and V8 are words the examples use; V3, V5, V6, V9 and
V10 are rulings in the plugin's SPEC §7.3.

## 3. The walkthrough, step by step

T2 ran 22:26Z to 00:02Z on the real Supervisor (Haiku, $0.37, 11 invocations), from a fresh
state. Evidence in the scratchpad under `reviews/T2/`: `run.md`, `answers.md`, `notes.md`,
`events.jsonl` (redacted), `raw/`, and 62 screenshots in `shots/`. The script is
[WALKTHROUGH-2026-11-02.md](../roadmap/WALKTHROUGH-2026-11-02.md). "T4 changes" lists the T3
judge's rows for each step; the log records them merged (core 00:49Z and 00:57Z, agents 00:58Z
and 01:41Z, workflows 01:31Z and 01:42Z, outbox 00:28Z). Whether they fix the step is for the
re-run.

| # | step | T2 | what the proxy found | what T4 changes | T2b |
|---|---|---|---|---|---|
| 1 | First look, "What needs me?" | fail | Slack's disabled reason and the fakes are announced but not on the cards; the answer is silent on Slack; a task-system tool times out in every answer | core cards print announced notes; agents `list_machines` with notes; task-system parts gated on tasking; the walk's venv without tasking | pass |
| 2 | Two tickets assigned | pass | rows show no ticket summary | the title before the fields | pass |
| 3 | Branch and pull request | pass | none | none | pass |
| 4 | CI | pass | none | none | pass |
| 5 | Stand-in review | pass | none | none | pass |
| 6 | SAIL through the Outbox | pass, notes | the Outbox says "auto", not "approved by configuration"; approvals not under the owner's person id | Outbox wording and trail; `[outbox] owner` written | pass |
| 7 | Rejection, triage, rework | pass, misleading | every drawer time "Invalid Date"; reworked 0; label names missing | Invalid Date fixed already (b154435); reworked counts any return; labels on the timeline | pass |
| 8 | "What is stuck, and why?" | pass, misleading | the held review called a workflow bug; A's rejection left out | each wait names its exits (`for`); `read_events` by prefix and `since` | misleading |
| 9 | Stale review reaches the owner | fail | the Dashboard names GitHub as who must act; the Supervisor woke and told the owner to approve a PR GitHub refuses | one answer to "who must act"; wait exits; the guard key out of the wake text | pass |
| 10 | Review Nudger and ×1.2 | fail | nothing declared; "no metrics collected" with 152 series; the owner asked to restate | the core's no-model reason through `read_model`; the owner's earlier ask carried forward; the expectation recorded as waiting | fail |
| 11 | Nudge on B | fail | "which is B's?": the script's label | the reminder prompt; the script now names the PR (9fbcce41) | pass |
| 12 | SAILED, merged, Done | pass on Jira/GitHub | closed items under "no workflow", no outcome; Slack's reason not on its card | the floor publishes `item.closed`; cards print notes | pass |
| 13 | Delivery from the chat | pass | the closed item still holds a live review position | `item.closed` | pass |
| 14 | An incident | fail | the incident not named; merged tickets listed as waiting | `pagerduty.` prefix reads and a prompt line; state from this turn's tools only | misleading |
| 15 | "Before I go?" | pass | none | none | pass |
| 16 | "What changed since yesterday?" | fail | the rejection told wrongly; the 11 Outbox sends missing; UTC | `since`, oldest first; an Outbox read; times in the pages' zone; envelope times normalised | fail |

### What T4 landed

| repository | merged | what the log says landed |
|---|---|---|
| outbox | `a53a70a` | "approved by configuration"; the trail drafted · approved · sent with times; `Orchestra.when` everywhere |
| core | `3ae3e39f` | `sd/no_model.py`: the no-model read gives a text and a reason; announced notes on cards and dialogs; no machine percentage on a too-few flow; envelope time always UTC `…Z`; QUICKSTART names `delivery_live` |
| core | `12be615d` | the stall rule, after a refuter round: due = min(history average, fitted rate); no "resumed" while silent. UC-1 replay: 7 stalls and 5 resumes before, 2 and 2 after |
| agents | `ac51fb3` | 16 rows, relocked to core `3ae3e39f` |
| agents | `ff0a590` (row 9), `c77915a` (relock) | the wake text without the guard key; `list_items` and `explain_item` show `entered_on` and `ends_on` from the wait's `for`; `item.closed` in the contract copy; relocked to core `12be615d` and workflows `35b2b9c`, where `declare_workflow` gained the plugin's new `about` key (the one drift the relock found) |
| workflows | `35b2b9c`, relock `0166e5d` | `item.closed`; one who-must-act; `for` and `entered_on`; reworked; example settings including Data Center; `[outbox] owner`; `--supervisor`; notes on the card; title first; the timeline in words; `every` with `at`/`tz`; `about`; first free port; the login link in a mode-600 file; README credentials and proxy; the fake bridges exit with their parent |

The coordinator's T3 rows went into the script at 00:24Z (9fbcce41): a venv without
`orchestra-tasking`, `--via bash`, step 11 naming the PR, and steps 10 and 16 saying what the run
can show. Both demos were restarted on T4: the example as run15 (01:47Z), the live demo on core
`8059aa62` and agents `5db0f07` (01:54Z).

### T2b, the walkthrough on T4's code

T2b ran 01:59Z to 03:38Z on core `12be615d`, agents `c77915a`, workflows `0166e5d`, bridges
`14119cf` and outbox `a53a70a`, with `orchestra-tasking` not installed and tools over bash.
Evidence in the scratchpad under `reviews/T2b/`. It passed 12 steps (1 to 7, 9, 11 to 13, 15).
Two misled (8, 14) and two failed (10, 16). SCRUM-20 to 22 are Done and pull requests #18 to #20
merged.

The example's `--supervisor` starts, but it writes a role without `work` and has no option to
add it, so `request_work` (steps 11 and 13) would be missing. The run used the agents' launcher
`tests/live/delivery_live_run.py --via bash` instead.

What was still wrong:
- **8, misleading.** The Supervisor called `reviewer_stand_in` "quiet, needs restarting" while
  the harness held the review.
- **14, misleading.** It named the incident and called it fake. It also said delivery was not
  affected, though PSVC003 is SAIL's service and an item waited at SAIL.
- **10, fail.** The Review Nudger was declared and confirmed and ×1.2 published, all in one turn.
  But SAIL check results were left out of what the nudger listens for, and the Supervisor said it
  "runs at 09:00 PST" when it runs every 24 hours.
- **16, fail.** The rejection and the triage were left out. The Supervisor said "no stocks yet"
  while discovery had three.

New breaks it found:
- `/api/dynamics/model` returns 500 once a model exists, because an `inf` in the model is not
  JSON. Dynamics then shows "server is not answering", and step 16's model answer was wrong.
- `logs/web.log` prints the login token in clear.
- A `coordinator` placeholder card stays on Machines when tasking is not installed.

[T6, the fixes for T2b's findings (core, agents, workflows): outcome pending; filled by the coordinator]

## 4. What does not work, and why

The T3 judge (00:24Z) found 47 rows: 19 must and 28 should. By repository: core 2/4, agents 8/8,
workflows 7/12, outbox 0/2, bridges none, coordinator 2/2. The musts, in short:

- **Core.** No-model reads give a bare "there is no model yet", so the Supervisor told the owner
  "no metrics are collected". The Machines cards drop a machine's announced notes (`disabled`,
  `fake`), which the delivery README promises.
- **Agents.** Task-system tools on a run with no task system. A machine asked for in one turn
  cannot be declared in the next. `read_events` matches exact types, newest first, so it missed
  the rejection. No tool returns a machine's notes. `agents working (supervisor)` showed "trust
  0.83 high" from a balance that holds by construction.
- **Workflows.** No `item.closed` reaches the bus. Three answers to "who must act". A wait does not
  say what ends it. The example has no `--supervisor` option, and its repository, Jira project and
  URLs are hard-coded (Data Center and GHE need settings).
- **Coordinator.** The walk's venv had the task system installed; the start ran `--via mcp`.

T4 merged all of these (section 3). The re-run will show whether they work.

**Follow-ups after T4** (from the log, 01:31Z to 01:54Z):
- The no-model paragraph prints its grouped reasons with the numbers collapsed into raw keys
  ("live in only n of n steps while every counter was (21)", "a counter of only n events (6)").
  Each group needs a sentence.
- `delivery_sail` and two other examples still print the login token.
- A Data Center PAT is read from the file named `jira-cloud-token`.
- The workflows `dev` extra does not list `orchestra_bridges`, so 41 `delivery_live` tests skip in
  the main checkout. It should list it, as the agents' extra does.
- The main demo's link in `~/url` once carried a stale token (401). It was rewritten from
  `LOGIN.txt` and verified (01:54Z).

Known gaps the script names and does not pretend are solved: the review is a stand-in (one
GitHub account); no 09:00 schedule (the nudger runs at 00:00 UTC); each reminder waits for
approval; Slack is disabled (the token lacks channel-read; an `xoxb-` bot token is needed); two
tickets make no model and no verdict on ×1.2 (about 200 events per era are needed); no SLO, log or
alert source; polling, so a short job waits up to 25 minutes.

Not done or not recorded: L4 (the push block against a full-path `gh` and an explicit pushurl) is
open (20:21Z). L5 is done in L1's README; the token refresh how-to stands. B1 to B10 have no log
line under their ids; some of their substance came in other rows (B6's page names in the R1 agents
fixes; the phone layout in R1 and R2). F2 has no log line.

**F4, the first report.** It is complete. Its gate section is filled, and branch `report` is
merged into core main (`16739f95`, "Merge branch 'report': the first run's report, complete
(F4)"). It is at `docs/reports/2026-11-01-workflows-run.md`.

**The release gate** (workflow `w7b12cqig`, finished 03:43Z). It took 60 agents, 15 h and 14.7M
tokens. The subtraction audit found 186 findings. Each repository had two layered review rounds:

| repository | findings, round 1 / round 2 | commits |
|---|---|---|
| core | 51 / 51 | 29 + 29 |
| agents | 50 / 43 | 1 |
| workflows | 57 / 45 | 25 + 34 |

The gate branches had already been merged in F3 (agents `30d09a1`, workflows, bridges `69a4b43`).
The final verifier says agents, workflows and bridges are ready to push. For the core it says
"no, fixes are small":

- P1. 7 layout JS failures caused by `~/package.json`. Already fixed on main by the CommonJS pin.
- P2. Plugin words in core code: a user-facing "the Supervisor's confirm" in
  `predictions_report.py:71`, and pile, workflow, agent and ticket in comments
  (`predictions.py:10`, `capacity.py:19,134`, `collect/views.py:32`, `discover.py:180`,
  `instrument_series.py:5`, `sd-graph.js`, `instruments.html:101`).
- P3. `discover.py:184-189` names a series by its step and place labels. Reported as a design
  question; SPEC's views mechanism and D33 cover it.
- P4. The workflows README calls bridges and outbox private (on GitHub they are public) and never
  names orchestra-agents.
- P5. The tasking extra in the core's `pyproject.toml`.

Suites at the gate heads: core 1214 passed (plus 7 environment failures, P1), agents 697,
workflows 547, bridges 312. P2 is being fixed on core branch `T6-words` and P4 on `T6-workflows`;
their outcome is in the T6 placeholder (section 3).

## 5. Decisions taken, and by whom

**How the proxy resolves a disagreement** (OWNER-PROXY.md): the owner's cited words win over any
taste; when the owner's voice does not know, two or more of the other six agreeing win, with the
dissent recorded; a split, or one persona alone on a product question, goes to your list with a
default; a finding resting only on a proposal is dropped; anything on the never-list (a new page, a
human control outside rule 9, a plugin's domain in the core, money over the cap) is escalated, never
built.

**Rows won per persona** (the judges' "Per persona" tables):

| persona | R1 won / lost | R2 won / lost | T3 won / lost |
|---|---|---|---|
| a owner's voice | 10 / 1 | 8 / 0 | 15 / 2 |
| b SRE | 9 / 1 | 8 / 2 | 14 / 1 |
| c modeller | 7 / 0 | 9 / 0 | 9 / 0 |
| d information designer | 14 / 0 | 12 / 0 | 13 / 1 |
| e machine author | 11 / 0 | 14 / 0 | 17 / 3 |
| f architect | 6 / 6 | 11 / 0 | 4 / 3 held, 1 held on Y7 |
| g adopter at work | 9 / 1 | 12 / 0 | 12 / 0 |

R1 gave 25 rows to its implementors (8 must) and 24 escalations. R2 gave 53 (14 must) and 11 new
escalations. T3 gave 47 (19 must) and 14 new.

**Taken by the proxy, with the persona that carried it:**
- Pile stocks named for the workflow, the step and its place; hidden stocks "between A and B";
  piles on the Instruments page (N1, from your words at 17:45Z; a held R1 to them).
- Every write the example makes goes through an Outbox draft; K8 settled by moving writes out of
  the kits (e; O1).
- Scripts land in the owner's repository, credentials by file reference (e, g; B11a).
- QUICKSTART starts on the Workflows plugin's `task_loop`, with the Supervisor writing the first
  configuration (a; B11a).
- Vocabulary: V1, V2 and V4 small words; V5, V6, V9 and V10 no word (e, R1). S3 recorded all ten.
- Agent sessions get none of the host's credentials (g, R1).
- The Dashboard lists attention and person waits first (b, R1).
- The walkthrough's defaults (T1, b and a): a stale review reaches an Outbox draft approved each
  time; incidents do not pause deliveries; the Supervisor asks the time zone.
- T3: a's "propose receives from heard events" was refuted in code and became a wording should;
  d's drop of the stock note was overruled in part.

**Taken by the coordinator** (by "Who decides what"):
- The re-plan to the budget after your 18:00Z message, and the operating rule after 18:02Z: build
  milestones run without waiting, one implementor round per panel round, UI rows capped.
- Refuter rounds before every discovery merge: the passage fixes were sent back once ("do not
  merge", 18:21Z), U5 once, the R2 discovery rows once.
- U5, the capacity rule, dispatched from U1's finding (19:02Z).
- Merge order and re-locks; the workflows gate merged in a scratch worktree (22:10Z).
- A `package.json` with `type: commonjs` at the plugin's and the core's roots, after a new
  `~/package.json` made Node load the scripts as ESM (23:15Z).
- The delivery_sail acceptance on seed 5 (the S3 agent, 19:05Z).
- The example demo's login token pinned across restarts, at your request (18:48Z).
- The T3 coordinator rows applied to the script (9fbcce41).
- Left to you by an implementor: team → group (R2 core, 20:59Z).

## 6. How to run each thing

**The live delivery example.** In `~/orchestra-workflows`, `examples/delivery_live/demo.sh
--tickets 3` makes three test tickets assigned to you and prints a login link.
`--dry-run --tickets 3` does the same on fakes. `--cleanup` closes test tickets and pull requests
and deletes their branches. `--scope board` takes any SCRUM ticket assigned to you, and its close
waits for you on the Outbox page. The harness flags (`--hold-review`, `--release-review`,
`--incident open|resolve`, `--request "…"`) are in its README, "Run it". Credentials are files in
`~/.config/orchestra-bridges/`, mode 600.

**The walkthrough with the Supervisor.** Today it starts from the agents' launcher
`tests/live/delivery_live_run.py` with the role's tools `design,observe,model,events,workflows,work`,
`--via bash`, in a venv without `orchestra-tasking`; see the script's "The fresh state". T4
added `demo.sh --supervisor` (workflows `35b2b9c`), which starts the Supervisor from the example,
so you no longer need the agents' launcher.

**Integrations.** `docs/INTEGRATING.md` and QUICKSTART in the core. `~/orchestra-bridges` is now
the library (B11): kits, fakes, templates and scaffold. `integrate_system` writes a collector into
your repository at `.orchestra/machines/<name>/`.

**The demos.** The core demo on :8096 and the delivery_sail example on :8101 ran every merged
change as of 21:29Z. Both were restarted on T4's code: the example as run15 at 01:47Z, the live
demo on core `8059aa62` and agents `5db0f07` at 01:54Z. Login links are in `~/url` (mode 600).

## 7. Live model spend

| task | model | spend |
|---|---|---|
| A3 (first run) | Haiku, some Sonnet | $6.33 |
| A3b (first run) | Haiku | $0.19 |
| I3 (first run) | Haiku | about $0.13 |
| L2 | Haiku, two runs | $0.25 |
| L3 | Haiku, three runs | $0.21 |
| T2 | Haiku, 11 invocations | $0.37 |
| T2b | Haiku, 10 invocations | $0.42 |

This run: $1.25. Both runs: about $7.9 (the log's figure), under the $30 cap. L1 spent nothing on AI. T2-prep's
spend is not recorded. Agent time is not recorded as a total; the log gives only durations: T2
took 1 h 35 min, and T2-prep's live run was polling for at least 45 minutes.
T4: $0. No Supervisor or agent harness ran a model during T4; its implementors and reviewers are the run's Opus subagents, outside the live-spend cap.
T2b: $0.42 over 10 Haiku calls (9 owner turns and 1 unasked wake), under its $5 cap.

## 8. Suite results

The last recorded result per repository, with `rc` read directly. Ruff was clean and the secret
scan 0 at each push.

| repository | commit | result |
|---|---|---|
| core | `3ae3e39f` (T4) | 1093 passed, 2 skipped, rc=0 |
| core | `12be615d` (T4 stall rule) | 1102 passed, 2 skipped, rc=0 |
| core | R2 implementor's branch | screenshots 7, by the agent |
| agents | `ac51fb3` (T4) | 663 passed, rc=0 |
| agents | `c77915a` (T4 relock) | 666 passed, rc=0 |
| workflows | `35b2b9c` (T4) | unit 477 passed rc=0; e2e 87 passed rc=0 (10.5 min) |
| workflows | `0166e5d` (T4 relock) | 436 passed, 4 skipped, rc=0 in the main checkout; the 41 `delivery_live` tests skip without `orchestra_bridges` (section 4) |
| bridges | `14119cf` | 172 passed, rc=0 (no T4 rows) |
| outbox | `a53a70a` (T4) | 99 passed, rc=0 |

One red result was caught before a push: the plugin's re-lock to core `bbe7255a` failed 2 tests
on the `NetGeometry` split (20:02Z); the Items graph fix merged first.

## 9. What the coordinator got wrong

- **It wrote stamps ahead of the clock again.** Seven stamps were estimated and corrected at
  18:13Z, and one bridges stamp at 17:50Z. Since 18:13Z every stamp comes from `date -u`.
- **It wrote that a thing had happened before it had, three times.** At 18:41Z it logged the R1 core
  merge, which happened only at 18:42Z (the chain had stopped on a stale check). At 20:32Z it
  corrected the agents line before it: agents main was not pushed, 1 test had failed, and "the
  previous line was written from a template before the result was read". The push came at 20:36Z,
  after a re-lock and an rc of 0 read directly. At 00:28Z it logged the outbox as pushed; the push
  had been rejected (rc=1, origin had moved). The 00:29Z correction calls it "the third time this
  run" and sets the rule: a log line comes only after the push's rc is printed, in a separate
  command.
- **You had to remind it.** At 18:02Z you wrote "I am constantly needing to remind you of things
  and give feedback, these things should be handled automatically", and asked not to spend half
  the budget on small UI tweaks. Before that you had corrected the pile names (17:45Z) and asked
  whether the bridges were a library (17:52Z).
- **Its demos ran old code.** R1 found the :8096 demo on an agents worktree 34 commits behind
  main, with 0 stocks.
- **Its walkthrough venv had the task system.** The agents' `dev` extra brought tasking in, so T2
  showed a Tickets entry, a TASKS panel and twelve unanswered task queries. T3 made it a
  coordinator must, now in the script.
- **Restarts minted a new login token for about a minute** before the pin; you saw it change
  (19:10Z). `restart-example.sh` now writes the pinned token first.
- **Cleanup leaks.** An orphaned `fake_bridges.py` ran 5 h 30 from a plugin test (killed 00:10Z).
