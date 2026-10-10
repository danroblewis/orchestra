"""The Worker <-> Orchestra ticket-hygiene contract.

Every Worker agent must finish its turn by emitting a structured JSON document that
Orchestra parses and applies to the task in the storage layer. This enforces
"don't claim a ticket is done unless it was actually verified": a ``DONE`` state is
only accepted when the Reviewer passed **and** CI passed. Anything less is coerced to
``FAILED``/``BLOCKED`` so Orchestra never advances a ticket on an unverified claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Accepted ticket states (mirrors shared.models.Status).
STATES = ("DONE", "IN_PROGRESS", "BLOCKED", "FAILED")


@dataclass
class TicketResponse:
    """A validated Worker response. ``valid`` is False on any parse/validation error."""

    task_id: str = ""
    state: str = "IN_PROGRESS"
    summary: str = ""
    blockers: list[str] = field(default_factory=list)
    branch: str = ""
    review: dict[str, Any] = field(default_factory=dict)
    ci: dict[str, Any] = field(default_factory=dict)
    valid: bool = True
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state,
            "summary": self.summary,
            "blockers": self.blockers,
            "branch": self.branch,
            "review": self.review,
            "ci": self.ci,
            "valid": self.valid,
        }


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #

# Matches a JSON object anywhere in a text blob (best effort; json.loads is tried
# first). Lets us recover from LLMs that wrap the object in prose/markdown fences.
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> Any:
    """Pull the first JSON value out of an assistant message."""
    if text is None:
        return None
    s = text.strip()

    # 1) whole string is JSON
    try:
        return _json.loads(s)
    except Exception:
        pass

    # 2) fenced code block
    m = _JSON_FENCE.search(s)
    if m:
        try:
            return _json.loads(m.group(1))
        except Exception:
            pass

    # 3) first balanced object
    m = _JSON_OBJECT.search(s)
    if m:
        try:
            return _json.loads(m.group(0))
        except Exception:
            pass

    return None


import json as _json  # noqa: E402  (kept near the extractor it needs)


def parse_ticket_response(text: str | None) -> TicketResponse:
    """Parse + validate a Worker's JSON ticket response.

    Never raises: on any failure a :class:`TicketResponse` with ``valid=False`` and a
    human-readable ``error`` is returned so the orchestrator can mark the ticket
    BLOCKED/FAILED instead of crashing.
    """
    raw = extract_json(text)
    if not isinstance(raw, dict):
        return TicketResponse(
            valid=False, error="No JSON ticket document found in the Worker output."
        )

    task_id = str(raw.get("task_id", "")).strip()
    if not task_id:
        return TicketResponse(valid=False, error="Missing required field 'task_id'.")

    state = str(raw.get("state", "IN_PROGRESS")).strip().upper()
    if state not in STATES:
        return TicketResponse(
            task_id=task_id,
            valid=False,
            error=f"Invalid state {state!r}; expected one of {STATES}.",
        )

    blockers = raw.get("blockers") or []
    if not isinstance(blockers, list) or not all(isinstance(b, str) for b in blockers):
        return TicketResponse(
            task_id=task_id,
            valid=False,
            error="'blockers' must be a list of strings.",
        )

    review = raw.get("review") or {}
    if not isinstance(review, dict):
        return TicketResponse(
            task_id=task_id,
            valid=False,
            error="'review' must be an object.",
        )
    ci = raw.get("ci") or {}
    if not isinstance(ci, dict):
        return TicketResponse(
            task_id=task_id,
            valid=False,
            error="'ci' must be an object.",
        )

    resp = TicketResponse(
        task_id=task_id,
        state=state,
        summary=str(raw.get("summary", "")),
        blockers=blockers,
        branch=str(raw.get("branch", "")),
        review=review,
        ci=ci,
        valid=True,
    )
    # Enforce the core invariant: DONE requires review + CI to have passed.
    if state == "DONE":
        if not review.get("passed"):
            resp.state = "FAILED"
            resp.error = "Claimed DONE but review.passed was not true."
        elif ci.get("status") not in (None, "passed"):
            resp.state = "FAILED"
            resp.error = "Claimed DONE but ci.status was not 'passed'."
    return resp


# --------------------------------------------------------------------------- #
# Prompt scaffolding
# --------------------------------------------------------------------------- #

WORKER_PROMPT_TEMPLATE = """You are the **Worker** for task ``{task_id}`` in the Orchestra system.

## Your task
{summary}

## Context
- Title: {title}
- Dependencies: {deps}
- Acceptance criteria: {acceptance}

## Your environment
You are working inside a **git worktree** on branch ``{branch}``. Only this branch is in play.
Make the changes needed, commit them on this branch as you go.

## Rules
1. Read the repo's conventions (AGENTS.md / project config) before editing files.
2. You may *read* other tickets to understand the project, but only act on ``{task_id}``.
3. Before you say you are finished, **verify** your work: run the repo's tests and confirm
   the changes are committed on your branch. Do not claim completion without verification.
4. When finished, reply with **ONLY** a single JSON document (no prose) in this exact shape:

```json
{{
  "task_id": "{task_id}",
  "state": "DONE | IN_PROGRESS | BLOCKED | FAILED",
  "summary": "what you changed and why",
  "blockers": ["human-readable blocker, or empty list"],
  "branch": "{branch}",
  "review": {{"required": true, "passed": false, "reviewer": "reviewer"}},
  "ci": {{"status": "passed | failed | pending", "tests_run": 0}}
}}
```

A `DONE` state is only valid if your review passed and CI (tests) passed. If either is
not true, use `FAILED` or `BLOCKED` and explain why in `summary`/`blockers`."""


def worker_prompt(task: dict[str, Any], branch: str) -> str:
    """Render the tailored Worker prompt for a ticket."""
    return WORKER_PROMPT_TEMPLATE.format(
        task_id=task.get("id", ""),
        summary=task.get("description") or task.get("title", ""),
        title=task.get("title", ""),
        deps=", ".join(task.get("dependency_ids", []) or ["(none)"]) or "(none)",
        acceptance=task.get("acceptance") or "(see description)",
        branch=branch,
    )


def reviewer_prompt(task: dict[str, Any], diff: str) -> str:
    """Render the tailored Reviewer prompt for a completed worker turn."""
    return f"""You are the **Reviewer** for task ``{task.get('id', '')}`` in Orchestra.

## Task
{task.get('description') or task.get('title', '')}

## The proposed changes (diff)
{diff}

## Your job
1. Verify the changes actually address the task and its acceptance criteria.
2. Run the repo's test suite (via bash) and report the outcome.
3. Judge whether the work is correct and complete.

Reply with **only** a single JSON document (this is the ticket-hygiene schema):

```json
{{
  "task_id": "{task.get('id', '')}",
  "state": "DONE" | "BLOCKED",
  "summary": "short summary of your judgment",
  "branch": "",
  "blockers": [],
  "review": {{"passed": true | false, "verdict": "..."}},
  "ci": {{"status": "passed" | "failed", "output": "..."}}
}}
```

Set ``review.passed`` true only if the changes are correct AND the test suite passes.
Set ``state`` to ``DONE`` only when ``review.passed`` is true and ``ci.status`` is ``passed``; otherwise ``BLOCKED``.
"""
