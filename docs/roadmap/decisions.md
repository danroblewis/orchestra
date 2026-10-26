# Decisions only the owner makes

Collected from the proposals, the handoff and the sessions since 2026-10-24. The plan proceeds
around these; no agent decides them. Each has the document that raised it and what waits on it.

| # | Question | Raised in | What waits |
|---|---|---|---|
| D1 | May a person fill a worker or reviewer role (a human as a machine), or do humans act only through the Supervisor (rule 9)? | `~/orchestra-tasking/docs/proposals/agents-split.md` §4 | Human worker/reviewer cards; the Supervisor's rebuild |
| D2 | Ticket-state gaps: DONE cannot be reopened; BLOCKED only from IN_PROGRESS; "needs a decision" is not distinct from blocked; OPEN mixes ready with waiting; no hold state; REJECTED returns only to a worker; APPROVED and MERGING are code-only. Which to change? | session 2026-10-25 | The task system's model; the Tasks panel's vocabulary |
| D3 | Bus and time-series backends for real use (NATS + VictoriaMetrics, or Postgres + TimescaleDB), hosting and retention | `docs/proposals/events-and-data-infrastructure.md` §8 | Anything beyond the file bus and Redis in demos |
| D4 | Discovery-first, or a designed skeleton that discovery fills? Decided only if H1's stop rule fires | `docs/proposals/system-dynamics-core.md` §13 | H1's exit |
| D5 | SD Lab as `orchestra/sdlab` (vendored, as now) or as a dependency | `AGENTS.md` rule 10; `docs/analysis-plan.md` §7 | Nothing immediate; affects how discovery improvements land |
| D6 | A launcher: should `orchestra run` start the plugins' processes, and how is that declared? | session 2026-10-26 | Demos use their own scripts until then |
| D7 | Datetime scheduling of machines (`machine.due`): the task system's or the agents'? | session 2026-10-25 | Scheduled agents stay in the agents' host |
| D8 | PR trees for code mode (gh-stack is the owner's tool; git-spice acceptable) | memory `pr-trees` | Code mode beyond one branch per ticket |
| D9 | One ingest boundary (catalogue, HTTP/OTLP, collectors, read-only adapters such as Prometheus, bridges) | session 2026-10-25; `docs/proposals/events-and-data-infrastructure.md` | H4's target-system model |
| D10 | FedRAMP data classes, model clearances, and posting as the owner | `docs/work-charter.md` §8 | H3's connectors and outbox |
| D11 | Which user stories apply ("delete the ones that don't"); the order of H3 | `docs/user-stories.md` header | H3 |
| D12 | Team and role open questions 1–11 | `docs/proposals/teams-and-roles.md` | Stage 2 of teams |
| D13 | Where the two plugins' every-page scripts put their nav button and banner when both are installed | session 2026-10-25 | Cosmetic; the agents' script currently takes the button, the task plugin's banner stands aside |
| D14 | Repository names and places: rename `~/orchestra_2` to `~/orchestra` once the SD Lab jobs in the old checkout finish; delete `~/orchestra-taskdemo` once the in-repo demos supersede it | session 2026-10-26 | Path references in four `pyproject.toml` files |

When one is decided, record the decision and date here, state the invariant change in the commit
that makes it (per `AGENTS.md`), and remove the row's "what waits".
