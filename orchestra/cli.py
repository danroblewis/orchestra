"""The `orchestra` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, runtime
from .config import ConfigError, Project, init_project, load_project
from .events import Events


def _project(args) -> Project:
    try:
        return load_project(getattr(args, "repo", None))
    except ConfigError as e:
        sys.exit(f"orchestra: {e}")


def _when(t: float | None) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t else "-"


def cmd_init(args) -> int:
    p = init_project(Path(args.repo or os.getcwd()), provider=args.provider, model=args.model)
    print(f"initialized {p.key}\n  repo:   {p.repo_root}\n  state:  {p.state_dir}\n  config: {p.repo_root / 'orchestra.toml'}")
    return 0


def cmd_run(args) -> int:
    """The bootstrap host."""
    from .host import Host

    Host(_project(args)).run(once=args.once)
    return 0


def cmd_web(args) -> int:
    import uvicorn

    from .web.app import create_app

    project = _project(args)
    runtime.update(project, lambda d: d.__setitem__("web", {"port": args.port, "pid": os.getpid(), "since": time.time()}))
    try:
        uvicorn.run(create_app(project), host=args.host, port=args.port, log_level="warning")
    finally:
        runtime.update(project, lambda d: d.pop("web", None) if (d.get("web") or {}).get("pid") == os.getpid() else None)
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


def cmd_metrics(args) -> int:
    """The metrics store: replay the event log into event counters, or list the series."""
    from . import collectors
    from .metrics import for_project as metrics_for

    project = _project(args)
    store = metrics_for(project)
    if args.action == "backfill":
        evs, _ = Events.for_project(project).read(0, limit=10_000_000)
        rep = collectors.backfill(evs, project=project.key, store=store, replace=not args.append)
        print(f"{rep.events} events ({_when(rep.first)} → {_when(rep.last)}) → {rep.points} points in {store.name}")
        print("types: " + ", ".join(f"{t} {n}" for t, n in sorted(rep.types.items(), key=lambda x: -x[1])[:20]))
        return 0
    for name, labels in store.series(""):
        if labels.get("project") == project.key:
            print(name, " ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "project"))
    return 0


def cmd_sd(args) -> int:
    """The system dynamics model: show it, fit its flows, list its versions."""
    from .metrics import for_project as metrics_for
    from .sd.fit import fit_model
    from .sd.store import ModelStore

    project = _project(args)
    models = ModelStore.for_state(project.state_dir)
    if args.action == "discover":
        from .sd.rediscover import rediscover

        r = rediscover(project, metrics_for(project), strategy=args.strategy, window_s=args.minutes * 60 if args.minutes else None,
                       step_s=args.step_s, note="discovered with orchestra sd discover")
        m = r.model
        print(f"{r.strategy}, over the last {m.discovery['window_s'] / 60:g} min in {m.discovery['step_s']:g} s steps: {len(m.stocks)} stocks, "
              f"{len(m.flows)} flows, {len(m.machines)} machines")
        for st in m.stocks:
            if "balance" not in st.evidence:
                print(f"  stock {st.id}: hidden (found by {r.strategy}, measured by no series)")
                continue
            terms = " ".join(("+ " if b["sign"] > 0 else "− ") + b["series"] for b in st.evidence["balance"])
            print(f"  stock {st.id}: Δ = {terms}   (R² {st.evidence['balance_r2']:.3f}, exact in {st.evidence['exact_steps']:.0%} of steps)")
        print("left out:")
        for k, why in m.discovery["left_out"].items():
            print(f"  {k}: {why}")
        print(f"saved as version {r.version}" if r.version else "structure unchanged: no new version")
        args.version = None
    if args.action == "versions":
        for v in models.versions():
            print(f"v{v['version']:<4} {_when(v['saved_at'])}  {v['stocks']} stocks, {v['flows']} flows ({v['fitted']} fitted)  {v['note']}")
        return 0
    m = models.load(args.version)
    if m is None:
        print("no model yet")
        return 1
    if args.action == "fit":
        fit_model(m, metrics_for(project), project.key, step=args.step * 3600)
        print(f"saved as version {models.save(m, note=f'fitted from the metrics store, {args.step:g} h steps')}")
    store = metrics_for(project)
    print(f"{m.name} (version {args.version or models.current_version()})")
    print("\nstocks (latest level):")
    for s in m.stocks:
        last = store.latest(s.series.name, s.series.labels) if s.series else None
        print(f"  {s.id:<24} {last[1] if last else '-':>8}")
    print("\nflows:")
    for f in m.flows:
        eq = f.current()
        if not eq:
            print(f"  {f.id:<36} no equation")
            continue
        p = eq.params
        rate = {"constant": f"{p.get('c', 0):.4g}", "proportional": f"{p.get('k', 0):.4g} × {(eq.inputs or [f.src])[0]}",
                "linear": f"{p.get('c', 0):.4g} {'+' if p.get('k', 0) >= 0 else '−'} {abs(p.get('k', 0)):.4g} × {(eq.inputs or ['?'])[0]}"
                }.get(eq.form, str(p)) + f" /{m.time_unit}"
        print(f"  {f.id:<36} {eq.origin:<10} {eq.form:<12} {rate:<30} n={eq.quality.get('events', 0):.0f}")
    print("\nmachines (attributed flows are hypotheses):")
    for mc in m.machines:
        print(f"  {mc.id:<20} {mc.kind:<8} flows: {', '.join(mc.attributed) or '-'}")
    return 0


def cmd_events(args) -> int:
    """The event log: where it lives, how much it holds, and copying it to another backend."""
    from .bus import open_bus

    project = _project(args)
    events = Events.for_project(project)
    if args.action == "info":
        print(f"{events.bus.name}: {events.end()} events")
        return 0
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestra", description="Orchestra: an event bus, a metrics store, and a "
                                "system dynamics model of the machines that use them")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--repo", help="repository root (default: ORCHESTRA_REPO or cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="register this repository and write orchestra.toml")
    s.add_argument("--provider", help="Pi provider (default: Pi's own default)")
    s.add_argument("--model", help="agent model id (default: the harness's own default)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="run the bootstrap host: Orchestra's own machine and its event collector")
    s.add_argument("--once", action="store_true", help="start, record one heartbeat, stop")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("web", help="serve the web UI")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_web)

    s = sub.add_parser("tools", help="the Orchestra tools agents get, as data (used by the Pi extension)")
    s.add_argument("--json", action="store_true")
    s.add_argument("--groups", help="comma-separated tool groups (default: ORCHESTRA_TOOLS, else all)")
    s.set_defaults(fn=cmd_tools)

    s = sub.add_parser("metrics", help="the metrics store: backfill event counters from the log, list series")
    s.add_argument("action", choices=["backfill", "series"])
    s.add_argument("--append", action="store_true", help="for backfill: keep existing points instead of replacing them")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("sd", help="the system dynamics model: discover it from the metrics, show it, fit it, list its versions")
    s.add_argument("action", choices=["show", "fit", "versions", "discover"])
    s.add_argument("--minutes", type=float, help="for discover: the window, in minutes back from now (default: [discovery] window)")
    s.add_argument("--step-s", dest="step_s", type=float, help="for discover: seconds per step (default: [discovery] step)")
    s.add_argument("--strategy", help="for discover: conservation or an SD Lab strategy (default: [discovery] strategy)")
    s.add_argument("--version", type=int, help="for show and fit: start from this past version (default: the current one)")
    s.add_argument("--step", type=float, default=1.0, help="for fit: hours per step (default 1)")
    s.set_defaults(fn=cmd_sd)

    s = sub.add_parser("events", help="the event log: info, or copy it to another bus backend")
    s.add_argument("action", choices=["info", "copy"])
    s.add_argument("--to", help="for copy: the target bus URL")
    s.add_argument("--force", action="store_true", help="for copy: append even if the target already has events")
    s.set_defaults(fn=cmd_events)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
