"""The pair: a second agent that watches one ticket's worker from the outside.

Pair programming with two agents. The worker drives: it edits, runs, commits. The pair
watches: it reads the worker's transcript as it grows (the external view only, tool calls
and results and messages, never the worker's thinking), keeps its own detached worktree in
sync with the branch, runs the tests there, and writes findings as ticket notes. When the
worker reports READY_FOR_REVIEW the pair gets a final turn and gives a verdict: `pass`
sends the ticket to review with the pair's notes attached; `block` sends it back to the
worker with the findings before any reviewer spends a turn. The pair never writes code.

Which tickets are paired is the project's choice (`[agents] pair`): `off`, `all`, or
`alternate`, where even-numbered tickets are paired and odd ones are the control group."""

from __future__ import annotations

import threading
import time

from . import agents
from .model import Note, now

POLL_SECONDS = 15
SYNC_EVERY = 60


def paired(mode: str, ticket_id: str) -> bool:
    if mode == "all":
        return True
    if mode == "alternate":
        try:
            return int(ticket_id.rsplit("-", 1)[-1]) % 2 == 0
        except ValueError:
            return False
    return False


def pair_notes(store, ticket_id: str) -> list[str]:
    return [n["text"] for n in store.notes(ticket_id) if n.get("kind") == "pair"]


class PairWatcher:
    """Owns the pair session for one ticket for the life of the worker's turn."""

    def __init__(self, loop, ticket, branch: str):
        self.loop, self.store, self.git = loop, loop.store, loop.git
        self.tid, self.branch = ticket.id, branch
        self.sid = f"pair-{ticket.id}"
        self.path = loop.project.worktrees_dir / f"{ticket.id}-pair"
        self.proc = None
        self.after = 0
        self.head = None
        self._stop = threading.Event()
        self._turn = threading.Lock()
        self.thread: threading.Thread | None = None
        self.turns = 0

    # -- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        head = self.git.rev_parse(self.branch)
        self.git.worktree_remove(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.git.run("worktree", "add", "--detach", str(self.path), head)
        self.head = head
        self.proc = self.loop._session(self.sid, "pair", self.path, self.tid)
        self.store.set_session(self.sid, kind="pair", status="idle", ticket_id=self.tid, pid=None,
                               session_file=self.proc.session_file, harness=self.proc.harness_name)
        self.thread = threading.Thread(target=self._watch, daemon=True, name=self.sid)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    def close(self) -> None:
        self.stop()
        if self.proc is not None:
            self.proc.close()
        self.git.worktree_remove(self.path)

    # -- the watch loop -------------------------------------------------------------

    def _watch(self) -> None:
        last_sync = time.time()
        while not self._stop.wait(POLL_SECONDS):
            if time.time() - last_sync < SYNC_EVERY:
                continue
            last_sync = time.time()
            try:
                head = self.git.rev_parse(self.branch)
            except Exception:
                continue
            if head == self.head:
                continue
            self._sync(head)
            self._prompt(agents.pair_delta_task(self.loop.project, self.tid, self.sid, head, self.after))

    def _sync(self, head: str) -> None:
        self.git.run("checkout", "--detach", "--force", head, cwd=self.path, check=False)
        self.head = head

    def _prompt(self, task: str) -> str:
        """One pair turn. Serialised, so the final verdict turn waits for a delta turn."""
        with self._turn:
            self.turns += 1
            self.loop._session_running(self.sid, "pair", self.proc, self.tid)
            text = ""
            try:
                res = self.proc.prompt(task, self.loop.cfg.turn_timeout or None, on_event=self.loop._on_event(self.sid),
                                       idle_timeout=self.loop.cfg.silence_timeout)
                self.loop._note_turn(self.sid, res, "pair")
                text = res.text or ""
            finally:
                self.loop._session_idle(self.sid, text)
            cursor = self.store.pair_cursor(self.tid)
            if cursor is not None:
                self.after = cursor
            return text

    # -- the verdict ----------------------------------------------------------------

    def final(self, head: str) -> dict | None:
        """The worker has reported READY_FOR_REVIEW: sync, give the pair its last word, and
        return its verdict report, or None if it gave none."""
        self.stop()
        if head != self.head:
            self._sync(head)
        self.store.pop_report(f"{self.tid}:pair")
        self._prompt(agents.pair_verdict_task(self.loop.project, self.tid, self.sid, head, self.after))
        report = self.store.pop_report(f"{self.tid}:pair")
        if report is None:
            self.store.add_note(self.tid, Note(author="orchestra", kind="note",
                                               text="the pair gave no verdict; the ticket goes to review as if it had passed"))
        return report


def external_view(messages: list[dict], after: int, limit: int) -> dict:
    """The part of a transcript a colleague could see: what was said and done, never the
    thinking. Tool arguments and results are cut short; `after` is the index to resume from."""
    out = []
    for i, m in enumerate(messages[after:], start=after):
        if m["role"] == "toolResult":
            out.append({"i": i, "role": "tool_result", "tool": m.get("tool_name"), "error": bool(m.get("is_error")),
                        "text": (m.get("text") or "")[:800]})
        else:
            out.append({"i": i, "role": m["role"], "text": (m.get("text") or "")[:3000],
                        "tool_calls": [{"name": tc.get("name"), "args": str(tc.get("args"))[:300]} for tc in m.get("tool_calls", [])]})
        if len(out) >= limit:
            break
    next_after = out[-1]["i"] + 1 if out else after
    return {"messages": out, "after": after, "next_after": next_after, "total": len(messages), "has_more": next_after < len(messages),
            "read_at": now()}
