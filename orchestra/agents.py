"""Spawn + poll Pi agent sessions for the orchestration loop.

These functions are the single place that constructs ``pi`` invocations. The
orchestrator never calls ``pi`` directly (per the design invariants: only the
programmatic automation spawns worker/reviewer processes), which keeps the
prompt-layering and session-lifecycle rules in one auditable spot.

A **worker** is a persistent ``pi --mode rpc`` session bound to a worktree.
A **reviewer** is a second ``pi`` session that checks the finished work by
applying the diff and (where the repo supports it) running the test suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.orchestrator import Transport  # noqa: F401 (interface)

from orchestra.gitops import Git  # noqa: E402
from orchestra.ticket_contract import TicketResponse, parse_ticket_response, reviewer_prompt, worker_prompt  # noqa: E402


@dataclass
class WorkerResult:
    task_id: str
    session_file: str
    raw_text: str
    response: TicketResponse
    success: bool = False  # True iff review passed AND ticket state == DONE


@dataclass
class ReviewResult:
    task_id: str
    session_file: str
    response: TicketResponse
    passed: bool = False


@dataclass
class DiffInfo:
    diff: str
    tests: str | None = None


class AgentError(Exception):
    """Raised when spawning or driving a Pi session fails."""


def _repo_config_prompt(project) -> str:
    """A short project-context preamble injected into every agent's system prompt."""
    lines = [
        f"You are operating inside an Orchestra-managed repository at {getattr(project, 'repo_root', '')}.",
        f"Base branch for merges: {getattr(project, 'base_branch', 'main')}",
    ]
    if getattr(project, "labels", None):
        lines.append(f"Tickets Orchestra manages carry these labels: {', '.join(project.labels)}")
    return "\n".join(lines)


def spawn_worker(
    orch,
    task: dict,
    branch: str,
    worktree_path: str,
    session_file: str,
    project=None,
) -> str:
    """Start a worker ``pi`` session bound to the worktree and return its prompt.

    Drives the session through ``Orchestrator.drive`` so the session log is
    created/persisted (the web viewer can render it) exactly as the Supervisor /
    Coordinator layers are.
    """
    prompt = worker_prompt(task, branch)
    system_prompt = "You are the Orchestra **Worker** layer.\n" + (
        _repo_config_prompt(project) if project else ""
    )
    # ``drive`` layers the system prompt via the transport (``--append-system-prompt``),
    # waits for ``agent_settled``, and persists the session log. We do NOT call
    # ``settle`` again (the agent is idle and would hang).
    # Derive the session slug from the dict (``to_dict`` exposes ``slug`` when set,
    # otherwise fall back to the id) so it matches the worktree branch slug the
    # driver recorded.
    slug = task.get("slug") or task.get("title")
    if slug:
        base = "".join(c if (c.isalnum() or c == " ") else " " for c in slug).strip()
        session_slug = "-".join(base.lower().split())
    else:
        session_slug = task.get("id", "worker")
    orch.orch.drive(f"worker-{session_slug}", "worker", prompt, system_prompt=system_prompt)
    return prompt


def collect_worker(orch, session_file: str) -> str:
    """Read the assistant's final text from a completed worker session."""
    return orch.orch.transport.read_last_assistant_text(session_file)


def build_diff(git: Git, branch: str, base: str) -> DiffInfo:
    """Return the diff of a worktree branch against its merge base, plus test output.

    The reviewer's "automated review pass = running unit tests" runs the repo's
    test command when present; otherwise it reports that no suite was detected.
    """
    diff = git._run("diff", f"{base}...{branch}").stdout
    tests = _run_repo_tests(git.repo_root)
    return DiffInfo(diff=diff, tests=tests)


def _run_repo_tests(repo_root: Path) -> str | None:
    """Best-effort run of the repo's unit test command. Returns output or None."""
    # Prefer a pytest target; fall back to `python -m pytest`.
    candidates = [
        ["python3", "-m", "pytest", "-q"],
        ["python", "-m", "pytest", "-q"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(
                    cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=180
                )
                if out.returncode == 0:
                    return out.stdout.strip()[-2000:]
                return f"tests FAILED (exit {out.returncode})\n{out.stderr.strip()[-2000:] or out.stdout.strip()[-2000:]}"
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return f"test run error: {cmd}"
    return None


def spawn_reviewer(
    orch,
    task: dict,
    diff_info: DiffInfo,
    session_file: str,
) -> str:
    """Start a reviewer ``pi`` session that judges the diff and test output."""
    prompt = reviewer_prompt(task, diff_info.diff)
    system_prompt = "You are the Orchestra **Reviewer** layer.\n"
    slug = task.get("slug") or task.get("title")
    if slug:
        base = "".join(c if (c.isalnum() or c == " ") else " " for c in slug).strip()
        session_slug = "-".join(base.lower().split())
    else:
        session_slug = task.get("id", "reviewer")
    orch.orch.drive(
        f"reviewer-{session_slug}", "reviewer", prompt, system_prompt=system_prompt
    )
    return prompt


def collect_reviewer(orch, session_file: str) -> TicketResponse:
    """Parse the reviewer's JSON verdict."""
    text = orch.orch.transport.read_last_assistant_text(session_file)
    resp = parse_ticket_response(text)
    # Rewrite reviewer fields onto the ticket response: the reviewer decides pass.
    if resp.valid:
        resp.review = {
            "passed": bool(resp.review.get("passed", False)),
            "verdict": resp.review.get("verdict", ""),
        }
        resp.ci = resp.ci or {}
    return resp
