# Proposal: a system dynamics model at the centre of Orchestra

Status: draft 2, 2026-10-24. Nothing built. An argument and a plan.

Draft 2 changes:
- Our work is now one system coupled to a larger one (production, and its change process).
- Choosing stocks is treated as an ontology question.
- The "objections" are recast as the strategy they imply.

Builds on:
- SD Lab (`~/orchestra/sdlab`: `MODEL.md`, `docs/SPEC.md`, `OPERATIONALIZATION.md`): stocks,
  flows, machines on flows, live runs, eras, fitting, discovery, and leverage;
- `docs/work-charter.md` (what my job is) and `docs/proposals/orchestra-for-the-whole-job.md`
  (the desk), which this proposal reframes rather than replaces.

---

## Decided, 2026-10-24 (supersedes anything below that conflicts)

1. **Orchestra is system-dynamics-first, now and permanently.** It isn't a task management system.
   Task management, agent invocation, review and the merge gate are **use cases**, implemented in
   the framework by adding **machines** to the **factory** (the model).
2. **Machines are attributed to flows.** A machine may be attributed to several flows. A machine
   doesn't define a flow's equation or values.
3. **Flow equations are observed, not proclaimed.** They are fitted or discovered from the actual
   data: events and sampled levels. A machine's *intended* effect on a flow is a hypothesis.
   It's validated by comparing the observed equations before and after the machine is attributed
   (an era), never asserted.
4. **The SD Lab work's value is its strategies for inferring system dynamics equations from raw
   data.** Those strategies are what moves into Orchestra (open: as `orchestra.sd` or as a
   dependency). The SD Lab editor and ladder stay where they are.
5. **The work happens in the Orchestra application** (this repository), not in `sdlab/`.

How to refactor the current task system into this shape is **not decided**. A candidate first
version is in `events-and-data-infrastructure.md` §7.

---

## 1. The claim

Orchestra's core today is a **task queue with a state machine and a merge gate**. That's a
hand-written model of one process (tickets become commits on `main`), and it treats a done
ticket as the goal.

For an SRE, nothing in that picture is the goal. The goal is **reliability**: fewer outages,
shorter ones, less risk. Those are stocks in a much larger system, production and the
organisation that changes it. We can't move them directly. Our work moves other things:
- an autoscaler's settings;
- an alert threshold;
- a runbook;
- a flag-ramp policy;
- a readiness review.

Those change **how production behaves**, and often **how changes to production behave**. If
reliability improves, it's because a structural change we made propagated through a system we
don't control.

So the proposal is to put **coupled system dynamics models** at the centre of Orchestra:

- a model of the **target system**: production, its load, its capacity, its risk, its failures,
  its change process;
- a model of the **work system**: what's asked of us, the work in progress, the machines
  (people, agents, programs), what we produce, and what we spend;
- an explicit **coupling**: which element of the target system each artifact of ours changes.

Task queues and merge gates become **one implementation** inside the work system, a template.
Agents are machines on flows. Every intervention is an experiment whose effect is predicted by
simulation and then checked against data, at every link of the chain from effort to outcome.

## 2. Two systems, and why our work is meta

### 2.1 Three layers

| Layer | What it is | Examples of its stocks |
|---|---|---|
| **Runtime of the target system** | Production as it runs. | Traffic, queues, in-flight requests, pods, memory, errors, open incidents, error budget |
| **Change process of the target system** | How production gets changed, mostly by other teams. | Deploys in flight, flag ramps in progress, unreviewed config changes, services without a readiness review |
| **Our work system** | How we change the first two. | Asks, criteria specified, tests passing, commits landed, docs approved, dollars and hours |

The layers run on different clocks: seconds, hours, and days. They are separate models, linked
by declared couplings (section 2.3), not one giant model.

### 2.2 Our work is a change to how things change

Most SRE work doesn't move material in production. It changes the **equations**:

| What we change | Meadows' level | Example |
|---|---|---|
| A number | Parameters (weakest) | Raise a memory request; change a timeout |
| A buffer | Buffer sizes | More headroom in a node pool |
| A structure | Stock-and-flow structure | Add a queue with load shedding |
| A delay | Lengths of delays | Faster detection (better alerts), faster rollback |
| A balancing loop | Strength of balancing feedback | Tune the vertical autoscaler; add a circuit breaker |
| A reinforcing loop | Gain around driving loops | Retry budgets that stop retry storms |
| Information | Information flows | Make flag ramps and deploys visible in the alert view |
| Rules | Rules of the system | Every prod change behind a flag; readiness review before prod |
| Goals | Goals of the system | Error-budget policy that freezes risky change |

The change-process layer is where "changes to the way changes change things" lives. A deploy is a
flow in the change layer. A fraction of deploys flows into incidents (the change failure rate).
Flag ramps, canaries, readiness reviews, and ramp approvals change **that fraction**, a
coefficient on a flow between two layers. That's second-order work, and it's most of governance.

### 2.3 The coupling is structural

An artifact of ours doesn't pour into a target stock. It changes an element of the target model:
- a parameter;
- an **effect** of a stock on a flow;
- a delay;
- a loop.

SD Lab can already represent this. A work-system stock such as `services_with_tuned_vpa` is an
**effect** on a target flow such as `oom_kills`, or a parameter of it. Every coupling is declared
in the model:
- which artifact stock;
- which target element;
- the expected shape;
- and the expected size.

**Decoupling is a design goal.** The fewer and narrower the couplings, the easier it is to say
what caused what. So:
- each work item declares the **one** target element it means to change;
- changes to the same region of the target system are **staggered**, not landed together;
- feature flags are used as **on/off eras**, which makes each one a natural experiment;
- the work system's own dynamics shouldn't depend on production, except through the
  incident and ask inflows, which are modelled as inputs.

### 2.4 The chain of verification

Every intervention has the same chain. Each link is checked separately, so a failure shows
**where** the chain broke.

```
effort ──► artifact ──► structural change ──► leading stocks ──► goal stocks
(agent turns,  (config     (the fitted parameter   (OOM kills,       (error budget,
 test runs)    landed)     actually moved)         latency, retries)  outages)
   │             │              │                       │                 │
 work         landing        discovery / refit      dense, fast        sparse, slow,
 efficiency   (certain)      on the target model    to verify          often simulated
```

Worked through for "tune the memory autoscaler" (section 5):

| Link | Question | How it's checked |
|---|---|---|
| Effort → artifact | Did the work land? | The commit is on master and deployed. Certain. |
| Artifact → structural change | Did production's behaviour actually change? | Refit the target model in the new era: did the memory-request gain move as intended? |
| Structural change → leading stocks | Did the dense symptoms respond? | OOM kills per day and pod restarts, compared across eras. |
| Leading → goal | Does the model say outages fall? | Simulate the old and new models under the same load. Outages avoided are **credit for prevention**, because they are too rare to count. |

The last link is where SD earns its place. Outages are rare, so their counts can't verify
anything in a quarter. A model fitted on dense leading stocks, and validated on the incidents
that did happen, can (Repenning and Sterman 2001).

## 3. Choosing stocks: an ontology problem

What we decide exists determines what we can learn. Sparse data isn't a flaw to put up with.
It's a sign that we picked the wrong things to count.

### 3.1 How much data a stock needs

Counts are roughly Poisson, so a rate measured from *n* events has a relative error of about
1/√*n*:

| Events per measurement window | Relative error |
|---|---|
| 10 | ~32% |
| 100 | ~10% |
| 1,000 | ~3% |

- **Tickets are too sparse.** 2,000 tasks in two weeks sounds like a lot, but split by type and
  state it's a few per cell per day.
- **My PRs at work are far too sparse.** About 10 merged a week gives a ±32% weekly rate, so no
  intervention could be judged inside a sprint.
- **Outages are sparser still.**

None of these can be the stocks we fit on. They can be the stocks we *report*.

### 3.2 The ladder of measures

Measures fall on a ladder. Lower rungs are dense and weak; higher rungs are sparse and
meaningful.

| Rung | Density | Meaning | Work-system examples | Target-system examples |
|---|---|---|---|---|
| **Activity** | Very high | Little on its own | Unit test runs, shell commands, agent turns, tokens, file edits, CI runs | Requests, deploys, config pushes |
| **Progress** | High | Work is converging | Acceptance tests newly passing; acceptance tests **verified by a separate agent** to check what their criterion says; review comments resolved | Canary checks passed; flag-ramp steps completed |
| **Output** | Medium | Something crossed the company boundary | Commits on remote master; PRs merged; docs approved; CCB approvals; alert tickets commented | Changes fully rolled out; readiness reviews passed |
| **Effect** | Medium (dense if the target is) | The target system's structure changed | Fitted parameter shifts; a loop's gain reduced; a delay shortened | OOM kills, retries, saturation, alert noise |
| **Outcome** | Low | What objectives are about | Points delivered; OKR key results | Error budget, SLO attainment, outages, outage minutes |

- The **flows between rungs are the efficiencies**: test runs per newly passing acceptance test,
  passing tests per commit landed, commits per effect observed. Each is a fitted ratio with an
  interval.
- The dense rungs give **statistical power**: an intervention's effect on activity and progress
  shows within days.
- The sparse rungs give **meaning**.
- The model links the two, so a change on a dense rung predicts the sparse one, and the
  prediction is checked when enough sparse data exists.

### 3.3 Tasks are bookkeeping

A ticket is useful for two things:
- **communication across the company boundary** (Jira, sprint points, the PR's Jira key);
- **grouping** for people.

It's not a good unit of work, for three reasons:
- **Sizes vary by an order of magnitude.** "One ticket" can be one hour or one week.
- **It isn't conserved.** Tickets split, merge, and get cancelled, so balance equations don't
  hold.
- **Its state is reported by whoever holds it,** not measured.

The proposed unit of work inside the work system is the **acceptance criterion with an
executable test**. Its chain of stocks:

```
criteria specified ─► tests written (failing) ─► tests passing ─► tests verified (by a separate agent)
                   ─► landed (commit on master) ─► rolled out ─► effect observed (target refit)
```

- Criteria are roughly comparable in size.
- They're counted by sensors: the test runner, git, CI.
- They're numerous enough to fit: tens per ticket, hundreds per week.
- They build on what Orchestra already insists on: verification and acceptance tests.

**Tickets are a grouping over criteria,** kept for Jira and for people. A ticket is done when
its criteria are landed. Its points are an estimate attached to the group, and the model can fit
how well points predict criteria and effort.

**Commits on master** stay as their own stock. They are what the company counts, there are
several per ticket, and they sit on the output rung.

### 3.4 What makes a good stock

A stock earns a place in the model when it is:

1. **Dense enough** for its role. On the fitting rungs, dozens or more per measurement window.
2. **Meaningful,** or linked by a fitted flow to something meaningful.
3. **Counted in conserved units,** so in − out = change holds and the balance can be checked.
4. **Sensed, not self-reported.** Read by a program from git, CI, the test runner, or an outside
   API, not taken from an agent's word. An agent's verdict counts as a measurement only when the
   verifying agent is separate from the producing one.
5. **Tied to an audience.** Someone judges it: me, my manager, upper management, the CCB, the
   service owners.
6. **Paired with its opposite,** so gaming one shows up in the other:
   - commits with reverts;
   - tests passing with tests flaking;
   - alerts commented with alert noise;
   - points delivered with rework.

### 3.5 OKRs pick the top of the ladder

An OKR's key results should be **stocks or rates in the model**, and its objective should be a
**goal stock in the target system**. So choosing stocks starts from the OKRs and works both ways:

- **Up to the objective:** which target-system stock the key result is meant to move, and
  through which coupling.
- **Down to dense measures:** which progress and effect stocks predict the key result, so it can
  be forecast in week three of the quarter, not discovered in week thirteen.

A key result with no path to a target-system stock is activity dressed as an outcome, and the
model makes that visible at planning time.

## 4. A catalogue of stocks

A starting catalogue, not a final one. For each stock: its rung, and whether it's a goal (G),
its opposite (O), or a resource (R).

### 4.1 Work system

| Group | Stocks |
|---|---|
| **Demand** | Asks from people (Slack, Jira); review requests to me; pages; customer tickets; commitments (sprint points committed, key results) |
| **Specification** | Problem statements, proposals, and designs, by status; acceptance criteria specified |
| **Activity** | Test runs; commands run; agent turns; tokens; CI runs |
| **Progress** | Acceptance tests failing, passing, and verified; review threads open and resolved |
| **Output** (G) | Commits on remote master; PRs merged; docs approved; CCB approvals; reviews given; alert tickets commented; postmortems published; action items closed |
| **Quality** (O) | Rework; reverts; bugs traced to my changes or my approvals; flaky tests; stale PRs; unanswered asks |
| **Resources** (R) | My hours (by kind: focus, meetings, on-call); budget dollars; agent capacity; CI capacity; reviewers' attention and goodwill (soft) |

### 4.2 Target system, per service or platform

| Group | Stocks |
|---|---|
| **Load and capacity** | Traffic; queue lengths; in-flight requests; pods; nodes; memory; CPU; headroom |
| **Change process** | Deploys in flight; flag ramps in progress; config changes; changes without a flag (O); services without a readiness review (O) |
| **Latent risk** (O, leading) | Open postmortem action items; secrets near expiry; untested disaster-recovery paths; unmonitored services; noisy alerts (alert debt); known single points of failure |
| **Failure** (O) | Errors; alerts firing; incidents open; OOM kills; retries |
| **Reliability** (G, lagging) | Error budget remaining; SLO attainment; outage minutes (O); detection and recovery times (delays, not stocks) |

### 4.3 Organisation (soft, mostly proxies)

| Stock | Proxy |
|---|---|
| Reviewer goodwill toward me | Time to first review on my PRs; reviews I gave each author |
| Management confidence | Commitments met; the monthly slide's reception (my note) |
| Team knowledge | Runbooks current; incidents resolved without escalation |
| My professional standing | Asks routed to me by name; designs approved on the first round |

Soft stocks are labelled as unmeasured and carried through proxies. Leaving them out would be
assuming their effect is zero (Sterman 2000).

## 5. Worked example: memory autoscaling and uptime

The target layer is a simplified version of the kubernetes structures SD Lab's ladder already
discovers (cases 300–317: `ready`, `pending`, `inflight`, `retries`, `oom_kills_total`, a hidden
memory leak in 310).

```
TARGET RUNTIME (time unit: minute)
  traffic ──► inflight ──► served
                 │  retries (reinforcing: errors ──► retries ──► inflight)
                 ▼
  memory_used ──(over limit)──► oom_kills ──► restarts ──► errors ──► budget_burn ──► error_budget (G)
       ▲                                                                       │
       └── vpa_adjust: gap(target_ratio × usage − request) / time   ◄── parameters (gain, bounds, cooldown)
                                                                               │
                                                                     outages = incidents when
                                                                     budget_burn > threshold (sparse)

TARGET CHANGE PROCESS (time unit: hour)
  deploys ──► rolled_out          deploys × change_failure_fraction ──► incidents
  flag_ramps ──► ramped           change_failure_fraction ← effect(flagged share, ramp review coverage)

OUR WORK SYSTEM (time unit: day)
  criteria specified ──► tests passing ──► tests verified ──► commits on master ──► rolled out
  ("VPA bounds follow     (unit and         (agent checks the    (config change)     (deployed)
   p99 usage per pod")     acceptance)       test asserts p99)

COUPLING (declared)
  rolled-out "vpa-tuning" change  ──sets──► vpa gain and bounds        (expected: OOM kills −60%)
  services_with_flags (work output) ──effect──► change_failure_fraction (expected: −20%)
```

**The hypothesis, before the work starts:**
- **Work:** about 12 criteria, about 3 commits, about $15 of agent work, 2 days.
- **Structural change:** the fitted VPA gain moves into the band the change sets. Checked by
  refitting the target model in the new era.
- **Leading stocks:** OOM kills per day down about 60% within a week; restarts follow.
- **Goal:** simulated error-budget burn under last month's traffic drops by X%. Simulated
  outages avoided this quarter: Y.
- **Kill criterion:** OOM kills not down 30% after 7 days, or p99 latency up.

**What each verdict means:**
- **Commits landed but the gain didn't move:** the config isn't doing what we think. It's a work
  problem, cheap to find.
- **The gain moved but OOM kills didn't:** our model of production is wrong. Discovery is pointed
  at that region.
- **OOM kills fell but budget burn didn't:** OOM wasn't the driver of burn. The coupling was
  aimed at the wrong lever, and the next intervention goes elsewhere.

None of that is visible from "ticket DONE".

## 6. Why tickets are the wrong centre

| Question I actually have | Task-queue answer | Model answer |
|---|---|---|
| Is my work improving reliability? | Unanswerable. | The chain in section 2.4, link by link. |
| Am I on pace for my key results? | Count closed tickets. | Forecast from the dense rungs feeding them. |
| Why is turnaround over 4 days? | Look at old tickets. | Little's law per stock: work in progress ÷ throughput. The largest stock is the bottleneck. |
| Should I add a worker agent? | Try it. | Simulate. If human review is the bottleneck, more workers only grow the review stock. |
| Is this agent worth $20/week? | Unknown. | Its cost per unit moved on its flow, against a program, me, or nothing. |
| What's eating my time untracked? | Nothing shows it. | Discovery infers a hidden stock where the measured ones don't balance. |

Software project dynamics has long shown that a forward-only queue hides the **rework cycle**,
where defects found late flow back into the work stock (Cooper 1980; Abdel-Hamid and Madnick
1991; Ford and Sterman 1998; Lyneis and Ford 2007).

## 7. From goal to intervention: the planning loop

1. **State a gap** on a goal stock, in data or in simulation.
2. **Find leverage** across both systems. Rank target-system elements by how much a change moves
   the goal (SD Lab's Leverage panel does this per flow). Then rank work-system flows by how
   cheaply they produce the change.
3. **Propose an intervention.** The **planner** (an agent) writes:
   - the declared coupling: which target element, and the expected effect;
   - the work-system edit: new flows, machines, criteria;
   - the hypothesis along the whole chain (section 2.4);
   - a cost cap, an evaluation horizon, and a kill criterion.
4. **Design the machines.** An agent machine's brief comes from its flow's contract: what one
   item is, which stocks it may put into (its report choices), which downstream flows judge its
   quality, and its capacity and cost. A program machine becomes a code ticket.
5. **Approve.** It goes to me through the Supervisor, with the simulation.
6. **Apply.** An era starts in each affected model, with its configuration snapshotted.
7. **Verify each link** at its own horizon: dense links in days, effect links in a week or two,
   the outcome by simulation now and by data as it accrues.
8. **Refactor.** For a kept agent, try a program on the same flow, and judge it as an era on
   rate, quality, and dollars per unit. That makes "agents first, programs later" a series of
   measured swaps.

## 8. Discovery: black-box, reproducible understanding

A designed model says what I believe. A discovered model says what the data supports, found by a
fixed algorithm at a fixed commit from measured levels alone. That makes it reproducible and
checkable by anyone. The uses here:

- **Verifying structural change:** the artifact-to-structure link in section 2.4. Did the fitted
  gain, delay, or loop actually change in the new era?
- **Finding what I left out:** a flow I didn't model, a hidden stock (an unmeasured backlog, a
  leak), a rate that isn't what I believed.
- **Keeping the target model current** with daily diffs and residual watch
  (`OPERATIONALIZATION.md`, ideas 1–4). Without that, the predictions decay.

The trust each use needs is set out in `OPERATIONALIZATION.md`: orientation (T1), comparing eras
(T2), forecasting (T3). Attribution with confidence (T4) comes as data accumulates. The
discovered target model is also where most SRE value lands anyway: metastability scans, the risk
calendar, alert thresholds, and change risk (ideas 16–34).

## 9. What Orchestra becomes

| Layer | What it is | Today's equivalent |
|---|---|---|
| **Models** | Versioned SD models (target runtime, target change process, work system), with declared couplings, goals, and hypotheses. Every edit starts an era. | Hand-written state machines in `loop.py` |
| **Items** | The real things in work-system stocks, with identity: criteria, tests, commits, PRs, alerts, threads. Tickets group them. | Tickets |
| **Runtime** | Fires each work flow whose machine has capacity and whose source has an item it can take. | The loop's tick |
| **Machines** | Program, agent (a harness session), person (my to-do list and outbox), environment (only sensed). | Workers, reviewers, gate, resident agents |
| **Sensors** | Read levels and flow counts: test runner, git, CI, GitHub, Jira, Slack, PagerDuty, Prometheus, Orchestra itself. History programs backfill. | Probes |
| **Flow log** | Every take, put, firing, cost, and era. It is the event bus, the ledger, and the audit trail. | `events.jsonl` |
| **Analysis** | Fit, discover, simulate, leverage, diff (SD Lab's engine). | None |
| **Planner** | Section 7. | None |

Today's mechanics map across:

| Today | In the model |
|---|---|
| Waiting states | Stocks |
| Active states | Items held by a live firing |
| No zombies | A firing that ends without a put returns its items (SD Lab: "a non-zero exit puts the items back") |
| `report_ticket` / "the agent's word is the state" | The machine prints `{"to": stock}`, restricted to its flow's outputs |
| Slots | Machine capacity |
| Rejection | A rework flow with a fitted fraction |
| Merge gate | A program machine on a landing flow, taking a batch |
| `wake_on`, the event map | A machine wakes when its source stock has takeable items. The event map becomes the model's drawing. |
| Teams and responsibilities | A team owns a group of stocks; responsibilities are their targets |
| Register, ledger, outbox, budget (desk proposal) | Targets on stocks; the flow log on output stocks; the person machine's approval flow; a stock drained by co-flows |

Code delivery (tickets, worktrees, worker and reviewer, the bisecting gate, staging) becomes a
**template** of data and programs. So do GitHub stacks and SAIL from `corporate-workflow.md`.

## 10. Invariants, restated

Proposed, to be argued over before any code:

1. **Only the runtime moves items.** Machines report where an item goes, chosen from their
   flow's outputs.
2. **No zombies.** An item is in a stock or held by a live firing. A firing that ends without a
   put returns its items in the same code path.
3. **Measured, not reported.** A stock on the fitting rungs is read by a sensor. An agent's word
   counts only when a separate agent verifies it.
4. **Every coupling is declared.** No artifact changes the target system without a declared
   element and an expected effect.
5. **Every change is an era with a hypothesis,** in every model it touches.
6. **Every firing has a cost.** A machine whose budget stock is empty doesn't fire.
7. **Speaking as me is a person-machine flow.**
8. **Templates own their rules** (worktrees, the gate) and test them.
9. Data classes, model clearances, and the harness rules are unchanged.

## 11. Strategy that follows from the constraints

What draft 1 listed as objections are design rules:

| Constraint | Strategy |
|---|---|
| Tickets and outages are sparse | Fit on dense rungs (activity, progress, effect). Report on sparse ones. Link them with fitted conversions (section 3.2). |
| Outages are too rare to verify against | Verify link by link. Credit prevention by simulation on a validated target model. |
| Attribution is hard when much changes at once | Decouple: one declared element per work item, staggered landings, flags as on/off eras. |
| Tasks vary in size and aren't conserved | Make the acceptance criterion with a test the unit of work. Tickets are groupings for the company boundary. |
| Self-reports are unreliable | Sense stocks with programs; verify agents with separate agents. |
| Any single count can be gamed | Pair every goal stock with its opposite. |
| Soft variables matter but can't be measured | Proxies, labelled as such. Never silently drop them. |
| Discovery is slow at scale | Small models per layer, linked by declared couplings. Warm-started nightly. |
| Building a platform instead of doing the job | Observe-only first. Each step answers a question I have now. |

## 12. Plan

A strangler-fig migration. The current loop keeps working until a template reproduces it.

1. **Model Orchestra's own work system, observe-only.**
   - Sensors on `events.jsonl`, test runs, git, and agent usage under `~/.orchestrator/`.
   - Stocks chosen by the ladder: test runs, acceptance tests passing, commits, ticket groups.
   - Fit, and run discovery.
   - **Question answered:** which rungs are dense enough, and what are the conversion rates?
2. **Re-centre the unit of work on acceptance criteria.** Workers already write tests. Make
   criteria and their verification first-class items, sensed from the test runner. Tickets
   become groupings.
3. **One target-system model, observe-only:** one service, from Prometheus, with the service
   owners' agreement (SD Lab's F7). Daily refit and diff.
4. **The first declared coupling:** a real change on that service, with the hypothesis written
   before the work. Verify every link.
5. **My job's work system,** backfilled from 90 days of GitHub and Jira, with OKRs as goal
   stocks and the ladder beneath them.
6. **The runtime drives new work:** desk subsystems run as machines on flows. Code delivery
   still runs on the old loop.
7. **Port code delivery to a template,** pass the e2e suite, and retire the old state machine.
8. **The planner loop,** with my approval at the apply step.

## 13. Open questions

1. **SD Lab and Orchestra:** one package (`orchestra.sd`, per AGENTS.md rule 10), or a library?
2. **Coupling across time scales:** a minute-scale target model and a day-scale work model.
   Couple through era boundaries and parameters only, or also through aggregated stocks (daily
   OOM kills as an input to the work model's demand)?
3. **Who writes the target model first:** discovery from raw data, or a designed skeleton that
   discovery corrects? The service owners' knowledge is cheap to ask for and expensive to
   rediscover.
4. **Verified acceptance tests:** what exactly the verifying agent checks (the test fails without
   the change, it asserts the criterion's words, it isn't trivially true), and whether that can
   become a program.
5. **OKR mapping:** which of this quarter's key results already have a path to a target-system
   stock, and which don't.
6. **Units on the output rung:** is "commits on master" a stock the model should optimise, or
   only report? It's what the company counts, but it's on the rung most easily gamed.

## Sources

- Abdel-Hamid, T. and Madnick, S. (1991). *Software Project Dynamics: An Integrated Approach.*
  Prentice Hall.
- Cooper, K. G. (1980). Naval ship production: a claim settled and a framework built.
  *Interfaces* 10(6).
- Ford, D. and Sterman, J. (1998). Dynamic modeling of product development processes. *System
  Dynamics Review* 14(1).
- Lyneis, J. and Ford, D. (2007). System dynamics applied to project management. *System
  Dynamics Review* 23(2–3).
- Meadows, D. (1999). Leverage points: places to intervene in a system.
- Repenning, N. and Sterman, J. (2001). Nobody ever gets credit for fixing problems that never
  happened. *California Management Review* 43(4).
- Reinertsen, D. (2009). *The Principles of Product Development Flow.* Celeritas.
- Sterman, J. (2000). *Business Dynamics.* McGraw-Hill.
- SD Lab: `MODEL.md`, `docs/SPEC.md`, `OPERATIONALIZATION.md`, `docs/LADDER.md` (kubernetes cases
  300–317).

These sources are cited from memory, not checked against the publications. Verify them before
the doc is shared.
