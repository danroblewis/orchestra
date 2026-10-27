# The environment, ghost machines, and replacing what we do not understand

Status: proposal, not built. From a conversation with the owner, 2026-10-26. It is the second half
of the curious-observer story (`docs/roadmap/use-cases.md` UC-0): observe, then influence, then
replace.

## 1. The environment is an actor

A project that only measures (weather, a river, a grid, a simulation) has a model with stocks and
flows and no machines or events. Every flow still has an equation; nothing says who sets it. That
unnamed actor is **the environment**.

- The model shows flows with no attributed machine as set by the environment, explicitly, not as a
  gap.
- The user's next move is a machine that acts on the environment. The model says where to act: the
  **leverage points** (Donella Meadows, *Leverage Points: Places to Intervene in a System*):
  - a stock you can fill or drain directly;
  - a flow whose drivers you control;
  - a loop you can strengthen or break.
- The owner's example: the lake (a stock) drains faster than the rivers fill it. A dam is a machine
  that sets one outflow by a rule, and the model shows whether the lake holds.

## 2. Ghost machines: a machine inferred from what the system already does

In system dynamics a rate equation is a **decision rule**: the policy of whoever sets that flow
(Forrester, *Industrial Dynamics*; Sterman, *Business Dynamics*, on decision rules). So every fitted
flow equation is already a description of a machine: "this is what it does, though we do not know
how."

A **ghost machine** promotes a group of fitted rates to an entity:
- **What it does:** the flows it sets, with their equations, inputs and origin (fitted).
- **What it reads:** the series its equations read.
- **Status:** "inferred, not running".

It appears on the Machines page and the event map. It sends no events of its own, but it is placed
where its flows are. Rates belong in one ghost when they share inputs and act on the same stocks.
This is the "one machine per decision rule" heuristic of §5.

Related practice:
- **System identification** (control theory): black-box and grey-box models from input/output
  data. That is what discovery does for flows.
- **Process mining** (Wil van der Aalst, *Process Mining*): reconstructing process models from
  event logs. It is the event-side twin of this: it could infer ghost machines from the bus as well
  as from metrics.

## 3. Shadow, swap, verify: replacing a component

A ghost machine is also a specification for a replacement. The path:
1. **Observe** the component's effect as flows (it may be an AI agent, a person's habit, a flaky
   service, or the environment).
2. **Fit** its decision rule (the ghost).
3. **Write a program** that implements the rule.
4. **Run it in shadow** beside the original. Shadow mode is the dark launch of web operations: its
   would-be flows are computed and compared, but it does not act.
5. **Swap it in per flow**, wherever the program matches. This is the strangler fig pattern
   (Martin Fowler), which replaces a legacy system piece by piece behind the same interface.
6. **Verify** in the next era that the flows did not change. These are the intended-effect and
   null tests of `docs/rationale/lifted-models.md` §3, at their own horizons.

The same path also makes an iffy component reliable without understanding it fully: the ghost's
equation becomes the rule a reliable program enforces.

### Replacing an AI agent

We use an AI agent as a universal machine: given a prompt, it does the thing, and we do not know
how. The ghost of an agent is the opposite, a universal machine whose behaviour is defined by what
it already does. Machine learning calls this behavioural cloning or distillation (training a
cheaper policy on an expensive one's behaviour).

The path is the same: observe the agent's flows, fit its rule, write the program, shadow it, swap
it per flow. The agent becomes a prototyping tool, and programs take over the parts that turn out
to be rules.

### Where it breaks

- **A fitted equation is the average, not the rare case.** The rare cases are often exactly why an
  AI was used: the unusual ticket, the judgement call. The agent stays as the fallback for whatever
  the program does not match.
- **Replacing a component changes the system around it.** This is Goodhart's law, and in economics
  the Lucas critique: a rule fitted under the old policy may not hold under the new one. So every
  swap is a hypothesis with a kill criterion, verified era by era, never a rewrite taken on trust.
- **Correlation is not a decision rule.** A ghost's inputs must be tested by impulse injection
  (UC-0 step 2) before its equation is trusted as a specification.

## 4. What Orchestra needs

Machines and flows stay separate, as now: a machine's attribution to a flow is a hypothesis
(`AGENTS.md` rule 6).

1. **Flows set by the environment** shown as such on the Dynamics page and the Machines page.
2. **Ghost machines**: groups of fitted rates promoted to entities, with inputs, outputs, origin and
   the evidence for the grouping. They are listed apart from observed machines and never override
   them (rule 2).
3. **Shadow mode** for a candidate machine: it declares the flows it would set, Orchestra computes
   its would-be flows from its decisions (logged, not acted on), and the Dynamics page shows them
   against the real ones.
4. **The replacement check**: when a machine takes over a flow, the next era's fitted equation is
   compared with the ghost's prediction, and the result is recorded with the swap.
5. **Leverage points**: the model marks stocks and flows a machine could act on, ranked by how much
   of the system each would move (sensitivity on the fitted model).

## 5. How many flows should one machine own?

There is no "one machine per flow" rule in the literature. Granularity is a trade-off every field
meets:

- **Factories.** Adam Smith's pin factory split the work into one operation per worker: a machine
  per flow, which maximises specialisation but puts a queue (a stock) at every hand-off. Lean
  manufacturing (Toyota; cellular layouts) moved back toward cells that do several consecutive
  steps, because the queues cost more than the specialisation gained. Theory of Constraints
  (Goldratt, *The Goal*) adds that only the bottleneck flow matters at any one time.
- **Services.** A service per API endpoint against a modular monolith is the same trade-off:
  independent scaling and failure against coordination and hand-off cost. Conway's law adds that
  the split tends to mirror who owns what.
- **Control theory** gives the sharpest rule: **one controller per controlled variable.** Two
  controllers acting on the same stock toward different goals fight and oscillate.

So, the heuristic:
- **One machine per decision rule:** flows set by the same policy from the same inputs belong
  together.
- **Never two machines steering one stock** without explicit coordination between them.
- **Split** when flows scale differently or have different owners. **Merge** when the hand-off
  between them creates a stock nobody wants.

The model can check this. It can flag stocks with more than one controlling machine, and hand-off
stocks that exist only because of a split.

## 6. Where it sits in the plan

See `docs/roadmap/README.md`:
- H1: impulse injection.
- H2: the environment shown as an actor, ghost machines, leverage points.
- H3: shadow mode and the replacement check, first used to distil a rule-like part of an agent's
  work into a program.
- Granularity checks: alongside H2.
