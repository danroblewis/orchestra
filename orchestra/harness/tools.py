"""The tools an agent uses to talk to Orchestra, defined once as data.

Every harness exposes these to its model in its own way: the Pi extension registers them
as Pi tools, the MCP server (``orchestra.harness.mcp``) serves them to Claude Code and any
other MCP client. Which tools an agent gets is decided by tool *groups*, never per tool."""

from __future__ import annotations

from dataclasses import dataclass, field


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


# The catalogue is empty in an empty Orchestra: the old task system's ticket tools went with it.
# The Supervisor's tools (publish an event, read the model, query metrics) come back here, defined
# once, for every harness.
TOOLS: tuple[ToolDef, ...] = ()

BY_NAME = {t.name: t for t in TOOLS}


def tools_for(groups: list[str] | tuple[str, ...] | set[str]) -> list[ToolDef]:
    g = set(groups)
    return [t for t in TOOLS if t.group in g]
