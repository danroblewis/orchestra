"""The harness interface: how Orchestra drives an agent session, whichever product runs it.

A *harness* is an agent runner (Pi, Claude Code, Codex, OpenCode). Orchestra needs four
things from one, and nothing else:

1. ``start(spec)`` opens a named, resumable session with a system prompt, a working
   directory, and a set of Orchestra tool groups.
2. ``session.prompt(text, timeout, on_event)`` runs one turn to completion and returns
   its final text; events arrive in the **normalized** vocabulary below so the loop and
   the UI never see harness-specific shapes.
3. ``session.session_file`` names the harness's own transcript, which is the only one
   Orchestra keeps (it never writes a parallel log); ``harness.read_transcript`` parses
   it into a common message list.
4. ``kill()`` / ``close()`` end a turn or the session.

Normalized events (dicts with ``type``):
  turn_start                 the prompt was accepted
  assistant_start            the model began a message
  token                      output is streaming (may be coalesced; used for liveness)
  tool_start {name, args}    a tool call began
  tool_end {name}            it finished
  assistant_end {text, tool_calls}   an assistant message completed
  settled {text}             the turn is over
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

OnEvent = Callable[[dict], None]


@dataclass
class TurnResult:
    text: str = ""
    settled: bool = False
    timed_out: bool = False
    error: str | None = None
    tool_calls: list[str] = field(default_factory=list)


@dataclass
class SessionSpec:
    """Everything a harness needs to open a session. ``env`` carries the ORCHESTRA_*
    variables the Orchestra tools read (repo, role, ticket, tool groups)."""

    session_id: str
    session_dir: Path          # Orchestra's per-project sessions directory
    cwd: Path
    system_prompt: str
    role: str
    tool_groups: tuple[str, ...]
    env: dict[str, str]
    log_path: Path             # harness stderr / diagnostics
    model: str | None = None
    provider: str | None = None
    thinking: str | None = None
    ticket_id: str = ""


class AgentSession(ABC):
    """One named session. Thread-safe for one prompt at a time."""

    spec: SessionSpec
    session_file: str | None = None   # the harness's transcript, once known

    @property
    def session_id(self) -> str:
        return self.spec.session_id

    @property
    def harness_name(self) -> str:
        return "unknown"

    @abstractmethod
    def open(self) -> None:
        """Make the session exist and learn ``session_file``. Idempotent."""

    @abstractmethod
    def prompt(self, text: str, timeout: float, on_event: OnEvent | None = None) -> TurnResult: ...

    @property
    @abstractmethod
    def pid(self) -> int | None:
        """A live OS process that proves this session is alive right now, or None."""

    @abstractmethod
    def alive(self) -> bool: ...

    @abstractmethod
    def kill(self) -> None:
        """Stop the running turn immediately (the operator's stop button)."""

    @abstractmethod
    def close(self) -> None:
        """Release the session's resources. The transcript stays; the session is resumable."""


class Harness(ABC):
    name: str = "unknown"

    @abstractmethod
    def start(self, spec: SessionSpec) -> AgentSession: ...

    @staticmethod
    @abstractmethod
    def read_transcript(session_file: str | Path) -> list[dict]:
        """Parse the harness's transcript into [{role, text, tool_calls, ts, ...}] where role
        is user | assistant | toolResult. ``ts`` is an ISO-8601 string or epoch seconds."""


def assistant_text(content) -> str:
    """Text of an assistant message whose content is a string or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""
