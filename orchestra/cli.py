"""The `orchestra` command line. SPEC.md section 10."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__, agents, api
from .agents.roles import ROLES
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
    events = Events.for_project(project)
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
    store, _ = _store(project)
    store._mutate_runtime(lambda d: d.__setitem__("web", {"port": args.port, "pid": os.getpid()}))
    try:
        uvicorn.run(create_app(project), host=args.host, port=args.port, log_level="warning")
    finally:
        store._mutate_runtime(lambda d: d.pop("web", None) if (d.get("web") or {}).get("pid") == os.getpid() else None)
    return 0


def cmd_status(args) -> int:
    from . import status as st

    project = _project(args)
    store, _ = _store(project)
    d = st.collect(project, store)
    print(json.dumps(d, indent=1) if args.json else st.render(d))
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
    from .harness import read_transcript

    project = _project(args)
    store, _ = _store(project)
    if args.action == "list":
        for s in store.sessions():
            print(f"{s['id']:28} {s.get('status', '?'):8} {s.get('ticket_id') or '':10} {(s.get('last_text') or '')[:60]!r}")
        return 0
    s = next((s for s in store.sessions() if s["id"] == args.id), None)
    if not s or not s.get("session_file"):
        sys.exit(f"no transcript for {args.id}")
    for m in read_transcript(s):
        tools = " ".join(f"[{t['name']}]" for t in m["tool_calls"])
        print(f"--- {m['role']} {tools}\n{m['text'][:3000]}\n")
    return 0


def cmd_tools(args) -> int:
    from .harness.tools import TOOLS, tools_for

    groups = args.groups or os.environ.get("ORCHESTRA_TOOLS")
    tools = tools_for([g for g in groups.split(",") if g]) if groups else list(TOOLS)
    if args.json:
        print(json.dumps([t.to_dict() for t in tools]))
        return 0
    for t in tools:
        print(f"{t.name:26} {t.group:14} {t.description[:80]}")
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


def _print_event(ev: dict) -> None:
    t = ev.get("type")
    if t == "tool_start":
        print(f"  ⚙ {ev.get('name', 'tool')} {json.dumps(ev.get('args') or {})[:160]}", flush=True)
    elif t == "assistant_end":
        content = ev.get("text") or ""
        if isinstance(content, list):
            txt = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            if txt.strip():
                print(f"\n{txt.strip()}\n", flush=True)


def _chat_attached(project: Project, store: LocalStore, port: int) -> int:
    import urllib.request

    print(f"Supervisor for {project.key} via orchestra run on 127.0.0.1:{port}. Ctrl-D or 'exit' to leave.\n")
    while True:
        try:
            line = input("you> ").strip()
        except EOFError:
            break
        if line in ("exit", "quit"):
            break
        if not line:
            continue
        req = urllib.request.Request(f"http://127.0.0.1:{port}/supervisor", method="POST",
                                     data=json.dumps({"message": line}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=(project.config.turn_timeout or 86400) + 30) as resp:
                for raw in resp:
                    ev = json.loads(raw)
                    if ev.get("type") == "done":
                        if ev.get("error") or ev.get("timed_out"):
                            print(f"[orchestra] turn ended: {ev.get('error') or 'timed out'}")
                    else:
                        _print_event(ev)
        except Exception as e:
            print(f"[orchestra] lost the loop: {e}. Is `orchestra run` still up?")
            return 1
    return 0


def cmd_chat(args) -> int:
    from .harness import SessionSpec, get_harness

    project = _project(args)
    store, events = _store(project)
    cfg = project.config
    ctl = store.runtime().get("control") or {}
    if ctl.get("port"):
        import urllib.request
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{ctl['port']}/health", timeout=3)
            return _chat_attached(project, store, int(ctl["port"]))
        except Exception:
            pass
    print("[orchestra] `orchestra run` is not running; starting a temporary supervisor session for this chat.")
    sid = "supervisor"
    role = ROLES["supervisor"]
    proc = get_harness(cfg.harness).start(SessionSpec(
        session_id=sid, session_dir=project.sessions_dir, cwd=project.repo_root,
        system_prompt=agents.role_prompt(project, "supervisor"), role="supervisor", tool_groups=tuple(role.tools),
        env={"ORCHESTRA_ROLE": "supervisor", "ORCHESTRA_REPO": str(project.repo_root), "ORCHESTRA_TICKET": ""},
        log_path=project.logs_dir / "agents" / "supervisor.stderr.log",
        model=cfg.model, provider=cfg.provider, thinking=cfg.thinking))
    try:
        proc.open()
    except Exception:
        pass
    store.set_session(sid, kind="supervisor", status="idle", pid=proc.pid or os.getpid(),
                      session_file=proc.session_file, harness=proc.harness_name)
    _, offset = events.read(0, limit=1)
    print(f"Supervisor for {project.key} ({cfg.harness}: {cfg.provider or ''}/{cfg.model or 'default'}). Ctrl-D or 'exit' to leave.\n")
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
            prefix = agents.supervisor_context(store.snapshot(), new, project, store)
            store.set_session(sid, status="running", started_at=time.time())
            events.emit("session_started", session=sid, kind="supervisor")
            res = proc.prompt(prefix + line, cfg.turn_timeout or None, on_event=_print_event, idle_timeout=cfg.silence_timeout)
            store.set_session(sid, status="idle", last_text=(res.text or "")[-500:], settled_at=time.time())
            events.emit("session_settled", session=sid)
            if res.error or res.timed_out:
                print(f"[orchestra] turn ended: {res.error or 'timed out'}")
    finally:
        proc.close()
        store.set_session(sid, status="idle", pid=None)
    return 0


def cmd_staging(args) -> int:
    from .gate.runner import run_specs
    from .git import Git
    from .staging import Staging, record_build

    project = _project(args)
    store, events = _store(project)
    st = Staging(project, store, events)
    if not project.config.staging_configured:
        sys.exit("orchestra: no [staging] section in orchestra.toml")
    if args.action == "status":
        print(json.dumps({k: v for k, v in st.state().items()}, indent=2))
    elif args.action == "logs":
        print(st.logs())
    elif args.action == "stop":
        st.stop(); print("stopped")
    elif args.action == "restart":
        r = st.restart()
        print({"ok": "restarted", "no_build": "no build recorded; use `orchestra staging deploy`",
               "start_failed": "start failed; see `orchestra staging logs`",
               "tunnel_failed": "running locally, but the tunnel probe failed; see staging/tunnel.log"}[r])
        if r in ("ok", "tunnel_failed"):
            print(f"local:  {st.local_url()}" + (f"\npublic: {st.public_url()}" if st.public_url() else ""))
    elif args.action == "deploy":
        # Build the current base branch head with the [build] stage and promote it.
        import glob
        import shutil
        import uuid

        cfg = project.config
        if not (cfg.build_command and cfg.build_artifact):
            sys.exit("orchestra: [build] command and artifact are required to deploy")
        git = Git(project.repo_root)
        commit = git.rev_parse(cfg.base_branch)
        bid = f"manual-{uuid.uuid4().hex[:8]}"
        path = project.gate_dir / bid
        git.worktree_add(f"orchestra/build-{bid}", path, cfg.base_branch)
        try:
            from .config import TestSpec
            ok, res = run_specs([TestSpec("build", cfg.build_command, timeout=cfg.build_timeout)], path,
                                project.logs_dir / bid, stage="build")
            if not ok:
                sys.exit(f"orchestra: build failed:\n{res[-1]['tail']}")
            matches = sorted(glob.glob(str(path / cfg.build_artifact)))
            if not matches:
                sys.exit(f"orchestra: no artifact matched {cfg.build_artifact}")
            dest = project.artifacts_dir / bid
            dest.mkdir(parents=True, exist_ok=True)
            artifact = shutil.copy(matches[-1], dest)
        finally:
            git.worktree_remove(path)
            git.branch_delete(f"orchestra/build-{bid}")
        build = {"id": bid, "gate_run_id": None, "commit": commit, "artifact_path": str(artifact),
                 "created_at": __import__("orchestra.model", fromlist=["now"]).now()}
        record_build(store, build)
        print(f"built {Path(artifact).name} from {commit[:10]}; deploying")
        print("deployed" if st.deploy(build) else "deploy FAILED; see `orchestra staging logs`")
        print(f"local:  {st.local_url()}" + (f"\npublic: {st.public_url()}" if st.public_url() else ""))
    return 0


def cmd_roles(args) -> int:
    from . import api as api_mod

    project = _project(args)
    store, _ = _store(project)
    if args.action == "list":
        for r in api_mod.handle(project, store, "list_roles", {})["roles"]:
            kind = "built-in" if r["builtin"] else "custom"
            wake = ", ".join(r.get("wake_on") or []) + (f" every {r['every']}" if r.get("every") else "") + (f" at {r['at']}" if r.get("at") else "")
            print(f"{r['name']:20} {kind:9} {r['session']:9} {'paused' if r['paused'] else '':7} {wake.strip() or '-'}")
        return 0
    print(json.dumps(api_mod.handle(project, store, "get_role", {"name": args.name}), indent=2))
    return 0


def cmd_metrics(args) -> int:
    """Measured series: replay the event log into the metrics store, list series, show a stock or flow."""
    from collections import Counter
    from datetime import UTC, datetime

    from . import collectors
    from .metrics import for_project as metrics_for

    project = load_project()
    store = metrics_for(project)
    if args.action == "backfill":
        events = Events.for_project(project)
        evs, _ = events.read(0, limit=10_000_000)
        sampled = Counter(t.state.value for t in LocalStore(project).list_tickets())
        rep = collectors.backfill(evs, project=project.key, store=store, sampled=dict(sampled),
                                  sampled_at=time.time(), replace=not args.append)
        when = lambda t: datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t else "-"  # noqa: E731
        print(f"{rep.events} events ({when(rep.first)} → {when(rep.last)}) → {rep.points} points in {store.name}")
        drift = {s: n for s, n in rep.shifts.items() if n}
        print("anchored to the ticket store; integrated levels were off by: " + (", ".join(f"{s} {n:+d}" for s, n in sorted(drift.items())) or "nothing"))
        print("flows: " + ", ".join(f"{f} {n}" for f, n in sorted(rep.flows.items(), key=lambda x: -x[1])))
        return 0
    if args.action == "series":
        for name, labels in store.series():
            print(name, " ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "project"))
        return 0
    if args.action == "show":
        kind, _, what = args.what.partition(":")
        series, label = ({"stock": (collectors.STOCK, "stock"), "flow": (collectors.FLOW, "flow"),
                          "event": (collectors.EVENTS, "type")}.get(kind) or (None, None))
        if not series:
            print("show stock:<STATE>, flow:<FROM>><TO> or event:<type>")
            return 2
        labels = {"project": project.key, label: what}
        pts = store.raw(series, labels)
        if not pts:
            print("no data; run `orchestra metrics backfill` first")
            return 1
        step = args.step * 3600
        start = pts[0][0] - pts[0][0] % step
        sampled = store.range(series, labels, start, pts[-1][0] + step, step)
        prev = None
        for t, v in sampled:
            stamp = datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M")
            extra = f"   +{v - prev:g} in the step" if kind != "stock" and prev is not None else ""
            print(f"{stamp}  {v:g}{extra}")
            prev = v
        return 0
    return 2


def cmd_sd(args) -> int:
    """The system dynamics model: declare Orchestra's own factory, fit its flows, show it."""
    from .metrics import for_project as metrics_for
    from .sd.factory import ticket_factory
    from .sd.fit import fit_model
    from .sd.store import ModelStore

    project = load_project()
    models = ModelStore(project.state_dir / "models")
    if args.action == "declare":
        m = ticket_factory(project.key)
        print(f"declared {m.id}: {len(m.stocks)} stocks, {len(m.flows)} flows, {len(m.machines)} machines → {models.save(m)}")
        return 0
    m = models.load(args.model) or ticket_factory(project.key)
    if args.action == "fit":
        fit_model(m, metrics_for(project), project.key, step=args.step * 3600)
        models.save(m)
    store = metrics_for(project)
    print(f"{m.name} ({m.id})")
    print("\nstocks (latest level):")
    for s in m.stocks:
        last = store.latest(s.series.name, s.series.labels) if s.series else None
        print(f"  {s.id:<18} {last[1] if last else '-':>6}")
    print("\nflows (fitted per hour while the loop runs; ± one standard error):")
    for f in m.flows:
        eq = f.current()
        if not eq:
            print(f"  {f.id:<30} no data")
            continue
        q = eq.quality
        (p, v), = eq.params.items()
        rate = f"{v:.3f}/h" if eq.form == "constant" else f"{v:.4f} × {f.src}/h"
        alt = [k for k in q if k.startswith("loglik_") and k != f"loglik_{eq.form}"]
        gap = f"  Δll {q['loglik'] - q[alt[0]]:+.1f}" if alt and q[alt[0]] != float("-inf") else ""
        stopped = f"  ({q['events_while_stopped']:.0f} while stopped)" if q.get("events_while_stopped") else ""
        print(f"  {f.id:<30} {eq.form:<12} {rate:<28} ±{q['se']:.4f}  n={q['events']:.0f}  disp={q['dispersion']:.1f}{gap}{stopped}")
    print("\nmachines (attributed flows are hypotheses):")
    for mc in m.machines:
        tag = " [bootstrap]" if mc.bootstrap else ""
        eng = ", ".join(f"{e.mode} via {e.driver}" for e in mc.engagement) or "observed only"
        print(f"  {mc.id:<16} {mc.kind:<8} {eng}{tag}")
        print(f"      flows: {', '.join(mc.attributed)}")
    return 0


def cmd_events(args) -> int:
    """The event log: where it lives, how much it holds, and copying it to another backend."""
    from .bus import open_bus

    project = load_project()
    events = Events.for_project(project)
    if args.action == "info":
        print(f"{events.bus.name}: {events.end()} events")
        return 0
    if args.action == "copy":
        if not args.to:
            print("copy needs --to URL (redis://, amqp://, kafka://, or file)")
            return 2
        target = open_bus(args.to, project_key=project.key, file_path=project.events_file.with_name("events.copy.jsonl"))
        if target.end() and not args.force:
            print(f"{args.to} already holds {target.end()} events for this project; use --force to append anyway")
            return 1
        offset, n = 0, 0
        while True:
            batch, end = events.bus.read(offset, limit=10_000_000)
            for ev in batch:
                target.append(ev)
            n += len(batch)
            if end <= offset + len(batch) or not batch:
                break
            offset = end
        print(f"copied {n} events from {events.bus.name} to {target.name}: it now holds {target.end()}")
        print(f"to use it, set [events] url = \"{args.to}\" in orchestra.toml")
        target.close()
        return 0
    return 2


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
    s.add_argument("--provider", help="Pi provider (default: Pi's own default)")
    s.add_argument("--model", help="Pi model id (default: Pi's own default)")
    s.add_argument("--prefix", help="ticket id prefix, e.g. ORC")
    s.add_argument("--unit-command", default="uv run pytest -q")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="run the orchestration loop and the long-lived agent sessions")
    s.add_argument("--once", action="store_true", help="one tick, wait for its work, exit")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("chat", help="talk to the Supervisor")
    s.set_defaults(fn=cmd_chat)

    s = sub.add_parser("web", help="serve the web UI")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_web)

    s = sub.add_parser("status", help="loop, agents, web, tunnels, merge gate, queue, staging")
    s.add_argument("--json", action="store_true")
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

    s = sub.add_parser("tools", help="the Orchestra tools agents get, as data (used by the Pi extension)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--groups", help="comma-separated tool groups (default: ORCHESTRA_TOOLS, else all)")
    s.set_defaults(fn=cmd_tools)

    s = sub.add_parser("api", help="machine interface the agent tools call")
    s.add_argument("command")
    s.add_argument("--args", default="{}", help="JSON object of arguments")
    s.add_argument("--compact", action="store_true")
    s.set_defaults(fn=cmd_api)

    s = sub.add_parser("staging", help="staging environment: status, logs, deploy, restart, stop")
    s.add_argument("action", choices=["status", "logs", "deploy", "restart", "stop"])
    s.set_defaults(fn=cmd_staging)

    s = sub.add_parser("roles", help="agent roles: built-in and custom")
    s.add_argument("action", choices=["list", "show"])
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_roles)

    s = sub.add_parser("metrics", help="measured series: backfill from the event log, list, show")
    s.add_argument("action", choices=["backfill", "series", "show"])
    s.add_argument("what", nargs="?", default="", help="for show: stock:OPEN, flow:OPEN>IN_PROGRESS, event:gate_started")
    s.add_argument("--step", type=float, default=24.0, help="for show: hours per step (default 24)")
    s.add_argument("--append", action="store_true", help="for backfill: keep existing points instead of replacing them")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("sd", help="the system dynamics model: declare Orchestra's own factory, fit it, show it")
    s.add_argument("action", choices=["declare", "fit", "show"])
    s.add_argument("--model", default="tickets")
    s.add_argument("--step", type=float, default=1.0, help="for fit: hours per step (default 1)")
    s.set_defaults(fn=cmd_sd)

    s = sub.add_parser("events", help="the event log: info, or copy it to another bus backend")
    s.add_argument("action", choices=["info", "copy"])
    s.add_argument("--to", help="for copy: the target bus URL")
    s.add_argument("--force", action="store_true", help="for copy: append even if the target already has events")
    s.set_defaults(fn=cmd_events)

    s = sub.add_parser("doctor")
    s.add_argument("--fix", action="store_true")
    s.set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
