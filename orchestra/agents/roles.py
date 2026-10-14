"""The role registry: every long-running agent kind is declared here.

Adding a role is one entry plus a prompt file in ``prompts/``. The loop keeps each
resident role's Pi session alive, wakes it on the listed events, and on a schedule
when ``every`` is set. Tools are granted by group name; the Pi extension reads the
groups from ORCHESTRA_TOOLS so no TypeScript changes are needed for a new role.

Tool groups (see harness/tools.py):
  tickets      read and write tickets and milestones, project status
  capacity     the runtime worker/reviewer capacity dial (0..configured max)
  context      read and update the project context document
  pipeline     gate runs, pipeline resume, staging status and restart
  escalate     escalate_to_supervisor
  events       read the event log
  team         read the organisation; brief ad hoc agents and message along the tree (leads, supervisor)
  roles        design the organisation: roles, agents, teams (supervisor)
  report_ticket / report_review   the worker and reviewer exit tools
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    name: str                       # ORCHESTRA_ROLE value, e.g. "pipeline_manager"
    session_id: str                 # Pi session id, e.g. "pipeline-manager"
    prompt: str                     # prompt file stem under agents/prompts/
    tools: tuple[str, ...]          # tool groups
    resident: bool = True           # kept alive for the life of `orchestra run`
    wake_on: tuple[str, ...] = ()   # event types that queue a wake-up (documentation; emitters call add_wakeup)
    every: float | None = None      # seconds between scheduled wake-ups, or None
    description: str = ""


ROLES: dict[str, Role] = {}


def register(role: Role) -> Role:
    ROLES[role.name] = role
    return role


register(Role(
    name="supervisor", session_id="supervisor", prompt="supervisor",
    tools=("tickets", "context", "pipeline", "roles", "team", "events"),
    wake_on=("human_message", "escalation"),
    description="Talks to the human; translates requests into objectives, verification, and tickets.",
))
register(Role(
    name="coordinator", session_id="coordinator", prompt="coordinator",
    tools=("tickets", "capacity", "escalate"), every=10 * 60,
    wake_on=("ticket_created", "ticket_done", "ticket_blocked", "review_threshold", "milestone_changed", "scheduled"),
    description="Keeps the plan executable: clarity, size, order, dependencies. Never changes intent.",
))
register(Role(
    name="pipeline_manager", session_id="pipeline-manager", prompt="pipeline_manager",
    tools=("tickets", "pipeline", "escalate"),
    wake_on=("base_broken", "gate_error", "staging_failed", "repeated_gate_rejection"),
    description="On-call for build, merge, and staging health.",
))
# Per-ticket roles are not resident; the loop starts them on demand.
register(Role(name="worker", session_id="worker-{ticket}", prompt="worker", tools=("report_ticket",), resident=False))
register(Role(name="reviewer", session_id="reviewer-{ticket}", prompt="reviewer", tools=("report_review",), resident=False))
register(Role(name="pair", session_id="pair-{ticket}", prompt="pair", tools=("pair",), resident=False,
              description="Watches one ticket's worker from the outside, runs the tests, and gives a verdict before review."))

# Future roles slot in here, for example:
#   register(Role(name="product_owner", session_id="product-owner", prompt="product_owner",
#                 tools=("tickets", "context", "escalate"), every=24 * 3600,
#                 description="Daily review of objectives versus landed work."))
#   register(Role(name="researcher", ..., every=7 * 24 * 3600))


def resident_roles() -> list[Role]:
    return [r for r in ROLES.values() if r.resident]
