# Analysis method: inventing meaningful simulations from a model

Status: draft, 2026-10-24. Documents the method used to produce the user-story simulations
(`user-story-diagrams.md`). The goal is that the same analysis can be run again: on larger models
of my work, from new perspectives, for new asks, by an agent or a person, and the result can be
inspected, reviewed and compared.

Companions:
- `models/README.md`: the models and their conventions.
- `user-stories.md`: the stories.
- `rationale/`: why system dynamics.

---

## 1. What "repeatable" means here

A model is not an analysis. A model of my work life will grow to hundreds of stocks. Any one ask
needs a handful of scenarios, measures and charts chosen from an enormous space. Examples of asks:
- "convince my managers this is worth the budget";
- "what happens if requests double";
- "is the review process the bottleneck".

Choosing well takes understanding of the model, and a point of view. That part is judgement, and
an agent can do it.

**Repeatable does not mean identical output.** Two runs of the method on the same ask may choose
different scenarios. Repeatable means four things:

1. **A fixed procedure.** The same steps, in the same order, with the same gates, whoever or
   whatever runs them.
2. **A complete record.** Every run produces an **analysis record**: what was asked, of which model
   version, which loops were considered, which scenarios were tried, kept and rejected (and why),
   which measures and charts were chosen, and what the checks found. Anyone can read how a
   conclusion was reached and rerun it.
3. **Mechanical parts are programs.** Anything that can be computed (finding loops, running
   scenarios, scoring divergence, classifying behaviour, linting charts) is a program, so it gives
   the same answer every time.
4. **Judgement is reviewable and comparable.** The agent's choices are made against written
   catalogues and a rubric. A run can be repeated, and its choices compared with an earlier run's,
   before anything goes to an audience.

The simulation itself is already deterministic: SD Lab's simulator, no noise. The same model,
variants and measures always give the same charts.

## 2. Inputs

| Input | Example |
|---|---|
| **Model** | One or more SD Lab models, by file and content hash (e.g. the desk model: four stories, 88 stocks). |
| **Ask** | The question in the asker's words: "Show my managers why agents are worth the budget." |
| **Audience** | Who will read the result, and what they already value: managers (time, cost, delivery, risk); me (my hours, my backlog); a team lead (team health). |
| **Perspective** | The stance taken: today vs designed; one policy vs another; robustness under stress; a specific worry. |
| **Constraints** | What may be changed in scenarios: e.g. "budget is fixed at $120 a week", "human review capacity can't change". |
| **Known facts** | Things the model must reproduce to be credible: "today I'm overloaded and my backlog grows". These become validity checks. |

## 3. The analysis record

Every run writes one record. It's data, versioned with the models, and it is the thing reviewed.
Today the charts and measures already live in `models/*.charts.json`. The record wraps them with
everything else.

```jsonc
{
  "id": "managers-budget-2026-10",
  "ask": "Show my managers why agents are worth the budget.",
  "audience": "managers: time, cost, delivery, risk",
  "perspective": "today against designed; robustness under a surge",
  "constraints": ["budget refill fixed at $120/week"],
  "model": {"files": ["story-1-simple-task.json"], "sha256": "…", "built_by": "build.py@<commit>"},
  "facts": [{"says": "today I am overloaded and the backlog grows", "check": "1.1"}],
  "loops": [                       // from the loop finder (program), annotated by the analyst (agent)
    {"id": "R-learning", "polarity": "reinforcing", "stocks": ["…"], "relevant": true,
     "why": "decides whether agents get better or worse; managers care about quality over time"}
  ],
  "scenarios": [                   // candidates, tried, kept or rejected, with reasons
    {"id": "surge", "template": "stress-demand", "targets": "R-trap", "change": {"flows": {"t_ask": "…"}},
     "kept": true, "behaviour": {"t_playbook": "peak-then-decline"}, "divergence": 0.62,
     "why": "shows the capability trap: the strongest argument for protecting lesson capture"},
    {"id": "double-reviewers", "template": "add-capacity", "kept": false,
     "why": "outside the constraints: review capacity is the company's"}
  ],
  "measures": {"…": "as in *.charts.json"},
  "charts": [{"title": "…", "claim": "learning beats decay unless the backlog stops capture", "…": "…"}],
  "checks": [{"id": "1.4", "kind": "requirement", "claim": "…"}],
  "findings": ["…"],
  "review": {"rubric": {"…": "…"}, "reviewer": "me", "decision": "ship | revise"}
}
```

## 4. The procedure

Each step lists its purpose, whether a **program** or the **analyst** (an agent or a person) does
it, what it writes into the record, and how it fails.

### Step 1: Frame the ask (analyst)

Restate the ask as **a comparison and a claim to test**. For example: "Against today, the designed
system frees my time and holds quality, and stays affordable as demand grows."

- Name the audience's measures. For managers: hours, dollars, delivery, escaped defects, risk.
- List the known facts the model must reproduce. They become validity checks.
- **Writes:** `ask`, `audience`, `perspective`, `constraints`, `facts`.
- **Fails when:** the claim is vague ("show it's good") or can't be falsified.

### Step 2: Check validity first (program, with the analyst writing the checks)

Run the baseline variant (today) and check it against the known facts.
- If the model doesn't reproduce what the asker lives with, stop and fix the model.
- An analysis built on a model that fails its own baseline persuades nobody.
- **Writes:** validity checks and their results.
- **Fails when:** the baseline is tuned to look bad. Validity checks state *observed* facts, not
  hoped-for contrasts.

### Step 3: Find the loops (program, then the analyst)

- **Program:** enumerate the model's feedback loops from its structure.
  - A stock affects a flow through a rate equation, an effect, or a co-flow; a flow changes a
    stock.
  - The program finds every cycle through stocks, with its polarity (the product of link signs;
    for table effects, the sign of the slope).
  - It reports each loop with its stocks and its delay, from the stock time constants in the loop.
- **Analyst:** mark each loop relevant or not to the ask, with a reason. Name the behaviour each
  relevant loop could produce (section 5.1).
- **Writes:** `loops`.
- **Fails when:** the analyst picks loops from the diagram by eye. The program's list is the
  starting point, so nothing is missed by not looking.

### Step 4: Generate scenarios (program proposes, analyst chooses)

- **Program:** for each relevant loop, propose scenarios from the templates in section 5.2, with
  concrete changes: which flow, stock or parameter, and by how much, within the constraints.
- **Analyst:** choose candidates that test the claim from step 1, and add any the templates miss.
  Every scenario changes one thing against the designed model, so the difference is attributable.
- **Writes:** `scenarios` (candidates).
- **Fails when:** scenarios change several things at once, or ignore the constraints.

### Step 5: Run, score and classify (program)

For every scenario, the program:
- simulates over the horizon (long enough for the slowest relevant loop: several of its time
  constants);
- **scores divergence** from the designed run on the audience's measures, as the normalised
  difference over time;
- **classifies behaviour** of each key stock: growth, decay, goal-seeking, S-curve,
  peak-then-decline, oscillation, collapse, flat;
- **flags implausible results:** a stock pinned at a bound for most of the run, a resource
  exhausted early, values outside stated ranges.

**Writes:** behaviour and divergence per scenario.

### Step 6: Keep, reject or fix (analyst)

- **Keep** scenarios that diverge, show the behaviour their loop predicts, and bear on the claim.
- **Reject** flat or redundant ones, with the reason recorded.
- **Treat implausible results as model problems:** fix the model, rerun from step 2, and record the
  fix. Example: in story 1, the agents spent the whole budget paying down debt by week 10. Debt
  repayment was priced wrong, and the fix is recorded in the model history.
- **Writes:** `kept`, `why`, and model fixes.
- **Fails when:** inconvenient results are rejected as "boring", or the model is tuned until it
  agrees with the claim. A fix must be justified by the real system, not by the chart it produces.

### Step 7: Choose measures (analyst, from the catalogue)

For each kept scenario, choose measures from section 5.3:
- the stocks that carry the loop (playbook, trust, confidence);
- the audience's measures (hours, spend, delivered, escaped defects);
- composites only when they're what the audience thinks in (spend per week, share of attempts
  going wrong).

Every measure has a formula, printed with the chart.

**Writes:** `measures`.

### Step 8: Design the charts (analyst; program lints)

Rules (section 5.4):
- **One claim per chart.** The title states the claim.
- **Two to four series**, always including the designed run and the baseline or the stressing
  scenario.
- **Show what drove it:** the formula of each measure, the starting values, and the inputs.
- **A demand or input chart first,** so the reader knows what the system was subjected to.

**Program:** lint the charts. Each needs a claim, ≤ 4 series, a formula for each measure, series
that actually differ, and a time axis covering the behaviour.

**Writes:** `charts`.

### Step 9: Turn claims into checks (analyst writes, program runs)

Each chart's claim becomes a check:
- **validity:** must hold for the model to be believed;
- **requirement:** a design target, which may honestly fail and is then a gap;
- **info:** a reported finding.

The checks run with every model change, so a later model that breaks a claim says so.

**Writes:** `checks`.

### Step 10: Write findings (analyst)

- A short list: what the model says, the gaps, what it doesn't show, and its limits.
- Every number in a finding comes from a check or a measure, never typed by hand.
- **Writes:** `findings`.

### Step 11: Review (person, with the rubric)

Score the record against the rubric (section 6), then ship it or revise it. For an important ask,
run the method a second time, independently, and compare the two records:
- Which loops, scenarios and claims did both choose?
- Where they differ, which is better supported?

**Writes:** `review`.

## 5. Catalogues

The analyst chooses from these, and adds to them when something new is needed.

### 5.1 Loop behaviours

| Loop shape | Behaviours it can produce | What to look for |
|---|---|---|
| Reinforcing, unconstrained | Exponential growth or collapse | Doubling time |
| Reinforcing, with a balancing limit | S-curve; limits to growth | Where the limit binds, and which resource |
| Balancing | Goal-seeking | Time to settle; the goal it actually seeks (eroding goals) |
| Balancing with a delay | Overshoot, oscillation | Period, damping |
| Two reinforcing loops sharing a resource | Success to the successful | Which one starves |
| Fix with a delayed side effect | Fixes that fail; better before worse | When the side effect overtakes |
| Investment competing with throughput | Capability trap; worse before better | Behaviour under stress |
| Stock with decay and replenishment | Learning against decay | Whether inflow outruns decay |

### 5.2 Scenario templates

Each changes one thing against the designed model.

| Template | Change | Exposes |
|---|---|---|
| **Baseline** | Reassign machines to today's arrangement | The value of the design |
| **Remove a flow** | A flow's machine off | What a loop is worth (e.g. no learning) |
| **Stress demand** | Step or ramp an outside inflow | Traps, limits to growth |
| **Starve a resource** | Lower a capacity or a budget | Which loop breaks first |
| **Shift a starting value** | One stock's initial level | Path dependence, recovery (e.g. blind trust) |
| **Push a policy too far** | Multiply a policy flow | Fixes that fail, Goodhart (nagging, quotas) |
| **Protect a flow** | Remove the effect that starves it | The cost of the trap, and the remedy |
| **Shorten or lengthen a delay** | A time constant | Oscillation, overshoot |
| **Remove a coupling** | Drop a declared cross-model effect | What one area does for another (reciprocity) |

### 5.3 Measure kinds

As implemented in `*.charts.json` and `render.mjs`.

| Kind | Formula |
|---|---|
| `stocks` | A stock's level, or the sum of several |
| `flows` (+ `per_week`) | A flow's rate, or the sum of several, optionally × 40 |
| `share` | 100 × Σ(some flows) ÷ Σ(other flows) |
| `machine_hours_per_week` | Busy share × capacity × 40 |
| `machine_busy_share` | Busy share × 100 |
| `waiting_for` | The sum of every stock a machine drains |
| `agent_spend_per_week`, `agent_spend_total` | Σ(rate × cost per item) over flows that use the budget |

New kinds are added to this table and to `render.mjs` together.

### 5.4 Chart rules

1. **The title is the claim:** "Agent playbook: learning against decay and the capability trap",
   not "Playbook".
2. **Two to four series.** The designed run is always one. Contrast it with the baseline or the
   scenario that stresses it.
3. **Under every chart:** what's plotted, and the formula.
4. **On every story:** starting values, outside inputs, and what each variant changes.
5. **Units the audience uses:** per week, dollars, hours, percentages.
6. **Long enough to see the behaviour,** and no longer.
7. **No chart without a check** behind its claim.

## 6. Review rubric

Score each from 0 to 2. Ship at 12 or more of 16, with no zeros on 1, 2 or 7.

| # | Criterion |
|---|---|
| 1 | **Validity.** The baseline reproduces every stated fact. |
| 2 | **Traceability.** Every number in charts and findings comes from a measure or check with a formula. |
| 3 | **Relevance.** Every kept scenario bears on the ask; rejected ones are recorded with reasons. |
| 4 | **Attribution.** Each scenario changes one thing. |
| 5 | **Loop coverage.** Every loop marked relevant is exercised by at least one kept scenario. |
| 6 | **Clarity.** Charts follow section 5.4. |
| 7 | **Honesty.** Gaps and limits are stated; no model fix was made to reach a desired chart. |
| 8 | **Robustness.** Key findings survive reasonable changes to the most uncertain parameters (sensitivity run, recorded). |

## 7. Tools to build

Programs, so the mechanical steps give the same answer every time.

| Tool | Step | What it does |
|---|---|---|
| `loops` | 3 | Cycles through stocks via rate equations, effects and co-flows; polarity from link signs and table slopes; delay estimate per loop. |
| `scenarios` | 4 | Proposes concrete scenario variants from section 5.2's templates for a set of loops, within constraints. |
| `explore` | 5 | Runs scenarios; divergence score on chosen measures; behaviour classifier per key stock; plausibility flags. (A first version exists as a scratch script used to write the stories.) |
| `sensitivity` | rubric #8 | Varies the most uncertain parameters ± a range; reports which findings flip. |
| `lint` | 8 | Checks charts against section 5.4. |
| `record` | all | Writes and validates the analysis record; hashes the model files; renders the record into the diagrams page. |

Already built:
- the simulator and validator (SD Lab);
- variants, couplings and the desk assembly (`lib.mjs`);
- measures and charts as data, with formulas printed (`*.charts.json`, `render.mjs`);
- checks (`check.mjs`).

**The analyst's instructions.** For an agent, this document's steps, catalogues and rubric become
its role prompt. It gets the tools above, and returns an analysis record for review. The prompt and
tool versions are recorded in the record, so a later run can be compared with this one.

## 8. Worked example, recorded after the fact: story 1 for the managers' ask

How the story 1 charts were produced, written as the record this method would have produced. It
was not produced by following the method, which didn't exist yet. It is the method's first test
case.

- **Ask:** show that agents carrying simple tasks are worth it.
- **Audience:** managers.
- **Perspective:** today against designed, plus robustness.
- **Facts:**
  - today I'm overloaded and the backlog grows: check 1.1, which passes;
  - requests are increasing.
- **Loops considered** (all eight in the model, all relevant):
  - learning;
  - decay;
  - overload;
  - capability trap;
  - trust;
  - reviewer fatigue;
  - debt;
  - reputation.
- **Scenarios kept:**

  | Scenario | Template | What it shows |
  |---|---|---|
  | `manual` | baseline | today, overloaded |
  | `no-learning` | remove a flow | the playbook rots and debt grows |
  | `surge` | stress demand | the capability trap |
  | `surge-protected` | protect a flow | the remedy works |
  | `blind-trust` | shift a starting value | dips and recovers |
- **Scenarios rejected:**
  - more implementer slots, because the budget, not slots, binds;
  - faster reviewers, because review capacity is outside our control.

  These weren't recorded at the time; this is the reconstruction.
- **Model fixes made during analysis:**
  - debt repayment repriced;
  - successes allowed to leave patterns as lessons;
  - waiting in the backlog made to erode requesters' confidence.

  Each was justified by the real system, not by the chart. A reviewer should check that claim.
- **Measures:** asks per week, playbook, share going wrong, requesters' confidence, backlog, agent
  spend per week, budget balance, trust, my hours, delivered.
- **Checks:** 1.1–1.11, including gaps 1.4 (capability trap), 1.8 (backlog) and 1.11 (turnaround).
- **Not done:**
  - no sensitivity run (rubric #8 scores 0);
  - no independent second run.

  Both are needed before showing this to managers.
