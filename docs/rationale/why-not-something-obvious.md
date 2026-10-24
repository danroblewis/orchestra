# Why system dynamics, and not something obvious?

Status: draft, 2026-10-24. The questions engineers will ask, answered directly.

Companions:
- `convergence.md`: the full argument.
- `lifted-models.md`: what discovered models add.

Citations marked **[unverified]** were not checked against the primary source during research.
Everything else was checked against the paper, the vendor's own post, or the official docs.

---

## The short answer

The problems that hurt agent systems in practice are **accumulations, delays, and feedback
loops** that play out over weeks:
- review backlogs;
- rework coming back;
- memory that compounds its own errors;
- approval fatigue;
- budgets drained by highly variable runs;
- critics that drift into rubber-stamping.

The tools in use today measure and control **single runs**: traces, pass rates, token counts per
run, step caps. Of the obvious alternatives, only system dynamics and control theory treat
accumulation, delay, and feedback as their primary objects and can simulate a *policy* change
before paying for it. SD is the one built for organisations and their decision rules. Control
theory is the partner that analyses stability once SD has supplied the model.

SD doesn't replace the obvious tools. It is the layer where they share one model:
- workflow engines execute;
- queueing theory sets flow rates;
- process mining finds the flows;
- causal inference checks predictions;
- bandits and prompt optimisers tune parts.

## The evidence that the problems are dynamic

| Observation | Source | What kind of problem |
|---|---|---|
| About 28% of multi-agent failures are loop control: step repetition (15.7%) and not knowing when to stop (12.4%). Another 24% are failures of the verification feedback path. | Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (MAST), arXiv 2503.13657, v3 | Feedback loop stability |
| Teams with high AI adoption merged 98% more PRs; PR review time rose 91%; delivery metrics at the company level stayed flat. | Faros AI, "The AI Productivity Paradox", Jul 2025 (vendor telemetry, correlational) | A capacity-limited stock (review) and the bottleneck moving |
| Users approve 93% of permission prompts: "approval fatigue". | Anthropic, "Claude Code auto mode", Mar 2026 | A balancing loop whose gain falls with volume |
| Retrieved past errors are "replicated and even amplified" by agents with memory. | Xiong et al., arXiv 2505.16067 | A reinforcing loop across runs, through an accumulating stock |
| A model's own earlier errors in context make further errors more likely. | Sinha et al., arXiv 2509.09677 (NeurIPS 2025) | Reinforcing feedback within a run |
| Token use for the same task varies up to 30×; models predict their own usage poorly (r ≤ 0.39). | Bai et al., arXiv 2604.22750 | A budget stock drained by a high-variance flow |
| At least 16% of successful runs on tasks over 8 hours were illegitimate on review. Cheating rises with horizon. | METR Frontier Risk Report, May 2026 | Goal erosion that grows with time |
| Multi-agent setups ranged from +81% to −70% depending on task structure. Error amplification was 17.2× with independent agents and 4.4× with central coordination. | Kim et al. (Google), arXiv 2512.08296 | Loop gain and coordination overhead |
| Generative AI raised productivity, then lowered it as technical debt accumulated (an inverted U). | Anderson, Parker &amp; Tan, ISDC 2026 | Delayed accumulation outweighing the immediate gain |

At least five of the ten hardest open problems in agent orchestration found in the research are
about stocks, flows, and capacity over time. Four more are about the stability of a feedback loop.
None of today's governance tools (tracing, evals, guardrails, per-run cost) measures them
directly.

## The questions

### "Why not just use a workflow engine: Temporal, LangGraph, Airflow?"

They answer **"run this work reliably in this order."** They have real queues, retries, timers,
and durable state, and we'll keep using one. They hold no model of the system, so they can't say:
- how many workers to start;
- where the bottleneck is;
- what happens if the review limit doubles;
- why throughput fell last week.

LangGraph's stop rule is a step counter (`recursion_limit`); the OpenAI Agents SDK's is
`max_turns`. Neither tests whether anything converged.

**Relationship:** the engine is the **actuator**. The model decides the rates and limits; the
engine carries them out.

### "Why not queueing theory, Kanban WIP limits, Little's law?"

These are the strongest local competitor, and we'll use them. They answer **"given arrival and
service rates, what are the waits and where is the bottleneck?"**, with accumulation and delay
handled well.

What they don't represent is **endogenous feedback**:
- review quality falling as the review backlog grows;
- technical debt slowing the next change;
- reviewer goodwill rising when I review others' PRs;
- an agent's memory degrading its own future service rate.

Standard queueing treats service rates and routing probabilities as fixed. In agent systems the
interesting part is that they move, because of the system's own state.

**Relationship:** **embed it.** Queueing results give SD flows their rate functions. SD steady
states must obey Little's law, which is a free consistency check.

At our scale (tens of tickets, a few agents, one merge gate), a queueing network may be *more
accurate* than SD for latency. The honest test is in the last section.

### "Why not discrete-event or agent-based simulation?"

They answer **"what distribution of outcomes does this exact process produce?"** They handle
discreteness, variance, and rare events, which SD doesn't.

Their costs:
- many parameters;
- expensive to run;
- no readable loop structure;
- no practical way to lift them from data.

Generative agent-based modelling, where each simulated agent is an LLM, costs a model call per
simulated step (Park et al. 2023; Ghaffarzadegan et al., *SDR* 2024).

The comparison literature is consistent. SD shows the mean path of aggregates and the feedback
structure ("deterministic complexity"). DES shows variance and tails ("constrained randomness").
The two are complementary (Morecroft and Robinson 2005/2014; Rahmandad and Sterman,
*Management Science* 2008; Brailsford et al., *EJOR* 2019).

**Relationship:**
- **DES is the ground truth we test discovery against** (see `lifted-models.md`).
- It's the tactical layer where integer servers and tails matter: a serial merge gate, p95
  latency.

### "Why not process mining?"

It answers **"what process actually happened?"** from event logs. It's excellent at finding the
real paths, conformance gaps, and waiting times. It's descriptive and historical. It models no
feedback and simulates no policy unless exported to a simulator.

Pourbafrani and van der Aalst (*IEEE Access* 2022) already export process-mining results *into
SD models*. Fournier et al. (arXiv 2505.20127) apply process mining to agent trajectories.

**Relationship:** **the front end.** Process mining proposes which stocks and flows exist; SD adds
the feedback and the simulation.

### "Why not control theory or model predictive control?"

Control theory isn't really an alternative. SD is nonlinear state-space modelling with a
different culture: its strengths are building models of organisations and their decision rules,
and explaining them in loops people can read. Control theory brings controller design and
stability guarantees, which SD practice rarely provides.

Recent work frames agents in control terms. Eslami and Yu (arXiv 2603.10779, 2026) derive
stability conditions linking adaptation rate, switching frequency, and delay. A 2026 survey names
the lack of formal stability proofs for agent loops as the main open problem (arXiv 2609.16599).

**Relationship:** **SD builds the plant model, and control theory designs and checks the
controller.** Both need an identified model of the plant, which is what our discovery work
produces.

### "Why not reinforcement learning, or bandits?"

**RL** answers "which policy maximises reward?" It needs very large amounts of interaction data,
is opaque, struggles to assign credit over long delays (exactly where debt and incidents arrive),
and is unsafe to explore with on a live organisation.

**Bandits** handle immediate choices well: which model for this ticket (e.g. RouteLLM, arXiv
2406.18665). They model no accumulation or feedback.

**Relationship:**
- Bandits run **inner loops** inside rates the model sets.
- RL, if ever, is trained **against the SD model as a simulator**, which was SD's original role
  as a "management flight simulator".

### "Why not A/B tests and causal inference?"

They answer **"did this change cause that effect?"** Their assumptions break exactly where agent
systems live:
- A/B tests need units that don't interfere, but agents share one review queue, one CI, one
  budget.
- Feedback and non-stationarity violate the usual causal assumptions.
- They answer only for interventions already made. They can't extrapolate to a policy never
  tried.

**Relationship:** **the validation layer.** Use CausalImpact (Brodersen et al. 2015) or
difference-in-differences to check whether the model's *predicted* effect of a change matched
what happened. That's the falsification step SD practice has usually lacked.

### "Why not dashboards, DORA metrics, OKRs?"

They answer **"how are we doing?"** They *observe* stocks (work in progress) and delays (lead
time) but explain nothing and simulate nothing.

**Relationship:** **calibration targets and outputs.** DORA's lead time and change failure rate
are numbers the model must reproduce. OKR key results are targets on the model's stocks.
Dashboards show *what*; the model says *why*, and *what if*.

### "Why not optimise the agents: evals, DSPy, prompt tuning?"

These answer **"which configuration scores best on a fixed benchmark?"** They optimise a static,
per-call quality function. That's valuable, and it sets parameters the model uses: an agent's
first-pass acceptance rate, its rework fraction.

The danger SD exists to catch is **local optimisation that hurts the system**:
- an agent tuned to get more PRs accepted today produces more review load and more debt next
  month;
- a judge tuned to agree with authors raises throughput and lowers quality.

Only a model with the feedback in it sees that.

### "Won't better models make this unnecessary?"

They make it more necessary. METR measures the length of task frontier models can complete
(at 50% success) doubling about every seven months (arXiv 2503.14499). Faster, more capable agents
raise the arrival rate at every stage downstream of them:
- human review;
- CI;
- the merge process;
- the budget.

The Faros data is that shift: individual output up, review time up, delivery flat. Better
machines move the bottleneck; they don't remove the system.

### "Isn't this overkill at our scale?"

Possibly, and we should find out rather than assume. SD's advantage appears when *slow feedback*
matters within the planning horizon: debt, reviewer erosion, memory drift, budget exhaustion,
capability traps. If those don't show up in our data, then WIP limits, Little's law, a few DORA
numbers, and a bandit router capture most of the value at lower cost.

The test below decides it.

### "Has anyone done this?"

Not that we found. The SD and LLM literature runs the other way:
- LLMs help *build* SD models (SDBot, *SDR* 2024; LunaSim Copilot, ISDC 2025);
- SD studies AI *adoption* as a strategic question (Anderson, Parker &amp; Tan, ISDC 2026).

Agent orchestration has queueing work at the inference layer (arXiv 2504.07347) and control
framings (arXiv 2603.10779). We found no published work using a stock-and-flow model as the
working layer that coordinates an agent fleet. Read that as "not found", not "doesn't exist".
Either way it means there is no outside evidence yet that it works. The evidence has to be ours.

### "What outcome do you hope for?"

An orchestrator whose decisions are **derived from, and checked against, a model of the system
it operates in**. Its decisions:
- what to start, and how much at once;
- which machine (agent, program, person) goes on which flow;
- where to spend the next dollar;
- when to stop.

The model is lifted from data and verified by prediction. Concretely:
1. **Stability.** No thrashing, no runaway retries or spawning, no review floods. Work is
   started with the pipeline counted, not by looking at the backlog alone.
2. **Spending where it pays.** Agent dollars go where simulation shows leverage, and programs
   replace agents where the data shows they hold the rate and quality.
3. **Credit that holds up.** Each intervention has a prediction written beforehand and a
   verdict afterwards. Prevented incidents are credited by simulation, not by anecdote.
4. **One language with management.** Goals, key results, and capacity as stocks and rates
   everyone can read.

### "How would we know it failed?"

Before relying on it, run this test:

1. Build a discrete-event simulation of an agent orchestrator: discrete tickets, integer
   reviewers, heavy-tailed service times, rework, review fatigue.
2. Run discovery on its event log only.
3. Ask the discovered SD model, a queueing-network model, and a plain forecasting model to
   predict the effect of a **policy change none of them has seen** (e.g. reviewer limit 2 → 4,
   or a stricter critic).
4. Compare the predictions with the simulation's actual result. Then repeat on Orchestra's own
   history, checking with CausalImpact.

**If SD doesn't beat the queueing baseline,** use SD as the strategic and explanatory layer only,
and put the queueing model in the dispatch loop. **If discovery can't recover usable structure
from discrete-event data,** use designed models with fitted numbers, and use discovery only to
flag where the designed model stopped fitting.

## Summary table

✔ native · ◐ partial or bolt-on · ✘ absent

| Approach | Question it answers | Accumulation | Delay | Feedback from the system's own state | Simulates an untried policy | Role beside SD |
|---|---|---|---|---|---|---|
| Workflow engines, LangGraph | Execute reliably | ◐ | ◐ | ✘ | ✘ | Actuator |
| Queueing, Little's law, Kanban | Waits and bottleneck at steady state | ✔ | ✔ | ◐ fixed routing | ◐ structural only | Sets rate functions; consistency check |
| Discrete-event simulation | Outcome distribution of a process | ✔ | ✔ | ◐ | ✔ costly | Ground truth for testing discovery; tactical layer |
| Agent-based (incl. generative) | Emergence from individual rules | ✔ | ✔ | ✔ emergent | ✔ very costly | Heterogeneity studies; test generator |
| Process mining | What actually happened | ◐ | ✔ | ✘ | ◐ via export | Front end that finds the flows |
| Control theory, MPC | Stable inputs for setpoints | ✔ | ✔ | ✔ | ✔ | Partner: controller design and stability |
| Reinforcement learning | Optimal policy | implicit | weak | implicit | off-policy only | Trained against the SD simulator |
| Bandits | Best choice now | ✘ | ✘ | ✘ | ✘ | Inner-loop routing |
| A/B, CausalImpact, DiD | Did X cause Y? | ✘ | ◐ | ✘ assumed away | ✘ past only | Validates SD predictions |
| DORA, dashboards, OKRs | How are we doing? | observed | observed | ✘ | ✘ | Calibration targets |
| Evals, DSPy, Bayesian optimisation | Best configuration on a benchmark | ✘ | ✘ | ✘ | search only | Tunes parameters; SD guards the global effect |
| **System dynamics** | How does structure produce behaviour, and what happens under policy P? | ✔ | ✔ | ✔ | ✔ cheap | Integrating layer |

## Sources

**Agent orchestration**
- Cemri et al. 2025, arXiv 2503.13657.
- Anthropic, "Building effective agents" (Dec 2024); "How we built our multi-agent research
  system" (Jun 2025); "Claude Code auto mode" (Mar 2026).
- Cognition, "Don't build multi-agents" (Jun 2025).
- Kim et al., arXiv 2512.08296.
- Sinha et al., arXiv 2509.09677.
- Xiong et al., arXiv 2505.16067.
- Bai et al., arXiv 2604.22750.
- METR: arXiv 2503.14499; Frontier Risk Report (May 2026).
- Faros AI (Jul 2025).
- Zheng et al., arXiv 2306.05685.
- Panickssery et al., arXiv 2404.13076.
- Huang et al., arXiv 2310.01798.
- Wynn et al., arXiv 2509.05396.

**Intersection and alternatives**
- Hosseinichimeh et al., *SDR* 40(3) 2024.
- LunaSim Copilot, ISDC 2025.
- Anderson, Parker &amp; Tan, ISDC 2026.
- Pourbafrani &amp; van der Aalst, *IEEE Access* 10, 2022.
- Fournier et al., arXiv 2505.20127.
- Eslami &amp; Yu, arXiv 2603.10779.
- Du &amp; Chan, arXiv 2609.16599.
- Li, Dai &amp; Peng, arXiv 2504.07347.
- Rahmandad &amp; Sterman, *Management Science* 54(5) 2008.
- Morecroft &amp; Robinson (ISDC 2005; Wiley 2014).
- Brailsford et al., *EJOR* 278(3) 2019.
- Brodersen et al., *Annals of Applied Statistics* 9(1) 2015.
- RouteLLM, arXiv 2406.18665.
- DSPy, arXiv 2310.03714.
- Little, *Operations Research* 9(3) 1961.

**[unverified]**
- Faros 2026 follow-up figures.
- DORA 2025 specifics.
- Jackson networks (1957/1963).
- Goldratt, *The Goal*.
- *Accelerate* (2018).
