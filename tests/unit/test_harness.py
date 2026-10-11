"""The harness layer: normalized events, transcript parsing, the MCP server, and the
tool catalogue, for every harness Orchestra supports."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestra.config import init_project
from orchestra.harness import HARNESSES, SessionSpec, get_harness, read_transcript
from orchestra.harness.claude_code import ClaudeCodeHarness, ClaudeCodeSession, _Normalizer as ClaudeNormalizer, transcript_path
from orchestra.harness.pi import PiHarness, _Normalizer as PiNormalizer
from orchestra.harness.tools import TOOLS, tools_for
from orchestra.store import LocalStore


def test_registry():
    assert set(HARNESSES) == {"pi", "claude_code"}
    assert get_harness(None).name == "pi"
    assert get_harness("claude-code").name == "claude_code"
    with pytest.raises(ValueError):
        get_harness("codex")


def test_tools_are_grouped_and_schema_shaped():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))
    assert [t.name for t in tools_for(["report_ticket"])] == ["report_ticket"]
    assert {t.group for t in tools_for(["tickets", "escalate"])} == {"tickets", "escalate"}
    d = next(t for t in TOOLS if t.name == "create_ticket").to_dict()
    assert d["inputSchema"]["type"] == "object" and "milestone_id" in d["inputSchema"]["required"]
    assert d["inputSchema"]["additionalProperties"] is False
    # Pi's extension and other harnesses read the catalogue from the CLI.
    out = subprocess.run([sys.executable, "-m", "orchestra", "tools", "--json", "--groups", "report_review"],
                         capture_output=True, text=True, check=True).stdout
    assert [t["name"] for t in json.loads(out)] == ["report_review"]


def collect(normalizer_cls, events):
    seen = []
    n = normalizer_cls(lambda e: seen.append(e))
    for e in events:
        n(e)
    return seen


def test_pi_events_normalize():
    seen = collect(PiNormalizer, [
        {"type": "response", "command": "prompt", "success": True},
        {"type": "message_start", "message": {"role": "assistant"}},
        {"type": "message_update"},
        {"type": "tool_execution_start", "toolName": "bash", "args": {"command": "ls"}},
        {"type": "tool_execution_end", "toolName": "bash"},
        {"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}, {"type": "toolCall", "name": "report_ticket"}]}},
        {"type": "message_end", "message": {"role": "user", "content": "ignored"}},
    ])
    assert [e["type"] for e in seen] == ["turn_start", "assistant_start", "token", "tool_start", "tool_end", "assistant_end"]
    assert seen[3] == {"type": "tool_start", "name": "bash", "args": {"command": "ls"}}
    assert seen[-1] == {"type": "assistant_end", "text": "hi", "tool_calls": ["report_ticket"]}


def test_claude_events_normalize():
    seen = collect(ClaudeNormalizer, [
        {"type": "system", "subtype": "init", "session_id": "u"},
        {"type": "stream_event", "event": {"type": "message_start"}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {}}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__orchestra__project_status", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}},
        {"type": "rate_limit_event"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
        {"type": "result", "subtype": "success", "result": "done"},
    ])
    assert [e["type"] for e in seen] == ["turn_start", "assistant_start", "token", "tool_start", "assistant_end", "tool_end", "assistant_end"]
    assert seen[3]["name"] == "project_status"            # the MCP prefix is dropped
    assert seen[5] == {"type": "tool_end", "name": "project_status"}


def test_pi_transcript(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in [
        {"type": "session", "id": "x"},
        {"type": "message", "timestamp": 1.0, "message": {"role": "user", "content": "do it"}},
        {"type": "message", "timestamp": 2.0, "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}, {"type": "toolCall", "name": "bash", "arguments": "{\"command\": \"ls\"}"}]}},
        {"type": "message", "timestamp": 3.0, "message": {"role": "toolResult", "toolName": "bash", "isError": False, "content": [{"type": "text", "text": "a.py"}]}},
    ]))
    msgs = PiHarness.read_transcript(f)
    assert [m["role"] for m in msgs] == ["user", "assistant", "toolResult"]
    assert msgs[1]["tool_calls"] == [{"name": "bash", "args": {"command": "ls"}}]
    assert msgs[2]["tool_name"] == "bash" and msgs[2]["text"] == "a.py"
    assert read_transcript({"harness": "pi", "session_file": str(f)}) == msgs
    assert read_transcript({"session_file": str(f)}) == msgs     # pi is the default


def test_claude_transcript(tmp_path):
    f = tmp_path / "u.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in [
        {"type": "queue-operation"},
        {"type": "user", "timestamp": "2026-10-11T10:51:53.231Z", "message": {"role": "user", "content": "do it"}},
        {"type": "attachment"},
        {"type": "assistant", "timestamp": "2026-10-11T10:51:54.000Z", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "mcp__orchestra__create_milestone", "input": {"name": "M"}}]}},
        {"type": "user", "timestamp": "2026-10-11T10:51:55.000Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "{\"ok\": true}"}]}]}},
        {"type": "assistant", "timestamp": "2026-10-11T10:51:56.000Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "Created M1."}]}},
    ]))
    msgs = ClaudeCodeHarness.read_transcript(f)
    assert [m["role"] for m in msgs] == ["user", "assistant", "toolResult", "assistant"]
    assert msgs[1]["tool_calls"] == [{"name": "create_milestone", "args": {"name": "M"}}]
    assert msgs[2]["tool_name"] == "create_milestone" and msgs[2]["text"] == '{"ok": true}'
    assert msgs[0]["ts"].startswith("2026-10-11")
    assert read_transcript({"harness": "claude_code", "session_file": str(f)}) == msgs


def spec(tmp_path, **kw) -> SessionSpec:
    return SessionSpec(session_id=kw.get("session_id", "worker-T-1"), session_dir=tmp_path / "sessions", cwd=tmp_path / "wt",
                       system_prompt="be good", role="worker", tool_groups=("report_ticket",),
                       env={"ORCHESTRA_ROLE": "worker", "ORCHESTRA_REPO": str(tmp_path), "ORCHESTRA_TICKET": "T-1"},
                       log_path=tmp_path / "logs" / "x.log", model="haiku")


def test_claude_session_identity_and_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    (tmp_path / "wt").mkdir()
    s = ClaudeCodeSession(spec(tmp_path))
    s.open()
    assert s.uuid and s.session_file == str(transcript_path(tmp_path / "wt", s.uuid))
    args = s._args()
    assert args[:2] == [s.binary, "-p"] and "--session-id" in args and "--resume" not in args
    assert "--model" in args and args[args.index("--model") + 1] == "haiku"
    assert "--strict-mcp-config" in args and "--dangerously-skip-permissions" in args
    cfg = json.loads(Path(args[args.index("--mcp-config") + 1]).read_text())["mcpServers"]["orchestra"]
    assert cfg["command"] == sys.executable and cfg["env"]["ORCHESTRA_TOOLS"] == "report_ticket"
    # Same session id later: same uuid; once Claude has written the transcript, we resume it.
    again = ClaudeCodeSession(spec(tmp_path))
    again.open()
    assert again.uuid == s.uuid
    Path(again.session_file).parent.mkdir(parents=True)
    Path(again.session_file).write_text("{}\n")
    assert "--resume" in again._args() and "--session-id" not in again._args()
    assert again.pid is None and again.alive()
    again.close()
    assert not again.alive()


def test_claude_turn_without_binary_reports_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    (tmp_path / "wt").mkdir()
    s = ClaudeCodeSession(spec(tmp_path), binary=str(tmp_path / "no-such-claude"))
    res = s.prompt("hi", timeout=5)
    assert res.error and "cannot start" in res.error and not res.settled


class McpClient:
    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, "-m", "orchestra.harness.mcp"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=env, bufsize=1)
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    return init_project(repo, provider="p", model="m", prefix="T")


def test_mcp_server_serves_the_role_tools(project, tmp_path):
    import os
    base = {**os.environ, "ORCHESTRATOR_HOME": str(tmp_path / "home"), "ORCHESTRA_REPO": str(project.repo_root)}
    c = McpClient({**base, "ORCHESTRA_ROLE": "supervisor", "ORCHESTRA_TOOLS": "tickets,context"})
    try:
        init = c.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        assert init["result"]["serverInfo"]["name"] == "orchestra" and "tools" in init["result"]["capabilities"]
        names = {t["name"] for t in c.rpc("tools/list")["result"]["tools"]}
        assert "create_milestone" in names and "get_project_context" in names and "report_ticket" not in names
        r = c.rpc("tools/call", {"name": "create_milestone", "arguments": {"name": "Via MCP"}})["result"]
        assert not r.get("isError") and json.loads(r["content"][0]["text"])["milestone"]["id"] == "M1"
        r = c.rpc("tools/call", {"name": "report_ticket", "arguments": {}})["result"]   # not granted
        assert r["isError"]
        r = c.rpc("tools/call", {"name": "create_ticket", "arguments": {"title": "x", "milestone_id": "M9"}})["result"]
        assert r["isError"] and "M9" in r["content"][0]["text"]                           # store error surfaces as text
        assert "error" in c.rpc("nonsense")
    finally:
        c.close()
    assert LocalStore(project).get_milestone("M1").name == "Via MCP"
    # The worker's exit tool goes through the same server with the ticket from the env.
    store = LocalStore(project)
    from orchestra.model import State
    t = store.create_ticket(title="w", milestone_id="M1")
    store.transition(t.id, t.version, State.IN_PROGRESS)   # reports are only accepted from a live worker
    w = McpClient({**base, "ORCHESTRA_ROLE": "worker", "ORCHESTRA_TOOLS": "report_ticket", "ORCHESTRA_TICKET": t.id})
    try:
        w.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        assert [x["name"] for x in w.rpc("tools/list")["result"]["tools"]] == ["report_ticket"]
        r = w.rpc("tools/call", {"name": "report_ticket", "arguments": {"state": "READY_FOR_REVIEW", "summary": "done"}})["result"]
        assert not r.get("isError"), r
    finally:
        w.close()
    assert store.pop_report(t.id)["state"] == "READY_FOR_REVIEW"
