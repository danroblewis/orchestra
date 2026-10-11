"""The tools an agent uses to talk to Orchestra, defined once as data.

Every harness exposes these to its model in its own way: the Pi extension registers them
as Pi tools, the MCP server (``orchestra.harness.mcp``) serves them to Claude Code and any
other MCP client. Each tool maps to an ``orchestra.api`` command. Which tools an agent
gets is decided by tool *groups* (``RoleDef.tools``), never per tool."""

from __future__ import annotations

from dataclasses import dataclass, field

STATES = "OPEN, BLOCKED, IN_PROGRESS, READY_FOR_REVIEW, IN_REVIEW, REJECTED, APPROVED, MERGING, DONE, CANCELLED"


@dataclass(frozen=True)
class ToolDef:
    name: str
    group: str
    description: str
    properties: dict = field(default_factory=dict)   # JSON schema properties
    required: tuple[str, ...] = ()
    command: str | None = None                        # api command; defaults to name

    @property
    def api_command(self) -> str:
        return self.command or self.name

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": dict(self.properties), "required": list(self.required),
                "additionalProperties": False}

    def to_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "description": self.description,
                "inputSchema": self.input_schema, "command": self.api_command}


def S(d: str) -> dict:
    return {"type": "string", "description": d}


def I(d: str = "") -> dict:
    return {"type": "integer", "description": d} if d else {"type": "integer"}


def A(d: str = "") -> dict:
    s = {"type": "array", "items": {"type": "string"}}
    return {**s, "description": d} if d else s


TOOLS: list[ToolDef] = [
    ToolDef("report_ticket", "report_ticket",
            "Report the outcome of your work on this ticket. Call exactly once when you are finished. "
            "READY_FOR_REVIEW means your changes are committed on your branch and ready for a reviewer. "
            "BLOCKED means you cannot proceed; blocked_reason is required and must say what you need.",
            {"state": {"type": "string", "enum": ["READY_FOR_REVIEW", "BLOCKED"]},
             "summary": S("What you changed and why, in a few sentences"),
             "blocked_reason": S("Required when state is BLOCKED")}, ("state", "summary")),
    ToolDef("report_review", "report_review",
            "Report your review verdict. Call exactly once when you are finished reading the change. "
            "APPROVED means the code is correct, complete against the acceptance criteria, and consistent "
            "with the repository. REJECTED must include specific, actionable feedback the worker can act on.",
            {"verdict": {"type": "string", "enum": ["APPROVED", "REJECTED"]},
             "summary": S("Short summary of the review"),
             "feedback": S("Required when REJECTED: concrete problems, with file and line where possible")},
            ("verdict", "summary")),
    # tickets
    ToolDef("project_status", "tickets", "Counts of tickets by state, milestones, active sessions, pipeline state."),
    ToolDef("list_milestones", "tickets", "List all milestones with id, name, status, and ticket counts."),
    ToolDef("create_milestone", "tickets", "Create a milestone to group tickets. Returns its id (M1, M2, ...).",
            {"name": S("Short name"), "description": S("What this milestone is for")}, ("name",)),
    ToolDef("update_milestone", "tickets", "Rename or re-describe a milestone.",
            {"id": S("Milestone id"), "name": S("New name"), "description": S("New description"), "order": I()}, ("id",)),
    ToolDef("close_milestone", "tickets",
            "Close a milestone. Only allowed when every ticket in it is DONE or CANCELLED. Irreversible.",
            {"id": S("Milestone id")}, ("id",)),
    ToolDef("list_tickets", "tickets", "List tickets, optionally filtered by state or milestone.",
            {"state": S(f"One of {STATES}"), "milestone_id": S("Milestone id")}),
    ToolDef("get_ticket", "tickets", "Full detail of one ticket including its notes.", {"id": S("Ticket id like ORC-12")}, ("id",)),
    ToolDef("create_ticket", "tickets",
            "Create a ticket in an open milestone. objective says why (which project objective it serves); "
            "description is a self-contained brief a worker can implement without asking; acceptance is what a "
            "reviewer checks in the diff; verification is how the merge gate's acceptance tests prove it, "
            "including any test that must be added.",
            {"title": S("Short imperative title"),
             "objective": S("Why this ticket exists and which objective it serves"),
             "description": S("Self-contained implementation brief"),
             "acceptance": S("Acceptance criteria, one per line"),
             "verification": S("How the gate proves it: existing acceptance test(s) or the test to add"),
             "milestone_id": S("Milestone id, e.g. M1"),
             "priority": I("1 (first) .. 9 (last); default 5"),
             "depends_on": A("Ticket ids that must be DONE first")},
            ("title", "objective", "description", "acceptance", "verification", "milestone_id")),
    ToolDef("update_ticket", "tickets",
            "Edit a ticket's title, description, acceptance, verification, objective, priority, milestone, or dependencies.",
            {"id": S("Ticket id"), "title": S("New title"), "description": S("New description"),
             "acceptance": S("New acceptance criteria"), "verification": S("New verification"),
             "objective": S("New objective (supervisor only)"), "priority": I(),
             "milestone_id": S("Move to this open milestone"), "depends_on": A()}, ("id",)),
    ToolDef("add_note", "tickets", "Append a note to a ticket.", {"id": S("Ticket id"), "text": S("Note text")}, ("id", "text")),
    ToolDef("cancel_ticket", "tickets", "Cancel a ticket that should not be done.", {"id": S("Ticket id"), "reason": S("Why")}, ("id", "reason")),
    ToolDef("unblock_ticket", "tickets",
            "Move a BLOCKED ticket back to OPEN after resolving its blocker. Explain the resolution in note.",
            {"id": S("Ticket id"), "note": S("How the blocker was resolved")}, ("id", "note")),
    # context
    ToolDef("get_project_context", "context",
            "Read the project context document (objectives, value propositions, non-goals, verification)."),
    ToolDef("update_project_context", "context", "Replace the project context document with the full new markdown text.",
            {"text": S("The complete document in markdown")}, ("text",)),
    # pipeline
    ToolDef("get_gate_run", "pipeline", "Detail and logs of one merge gate run.", {"id": S("Gate run id")}, ("id",)),
    ToolDef("list_gate_runs", "pipeline", "Recent merge gate runs."),
    ToolDef("get_staging_status", "pipeline", "Status and recent log of the staging environment."),
    ToolDef("restart_staging", "pipeline", "Restart the staging process on its current build."),
    ToolDef("resume_pipeline", "pipeline", "Resume the merge pipeline after a base-branch failure has been fixed.",
            {"note": S("What was fixed")}, ("note",)),
    # capacity
    ToolDef("get_capacity", "capacity", "Current worker/reviewer capacity: the runtime dial and the configured maximum."),
    ToolDef("set_capacity", "capacity",
            "Set how many workers and reviewers may run at once, between 0 and the configured maximum. "
            "Use 0 to pause pickup while re-planning; raise it again afterwards.",
            {"workers": I(), "reviewers": I(), "note": S("Why")}, ("note",)),
    # events
    ToolDef("read_events", "events",
            "Recent Orchestra events (ticket changes, gate runs, staging, agents). Use to look back over what happened.",
            {"minutes": I("How far back, default 60"), "types": A("Event types to include; empty for all")}),
    # roles
    ToolDef("list_roles", "roles", "All agent roles, built-in and custom, with their wake rules and paused state."),
    ToolDef("get_role", "roles", "One role's definition and prompt.", {"name": S("Role name")}, ("name",)),
    ToolDef("create_role", "roles",
            "Create a custom long-running agent role after agreeing its design with the human. The prompt is its full "
            "responsibilities in markdown. wake_on lists event types (optionally 'ticket_transition:DONE'); every is an "
            "interval like '6h'; at is a daily time 'HH:MM'. session is 'resident' (one long-lived session) or "
            "'ephemeral' (fresh session each wake).",
            {"name": S("lowercase_with_underscores"), "description": S("One line: what this agent is for"),
             "prompt": S("Responsibilities in markdown"),
             "tools": A("Tool groups: tickets, context, pipeline, capacity, escalate, events"),
             "session": S("resident | ephemeral"), "wake_on": A(), "every": S("e.g. 30m, 6h, 1d"), "at": S("HH:MM")},
            ("name", "description", "prompt")),
    ToolDef("update_role", "roles", "Change a custom role's definition or prompt.",
            {"name": S("Role name"), "description": S(""), "prompt": S("New full prompt"), "tools": A(),
             "session": S(""), "wake_on": A(), "every": S(""), "at": S("")}, ("name",)),
    ToolDef("delete_role", "roles", "Delete a custom role; its sessions are archived.", {"name": S("Role name")}, ("name",)),
    ToolDef("pause_role", "roles", "Pause a role: wake-ups queue until resumed.", {"name": S("Role name")}, ("name",)),
    ToolDef("resume_role", "roles", "Resume a paused role.", {"name": S("Role name")}, ("name",)),
    ToolDef("restart_role", "roles", "Restart a role's session (fresh process; transcript kept).", {"name": S("Role name")}, ("name",)),
    # escalate
    ToolDef("escalate_to_supervisor", "escalate",
            "Wake the Supervisor with a note when a decision about intent, scope, or priorities is needed.",
            {"note": S("What needs deciding and why")}, ("note",)),
]

BY_NAME = {t.name: t for t in TOOLS}


def tools_for(groups: list[str] | tuple[str, ...] | set[str]) -> list[ToolDef]:
    g = set(groups)
    return [t for t in TOOLS if t.group in g]
