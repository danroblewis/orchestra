"""The `orchestra` command line. SPEC.md section 10."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, agents, api
from .config import ConfigError, Project, init_project, load_project
from .events import Events
from .model import STATE_ORDER, State
from .store import LocalStore, StoreError


def _project(args) -> Project:
    try:
        return load_project(getattr(args, "repo", None))
    except ConfigError as e:
        sys.exit(f"orchestra: {e}")


def _store(project: Project) -> tuple[LocalStore, Events]:
    events = Events(project.events_file)
    return LocalStore(project, events), events


# -- commands --------------------------------------------------------------------

def cmd_init(args) -> int:
    p = init_project(Path(args.repo or os.getcwd()), provider=args.provider, model=args.model,
                     prefix=args.prefix, unit_command=args.unit_command)
    print(f"initialized {p.key}\n  repo:   {p.repo_root}\n  state:  {p.state_dir}\n  config: {p.repo_root / 'orchestra.toml'}")
    return 0


def cmd_run(args) -> int:
    from .loop import Loop

    project = _project(args)
    store, events = _store(project)
    Loop(project, store, events).run(once=args.once)
    return 0


def cmd_web(args) -> int:
    import uvicorn

    from .web.app import create_app

    project = _project(args)
    uvicorn.run(create_app(project), host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_status(args) -> int:
    project = _project(args)
    store, _ = _store(project)
    snap = store.snapshot()
    print(f"{snap['project']['key']}  base={snap['project']['base_branch']}  model={snap['project']['model']}")
    print("pipeline:", "PAUSED " + str(snap["pipeline"].get("reason")) if snap["pipeline"].get("paused") else "running")
    print("tickets:", "  ".join(f"{s.value}={snap['counts'][s.value]}" for s in STATE_ORDER if snap["counts"][s.value]) or "none")
    running = [s for s in snap["sessions"] if s.get("status") == "running"]
    print("sessions running:", ", ".join(s["id"] for s in running) or "none")
    return 0


def cmd_ticket(args) -> int:
    project = _project(args)
    store, _ = _store(project)
    if args.action == "list":
        for t in store.list_tickets():
            print(f"{t.id:10} {t.state.value:17} p{t.priority} {t.milestone_id:4} {t.title}")
        return 0
    t = store.get_ticket(args.id)
    print(json.dumps({**t.to_dict(), "notes": store.notes(t.id)}, indent=2))
    return 0


def cmd_milestone(args) -> int:
    project = _project(args)
    store, _ = _store(project)
    if args.action == "list":
        for m in store.list_milestones():
            n = len(store.list_tickets(milestone_id=m.id))
            print(f"{m.id:5} {m.status.value:7} {n:3} tickets  {m.name}")
        return 0
    print(json.dumps(store.get_milestone(args.id).to_dict(), indent=2))
    return 0


def cmd_sessions(args) -> int:
    from .pi.client import read_transcript

    project = _project(args)
    store, _ = _store(project)
    if args.action == "list":
        for s in store.sessions():
            print(f"{s['id']:28} {s.get('status', '?'):8} {s.get('ticket_id') or '':10} {(s.get('last_text') or '')[:60]!r}")
        return 0
    s = next((s for s in store.sessions() if s["id"] == args.id), None)
    if not s or not s.get("pi_session_file"):
        sys.exit(f"no transcript for {args.id}")
    for m in read_transcript(s["pi_session_file"]):
        tools = " ".join(f"[{t['name']}]" for t in m["tool_calls"])
        print(f"--- {m['role']} {tools}\n{m['text'][:3000]}\n")
    return 0


def cmd_api(args) -> int:
    project = _project(args)
    store, _ = _store(project)
    try:
        payload = json.loads(args.args) if args.args else {}
        out = api.handle(project, store, args.command, payload,
                         role=os.environ.get("ORCHESTRA_ROLE", ""), ticket_env=os.environ.get("ORCHESTRA_TICKET", ""))
    except (StoreError, KeyError, ValueError) as e:
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1
    print(json.dumps(out, indent=None if args.compact else 1))
    return 0


def cmd_chat(args) -> int:
    from .pi import PiProcess

    project = _project(args)
    store, events = _store(project)
    cfg = project.config
    sid = "supervisor"
    proc = PiProcess(session_id=sid, session_dir=project.sessions_dir, cwd=project.repo_root,
                     system_prompt=agents.role_prompt(project, "supervisor"),
                     provider=cfg.provider, model=cfg.model, thinking=cfg.thinking,
                     env={"ORCHESTRA_ROLE": "supervisor", "ORCHESTRA_REPO": str(project.repo_root)},
                     log_path=project.logs_dir / "pi" / "supervisor.stderr.log")
    try:
        proc.get_state()
    except Exception:
        pass
    store.set_session(sid, kind="supervisor", status="idle", pi_session_file=proc.session_file)
    _, offset = events.read(0, limit=1)
    print(f"Supervisor for {project.key} ({cfg.provider}/{cfg.model}). Ctrl-D or 'exit' to leave.\n")

    def on_event(ev: dict) -> None:
        t = ev.get("type")
        if t == "tool_execution_start":
            print(f"  ⚙ {ev.get('toolName') or ev.get('name', 'tool')} {json.dumps(ev.get('args', ev.get('arguments', {})))[:160]}", flush=True)
        elif t == "message_end" and ev.get("message", {}).get("role") == "assistant":
            content = ev["message"].get("content")
            if isinstance(content, list):
                txt = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                if txt.strip():
                    print(f"\n{txt.strip()}\n", flush=True)

    try:
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                break
            if line in ("exit", "quit"):
                break
            if not line:
                continue
            new, offset = events.read(offset)
            new = [e for e in new if e["type"] not in ("session_started", "session_settled")]
            prefix = agents.supervisor_context(store.snapshot(), new)
            store.set_session(sid, status="running", started_at=time.time())
            events.emit("session_started", session=sid, kind="supervisor")
            res = proc.prompt(prefix + line, cfg.turn_timeout, on_event=on_event)
            store.set_session(sid, status="idle", last_text=(res.text or "")[-500:], settled_at=time.time())
            events.emit("session_settled", session=sid)
            if res.error or res.timed_out:
                print(f"[orchestra] turn ended: {res.error or 'timed out'}")
    finally:
        proc.close()
        store.set_session(sid, status="idle")
    return 0


def cmd_doctor(args) -> int:
    from .git import Git

    project = _project(args)
    store, _ = _store(project)
    git = Git(project.repo_root)
    known = {w["path"] for w in store.runtime()["worktrees"].values()}
    problems = 0
    for p in project.worktrees_dir.glob("*"):
        if str(p) not in known:
            problems += 1
            print(f"orphan worktree: {p}")
            if args.fix:
                git.worktree_remove(p)
    if not project.config.unit:
        print("warning: no [[gate.unit]] specs; the gate and reviews run no tests")
    if not project.config.build_command or not project.config.acceptance:
        print("warning: no [build]/[[gate.acceptance]]; the gate cannot prove the built artifact works")
    print("ok" if not problems else f"{problems} problem(s)")
    return 0


# -- parser ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestra", description="Orchestra: tickets, planning, and CI/CD run by Pi agents")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--repo", help="repository root (default: ORCHESTRA_REPO or cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="register this repository and write orchestra.toml")
    s.add_argument("--provider", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--prefix", help="ticket id prefix, e.g. ORC")
    s.add_argument("--unit-command", default="uv run pytest -q")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="run the orchestration loop")
    s.add_argument("--once", action="store_true", help="one tick, wait for its work, exit")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("chat", help="talk to the Supervisor")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("web", help="serve the web UI")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_web)

    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("ticket")
    s.add_argument("action", choices=["list", "show"])
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_ticket)

    s = sub.add_parser("milestone")
    s.add_argument("action", choices=["list", "show"])
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_milestone)

    s = sub.add_parser("sessions")
    s.add_argument("action", choices=["list", "show"])
    s.add_argument("id", nargs="?")
    s.set_defaults(fn=cmd_sessions)

    s = sub.add_parser("api", help="machine interface used by the Pi extension")
    s.add_argument("command")
    s.add_argument("--args", default="{}", help="JSON object of arguments")
    s.add_argument("--compact", action="store_true")
    s.set_defaults(fn=cmd_api)

    s = sub.add_parser("doctor")
    s.add_argument("--fix", action="store_true")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
