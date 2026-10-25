"""A stdio MCP server exposing Orchestra's tools to a harness that speaks MCP (Claude Code,
Codex, OpenCode). Dependency-free: newline-delimited JSON-RPC 2.0 over stdin/stdout.

    ORCHESTRA_REPO=<repo> ORCHESTRA_ROLE=<role> ORCHESTRA_TOOLS=<groups> python -m orchestra.harness.mcp

The catalogue (``tools.py``) is empty in an empty Orchestra, so this serves no tools yet."""

from __future__ import annotations

import json
import os
import sys
import traceback

from .tools import BY_NAME, tools_for

PROTOCOL = "2024-11-05"
SERVER_NAME = "orchestra"


def _reply(req_id, result=None, error=None) -> None:
    msg: dict = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _tool_text(result) -> str:
    return result if isinstance(result, str) else json.dumps(result, indent=1, default=str)


class Server:
    def __init__(self) -> None:
        groups = [g for g in (os.environ.get("ORCHESTRA_TOOLS") or "").split(",") if g]
        self.tools = tools_for(groups)
        self.role = os.environ.get("ORCHESTRA_ROLE", "")

    def call(self, name: str, args: dict) -> dict:
        tool = BY_NAME.get(name)
        if tool is None or tool not in self.tools:
            return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": f"unknown tool {name}"})}], "isError": True}
        # no tool has a handler yet: the catalogue is empty in an empty Orchestra
        return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": f"{name} has no handler"})}], "isError": True}

    def handle(self, msg: dict) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            _reply(req_id, {"protocolVersion": params.get("protocolVersion") or PROTOCOL,
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": SERVER_NAME, "version": "1"}})
        elif method == "notifications/initialized" or (method or "").startswith("notifications/"):
            return
        elif method == "ping":
            _reply(req_id, {})
        elif method == "tools/list":
            _reply(req_id, {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                                      for t in self.tools]})
        elif method == "tools/call":
            _reply(req_id, self.call(params.get("name", ""), params.get("arguments") or {}))
        elif req_id is not None:
            _reply(req_id, error={"code": -32601, "message": f"method not found: {method}"})

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                self.handle(msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                if msg.get("id") is not None:
                    _reply(msg["id"], error={"code": -32603, "message": "internal error"})


def main() -> None:
    Server().serve()


if __name__ == "__main__":
    main()
