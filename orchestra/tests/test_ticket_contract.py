"""Tests for the Worker <-> Orchestra ticket-hygiene contract."""

from __future__ import annotations

from orchestra.ticket_contract import (
    parse_ticket_response,
    worker_prompt,
)


def test_parse_valid_done_with_review_and_ci():
    text = """Here is my response:
```json
{
  "task_id": "abc",
  "state": "DONE",
  "summary": "added login form",
  "blockers": [],
  "branch": "orchestra-login",
  "review": {"passed": true},
  "ci": {"status": "passed"}
}
```"""
    r = parse_ticket_response(text)
    assert r.valid
    assert r.task_id == "abc"
    assert r.state == "DONE"
    assert r.summary == "added login form"
    assert r.blockers == []


def test_done_without_review_is_coerced_to_failed():
    r = parse_ticket_response('{"task_id": "t", "state": "DONE", "review": {"passed": false}}')
    assert r.valid
    assert r.state == "FAILED"


def test_done_without_ci_passed_is_failed():
    r = parse_ticket_response(
        '{"task_id": "t", "state": "DONE", "review": {"passed": true}, "ci": {"status": "pending"}}'
    )
    assert r.state == "FAILED"


def test_valid_done_with_ci_passed():
    r = parse_ticket_response(
        '{"task_id": "t", "state": "DONE", "review": {"passed": true}, "ci": {"status": "passed"}}'
    )
    assert r.state == "DONE"


def test_blocked_state_preserved():
    r = parse_ticket_response(
        '{"task_id": "t", "state": "BLOCKED", "blockers": ["need API key"], "summary": "stuck"}'
    )
    assert r.valid
    assert r.state == "BLOCKED"
    assert r.blockers == ["need API key"]


def test_invalid_state_rejected():
    r = parse_ticket_response('{"task_id": "t", "state": "MAYBE"}')
    assert not r.valid
    assert "Invalid state" in r.error


def test_missing_task_id_rejected():
    r = parse_ticket_response('{"state": "DONE"}')
    assert not r.valid
    assert "task_id" in r.error.lower()


def test_no_json_rejected():
    r = parse_ticket_response("I did the thing, no json here")
    assert not r.valid
    assert "No JSON" in r.error


def test_in_progress_is_valid():
    r = parse_ticket_response('{"task_id": "t", "state": "IN_PROGRESS"}')
    assert r.valid
    assert r.state == "IN_PROGRESS"


def test_worker_prompt_contains_task_and_contract():
    task = {
        "id": "t1",
        "title": "Login form",
        "description": "render login",
        "dependency_ids": [],
        "acceptance": "form submits",
    }
    prompt = worker_prompt(task, "orchestra-login")
    assert "t1" in prompt
    assert "orchestra-login" in prompt
    assert '"state"' in prompt
    assert "verify" in prompt.lower()
