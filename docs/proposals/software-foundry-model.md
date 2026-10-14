# The software foundry model: stocks, flows, and what Orchestra shows

Status: proposal, 2026-10-14, revised after an independent review (the review's measurements
are quoted below as "measured"). Replaces the ticket-state "stocks and flows" map on the
Agents page. Sources: `docs/research/sd-software-models.md` (the published structures),
`docs/research/foundry-sd-claude.md` and `docs/research/foundry-sd-gemini.md` (two
independent answers to the same question).

## 1. What the foundry produces

Orchestra is a software foundry: AI agents are the machines, and the product is good
software. The ticket tracker is the work-order system of the foundry, not its output. A
ticket can reach DONE and the software still be worse. The map therefore shows what the
foundry holds and produces, with tickets appearing only as demand and as the owners of
work in progress.

The system-dynamics models of software projects (Cooper's rework cycle, 1980, surveyed by
Cooper and Mullen in 1993 and by Lyneis and Ford in 2007; Abdel-Hamid and Madnick, 1991;
Madachy's defect flows, 2008; Ford and Sterman's phase model, 1998) share one structure:

```
Work to do ──progress──▶ Work done
                           ├── really done                       (fraction correct and complete, FCC)
                           └── undiscovered rework ──discovery──▶ Known rework ──rework──▶ Work to do
```

Three parameters govern it: productivity (work per unit effort), FCC (the share of work
that is right the first time), and discovery (at an inspection, a probability of detection;
after release, a delay). Every named loop in the literature changes one of those three.

Two other bodies of work are used here without claiming they reduce to that structure:
Reinertsen's queues (every waiting stage is a stock whose outflow is capacity-limited, and
variability at high utilisation blows up its residence time) and the DORA keys, which read
the release stage of the same chain. Two stocks on this page, verified behaviour (T) and
environment resources (R), are Orchestra's additions: the literature treats test effort as
a detection-efficiency parameter and improvement as Repenning and Sterman's capability
stock, not as things counted in a repository. They are labelled as additions on the page.

Orchestra's job on this page is to measure what it can of those parameters and stocks, to
say plainly what it cannot, and to show which agent sits on which flow and which flows have
no agent, so the operator can see where to add an agent or an event binding.

## 2. The stocks

A stock is a quantity the foundry holds that accumulates and drains. Each has one unit, an
inflow, an outflow, and one or more estimators (section 4). The built-in stocks are the
software foundry's defaults; a project in another domain declares its own (section 5).

| # | Stock | Unit | What it is | Inflows | Outflows |
|---|-------|------|------------|---------|----------|
| D | **Demand** | tickets | Work ordered and not started: OPEN and BLOCKED tickets. | ticket_created, reopen, a ticket blocked back to the planner | start (OPEN → IN_PROGRESS), cancel |
| W | **Work in progress** | changes | Changes being worked now: tickets IN_PROGRESS, a first implementation or a fix. The chain counts changes in every stock, so one unit is conserved from D to the gate; the commits ahead of main on each change's branch are the detail beside every chain stock's level (a change waiting at the gate still shows its +12). | start, fix pickup | submission, cancel, blocked back to demand |
| Q | **Awaiting review** | changes | Submitted changes the reviewer has not judged yet (Reinertsen's queue). The rework cycles circulate the change through here; the defect co-flows into U. | submission (READY_FOR_REVIEW) | the reviewer's verdict (IN_REVIEW → APPROVED / REJECTED) |
| K | **Known rework** | open defects | Defects a reviewer or the gate found whose fix has not landed (Cooper\'s rework to do, Madachy\'s detected defects). The fix pickup carries the change back into W without draining it. Send-backs with no verdict are not defects and go to Returned (section 3). | defect found in review; defect found at the gate; defect found after landing | the fix lands (gate_landed) |
| U | **Undiscovered rework** | commits | Defects in W and L not yet found. Hidden. **Not displayed as a number until a post-landing estimator exists** (section 4); shown as "not estimable" with the reason. | injection = progress × (1 − FCC) | discovery |
| L | **Landed software** | commits | Commits the gate put on main, with first-parent diff size. The product. | gate_landed | none (rewrites are measured as churn, below) |
| A | **Really done** | acceptance tests passing | Acceptance tests that pass, not skipped, against the current staging build. Abdel-Hamid's *actual* progress, against DONE tickets as *perceived* progress. | tests pass on a new build | tests fail or are skipped on a new build |
| B | **Working build** | builds | The staging build the acceptance suite last ran against, and whether it is up (a health check in the last ten minutes). | staging_deployed | staging_failed; staging_restarted (the health loop restarting it) |
| P | **Pipeline blocked** | pauses | The gate is paused: main itself failed the gate, or an operator paused the pipeline. The pipeline manager's resume drains it; broken base balances through it. | gate_base_broken, pipeline_paused | pipeline_resumed |
| T | **Verified behaviour** (Orchestra's addition) | tests | Tests on main by stage: collected, passed, failed, skipped, from the last gate run. Skipped tests are shown and never counted as verified. | tests added per landed change | removed or skipped |
| R | **Environment resources** (Orchestra's addition; Repenning's capability stock) | documents | What the worker and reviewer read before working: AGENTS.md, README, team docs, roles, decided lessons, team tools. Count and line budget; accuracy by judgement. | lessons decided; agent-facing doc commits landed | pruned; over budget |
| C | **Agent time** | agent-hours per day | Wall time of agent sessions by activity: implement, fix (a session on a REJECTED ticket), review, improve (devex), plan (coordinator, product owner, supervisor). Losses are listed beside it: restarts, timeouts, compactions, resets. No serving-capacity term. | sessions | sessions |

Measured on the demo log over 2.58 days: D = 4, W = 3 tickets with 16 commits ahead (CA-18
+12, CA-24 +4), K = 1, L = 21 landings (+7,067/−435 lines), T = 116 tests with 13
acceptance tests skipped, R = 16 documents, 306 lines, 8 decided lessons, C = worker 86.5 h,
coordinator 28.5 h, reviewer 20.7 h, devex 18.8 h.

Integration must balance. W integrated from ticket transitions does not (start − land −
send back − restart gave −49 against a true level of 3, because the fix return and BLOCKED
flows were missing), which is why W is measured in commits from git and the ticket-state
pipeline is only a drill-down (section 6). An events-level estimator always has an anchored
initial value (section 5).

## 3. The flows, the machines on them, and the loops

**How this section is used.** The flows and loops below describe the software foundry's
reference arrangement. In Orchestra they are *detected*, never declared: `foundrygraph`
builds a signed causal graph from the stocks' filling and draining events, every agent's
wake rules and emits (Orchestra's own bindings included), the stocks' consumers with their
declared effect sign, and agent-to-agent triggers; it enumerates the graph's elementary
cycles through at least one stock and one agent, computes each cycle's polarity from its
link signs, and matches the model's expected loops by membership. The reference
configuration lives in `tests/unit/test_foundry_golden.py` and must stay detected; a
second model from outside software (`test_foundry_golden_repenning.py`) keeps the detector
honest. The tables below are the expectation, not the implementation.

The detector's rules, each tested in `tests/unit/test_foundry_golden.py`:

- **Links.** An agent that emits an event filling a stock is a + link to it; emitting one that
  drains it is a − link. A stock wakes an agent on an arrival (+). A departure never links
  from the level: it reaches the woken agent as a − trigger from the agent that caused it
  (the gate's failure wakes the pipeline manager). A stock's declared consumers get the
  declared sign. An agent whose event wakes another agent and fills no stock is a + trigger
  between them; on the same pair, a trigger that lowered a stock outranks one that did not.
  What an agent emits is its declaration plus what its tools cause (the tickets group files
  tickets) plus, with the events group, its team chain's declared types (`effective_emits`).
- **Parallel links** with opposite mechanisms between the same two nodes are indeterminate
  from structure; the window's event counts only say which dominates today, and the card
  says so. No tie-break by name or order.
- **Cycles** pass through at least one stock, or are agent-only when a trigger on them lowered
  a stock; the stock is then a member.
- **Polarity.** A conserved material circuit, judged on the path (each stock on it filled by
  the agent before it and drained by the agent after it), is a stock-flow chain, not a
  causal loop: it carries no polarity and is drawn as pipes, with the source's claim beside
  it (Sterman ch. 6). Any other cycle is signed by the product of its link signs: negative is
  balancing, reinforcing otherwise, "?" when a link is indeterminate. First-order pairs (a
  stock and the agent that drains it) are the balancing loops the material circuits rest on
  and are listed as such; the template declares the rework cycles with no polarity and the
  broken-base controller as its pair (pipeline blocked ↔ pipeline manager), so the template
  and the detector say the same thing.
- **Send-backs without a verdict are not rework.** A review turn that ended at the limit, a
  lost gate run (timed out, failed to start) and a merge conflict return the change with no
  defect found: they fill *Returned without a verdict*, a stock of machine loss, not K; the
  re-pick drains it back into W. The same events fill K and Returned, so the pipes out of Q
  and out of the gate split by cause, each with its own count, and the pickups out of K and
  out of Returned are two flows ("11 fix pickups", "19 re-picks (loss)"). Every transition
  that follows a send-back carries the send-back's cause (defect, gate, no_verdict, lost,
  conflict) in the log's attribution, a pending defect's cause surviving the no-verdict
  send-backs after it, and a transition out of a working spell is attributed to the state the
  spell began from, looking past the restarts a turn limit causes.
- **Blocked is its own stock.** A worker's block moves the ticket to *Blocked*, with the
  planner; the coordinator's re-plan moves it back to Demand. Re-planning is then the
  conserved circuit W → Blocked → Demand → W, with the coordinator and Orchestra as its
  valves.
- **The cause a transition carries** is decided by its kind: a send-back carries its own
  verdict; a pickup carries the send-back it follows (a fix pickup or a re-pick); a
  submission is a fix while a defect is pending before it (through blocks, re-plans and the
  restarts a turn limit causes), otherwise a re-run after a send-back with no verdict; a
  verdict on a fix (an approval, a gate result) carries the defect not yet landed. A ring
  step with a cause counts every transition of its event that carried that cause, so the
  two rework rings' fix submissions sum to the fix rounds. A no-verdict return finds nothing,
  so a loss stock never takes a co-flow from the hidden stock.
- **Known rework is a stock of open defects** (Cooper's rework to do, Madachy's detected
  defects): a send-back for a defect fills it and the landing of the fix drains it, so the
  level is the integral of its own flows and is drawn in its own unit. The change itself sits
  in whatever box its state says (at the gate, blocked, being fixed), and every chain box
  names how many of its changes carry an open defect. The fix pickup carries the change
  back into W (a carrying link: the defect stays open), so the rework cycles are conserved
  circuits of the change through the pickup, the re-submission and the inspection, with no
  causal polarity; a bad fix re-enters them (Rahmandad and Hu's task cycling), and their
  balancing is the first-order pair of K and the gate that lands the fix.
- **A carrying event.** A stock may declare `carried_by` events that carry its content on
  without draining it, and `carried_to` the stock each delivers to: a deploy carries the
  landed commits into the build, so L → B is drawn as a pipe while main keeps its commits.
  Carries are not links of the causal graph.
- **A restart is a return.** W is counted in changes, so a turn-limit restart moves the change
  back to Demand: a pipe W → D labelled as a loss, not a creation into Demand.
- **Send-backs per ticket come from the log**, not the tracker's counter.
- **A pipe into a stock that splits send-backs by cause is counted by those causes**, and when
  the agent on the pipe moved none of them and Orchestra did, its valve is the turn limit.
- **A gate timeout that recurs is a defect.** A run that hits the gate's time limit is a loss
  (the machine), unless the same change timed out at the same stage more than once while
  other runs finished that stage: then the change under test hangs, and the runs are
  defects, named on the gate's label.
- **Ties keep their log order.** A send-back and its pickup logged in one second are read in
  the order the log wrote them; every rule that asks "what came before this transition" names
  the transition and takes everything logged before it, never everything with an earlier
  second.
- **A fix is judged by whoever judged it.** Bad fixes are split by the verdict that found
  them bad (the reviewer or the gate); the review loop's signal is the reviewer's share and
  the gate loop's the gate's, so a card never blames the reviewer for what the gate found.
- **Demand splits ready from waiting.** An OPEN ticket waiting on a dependency that is not
  DONE is not ready for pickup; the box says how many are ready, what the rest wait on, and
  the residence time is the ready part's.
- **A fix round belongs to the loop it was on**: the review loop's bad-fix fraction is the
  share of fixes of review-found defects that were judged bad, the gate loop's the share of
  fixes of gate-found defects, so the rings' counts and the cards' fractions have the same
  denominator.
- **An alarm retires**: "median turn at the limit" is not shown once the limit in force has
  gone twenty turns unhit.
- **A state is marked ◇** (a build, a check, a pause): its declared flows set it; they are
  never summed.
- **The chain is one line**: a pipe along a row is a hump over the gap between its boxes with
  the label on the run; pipes across rows take neighbouring bands by destination.
- **Each turn limit ends one turn**: a timeout within seconds of a settle belongs to the
  latest turn it falls in, never to two.
- **Verification is a state, never a substituted level.** Really done keeps what the last
  deploy proved and reads "unverified" while the build is down or main is broken; Verified
  behaviour reads the last clean check marked "stale" when the latest check failed on a
  suspect host, and the latest check otherwise.
- **How late** is the median delay from the submission a verdict judged to the verdict, by
  stage, and from a deploy to its first trouble after landing, shown with the discovery tile.
- **Starts split three ways**: first starts, starts after a re-plan (the re-planning loop's
  flow) and re-picks after a restart (a loss).
- **The rework flow.** The fix pickup (REJECTED → IN_PROGRESS) carries the change from K into
  W and is drawn as that pipe; W → U is the submission's co-flow. The rework cycles run K →
  Orchestra (the pickup) → W → worker → Q → reviewer → K, and through the gate.
- **Rework share is effort**: fix hours over fix plus implement hours, each net of the turns
  the limit killed; the wall-time share is beside it.
- **A loop ring's counts are the loop's own.** A transition on a ring is counted by the state
  the ticket came from: the step's event is the one that drained the stock before the agent
  on the ring, and the count is of transitions whose previous state belongs to that stock
  (for the review loop, submissions that followed a review rejection, not every submission;
  for re-planning, starts that followed an unblock, not every start). The log attributes
  each transition by its previous state for this.
- **Discovery after landing** is an expected loop (build → known rework → … → gate → build)
  with no agent on its first link until one is created, so the map carries a hollow stub at
  the build and at known rework, and the loop card the recipe.
- **A drained stock's level is a state.** Really done keeps what the last deploy proved and
  reads "unverified" while the build is down or main is broken (its declared outflows are
  the events that make it unverified, not a quantity to subtract); Verified behaviour reads
  the last clean check marked stale when the latest check failed on a suspect host.
- **Pipes across rows run orthogonally**, each on its own band between the rows with its
  label on the horizontal run; pipes along a row run above it with their labels above them.
  A label sits beside the vertical runs that pass its height where it can stay within reach
  of its own pipe; where it cannot, it keeps its halo and the crossing, since a label far
  from its pipe is worse than a line through its halo.
- **Rework is counted while the defect is unlanded.** A fix round is every re-submission of
  a change whose defect has not landed (Cooper: all effort between discovery and completion
  is rework), through blocks, re-plans and no-verdict reviews; a fix turn likewise; a fix is
  bad when the defect's next verdict is another rejection for a defect, good when it is a
  landing, and re-submissions between two verdicts share the verdict. The rounds histogram
  is the tracker's send-backs per ticket, said so.
- **A no-verdict send-back's valve is the turn limit**, not the agent whose turn was cut; a
  restart stands for a crash until `staging_failed` is emitted and says so; "down" is
  inferred from the silence of the health check and says since when.
- **Verdict latency, not discovery delay.** The time from the submission a verdict judged to
  the verdict, by stage, with n, and from a deploy to its first trouble; the defect's age
  needs the commit that introduced it (step 2).
- **Agents sit over the pipes they are the valve on.** An agent's circle is placed over the mean of the stocks
  it drains (over what wakes it, or what it fills, if it drains nothing), on three rows, and
  pushed apart only as far as names need; an agent on no flow sits at the right.
- **Gap advice names only the project's own agents and events.** The detector's fix for an
  open loop never tells Orchestra's processes to change and never lists Orchestra's own
  events as something a custom agent should emit; where a loop's template carries a recipe,
  the card shows that recipe and the detector's facts beside it.
- **Restarts are two losses.** A restart within ten seconds of a turn limit is the limit's;
  any other (a loop stop, a reset, an error) is an interrupt, and the label says both.
- **A first-order pair is balancing through its drain, never signed by a vote.** The window's
  dominant mechanism signs a disputed link only on a longer loop; a pair is its drain's.
- **Agents on the inlet** (they create tickets and move nothing between stocks) read "N
  tickets" or "fills only", never "unattached"; agents on no flow sit on their own row.
- **A disputed link is signed by the window.** Where one agent both fills and drains a stock
  (the gate rejects a fix into Known rework and lands a good one out of it), the link's sign
  is the mechanism the window saw most, and the card says which and how many; with no window
  the loop is indeterminate.
- **Flows drawn.** One event moves one thing. When an agent's event drains one stock and
  fills another it is a conversion, drawn as a pipe with the agent as the valve. Where the
  same event converts along the product's own path (chain row to chain row), its other
  conversions are the same movement seen from a rework stock and are not drawn again; a
  conversion into or out of the hidden stock is a co-flow (the defect inside the change),
  drawn as a thin dashed twin and never counted. So a submission is W → Q once, with K → U as
  its co-flow; a landing is approved → landed once.
- **Observed vs closable.** A cycle is observed when every step of it was seen in the window:
  an agent's event attributed to it (by `by`/`author`, by the state a transition leaves with
  REJECTED split by cause, or by the author of a note seconds before an unblock or cancel),
  or a wake or trigger whose event occurred. A cycle closable by declaration alone is shown
  as such.
- **Gaps.** An expected loop no cycle covers reports its missing members and, for each
  consecutive pair with no link, the binding that would close it, naming the project's own
  agent already woken by the first stock when there is one, and never telling a custom agent
  to emit one of Orchestra's own events.

| Flow | From → To | Machine | Measured by | Bindable event |
|------|-----------|---------|-------------|----------------|
| start | D → W | orchestra (pickup) | OPEN → IN_PROGRESS | ticket_transition:IN_PROGRESS |
| implement | effort → W | worker | commits on the ticket branch; READY_FOR_REVIEW arrivals | ticket_transition:READY_FOR_REVIEW |
| pre-review check | W → (pass / fail) | orchestra (runs the unit stage in the worktree before review) | **no event today**; the result goes only to the reviewer | to add: worktree_checked |
| inspect in review | W → K (defect) | reviewer | IN_REVIEW → REJECTED with cause = defect | ticket_transition:REJECTED |
| inspect at the gate | W → K (defect) | merge gate | gate_rejected where a stage failed on its own result | gate_rejected |
| conflict | W → W (re-queued) | merge gate | gate_conflict; Ford and Sterman's concurrence rework, driven by WIP, not by FCC | gate_conflict |
| machine failure | no change to W; a loss in C | — | gate stage timeout (rc 124), gate start failure, reviewer with no verdict, worker crash, turn timeout | turn_timed_out, turn_error, agent_crashed, gate_error |
| discover after landing | L → K | **unattended** (acceptance run on staging, the smoke test, humans) | a test that passed on a prior build and fails now; a bug ticket citing a landed commit; staging restarted | staging_failed, staging_restarted, ticket_created (bug) |
| fix | K → W | worker | REJECTED → IN_PROGRESS … READY_FOR_REVIEW; bad fixes are rounds rejected again | ticket_transition:IN_PROGRESS |
| land | W → L | merge gate | gate_landed | gate_landed |
| deploy | L → B | merge_gate (only the gate's success promotes a build) | staging_deployed | staging_deployed |
| add tests | effort → T | **unattended by default** (workers add tests as part of tickets; qa agents if declared) | test counts on main after vs before each landing | gate_landed |
| improve | K → R | environment keeper, devex | lessons decided; agent-facing doc commits landed | to add: lesson_decided |
| broken base | L → everyone's FCC | — | gate_base_broken | gate_base_broken |

Measured on the demo log: of 44 gate send-backs, 18 were conflicts and, of 28 failed runs,
11 were the acceptance stage hitting the gate's own 900-second timeout, 3 were start
failures, 14 were acceptance failures, and none failed at build or unit. 247 of 328 starts
were restarts after a turn ended without a result. The pre-review check runs only the unit
stage. So on this log, machine failures and conflicts outnumber defects found at the gate,
and the one place a defect is found is the stage the pre-review check does not run. The
page must make that readable.

Restarts return the change to Demand (W is counted in changes; the branch keeps its commits). They are a productivity loss
(Abdel-Hamid: actual productivity = potential − losses) and are shown beside C.

Readings, each defined by its estimator and shown with its window:

- **Inspection pass rate, review.** APPROVED verdicts over all verdicts (APPROVED plus
  REJECTED with a reviewer's note). This is Ford and Sterman's (1 − FCC) × p_detect seen
  from the outside, not FCC. A review that produced no verdict is not an inspection: it is
  a machine loss, counted apart, and the worker's following turn is a re-run.
- **Inspection pass rate, gate.** Gate runs that landed, over runs that ended on their own
  result (timeouts, start failures and conflicts excluded, and shown separately).
- **Gate failures by stage.** Build, unit, acceptance, start, timeout, conflict. Distinct
  defects are counted per ticket and stage: an environment fault that fails twenty tests is
  one defect; the failing tests are listed beside it.
- **FCC landed, upper bound.** Landed commits whose added lines survive unchanged after N days,
  over landed commits older than N days, by `git blame --first-parent` (GitClear's churn
  window; measured 8 % aggregate churn, 10 of 21 landings fully surviving at 2.58 days). It is
  an upper bound on FCC because discovery is incomplete: young cohorts look better than they
  are.
- **Time to restore.** From the first trouble of an outage (a staging failure or a health
  restart) to the next deploy that stayed healthy until the deploy after it; troubles inside
  an outage already counted do not start another. The health loop, not the pipeline manager,
  emits restarts and failures.
- **Escape rate.** Defects found after landing: each ticket created in the window that cites
  a DONE ticket or a landed commit (a bug report against shipped work), plus the deployed
  builds the health loop had to restart, where consecutive crashing builds with no healthy
  build between them are one surviving defect (Rahmandad and Hu's task cycling), and a ticket
  that names one of those builds is that defect's ticket, plus staging failures. It is the only estimator for U's outflow; U itself stays "not
  estimable" until a second, independent estimate exists (section 4), but the discovery
  share ("in review", "at the gate", "after landing") uses it.
- **Really done ratio.** A (acceptance tests passing, not skipped) against DONE tickets, and
  skipped tests shown next to it. The one number that says whether the software is good.
- **Rework share.** Fix hours over productive worker hours (implement + fix). Re-runs after
  a review that gave no verdict are a machine loss shown beside it, not productive time.
  Repenning's threshold of roughly a third was calibrated on total hours; the tooltip says
  which denominator is used.
- **Rounds per ticket.** The distribution, not only the median: Rahmandad and Hu show a few
  tasks cycling many times dominate rework (measured: 29 tickets at 0 rounds, two at 25 and
  27).
- **Review misses.** Approvals the gate then rejected for a defect before the next
  re-submission (each approval is a miss), shown with the distinct defects missed, one per
  ticket and gate stage: six approvals of one failing acceptance test are six misses of one
  defect.
- **Bad-fix fraction.** Fix rounds (a re-submission while a defect send-back is pending)
  followed to the defect's next verdict: a review or gate rejection for a defect makes the
  fix bad, a landing makes it good; approvals, no-verdict reviews, blocks and further
  re-submissions on the way do not decide it. Known rework is not cleared by a block (on an
  agent org a block is usually a turn-limit escape); beside its level the page shows the
  tickets whose defect send-back has not yet been followed by a landing.
- **Losses.** Restarts, turn timeouts, compactions, resets per day, as hours lost where the
  session time is known.
- **DORA keys, post-deploy only.** Landing frequency (gate_landed per day); lead time
  (creation → DONE, and reviewed commit → staging_deployed); change failure (deploys followed
  by staging_failed or a health restart); time to restore (staging_failed or restart →
  next healthy deploy). Gate rejections are *not* change failures; they are inspection results.

Schedule pressure, Abdel-Hamid's multiplier on error generation, has no analogue in
Orchestra: there is no deadline, no schedule variable, and no agent that works faster under
one. It is not modelled. A model or prompt change is the cohort variable that replaces
Abdel-Hamid's experience mix; every reading series breaks when the project's model or a
role's prompt changes.

The loops, with polarity from the literature and the signal that shows each one working.
A loop is drawn when its edges are observed in the log (the existing latent/observed rule
in `eventgraph`); hypothesised loops are listed, not drawn.

| Loop | Structure | Status | Signal |
|------|-----------|--------|--------|
| B1 defect removal | K → fix picked up → W → re-submitted → inspected → K: a conserved circuit of the change, drawn as pipes; its balancing is the first-order pair of K and the gate that lands the fix | observed | fix round trip short and stable; bad-fix fraction low |
| B2 earlier detection (Orchestra's addition) | T ↑ and pre-review checks ↑ → defects found before the gate | hypothesised until worktree_checked exists | share of defects found before the gate rising |
| B3 WIP limit | W ↑ → pickup paused, capacity lowered → conflicts and queue ages fall | observed when capacity_changed or pickup_paused follows | conflicts per landing and queue ages not rising |
| B4 capability (Repenning's "work smarter") | K by cause → improve → R → fewer send-backs for that cause | observed when devex edges are seen | the cause-specific send-back rate falling after its lesson lands; a cause not recurring |
| B5 broken base | gate_base_broken → pipeline paused → repaired | observed | time from base broken to next landing |
| R1 firefighting (Repenning) | rework share ↑ → worker slots and coordinator priority go to fixes → less add-tests and improve → more send-backs | hypothesised; the shared resource is the worker slots and coordinator priority, since devex has its own agents | rework share rising week on week with add-tests falling |
| R2 debt drag (Franco; no pressure term) | churn ↑ → maintainability ↓ → landed per agent-hour ↓ | hypothesised | landed per worker-hour falling while diff size is constant |

B4 is the devex loop. It closes through the world: a lesson becomes a doc, a doc becomes a
worker's context, and the effect appears as a lower send-back rate for that cause, delayed
by however long it takes a lesson to land. Measuring it needs the cause class as data,
which today exists only as prose in the lesson files (section 7).

## 4. Estimators: how a stock gets a number

Finding measurable stocks is the hard part of every system-dynamics model. Orchestra uses
three kinds of estimator and shows them side by side when more than one exists; where they
disagree (measured: CA-24 is REJECTED and carries 4 unlanded commits, so W by ticket state
and W by git differ) the page shows both and says which one the map uses.

1. **Inside the model.** Integrate the flows the log records: level = initial + Σ inflow −
   Σ outflow, with an anchored initial value and every flow enumerated. Exact for D and K.
   For U, the first-order estimate U ≈ τ × discovery rate applies only to the post-landing
   stage, where discovery is a delay; at an inspection, discovery is a probability per
   inspection, not a delay, and the review's cycle time (measured median 0.25 h) says nothing
   about how long a defect stays hidden. If a first-order delay is ever fitted, the median
   lag is 0.69 τ, not τ. A second, independent estimate of what remains hidden is
   capture-recapture between the reviewer and the gate on the same change (Eick et al. 1992;
   noisy, per Briand et al. 2000). U is displayed only when both an escape-rate series and a
   second estimate exist, and then with the two values as its range.
2. **Outside the model, deterministic.** A probe: a command that prints a number, run on an
   interval, in the team's space or in the repo with read-only access (the existing
   `Prober`). Also event counts and git queries. Used for W, L, A, B, T, R, C.
3. **Outside the model, by judgement.** An AI judge. It is an agent (an `AgentDef` with the
   `stocks` tool group and a `measure_stock` tool), never a command under the Prober, so its
   transcript is the harness session file like every other agent's. To contain volatility:
   the rubric asks for a class from a fixed list, never a magnitude; the judged input is
   snapshotted and its hash recorded with the reading; the judge makes N independent turns
   and the reading is the mode (median for ordinal classes) with the agreement recorded, and
   a reading below an agreement floor is withheld; comparisons ("better than the previous
   version?") are preferred over absolute ratings and the previous artefact is put in the
   judge's context by the tool; a change of model, prompt or rubric starts a new series and
   the chart shows the break. This needs a per-agent model override, which `AgentDef` does
   not have today and which all three harnesses must honour; until it exists, the judge runs
   on the project's model and the series breaks when that changes. Used for cause
   classification of send-backs (already done by devex in prose), lesson applicability, and
   doc accuracy.

Every reading is an event, `stock_measured` {stock, estimator, value, input_hash, samples,
agreement, window}, so the series is in the log like everything else, and a stock's
"perceived" value is the smoothed series (Sterman's perceived-vs-actual pair), not the last
sample.

## 5. The model is data; the software foundry is the template

The stocks, flows, and loops above are Orchestra's **template** for a software foundry: an
initial diagram of what a project's workflow might need. They are not the model. Every
project has its own outputs (a Lab produces research a Product Owner consumes; a devex team
produces resources the workers consume; a non-software project produces something else) and
its own limiting constraints (a token budget, a review quota, a single staging host). So the
model lives in the project's repository as data, like roles, agents, and teams, and an agent
within the system curates it. Nothing about the model is hard-coded in Orchestra; code holds
only the instruments (how a number is measured) and the renderer.

```
.orchestra/model/
  stocks/<key>.json      # one stock: name, unit, description, inflows, outflows, consumers, estimators, hidden, addition, row, pos
  loops/<key>.json       # one expected loop: name, polarity (as claimed), structure, nodes, signal, readings, hint, source
```

There is no flows directory: flows are derived by the detector from the agents' wake rules
and emits and the stocks' events.

`orchestra init` writes the software-foundry template there. A project that predates the
model gets the template at the first `orchestra` start that finds no `.orchestra/model/`,
written and reported in the log so the Supervisor knows it is a starting point.

A stock's estimators name an **instrument kind** and its parameters; the kinds are the only
part in code, and adding one is a code change:

| kind | parameters | measures |
|------|------------|----------|
| `tracker` | `states` | tickets in those states now |
| `pending_defects` | | tickets sent back for a defect and not yet re-submitted |
| `git_ahead` | | commits ahead of the base branch on open ticket branches, and commits made in the window |
| `landed` | | commits the gate put on main, lines, survival |
| `gate_tests` | `stage`, `source: deployed|main` | pytest counts for that stage of the chosen gate run |
| `staging` | | the staging process state and its deploy event |
| `repo_docs` | `globs` | files matching the globs, their lines, decided lessons |
| `turn_hours` | | agent turn time by activity, losses |
| `events` | `inflows`, `outflows`, `initial`, `since` | initial + Σ inflows − Σ outflows |
| `probe` | `command`, `every` | a command that prints a number, run under the Prober in the owning team's space, read-only in the repo |
| `judge` | `agent`, `rubric`, `classes`, `turns`, `min_agreement` | an agent's classification (section 4) |
| `none` | `reason` | a hidden stock, never a number |

A loop's `signal` names one of the computed signals and its adverse direction and
threshold; the detector marks it observed when every step of its cycle was seen in the log.

Rules, enforced by the store like the rest of the org model:

- Before placing an agent, an agent asks the model: `inspect_model` (no argument: every
  flow with its valve, every open loop with its fix, departures nobody wakes on, agents on
  no flow; `agent=`, `stock=`, `event=`, `loop=` for one part and everything connected to
  it) and `what_if_agent name= wake_on= emits=` (the loops a hypothetical agent would close,
  the flows it would be the valve on, the departures it would start consuming, the bindings
  that touch no stock; nothing saved, the `create_agent` call returned). Both are read-only
  and in the `team` tool group, so any lead may ask.
- The `model` tool group carries the three mutations. The Supervisor has it; a role the
  Supervisor creates with it (a scheduled model curator) may curate stocks and loops, and
  other agents can send it their model questions instead of learning the tools.
- Otherwise only the Supervisor creates, changes, or deletes model elements (`list_model`,
  `propose_model`, `add_model_element`, `update_model_element`, `remove_model_element` in
  `api_org`), in conversation, exactly as teams and agents are made. The org guide gets a
  section on when to add one: when a team produces something another agent consumes, when a
  loop's purpose names a quantity the map cannot otherwise show, or when a constraint the
  project is subject to should be visible beside the flows it limits.
- A custom inflow or outflow event type must already be in the owning team's `emits`;
  `create_stock` refuses otherwise and says to `update_team` first.
- Keys are snake_case and unique across stocks, flows, and loops. Deleting an element does
  not delete its measurements; the series stays in the log.
- Producers are not declared: they are the agents whose own or team `emits` include an
  inflow type, and `bound` agents on a flow are those whose wake rules match its `binds`.
- Positions and routes are hints for the renderer; an element without them is placed in a
  free slot of its row (`capability`, `chain`, `rework`), never dropped.

Discovery of candidate stocks is a Supervisor task, not code: the loop detector already
reports loops the Supervisor has not named, and the same wake-up can list event types and
team spaces that no stock names, so the Supervisor can propose one.

## 6. What the page shows

The "The foundry" section of the Agents page is drawn from the model and the detector only.
Every term that is not plain English has a one-line definition in its tooltip, and every
number states its estimator.

1. **Headline readings.** Really done (acceptance passing in the deployed build's run, main's
   latest run beside it); inspection pass rates on verdicts and on the gate's own results,
   with distinct defects beside detections; rework share; agent hours in turns that timed
   out and each machine's timeout share; rounds per ticket and bad fixes; FCC landed upper
   bound; landing frequency with each lead time; change failure after deploy.
2. **The map.** Stocks are boxes placed by their row (capability, chain, rework) with their
   level and one line of detail; the hidden stock is dashed and never a number. Agents are
   circles placed over the stocks that wake them, with in-use/capacity and median turn
   (flagged when the median is the turn limit). Every derived link is drawn with its sign:
   fills and wakes and reads positive, drains and declared negative effects in the warning
   colour, with the day's count of the link's event. Hovering a stock, an agent, or a loop
   card isolates it; clicking an agent opens it.
3. **Loop cards.** One card per expected loop: detected (its ring drawn from the detected
   cycle, polarity from the signs, and "source says X" when the claim differs) or a
   hypothesis the current org does not close (its expected members, so the gap is
   explicit). Each card shows its signal's reading and direction from the day before and a
   hint only when the signal is adverse. Cycles the detector finds that no loop names are
   drawn as unnamed cards with a signature the Supervisor can name.
4. **The binding catalogue** (agents × events) stays, and the ticket-state pipeline is the
   drill-down for reconciling against the tracker.

## 7. Data Orchestra already has, and what it must add

Already in the log or store: every ticket transition with from/to; gate runs with outcome,
stage results and return codes (in `runtime.json`), and tickets; staging deploys and
restarts; sessions with kind and duration; the classified causes the devex team files as
prose in lesson files; team probes.

Step 1, buildable now from what is measurable: inspection pass rates (the existing
`RETURNS` in `loopmetrics`, with non-defect send-backs excluded once the cause exists, and
until then labelled "all send-backs"); gate failures by stage with timeouts and conflicts
separated; rework share; rounds per ticket; windowed churn by `git blame --first-parent`;
really-done from the last gate run's acceptance summary and the staging state; losses;
the DORA keys restricted to post-deploy signals; W and L from git. Built-in stock
definitions in `foundry.py`; the page as in section 6 with U "not estimable".

Step 2, the events the remaining estimators need:

1. `worktree_checked` from the pre-review run in the loop (stage, passed, failed, skipped,
   rc), so the discovery split has a "before review" bin.
2. Per-stage test counts (collected, passed, failed, skipped) and the timeout flag on every
   gate run, parsed by the gate runner rather than from the tail, and the first-parent diff
   size on `gate_landed`.
3. `cause` on every send-back: `defect`, `no_verdict`, `timeout`, `conflict`, `crash`, set by
   the loop where it already knows (reviewer with no verdict, worker crash) and by the gate
   (stage rc 124, start failure, conflict). Review rejections default to `defect`.
4. `kind` on `session_settled`, so C by activity needs no join.
5. `lesson_decided` (and a doc-landing event when an agent-facing file lands), with the cause
   class as a structured field, declared in the devex team's `emits`.

Step 3: the model as data: `.orchestra/model/` written by `orchestra init` (and on first
start for older projects), loaded by the store, the Supervisor's model tools, the org guide
section, `stock_measured` events, and the judge agent with `measure_stock` after a per-agent
model override exists. U appears only when section 4's condition holds. This step is part of
the definition of done: the map is not finished while any stock, flow, or loop is hard-coded.

## 8. Open questions

- The churn window N for FCC landed: GitClear uses 14 days; the demo project has run for
  under three, so the reading starts as "no cohort old enough".
- Whether "really done" should also count acceptance criteria on DONE tickets that have a
  named test, so a ticket closed without a test shows as unverified.
- Whether the escape-rate series can ever be dense enough in a project with no users to make
  U estimable, or whether U stays a dashed box by design and the page says so.

### The template and the project's model

`orchestra init` writes the template into `.orchestra/model/`, each element carrying a
`template_hash` of its own content. At every start of `orchestra run`, `orchestra web` and
`orchestra model init`, an element whose content still matches its mark (never curated) is
replaced by the current template; a curated element is kept; an element with no mark that
differs from the template is reported on the page and by `model init`, and only `--force`
replaces it. So a project follows the template until it curates an element, and never loses
what it curated.

A declared loop is detected by a cycle that covers its nodes with at most two members beyond
them: a long cycle that happens to pass through a loop's stocks is a different structure, and
is listed among the unnamed cycles instead.

