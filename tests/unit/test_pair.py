"""The pair sees the external view only, reads deltas, and only the pair may use its tools."""

import json
import subprocess

import pytest

from orchestra import api
from orchestra.config import init_project
from orchestra.harness.pi import PiHarness
from orchestra.pair import external_view, paired
from orchestra.store import LocalStore, StoreError


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return init_project(repo, provider="p", model="m", prefix="T")


def test_alternate_pairs_even_tickets():
    assert paired("all", "T-1") and paired("all", "T-2")
    assert not paired("off", "T-2")
    assert paired("alternate", "T-2") and paired("alternate", "T-10") and not paired("alternate", "T-3")


def test_external_view_has_no_thinking_and_pages_by_cursor(tmp_path):
    f = tmp_path / "s.jsonl"
    msg = lambda role, content: json.dumps({"type": "message", "timestamp": "2026-10-14T00:00:00Z", "message": {"role": role, "content": content}})
    f.write_text("\n".join([
        msg("user", [{"type": "text", "text": "do the thing"}]),
        msg("assistant", [{"type": "thinking", "thinking": "SECRET PLAN"}, {"type": "text", "text": "I will edit app.py"},
                           {"type": "toolCall", "name": "bash", "arguments": {"command": "x" * 1000}}]),
        msg("toolResult", [{"type": "text", "text": "y" * 2000}]),
        msg("assistant", [{"type": "text", "text": "done"}]),
    ]) + "\n")
    msgs = PiHarness.read_transcript(f)
    v = external_view(msgs, 0, 2)
    assert "SECRET" not in json.dumps(v) and v["messages"][1]["text"] == "I will edit app.py"
    assert len(v["messages"][1]["tool_calls"][0]["args"]) <= 300 and v["has_more"] and v["next_after"] == 2
    v2 = external_view(msgs, v["next_after"], 40)
    assert [m["role"] for m in v2["messages"]] == ["tool_result", "assistant"] and len(v2["messages"][0]["text"]) == 800
    assert not v2["has_more"] and v2["next_after"] == 4


def test_only_the_ticket_pair_may_use_the_pair_tools(project):
    store = LocalStore(project)
    m = store.create_milestone(name="m")
    t = store.create_ticket(title="x", milestone_id=m.id)
    for role in ("worker", "reviewer", "supervisor"):
        with pytest.raises(StoreError):
            api.handle(project, store, "pair_note", {"text": "hi"}, role=role, ticket_env=t.id)
    with pytest.raises(StoreError, match="only its own worker"):
        api.handle(project, store, "read_transcript", {"session_id": "worker-T-99"}, role="pair", ticket_env=t.id)
    with pytest.raises(StoreError, match="block requires findings"):
        api.handle(project, store, "pair_verdict", {"verdict": "block"}, role="pair", ticket_env=t.id)
    api.handle(project, store, "pair_note", {"text": "app.py:12 flag parsed but never used"}, role="pair", ticket_env=t.id)
    assert [n["kind"] for n in store.notes(t.id)] == ["pair"]
    api.handle(project, store, "pair_verdict", {"verdict": "block", "findings": "unwired"}, role="pair", ticket_env=t.id)
    rep = store.pop_report(f"{t.id}:pair")
    assert (rep["kind"], rep["verdict"], rep["findings"]) == ("pair", "block", "unwired")
    assert store.pop_report(t.id) is None                                                   # not the worker's report
