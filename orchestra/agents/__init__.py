"""Role prompts and per-turn task prompts for the five agent kinds."""

from __future__ import annotations

from pathlib import Path

from ..config import Project
from ..model import State, Ticket

PROMPTS_DIR = Path(__file__).parent / "prompts"


def role_prompt(project: Project, role: str) -> str:
    override = project.config.prompt_overrides.get(role)
    path = (project.repo_root / override) if override else (PROMPTS_DIR / f"{role}.md")
    text = path.read_text(encoding="utf-8")
    return text.replace("{base_branch}", project.config.base_branch).replace(
        "{ticket_prefix}", project.config.ticket_prefix)


CONTEXT_TEMPLATE = """# Project context

_Maintained by the Supervisor. Every Supervisor turn starts with this document._

## Objectives
(What this project is trying to achieve, in priority order.)

## Value propositions
(Who benefits and how.)

## Non-goals
(What we deliberately will not do.)

## Definition of done
A ticket is DONE when its branch has landed on the base branch through the merge gate.

## Verification
(Which acceptance tests exist, what they cover, and what a new feature must add.)
"""


def context_path(project: Project) -> Path:
    return project.state_dir / "PROJECT.md"


def read_context(project: Project) -> str:
    p = context_path(project)
    if not p.exists():
        seed = project.repo_root / ".orchestra" / "PROJECT.md"
        p.write_text(seed.read_text(encoding="utf-8") if seed.exists() else CONTEXT_TEMPLATE, encoding="utf-8")
    return p.read_text(encoding="utf-8")


def write_context(project: Project, text: str) -> None:
    context_path(project).write_text(text, encoding="utf-8")


def _ticket_block(t: Ticket) -> str:
    deps = ", ".join(t.depends_on) or "none"
    return (f"Ticket: {t.id}\nTitle: {t.title}\nPriority: {t.priority}\nDepends on: {deps}\n\n"
            f"## Objective (why)\n{t.objective.strip() or '(not stated)'}\n\n"
            f"## Description\n{t.description.strip() or '(none)'}\n\n"
            f"## Acceptance criteria\n{t.acceptance.strip() or '(none given; use the description)'}\n\n"
            f"## Verification (how the merge gate proves it)\n{t.verification.strip() or '(none stated; existing tests must keep passing)'}\n")


def worker_task(project: Project, t: Ticket, unit_command: str | None) -> str:
    test_line = f"Run the unit tests with: `{unit_command}`" if unit_command else "There is no configured unit test command."
    head = f"# Your assignment\n\n{_ticket_block(t)}\n"
    env = (f"## Environment\nYou are in a git worktree checked out on branch `{t.branch}`. "
           f"The base branch is `{project.config.base_branch}`. Only this branch is yours. "
           f"{test_line}\n\n")
    if t.feedback and t.rejected_by:
        return (head + env + f"## This ticket was REJECTED by the {t.rejected_by} (round {t.review_rounds})\n"
                f"Address every point below, commit, re-run the tests, then call `report_ticket`.\n\n"
                f"{t.feedback.strip()}\n")
    if t.feedback:
        return head + env + f"## Note from the planner\n{t.feedback.strip()}\n\nImplement the ticket, then call `report_ticket`.\n"
    return (head + env + "Implement the ticket. If the verification section names a test to add or extend, "
            "that test is part of the work. Verify, commit on your branch, then call `report_ticket`.\n")


def reviewer_task(project: Project, t: Ticket, commit: str, diff: str, files: list[str],
                  log: str, test_output: str | None) -> str:
    diff = diff if len(diff) < 60000 else diff[:60000] + "\n... (diff truncated; open files in the worktree for the rest)\n"
    tests = f"## Unit test output (already run by Orchestra)\n```\n{test_output.strip()[-4000:]}\n```\n" if test_output else \
        "## Unit tests\nNo unit test command is configured.\n"
    return (f"# Review request\n\n{_ticket_block(t)}\n"
            f"## Commit under review\n{commit}\n\n## Commits on the branch\n```\n{log.strip()}\n```\n\n"
            f"## Changed files\n```\n" + "\n".join(files) + "\n```\n\n"
            f"{tests}\n## Diff against `{project.config.base_branch}`\n```diff\n{diff}\n```\n\n"
            "Review it like a pull request. Check that the verification named in the ticket was actually "
            "added or extended. Then call `report_review` exactly once.\n")


def wake_task(target: str, reasons: list[str], snapshot: dict) -> str:
    counts = ", ".join(f"{k}={v}" for k, v in snapshot["counts"].items() if v)
    lines = [f"# Wake-up for the {target.replace('_', ' ')}", "", "## Why you were woken"]
    lines += [f"- {r}" for r in reasons]
    lines += ["", "## Project snapshot", f"Ticket counts: {counts or 'none'}",
              f"Pipeline: {'PAUSED: ' + str(snapshot['pipeline'].get('reason')) if snapshot['pipeline'].get('paused') else 'running'}",
              "", "Milestones:"]
    for m in snapshot["milestones"]:
        lines.append(f"- {m['id']} [{m['status']}] {m['name']}")
    lines += ["", "Tickets (id, state, priority, milestone, title):"]
    for t in snapshot["tickets"]:
        if t["state"] in (State.DONE.value, State.CANCELLED.value):
            continue
        extra = f" BLOCKED: {t['blocked_reason']}" if t["state"] == "BLOCKED" else ""
        extra += f" (review rounds: {t['review_rounds']})" if t["review_rounds"] else ""
        obj = f" | objective: {t['objective'][:80]}" if t.get("objective") else ""
        lines.append(f"- {t['id']} {t['state']} p{t['priority']} {t['milestone_id']} {t['title']}{extra}{obj}")
    lines += ["", "Use your tools to act, then reply with a two-to-five line summary of what you did and why."]
    return "\n".join(lines)


def supervisor_context(snapshot: dict, events: list[dict], project: Project | None = None) -> str:
    out = ""
    if project is not None:
        out += "[Orchestra: project context]\n" + read_context(project).strip() + "\n\n"
    if not events:
        return out
    lines = ["[Orchestra: events since your last turn]"]
    for e in events[-40:]:
        parts = [e["type"]]
        for k in ("ticket", "milestone", "from", "to", "reason", "by", "summary"):
            if k in e and e[k]:
                parts.append(f"{k}={e[k]}")
        lines.append("- " + " ".join(str(p) for p in parts))
    counts = ", ".join(f"{k}={v}" for k, v in snapshot["counts"].items() if v)
    lines.append(f"[Orchestra: ticket counts now: {counts or 'none'}]")
    return out + "\n".join(lines) + "\n\n"
