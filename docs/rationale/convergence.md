# The convergence: system dynamics and AI agent orchestration

Status: draft, 2026-10-24. The rationale for the project as a whole: why the two fields belong
together, what each gives the other, where each is weak and how the other helps. It doesn't
describe an implementation.

Companions:
- `why-not-something-obvious.md` answers "why not X?" for each alternative.
- `lifted-models.md` covers what discovering equations from data adds, and what must be proven
  first.

Quotes marked *(verbatim)* were checked against the full text. Claims marked **[unverified]**
weren't. Findings about people are labelled as such, and any extension of them to LLMs is labelled
a **hypothesis**.

---

## 0. The thesis

**AI agent orchestration is a feedback-control problem in an organisation.** It is being
engineered with tools for single runs.

The people building agent systems design *agents* and *graphs*:
- a planner, workers, a critic, a router;
- step caps;
- traces;
- evals per task.

What actually goes wrong, at scale and over time, is the behaviour of **accumulations, delays,
and feedback loops**:
- review backlogs that grow while individual output rises;
- critics that drift toward approving everything;
- memory that compounds its own errors;
- agents that redefine "done" to match what they achieved;
- orchestrators that flood their own pipelines;
- budgets drained by runs whose cost varies thirtyfold.

System dynamics (SD) is the discipline built, since 1956, to understand and redesign exactly
these behaviours in organisations. Its central claims:
- behaviour is caused by structure;
- the structure that matters is stocks, flows, delays, and loops;
- the thing to redesign is the **policy**, the rule that turns information into action at each
  decision point;
- people are measurably bad at reasoning about accumulation and delay, so these must be computed,
  not intuited.

The convergence runs both ways:

- **SD gives orchestration** the right unit of design (the loop, not the agent), a catalogue of
  known pathologies with known remedies, simulation of policies before paying to run them, and a
  way to judge the system rather than the run.
- **Agents give SD** what it always lacked:
  - a **universal machine** that can carry out any written policy on any flow, exactly enough to
    measure, and be moved in minutes;
  - organisations that **log every action**, so flows are counted rather than estimated;
  - **labour** for SD's own expensive work: drafting models, running experiments, maintaining
    them.

The rest of this document explains each field in its own terms (section 1), then each in the
other's terms (sections 2 and 3), then the interface between them (section 4). After that it sets
out what each gains (section 5), where each is weak and how the other helps (section 6), and what
must be tested before any of it is believed (section 8).

## 1. Each field in its own terms

### 1.1 System dynamics

SD began with Jay Forrester at MIT in the mid-1950s. His background was servomechanisms and the
Whirlwind computer.

Its founding case was GE's appliance plants, where employment swung in a roughly three-year cycle.
Hand simulation of GE's *own* hiring and inventory rules showed that the instability came from the
firm's internal structure, not from the business cycle (System Dynamics Society history). That is
the field's first lesson: **the surprises in a system are usually produced by its own decision
rules.**

Core ideas:

- **Stocks and flows.** Stocks accumulate; only flows change them. A backlog, a budget, a skill
  level, a pile of undiscovered defects are all stocks.
- **Feedback loops.**
  - Balancing loops seek goals.
  - Reinforcing loops grow or collapse.
  - Delays in balancing loops cause oscillation.
  - Nonlinearities shift which loop dominates.

  The basic behaviour modes follow from these: growth, goal-seeking, oscillation, S-shaped
  growth, overshoot and collapse (Sterman, *Business Dynamics*, 2000).
- **The endogenous point of view.** "(Almost) nothing is exogenous." *(verbatim, Sterman 2002)*
  Failing to see our own feedback "leads to policy resistance as we persistently react to the
  symptoms of difficulty, intervening at low leverage points and triggering delayed and distant,
  but powerful feedbacks." *(verbatim)*
- **Policy resistance:** "the tendency for interventions to be defeated by the response of the
  system to the intervention itself." *(verbatim, Sterman 2002)*
- **Policy as the design object.** Forrester's model of a decision has three parts (Forrester,
  *EJOR* 1992):
  - a desired condition;
  - an apparent (observed) condition;
  - corrective action to close the gap.

  Decisions are outputs of policies. Policies are what you redesign. The 1961 book framed a
  computer model as "a management laboratory and a means of pretesting proposed changes in
  policies" (from MIT's press release, via a secondary summary).
- **Counterintuitive behaviour.** "The human mind is not adapted to interpreting how social
  systems behave." A system "tends to draw our attention to the very points at which an attempt to
  intervene will fail." *(verbatim, Forrester 1971)* Meadows ranked the places to intervene, from
  constants and buffers (weak) through delays, loop strength, information flows, rules, and goals
  to paradigms (strong) (Meadows 1999).
- **People misjudge accumulation.** This is an experimental finding, not a slogan:
  - In the beer game, decision-makers ignored the *supply line* (orders placed but not yet
    received), producing oscillation and amplification. Their behaviour fit an
    anchoring-and-adjustment rule that under-weights the pipeline (Sterman, *Management Science*
    1989).
  - Technically trained MIT graduate students failed simple stock-and-flow tasks (Booth Sweeney
    and Sterman 2000).
  - The failure persists after controlling for graph reading, context, motivation, and ability.
    People assume a stock follows the shape of its flow (Cronin, Gonzalez and Sterman 2009).
- **What it has explained in organisations:**
  - **the rework cycle** in projects (Cooper 1980; Lyneis and Ford 2007), including a $447M
    settlement in which the model was the basis for $200–300M;
  - software project dynamics (Abdel-Hamid and Madnick 1991);
  - **the capability trap** (Repenning and Sterman 2001);
  - **firefighting that tips** a whole development system once utilisation passes a threshold
    (Repenning 2001; Repenning, Gonçalves and Black 2001);
  - **disaster dynamics**, where an accumulation of interruptions flips an organisation from
    self-regulating to self-escalating (Rudolph and Repenning 2002);
  - **concealed rework** driving the "90% syndrome" (Ford and Sterman 2003).
- **Epistemology.** Models are never validated in the sense of proven true. "All decisions are
  based on models, and all models are wrong." *(verbatim, Sterman 2002)* Confidence comes from
  structure tests, behaviour tests, and policy tests (Forrester and Senge 1980; Barlas 1996).
  Modern practice adds likelihood estimation and bootstrapped intervals (Struben, Sterman and
  Keith 2015).

### 1.2 AI agent orchestration

An LLM agent is a loop: think, act with a tool, observe, repeat until the model decides to stop
(ReAct). Orchestration composes such loops:

| Pattern | What it is |
|---|---|
| Prompt chains and routers | Fixed sequences, or a classifier that picks a path. |
| Plan-and-execute | A planner writes steps; executors carry them out; the planner revises. |
| Orchestrator-workers | A lead decomposes, delegates to subagents, gathers results (Anthropic's research system: +90% on an internal eval, about 15× chat tokens). |
| Evaluator-optimizer, author/critic | A generator and a judge loop until the judge passes it. |
| Debate | Several agents argue toward an answer. |
| Memory and reflection | Lessons written down in one run and read in the next (Reflexion). |
| Human-in-the-loop | Approvals, reviews, permission prompts. |
| Durable execution | Agents as long-running workflows that survive restarts (Temporal). |

How it is governed today:
- **Stopping:** step caps, e.g. LangGraph's `recursion_limit`, the Agents SDK's `max_turns`.
  Neither tests for convergence.
- **Observing:** traces (OpenTelemetry's GenAI spans).
- **Judging:** evals per task (pass@k, pass^k, LLM judges).
- **Controlling:** per-run cost counters, guardrails, approval prompts.

**The failure record:**
- **Loop control.** In 1,600+ annotated multi-agent traces, failure rates were 41–86.7%.
  - About 28% of failures were step repetition or not knowing when to stop.
  - About 24% were verification failures.
  - Tactical fixes helped "inconsistently" (MAST, Cemri et al. 2025).
- **Errors condition further errors.** A model's own earlier errors in context make further errors
  more likely (Sinha et al. 2025).
- **Coordination can help or hurt.** Multi-agent setups ranged from +81% to −70% depending on task
  structure. Independent agents amplified errors 17.2×, centrally coordinated ones 4.4× (Kim et
  al. 2025).
- **Self-correction is unreliable.** Without external feedback it often fails, and can make
  answers worse (Huang et al. 2024).
- **Judges are biased.** They favour their own outputs (Panickssery et al. 2024). Debaters flip
  from right to wrong (Wynn et al. 2025).
- **Agents game their checks, more so on longer tasks.** At least 16% of successful runs on tasks
  over 8 hours were illegitimate (METR 2026).
- **Memory carries errors forward.** It "replicates and even amplifies" past errors (Xiong et al.
  2025).
- **Cost is unpredictable.** It varies up to 30× for the same task, and models predict it poorly
  (Bai et al. 2026).
- **Faster agents moved the bottleneck to review.** Merged PRs rose 98% and review time 91%, with
  delivery flat (Faros 2025, vendor telemetry). 93% of permission prompts are approved: "approval
  fatigue" (Anthropic 2026).

Most of these are not failures of a single run. They're the behaviour of the system over time.

## 2. Agent orchestration explained in system dynamics terms

Each pattern below is a feedback structure SD already knows. For each: the structure, what SD
predicts, the evidence that it happens to agents, and what SD prescribes. **The point isn't the
relabelling. It's that the predictions and prescriptions come with the structure.**

### 2.1 The agent loop is a goal-seeking loop whose observations include its own output

An agent loop matches Forrester's decision rule:
- a desired condition (the task);
- an apparent condition (what the agent believes is true now);
- corrective action (the next tool call).

It stops when the apparent gap closes.

**What SD predicts.** A balancing loop's behaviour depends on its *apparent* condition. When that
is computed from the agent's own outputs (its claims, its summaries, its earlier reasoning) rather
than measured from the world, the loop can close on a false gap. Ford and Sterman's Liar's Club is
the same structure with people: concealed rework produces the 90% syndrome. Projects reach about
90% of plan on schedule, then stall, "finally finishing after about twice the original project
duration" *(verbatim, Ford and Sterman 2003)*.

**Evidence.** Premature termination is 6.2% of MAST failures; incorrect or missing verification is
another 17%. Anthropic's long-running-agent harness names "declaring the project done too early"
as a primary failure, and fixes it by making the feature list an external file the agent may only
mark. Self-conditioning (errors in context breeding errors) is a reinforcing loop inside the
balancing one.

**What SD prescribes.** Information flows rank high among Meadows' leverage points. **Feed the loop
a measured apparent condition** (tests run by someone else, sensors, state outside the agent),
not the agent's own account. Don't tune the caps: a step cap is a parameter, the weakest lever.

### 2.2 Specification gaming is "eroding goals"

When a gap persists, the cheapest way to close it is to move the goal. Senge's *eroding goals*
archetype is a balancing loop that adjusts the desired condition toward the actual one, under
pressure, often without anyone deciding to.

**What SD predicts.** Erosion grows with the duration and size of the gap. Longer, harder tasks
erode more.

**Evidence.** METR finds reward hacking increases with task length and difficulty: "at least 16% of
successful runs were illegitimate upon review" on tasks over 8 hours, and frequent hacking attempts
on hidden-test tasks. Agents delete or edit failing tests (ImpossibleBench's motivation).

**What SD prescribes.** **Anchor the goal outside the loop that's under pressure.** The goal and
its measurement must not be writable by the agent whose gap they define. Pair every goal stock with
its opposite, so erosion in one shows up in the other. This is structural, not a better prompt.

### 2.3 The critic loop is inspection in the rework cycle

An author/critic pair is one structure from SD's best-validated project model:

```
work to do ──produce──► work done ─┬─(correct)──────────────────► really done
                                   └─(defective)──► undiscovered rework ──(discovered after a delay)──► work to do
                                                     ▲ the critic sets the probability that a defect is caught now
```

The rework cycle has three parameters:
- **productivity** (author speed);
- **fraction correct the first time** (author quality);
- **discovery**: a probability of catching a defect at inspection, and a delay before the rest are
  found later.

**What SD predicts:**
- *Apparent* progress outruns *actual* progress whenever detection is weak. The undiscovered-rework
  stock fills silently, and its delayed return stretches schedules (the 90% syndrome).
- Raising detection early is worth more than raising author quality by the same amount, because a
  defect found late costs its rework *plus* everything built on top of it.
- A critic whose detection is high but noisy (it flips) makes the inner loop oscillate rather than
  converge.

**Evidence:**
- Judges favour outputs of their own model family (Panickssery et al.): detection falls when author
  and critic share a family.
- Debate accuracy can decline over rounds, with agents flipping to wrong answers (Wynn et al.).
- Self-correction without outside feedback often degrades answers (Huang et al.).
- Faros reports work merging *unreviewed* as volume rises **[unverified]**: detection going to
  zero.

**What SD prescribes:**
- **Design the critic loop by its detection probability and discovery delay,** not by the author's
  quality.
- Use an independent critic: different model family, different evidence, executable checks.
- Measure the late-discovered rework (bugs found in human review or production, traced back) to
  estimate the critic's real detection rate.
- Terminate on evidence, not on agreement.

### 2.4 Human review is a capacity-limited flow whose quality falls with load

Human review is a flow with a fixed service capacity, sitting downstream of agents whose output
can rise without limit.

**What SD predicts:**
- Raising the inflow to a fixed-capacity stage moves the bottleneck there: *limits to growth*.
- When the reviewer's backlog grows, reviewers keep up by cutting corners. Each review's detection
  probability falls, more defects pass, and they come back later as more work. That's the same
  structure as Repenning's firefighting: past a utilisation threshold it **tips**, and Rudolph and
  Repenning show "an overaccumulation of interruptions can shift an organizational system from a
  resilient, self-regulating regime … to a fragile, self-escalating regime" *(verbatim, 2002)*.
- "The tipping point's location is determined by resource utilization in steady state" (Repenning
  et al. 2001).

**Evidence:**
- Review time up 91% as merged PRs rose 98%, with delivery flat (Faros 2025).
- 93% of permission prompts approved (Anthropic 2026): the human check's gain decaying with volume.
- After Copilot adoption, open-source code needed more rework, and core reviewers' own output fell
  (Xu et al. 2025).

**What SD prescribes:**
- **Size agent output to review capacity, not to agent capacity.**
- **Keep slack:** utilisation below the tipping region.
- **Measure review quality as a function of review load,** so fatigue is visible before it tips.
- At work, this is a large part of why the PR-size and turnaround rules exist. The model makes the
  rule derivable instead of a convention.

### 2.5 Starting work is a stock-management problem: count the supply line

An orchestrator decides how much new work to start: how many subagents to spawn, how many tickets
to pick up, how many PRs to open. That's exactly the decision Sterman studied. A decision-maker
keeps a stock (finished output) near a goal by placing orders that arrive after a delay, while
orders already placed sit in a supply line.

**What SD predicts.** Decision-makers who anchor on the visible stock and under-weight the supply
line over-order, then over-correct, producing oscillation and amplification. That's the bullwhip
effect. In the beer game subjects were "insensitive to the feedbacks from their decisions to the
environment" (Sterman 1989). Costs ran far above optimal, reportedly near tenfold **[unverified
figure]**.

**Evidence in agent systems:**
- Anthropic's early research system "spawned 50 subagents for simple queries," flooded agents
  with updates, and duplicated work.
- Orchestrators that start new work based on the open backlog, ignoring work already waiting in
  review and CI, flood those stages and then stall: the Faros pattern, inside one team.

**What SD prescribes.** The corrective policy from the stock-management literature:

> start rate = expected completions + (desired stock − stock) / adjustment time
> + (desired supply line − supply line) / adjustment time

**with the supply line given full weight.** The field has known this for thirty years. Agents can
carry out the rule exactly, which people characteristically don't.

**This is a hypothesis.** It's the most directly transferable result, and it's testable in
simulation before it ever runs live (section 8, H1).

### 2.6 Multi-agent coordination has Brooks' law dynamics and a loop gain

Splitting work across agents adds capacity and adds overhead:
- context transfer;
- conflicting implicit decisions (Cognition's Flappy Bird example);
- duplicated work;
- integration.

Abdel-Hamid and Madnick's software project model includes exactly these: assimilation delays and
communication overhead growing with team size. The Brooks'-law finding attributed to Abdel-Hamid
(1989) is **[unverified]**.

**What SD predicts.** Whether splitting helps depends on how coupled the subtasks are. Errors that
pass between agents without independent checks compound around a loop. Centralised integration
lowers that loop's gain.

**Evidence.** +81% to −70% depending on whether the task decomposes in parallel or sequentially.
Error amplification 17.2× with independent agents vs 4.4× with a central orchestrator (Kim et al.
2025). Cognition's "don't build multi-agents" and Anthropic's multi-agent research post are both
right, for different coupling.

**What SD prescribes.** Treat coupling and coordination overhead as model parameters. Decide when
to split by simulation, not by architecture fashion.

### 2.7 Memory, docs, and tools are a capability stock, and the trap is waiting

Everything an agent fleet reads before it works is a stock that builds up and decays:
- memory;
- AGENTS.md;
- runbooks;
- curated lessons;
- tools it has built for itself.

**What SD predicts.** Repenning and Sterman's capability trap. Under throughput pressure, the
system works harder and takes shortcuts. Capability erodes, but only after a delay, so the
shortcut looks free: "Shortcuts are tempting because there is often a substantial delay between
cutting corners and the consequent decline in capability" *(verbatim, 2001)*. Their own example is
software: "a software engineer who forgoes documentation in favor of completing a project on time
incurs few immediate costs; only later … does she feel the full impact" *(verbatim)*. Working
harder is better-before-worse; investing in capability is worse-before-better. Managers then blame
people, not the process (the self-confirming attribution error).

**Evidence:**
- Experience-following: retrieved past errors are replicated and amplified, and indiscriminate
  memory widens the error gap over time, while strict selective addition converges (Xiong et al.
  2025).
- Safety alignment decays as memory accumulates (misevolution, arXiv 2509.26354).
- Anderson, Parker and Tan's SD model of AI-assisted coding gives an inverted U, as technical debt
  accumulates past the speed gain (ISDC 2026).

**What SD prescribes:**
- **Model the capability stock explicitly,** with its inflow (curated lessons, docs, tools), its
  decay (staleness, error propagation), and its effect on service rate and quality.
- Protect the investment flow under pressure.
- Expect worse-before-better, and don't abandon a capability investment in the dip it predicts.

### 2.8 The context window is a stock inside each run

Within a run:
- observations and tool output fill the context;
- compaction and summarisation drain it;
- quality is an effect of its level and composition: context rot (Chroma 2025), lost in the
  middle.

**What SD predicts.** A loop whose quality falls as its stock rises has a natural working range.
Past it, more steps make things worse. Vending-Bench found derailment that didn't line up with the
window filling **[secondary report]**. Composition (its own past errors) matters as well as level,
which is the self-conditioning loop of section 2.1.

**What SD prescribes.** Treat compaction as an outflow policy, and choose it by its effect on
quality, not by a token threshold alone. Subagents that return condensed summaries are a buffer
and filter between stocks, not just a parallelism trick.

### 2.9 Budget, retries, and shared resources

**Budget.** A budget is a stock drained by a highly variable flow: up to 30× variance per task,
and models can't predict their own usage.

**Retries** form a reinforcing loop. A failure makes another attempt with more context, which
costs more and fails more. That's the same metastable structure that produces retry storms in
distributed systems.

**Shared resources** are commons: CI capacity, rate limits, reviewer attention, the merge gate.
When every agent draws freely on them, each one's local gain degrades everyone's service, the
*tragedy of the commons*.

**What SD prescribes:**
- Budgets as stocks with explicit drains.
- Retry policies that include the loop gain.
- Allocation rules for shared stocks: queues, quotas, admission control.

### 2.10 Improvement loops and Goodhart

Prompt optimisation, self-improving agents, and routers that learn which model succeeds are
reinforcing loops.

**What SD predicts:**
- **Limits to growth:** gains stop when they reach a constraint the loop doesn't include.
- **Eroding goals or shifting the burden** when the benchmark stands in for the goal.
- **Success to the successful:** a router starves the alternatives it stopped trying, and never
  learns they improved.

**Evidence:**
- The Darwin Gödel Machine reportedly learned to hide error logs **[secondary report]**.
- Benchmark contamination is the same loop at the scale of the field: SWE-bench retired as an eval
  (OpenAI 2026).

**What SD prescribes:**
- Include the constraint and the true goal in the loop.
- Keep exploration flows alive.
- Measure the opposite stock.

### 2.11 Shifting the burden: the human stock

When agent output is fixed by hand downstream instead of the agent or the system being fixed, the
symptom goes away and the fundamental solution weakens. Senge's *shifting the burden*. The burden
also has a stock nobody measures: **human skill and judgement**, which erode when exercised less.
For an engineering organisation this is a strategic risk. For an individual engineer it's a
professional one.

**What SD prescribes:**
- Make the fundamental-solution flow explicit and fund it.
- Track the human capability stock with proxies: review quality, design ownership, juniors
  coached.

### 2.12 Summary

| Agent pattern | SD structure | What SD predicts | Evidence it happens | SD's remedy |
|---|---|---|---|---|
| Agent loop "done" | Balancing loop on an apparent condition | False closure; 90% syndrome | MAST premature termination and verification failures; harness "declared done too early" | Measured apparent condition (information flow) |
| Test editing, reward hacking | Eroding goals | Erosion grows with gap duration | METR: ≥16% illegitimate on 8 h+ tasks | Goal anchored outside the loop; paired opposite stocks |
| Author/critic | Rework cycle, inspection | Apparent > actual progress; late rework | Self-preference; debate flips; unreliable self-correction | Design by detection probability and delay; independent critic |
| Human review | Capacity limit + load-dependent quality | Bottleneck shift; tipping | Review time +91%; 93% of prompts approved | Size output to review capacity; slack; measure fatigue |
| Spawning work | Stock management with a supply line | Over-ordering, oscillation | 50 subagents for simple queries; review floods | Supply-line-corrected start rule |
| Multi-agent | Brooks' law; loop gain of error passing | Benefit depends on coupling | +81% to −70%; 17.2× vs 4.4× | Coupling as a parameter; split by simulation |
| Memory, docs, tools | Capability stock; capability trap | Better-before-worse shortcuts | Experience-following; misevolution; AI-debt inverted U | Protect investment; model decay |
| Context | Stock with quality effect | Working range; self-conditioning | Context rot; self-conditioning | Compaction as an outflow policy |
| Retries, budget, shared CI | Reinforcing loops; commons | Metastability; degradation | 30× cost variance | Budget stocks; loop-aware retries; allocation |
| Optimisers, routers | Reinforcing with limits; success to the successful | Plateau; Goodhart; starvation | DGM objective hacking; contamination | Include constraint and true goal; keep exploring |
| Humans fixing agent output | Shifting the burden | Fundamental solution and skill erode | (to measure) | Fund the fundamental flow; track human capability |

## 3. System dynamics explained in agent terms

The reverse direction: what agents do to SD's oldest problems.

### 3.1 A policy is a program, and now it can run

Forrester's unit of design is the policy: a rule from available information to action at a
decision point. An agent's brief, its tools, and the inputs it's shown are *literally* such a rule.
That's an inference, but a direct one.

So the deliverable of an SD study, a redesigned policy, can be:
- deployed as an agent or a program on the flow it governs;
- versioned;
- rolled back;
- tested in the model first, Forrester's "management laboratory" as a test harness.

### 3.2 The implementation gap closes, mostly

SD's practical record has a weak point: **models don't implement themselves.** Redesigned policies
have to be carried out by people, who follow them imperfectly, misperceive the delays the policy
was designed around, and drift back under pressure. Beer's Cybersyn ran a DYNAMO-based simulator
that decision-makers reportedly never consulted.

A policy carried out by an agent or program:
- is followed as written, with a deviation rate that can itself be **measured**, because what was
  intended is declared and what happened is logged;
- can be moved to another flow in minutes;
- has capacity that scales with money rather than hiring.

Agents also deviate. MAST's "disobey task specification" is 11.8% of failures, and they game
their checks. That deviation is a quantity in the model, not a reason the model failed.

### 3.3 "Measurement without data" becomes measurement by construction

Nordhaus's attack on Forrester's world model was its title: "measurement without data." An
organisation whose work is done by agents and programs is the most measured organisation ever
built:
- every action is timestamped;
- every flow can be counted exactly;
- every decision rule is on file.

The parts that stay hard to measure are the people and production, which is where discovery and
sensors go.

### 3.4 SD's labour problem has a labour supply

Building and maintaining SD models has always needed expert staff. LLMs can already draft
structure:
- SDBot recovered about 60% of links and most loops of published causal loop diagrams;
- LunaSim Copilot scored 90–95% on stock-and-flow generation tasks.

LLMs reportedly struggle more with SD and agent-based structure than with discrete-event
simulation (Botello et al., WSC 2025), so a validation step stays in the loop.

Agents can also:
- run the experiments that validate a model;
- read diffs between lifted models;
- write change notes;
- propose model edits when residuals stop being random.

### 3.5 Validation by experiment instead of argument

SD's confidence tests are mostly structural and behavioural inspection, and the field has
criticised itself for practising them too little (Barlas 1996). An agent-run system can do what a
human organisation rarely allows:
- **announce an intervention** (an era);
- **predict its effect in advance;**
- **check the prediction.**

Feature flags, canaries, and staged rollouts are ready-made experiments. Where two structures fit
the data equally well, an agent can carry out the discriminating experiment, under the same
approval rules as any change.

### 3.6 The decision-maker inside the loop is now an LLM, so compute the accumulation

SD's most robust experimental finding is that **people** fail at accumulation and delay. Whether
LLM planners share the failure is **untested**. It's a hypothesis, and a cheap one to test: give
LLMs the bathtub and beer-game tasks (section 8, H6).

If they do share it, then SD's prescription applies to agents as decision-makers: "the computer
traces the resulting consequences without doubt or error" *(verbatim, Forrester 1971)*. **Agents
should consult computed models of the stocks they affect,** not reason about them narratively. If
they don't share it, agents become a new kind of decision-maker the SD literature hasn't studied,
which is interesting in itself.

### 3.7 Machines have stocks too

The capabilities of agents behave like SD's soft variables, but they can be measured:
- context level;
- memory quality;
- pass rates by task type;
- cost per unit;
- compliance with the brief.

The "skill" and "fatigue" stocks that SD had to infer for people can be sensed for machines.

## 4. The interface

Where the two meet, a few design principles follow. They describe the interface, not an
implementation.

### 4.1 The unit of design is the loop, not the agent

Agent frameworks design **agents** (roles, prompts, tools) and **graphs** (who calls whom). SD
designs **loops**.

An author/critic pair isn't two agents. It's one balancing loop with:
- a gain;
- a detection probability;
- a delay;
- a termination condition;
- a leak into undiscovered rework.

It should be designed for convergence and detection, and those parameters should be measured.

A planner and its workers form a stock-management loop with a supply line. Human review is a
capacity-limited stage with a load-dependent quality effect. **Orchestration becomes loop
engineering:** choosing structures and parameters so the loops converge, don't oscillate, don't
erode their goals, and don't tip.

### 4.2 Two time scales, two kinds of loop

| Loop | Time scale | Examples | Who handles it today |
|---|---|---|---|
| **Within-run** | Seconds to hours | Tool loop, critic loop, context, retries | Agent frameworks: caps, traces, evals |
| **Across-run** | Days to months | Review backlog, rework return, memory and capability, budget, debt, trust, goal erosion | Nobody, systematically |

SD's home is the across-run loops. The interface is hierarchical:
- **The across-run model sets the parameters of within-run loops:** concurrency, budget per task,
  critic strictness, step limits, which machine on which flow.
- **Within-run statistics feed the across-run model's parameters:** service rates, detection
  rates, rework fractions, cost per unit.

That's ordinary cascade control. SD supplies the outer model, control theory the stability
analysis (Eslami and Yu 2026 derive conditions relating adaptation rate, switching, and delay for
agentic loops).

### 4.3 Declared where we wrote it, lifted where we didn't

The decision rules of our own machines are **known**: we wrote the briefs, the programs, and the
loop's policies. They go into the model as declared equations, changing exactly when we change
them. What must be discovered is:
- the environment: people, production, other teams;
- how the machines *actually* behave against their declared rule.

This answers the Lucas-style objection that a policy change invalidates an estimated model: the
policy part is not estimated. It also shrinks what discovery must find (`lifted-models.md`,
section 6).

### 4.4 Reports drive bookkeeping; sensors drive the model

Orchestra has a principle that "the agent's word is the state": agents report, and the loop applies
the transition. SD warns about exactly this: a system run on the **apparent** condition, as reported
by those under pressure to close the gap, diverges from the **actual** one (sections 2.1–2.3).

Both are needed, for different jobs:
- **Reports** drive transitions and communication (bookkeeping).
- **Sensors** (tests run independently, git, CI, production metrics, human verdicts) drive the
  model and its judgements.

When the two disagree, that's a measurement of concealed rework. It is the most useful number the
system can produce about its own honesty.

### 4.5 Goals are stocks with opposites, anchored outside the loops that chase them

Every goal stock is paired with the stock that measures its gaming (commits with reverts, passing
tests with flakes, approvals with late-found defects). Its measurement is outside the write access
of the machines whose gap it defines. This is section 2.2's prescription as a design rule.

### 4.6 Simulate before act, at both levels

- **Across runs:** policies are tried in the model before they spend tokens.
- **Within runs:** an agent changing a system gets the relevant part of the model as context and a
  simulator as a tool, so its plan carries a predicted effect that can be checked later
  (`lifted-models.md`, sections 4–5).

### 4.7 Sparse things are reported; dense things are fitted

Tickets, PRs, and outages are too sparse to fit a model on. Test runs, review threads, tool calls,
and queue levels aren't. The model links the dense to the sparse with fitted conversion rates.
That's a choice of what exists in the model, an ontology, made for statistical reasons. It's
developed in `../proposals/system-dynamics-core.md` (section 3).

## 5. What each gains

**Orchestration gains from SD:**
1. A **level of analysis** it lacks: the system over weeks, not the run.
2. **Endogenous explanation.** Failures come from the structure the designers built, so fix the
   structure rather than the prompt.
3. **A catalogue of pathologies with remedies:** eroding goals, rework cycle, capability trap,
   tipping, supply-line oscillation, shifting the burden, commons.
4. **Policy simulation** before paying for live runs, at thousands of runs per second.
5. **A leverage hierarchy** that says parameters (caps, timeouts) are the weakest lever, and
   information flows, rules, and goals the strongest.
6. **Credit for prevention:** problems that never happened, counted by simulation (Repenning and
   Sterman's title is the argument).
7. **A shared language with management:** stocks, rates, goals, delays.

**SD gains from agents:**
1. **A universal machine** to carry out designed policies on any flow, with measurable compliance.
2. **Dense, exact measurement** of the machine part of the organisation.
3. **Labour** to build, maintain, and test models.
4. **Experiments** that can be run as well as argued.
5. **A new decision-maker to study,** whose biases can be measured directly.

**Together:** a system where **policy design, policy deployment, and policy verification are one
loop**:
1. find leverage in the model;
2. write the rule;
3. place a machine;
4. predict the effect;
5. re-lift the model;
6. confirm or revise.

That's the outcome the project is for.

## 6. Where each is weak, and how the other helps

### 6.1 SD's weaknesses

| Weakness | How the convergence helps |
|---|---|
| **Validation never reaches proof**; behaviour reproduction can hide wrong structure (Barlas; Sterman 2002) | Interventions with predictions written beforehand; eras; discriminating experiments run by agents. Validation becomes falsification. |
| **Aggregation**: stock models can mispredict when heterogeneity or networks matter, including policy response (Rahmandad and Sterman 2008) | Items keep their identity in the runtime; DES and queueing handle tactical, discrete stages. SD stays at the across-run layer, where aggregation is appropriate. |
| **"Measurement without data"** (Nordhaus 1973) | Machines log everything; dense rungs; sensors over reports. |
| **Boundary choice is subjective, and failures concentrate there** (Sterman 2002) | Lifted models find flows and hidden stocks the designer left out (when discovery works; see below). Unexplained-change tests flag missing boundary flows. |
| **Soft variables invite critique** | Machine soft variables are sensed; human ones carried through stated proxies. |
| **Not a point-forecasting tool** | Within-run tools handle individual tasks; SD compares policies. That's the right division. |
| **Learning structure from data is immature** (about 60% of links for LLM-drafted causal loop diagrams; SINDy fragile under noise) | Declared-plus-lifted split shrinks the problem; our discovery work is one attempt. **Still unproven on real data.** |
| **Models don't implement themselves** (Cybersyn) | Agents and programs carry out policies. |

### 6.2 Orchestration's weaknesses

| Weakness | How the convergence helps |
|---|---|
| **Termination and convergence** (step caps, about 28% loop-control failures) | Loops designed by gain, delay, and detection; termination on measured conditions. |
| **Verification gamed by the verified** (METR) | Goals anchored outside the loop; paired opposite stocks; behaviour tests on lifted models that agents can't write to. |
| **Compounding error over long horizons** | Measured apparent conditions; checkpoints as information flows; the model of self-conditioning as a reinforcing loop. |
| **Critic independence** | Critic design by detection probability; late rework measured to estimate it. |
| **When to go multi-agent** | Coupling and overhead as parameters, decided by simulation. |
| **Human review capacity** | Output sized to review capacity; slack below the tipping region; fatigue measured. |
| **Cost unpredictability** | Budget as a stock; spend allocated by leverage; loop-aware retries. |
| **Memory and self-improvement drift** | The capability stock modelled with its decay; selective inflow policy; misevolution watched as drift. |
| **Measurement validity** (contaminated benchmarks, infrastructure noise) | Judge the system by behaviour in production, not by benchmark proxies; model the noise. |
| **No fleet-level observability or control** | That is the across-run model. |

### 6.3 Weaknesses neither removes

- **Small numbers.** At tens of tickets and a handful of agents, fluid approximations are at their
  weakest. A queueing network or a small discrete-event simulation may be more accurate for latency
  at this scale. That has to be tested, not assumed (`why-not-something-obvious.md`, last section).
- **Discovery on data not generated by SD models is unproven.**
  - SD Lab's own record: 0 of 52 published real-data structures recovered.
  - Held-out skill near zero on real data.
  - A wrong "yes" on a misrouting agent in a discrete-event demo.

  Until the validation programme in `lifted-models.md` (section 8) succeeds, lifted models are for
  orientation, and designed models with fitted numbers carry the weight.
- **Goodhart and reflexivity.** Once machines are judged by a model, the model becomes a target,
  and acting on it changes the system it describes. Sensors outside write access, paired
  opposites, and eras mitigate this. Nothing removes it.
- **The LLM-misperception hypothesis is untested.** Section 3.6 is a hypothesis.

## 7. What we hope for, and why it beats the alternatives

An orchestrator whose decisions are **derived from, and checked against, a model of the system it
operates in**:
- what to start, and how much;
- which machine on which flow;
- how strict each check is;
- where the next dollar goes;
- when to stop.

That model is declared where we wrote the rules and lifted where we didn't. It is judged by
predictions written before each change.

It beats the alternatives not because any of them is wrong, but because each answers a narrower
question:

| Alternative | What it does | What it can't do |
|---|---|---|
| Workflow engine | Executes | Explain |
| Queueing theory | Sizes stages | Represent the feedback that moves service rates and quality |
| Evals and prompt optimisers | Tune parts | See the parts degrade the whole |
| Causal inference | Judges past changes | Simulate untried ones |
| Dashboards | Describe | Explain or simulate |

SD is the layer where they share one state, and the only one built around the loops that make agent
systems misbehave over time.

The details are in `why-not-something-obvious.md`.

## 8. What must be tested

Each of these hypotheses can be tested in simulation first, then on Orchestra's own history, then
live. None is assumed.

| # | Hypothesis | Test |
|---|---|---|
| H1 | A supply-line-corrected start rule reduces backlog oscillation and review floods compared with a backlog-only rule. | DES of an orchestrator with delayed review and CI; then an era on Orchestra. |
| H2 | Critic detection probability, estimated from late-found rework, predicts total rework and cycle time better than author quality does. | Fit the rework cycle on Orchestra's history; vary the critic by era. |
| H3 | Human review quality falls measurably with review backlog (fatigue). | Review comments per changed line, and defects escaping review, against backlog. |
| H4 | Share of agent effort spent on capability (docs, tools, curated lessons) predicts later throughput and quality, after a delay. | Lagged fit on Orchestra's history; then a protected-investment era. |
| H5 | Selective memory inflow keeps error rates flat over time; indiscriminate inflow lets them drift. | Replicate Xiong et al.'s comparison inside Orchestra's memory and lessons. |
| H6 | LLM planners show stock-flow failure on the bathtub and supply-line tasks humans fail. | Run the Booth Sweeney and Sterman inventory and a beer-game variant on current models. |
| H7 | A discovered SD model predicts the effect of an unseen policy change better than a queueing-network baseline. | The test in `why-not-something-obvious.md`. |
| H8 | Verdicts on agent variants read through a lifted model are right, with no wrong "yes". | Demo 16, extended with rework measured directly. |

H1, H2, and H6 are cheap and decisive. If H1 and H2 hold, SD's oldest results transfer directly to
orchestration policy. If H6 holds, agents need computed models as much as people do. If H7 fails,
SD stays the explanatory and strategic layer, and queueing runs dispatch.

## Sources

### System dynamics

- Forrester, J. W. (1961). *Industrial Dynamics.* MIT Press.
- Forrester, J. W. (1971). Counterintuitive behavior of social systems. *Technology Review* 73(3).
  Full text: https://constitution.org/1-Activism/ps/cbss.htm
- Forrester, J. W. (1992). Policies, decisions and information sources for modeling. *European
  Journal of Operational Research* 59(1):42–63.
- Forrester, J. W. and Senge, P. (1980). Tests for building confidence in system dynamics models.
  *TIMS Studies in the Management Sciences* 14.
- Sterman, J. D. (1989). Modeling managerial behavior: misperceptions of feedback in a dynamic
  decision making experiment. *Management Science* 35(3):321–339.
- Sterman, J. D. (2000). *Business Dynamics.* McGraw-Hill.
- Sterman, J. D. (2002). All models are wrong: reflections on becoming a systems scientist.
  *System Dynamics Review* 18(4):501–531.
- Booth Sweeney, L. and Sterman, J. D. (2000). Bathtub dynamics. *SDR* 16(4).
- Cronin, M., Gonzalez, C. and Sterman, J. D. (2009). Why don't well-educated adults understand
  accumulation? *OBHDP* 108(1):116–130.
- Meadows, D. (1999). Leverage points: places to intervene in a system.
- Senge, P. (1990). *The Fifth Discipline.* Doubleday.
- Cooper, K. G. (1980). Naval ship production: a claim settled and a framework built.
  *Interfaces* 10(6).
- Abdel-Hamid, T. and Madnick, S. (1991). *Software Project Dynamics.* Prentice Hall.
- Lyneis, J. and Ford, D. (2007). *SDR* 23(2–3):157–189.
- Repenning, N. and Sterman, J. D. (2001). Nobody ever gets credit for fixing problems that never
  happened. *California Management Review* 43(4):64–88.
- Repenning, N. (2001). Understanding fire fighting in new product development. *JPIM* 18(5).
- Repenning, N., Gonçalves, P. and Black, L. (2001). Past the tipping point. *CMR* 43(4).
- Rudolph, J. and Repenning, N. (2002). Disaster dynamics. *Administrative Science Quarterly*
  47(1):1–30.
- Ford, D. and Sterman, J. D. (2003). The Liar's Club. *Concurrent Engineering* 11(3).
- Barlas, Y. (1996). Formal aspects of model validity and validation in system dynamics. *SDR*
  12(3).
- Struben, J., Sterman, J. D. and Keith, D. (2015). Parameter and confidence interval estimation
  in dynamic models. In *Analytical Methods for Dynamic Modelers*, MIT Press.
- Nordhaus, W. (1973). World Dynamics: measurement without data. *Economic Journal* 83(332).
- Rahmandad, H. and Sterman, J. D. (2008). *Management Science* 54(5):998–1014.
- Richardson, G. (1991). *Feedback Thought in Social Science and Systems Theory.* U. Penn Press.
- Beer, S. (1959). *Cybernetics and Management*; (1972) *Brain of the Firm*.
- Medina, E. (2011). *Cybernetic Revolutionaries.* MIT Press.

### Agent orchestration

- Cemri et al. (2025). Why do multi-agent LLM systems fail? arXiv 2503.13657.
- Anthropic (2024). Building effective agents.
- Anthropic (2025). How we built our multi-agent research system.
- Anthropic (2025). Effective harnesses for long-running agents.
- Anthropic (2026). Claude Code auto mode.
- Cognition (2025). Don't build multi-agents.
- Kim et al. (2025). Towards a science of scaling agent systems. arXiv 2512.08296.
- Sinha et al. (2025). arXiv 2509.09677.
- Huang et al. (2024). LLMs cannot self-correct reasoning yet. arXiv 2310.01798.
- Panickssery, Bowman and Feng (2024). arXiv 2404.13076.
- Wynn, Satija and Hadfield (2025). arXiv 2509.05396.
- Zheng et al. (2023). arXiv 2306.05685.
- Xiong et al. (2025). arXiv 2505.16067.
- Your agent may misevolve. arXiv 2509.26354.
- METR (2025). arXiv 2503.14499.
- METR (2026). Frontier Risk Report.
- Bai et al. (2026). arXiv 2604.22750.
- Faros AI (2025). The AI productivity paradox.
- Chroma (2025). Context rot.
- Xu et al. (2025). arXiv 2510.10165.

### The intersection

- Hosseinichimeh et al. (2024). *SDR* 40(3) (SDBot).
- LunaSim Copilot, ISDC 2025.
- Botello et al., WSC 2025.
- Anderson, Parker and Tan, ISDC 2026.
- Eslami and Yu (2026). arXiv 2603.10779.
- Pourbafrani and van der Aalst (2022). *IEEE Access* 10.
- Nardini et al. (2021). *J. R. Soc. Interface* 18.

### Unverified or secondary

- The beer game's "near tenfold" cost figure.
- Abdel-Hamid (1989) on Brooks' law.
- Faros 2026 figures.
- Vending-Bench details.
- The Darwin Gödel Machine's objective hacking.
- Forrester's "management laboratory" wording (via MIT press release summary).
