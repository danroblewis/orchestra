"""Tests for the RPC transport's line-protocol loop (no live ``pi`` needed).

These tests exercise the real :class:`~orchestra.rpc_transport._PiSession` event
loop: subscribe -> prompt -> await ``agent_settled`` -> read
``get_last_assistant_text``. They feed scripted stdout line-by-line to mimic what
``pi --mode rpc`` writes, so no model or subprocess is required.
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestra.rpc_transport import _PiSession, RpcError, _read_log_assistant_text


class _FakeProc:
    returncode = 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class _ScriptedStdout:
    def __init__(self, lines):
        self.lines = list(lines)

    def readline(self):
        if self.lines:
            return self.lines.pop(0) + "\n"
        return ""


class _NoopStdin:
    def write(self, _s):
        pass

    def flush(self):
        pass

    def close(self):
        pass


def _make_session(lines):
    proc = _FakeProc()
    proc.stdout = _ScriptedStdout(lines)
    proc.stdin = _NoopStdin()
    return _PiSession("session-file", proc, 5)


def _prompt_accepted_response(req_id="req-1"):
    return json.dumps(
        {"id": req_id, "type": "response", "command": "prompt", "success": True}
    )


def _assistant_text(text):
    return json.dumps(
        {"id": "txt", "type": "response", "command": "get_last_assistant_text", "success": True, "data": {"text": text}}
    )


def test_run_prompt_settles_and_reads_assistant_text():
    # subscribe has no response; then prompt accepted, then settle, then text.
    lines = [
        _prompt_accepted_response(),
        json.dumps({"type": "agent_start"}),
        json.dumps({"type": "agent_settled"}),
        _assistant_text("worker response"),
    ]
    sess = _make_session(lines)
    result = sess.run_prompt("do the task")
    assert result["settled"]["type"] == "agent_settled"
    assert result["text"] == "worker response"


def test_run_prompt_raises_on_rejection():
    lines = [
        json.dumps({"id": "req-1", "type": "response", "command": "prompt", "success": False, "error": "bad prompt"}),
    ]
    sess = _make_session(lines)
    try:
        sess.run_prompt("bad")
        assert False, "expected RpcError"
    except RpcError as e:
        assert "rejected" in str(e)


def test_run_prompt_raises_when_never_settled():
    # prompt accepted but never settles -> timeout error.
    lines = [_prompt_accepted_response(), json.dumps({"type": "agent_start"})]
    sess = _make_session(lines)
    try:
        sess.run_prompt("hang")
        assert False, "expected RpcError"
    except RpcError as e:
        assert "did not settle" in str(e)


def test_get_last_assistant_text_only():
    sess = _make_session([_assistant_text("just text")])
    assert sess.get_last_assistant_text() == "just text"


def test_get_last_assistant_text_empty_on_failure():
    sess = _make_session(
        [json.dumps({"id": "txt", "type": "response", "command": "get_last_assistant_text", "success": False})]
    )
    assert sess.get_last_assistant_text() == ""


def test_read_log_assistant_text_raw_format(tmp_path: Path) -> None:
    """The JSONL log is the durable source of the agent's final text."""
    log = tmp_path / "s.jsonl"
    entries = [
        {"type": "session", "version": 3},
        {
            "type": "message",
            "role": None,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "running tests..."}]},
        },
        {
            "type": "message",
            "role": None,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "```json\n{\n  \"state\": \"DONE\"\n}\n```"}]},
        },
        {"type": "agent_settled"},
    ]
    log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    text = _read_log_assistant_text(str(log))
    # The code-fence wrapper is stripped so downstream JSON parsing works.
    assert "\"state\": \"DONE\"" in text


def test_read_log_assistant_text_web_format(tmp_path: Path) -> None:
    """Also handles the simpler web ``text`` field format."""
    log = tmp_path / "web.jsonl"
    entries = [
        {"type": "message", "role": "assistant", "text": "hello"},
    ]
    log.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    assert _read_log_assistant_text(str(log)) == "hello"


def test_read_log_assistant_text_missing_file() -> None:
    assert _read_log_assistant_text("/no/such/file.jsonl") == ""
