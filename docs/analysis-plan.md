# Plan: building the analysis method

Status: plan, 2026-10-24; the 2026-10-24 planning set, kept as examples (`docs/roadmap/decisions.md`
D11). The models are planning estimates. The toolchain in `docs/models/` (lib.mjs, check.mjs,
render.mjs, build.py) targets a separate SD Lab checkout named by `SDLAB` and is not run by this
repository (the vendored `orchestra/sdlab` has no `static/sim.js`, so it cannot be re-pointed). What
comes next after `analysis-method.md`, in order. Each step is usable on its own. Steps 1–5 stay as
scripts in `docs/models/` (agents first, programs later). Steps 6–7 move into Orchestra only after
the method has worked twice.

## 1. Loop finder (`docs/models/loops.mjs`)

- **Builds a signed graph from a model:**
  - stock → flow, when the stock is read by the flow's rate equation, an effect, or a co-flow;
  - flow → stock, by the flow's direction.
- **Signs the links:**
  - a rate term's coefficient gives the sign;
  - a table effect's sign is the slope between its first and last points (mixed if the slope
    changes sign);
  - a flow drains its source (−) and fills its target (+).
- **Enumerates elementary cycles through stocks:** polarity is the product of the signs.
- **Estimates each loop's delay** from the time constants of its stocks.
- **Output:** JSON loops, matched against each model's hand-written `loops` key. Reports declared
  loops it can't find, and real loops nobody declared.
- **Test:** every declared loop in the four story models is found with the declared polarity.

## 2. Explore tool (`docs/models/explore.mjs`)

This promotes the scratch exploration script.
- **Runs** a model with all its variants.
- **Divergence:** the normalised difference over time from the designed run, on chosen measures.
- **Behaviour classifier** per stock: growth, decay, goal-seeking, S-curve, peak-then-decline,
  oscillation, collapse, flat.
- **Plausibility flags:** a stock pinned at a bound, a resource exhausted early, a value out of
  range.
- **Test:** story 1's surge playbook is classified peak-then-decline, and designed is S-curve or
  growth.

## 3. Scenario proposer (`docs/models/scenarios.mjs`)

- For each loop from step 1, it proposes variants from the templates in `analysis-method.md` §5.2.
  The proposals are concrete changes in the variants format, within declared constraints.
- **Test:** for story 1 it proposes `no-learning`, `surge` and `surge-protected` equivalents among
  its candidates.

## 4. Record and lint (`docs/models/record.mjs`)

- **The analysis record format:** a JSON schema, and a validator.
- **Writing records:** each record hashes the model files it was run against.
- **Lints charts** against §5.4: a claim title, at most 4 series, a formula for each measure, series
  that differ, and a horizon that covers the behaviour.
- **Renders** the record's scenarios, rejections and findings into the diagrams page.

## 5. Sensitivity (`docs/models/sensitivity.mjs`)

- Varies the parameters marked most uncertain by ±50%.
- Reruns the checks, and reports which findings flip (rubric #8).
- First run: story 1.

## 6. First real run: the managers' budget question

- An agent follows `analysis-method.md` with tools 1–5, on the desk model.
- Ask: "Show my managers why agents are worth the budget."
- It produces an analysis record, reviewed against the rubric.
- Then a second, independent run, compared with the first.
- **Before showing managers:** fit the company-side rates (review time, SAIL failure rate, request
  volume) from real GitHub and Jira history, and record each number's origin.

## 7. Into Orchestra (after two successful runs)

1. **An `analyst` role** whose prompt is `analysis-method.md`, and an Analysis team with its space.
   No loop changes.
2. **The tools from steps 1–5** as Orchestra tools in `orchestra_agents/harness/tools.py` (in `~/orchestra-agents`).
3. **Analysis records behind a store;** a web UI page for charts and records; checks rerun on model
   change as a probe.
4. **Decide first:** whether SD Lab becomes `orchestra.sd` or a dependency (AGENTS.md rule 10).
