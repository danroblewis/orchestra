# Rationale: system dynamics and AI agent orchestration

Why this project exists, written for engineers who will ask "why system dynamics instead of
something obvious?"

| Document | What it answers |
|---|---|
| [convergence.md](convergence.md) | The main argument. Agent orchestration explained in SD terms, SD explained in agent terms, the interface between them, what each gains, where each is weak and how the other helps, and the hypotheses to test. |
| [why-not-something-obvious.md](why-not-something-obvious.md) | Workflow engines, queueing, DES/ABM, process mining, control theory, RL, causal inference, dashboards, prompt optimisation: what each does, what it can't, how it fits beside SD, and the test that would show SD isn't worth it. |
| [lifted-models.md](lifted-models.md) | The next topic. What discovering equations from data adds (predictions as acceptance tests, null tests, tasks as dynamics, models as agent context, the universal machine), the honest status of discovery, and the validation programme for real data. |

Applied proposals that build on these:
- `../proposals/system-dynamics-core.md`
- `../proposals/orchestra-for-the-whole-job.md`
- `../proposals/corporate-workflow.md`
- `../work-charter.md`

Research behind these documents: four literature and code surveys made on 2026-10-24 (system
dynamics foundations; agent orchestration patterns and failures; the intersection and the
alternatives; SD Lab's discovery record). Their citations were checked against primary sources
where marked. Unverified items are flagged in each document.
