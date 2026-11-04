"""The `orchestra` command line."""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, commands, runtime
from .config import ConfigError, Project, init_project, load_project
from .events import Events

COPY_PAGE = 10_000             # events read per page by `events copy`


def _project(args) -> Project:
    try:
        return load_project(getattr(args, "repo", None))
    except ConfigError as e:
        sys.exit(f"orchestra: {e}")


def _when(t: float | None) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M") if t else "-"


def cmd_init(args) -> int:
    try:
        p = init_project(Path(args.repo or os.getcwd()))
    except ConfigError as e:
        print(f"orchestra: {e}" + ("; run git init first" if "git repository" in str(e) else ""), file=sys.stderr)
        return 1
    print(f"initialized {p.key}\n  repo:   {p.repo_root}\n  state:  {p.state_dir}\n  config: {p.config_file}\n  private overlay (if any): {p.overlay_file}")
    return 0


def cmd_run(args) -> int:
    """The bootstrap host."""
    from .host import Host

    Host(_project(args)).run(once=args.once)
    return 0


def _cannot_bind(host: str, port: int) -> str | None:
    """Why the web server could not listen on ``host:port``, checked before any token is printed
    or the runtime record names it; None when it can."""
    import socket

    try:
        family, kind, proto, _, addr = socket.getaddrinfo(host or None, port, type=socket.SOCK_STREAM,
                                                          flags=socket.AI_PASSIVE)[0]
        with socket.socket(family, kind, proto) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(addr)
    except OSError as e:
        return f"port {port} is in use" if e.errno in (errno.EADDRINUSE,) else f"cannot listen on {host}:{port}: {e.strerror or e}"
    return None


def cmd_web(args) -> int:
    from .web import auth

    project = _project(args)
    if args.action == "token":
        tok = auth.rotate_token(project) if args.rotate else auth.token(project)
        if args.rotate:
            print("a new token: every browser must log in again, and programs need the new one", file=sys.stderr)
        print(tok)
        return 0
    try:
        on = auth.enabled(project, args.host)
    except ConfigError as e:
        sys.exit(f"orchestra: {e}")
    if why := _cannot_bind(args.host, args.port):
        print(f"orchestra: {why}; serve on another: orchestra web --port {args.port + 10}", file=sys.stderr)
        return 1
    import uvicorn

    from .web.app import create_app

    shown = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "[::1]"}.get(args.host, f"[{args.host}]" if ":" in args.host else args.host)
    url = f"http://{shown}:{args.port}"
    if on and sys.stdout.isatty():
        tok = auth.token(project)
        print(f"orchestra web: {url}/\n  log in:  {url}/login#token={tok}\n  token:   {tok}  "
              f"(again: `orchestra web token`; kept in {auth.token_file(project)})", flush=True)
    elif on:
        # not a terminal: the banner lands in a log file (logs/web.log), which never holds the token
        print(f"orchestra web: {url}/\n  log in:  {url}/login with the token from `orchestra web token` "
              f"(kept in {auth.token_file(project)})", flush=True)
    else:
        print(f"orchestra web: {url}/  ([web] auth = \"off\": no login, and only requests from this computer are served)", flush=True)
    runtime.update(project, lambda d: d.__setitem__("web", {"port": args.port, "pid": os.getpid(), "since": time.time()}))
    try:
        # proxy_headers off: the client and scheme are the socket's, never a forwarded header's
        uvicorn.run(create_app(project, args.host), host=args.host, port=args.port, log_level="warning", proxy_headers=False)
    finally:
        runtime.update(project, lambda d: d.pop("web", None) if (d.get("web") or {}).get("pid") == os.getpid() else None)
    return 0


def cmd_metrics(args) -> int:
    """The metrics store: list the project's series."""
    from .metrics import for_project as metrics_for

    project = _project(args)
    for name, labels in metrics_for(project).series("", {"project": project.key}):
        print(name, " ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "project"))
    return 0


def _predictions(models, args) -> int:
    """The predictions recorded and their verdicts, by era (sd/predictions.py, sd/judge.py)."""

    from .sd import eras as era_record
    from .sd import predictions as P
    from .sd.predictions_report import lines

    preds, eras = P.recorded(models), era_record.recorded(models)
    if args.json:
        by_cause = {c: e.id for c, e in era_record.by_change(eras).items()}
        print(json.dumps({"predictions": [{**p, "era": by_cause.get(p.get("change"))} for p in preds], "eras": [vars(e) for e in eras]}))
        return 0
    print("\n".join(lines(preds, eras)))
    return 0


ELSEWHERE = "The Dynamics page lists why each series was left out, or `orchestra sd discover` prints it (and looks once)."


def _why_no_model(project, models) -> str:
    """Why there is no saved model, in the paragraph the Dynamics page and the model reads give
    (``sd.no_model``), and where the reason for each series is."""
    from .sd.no_model import NoModel, host_running

    cached = models.latest_discovery()
    if cached and cached[1].stocks:
        return f"the latest discovery found {len(cached[1].stocks)} stocks, but no version of it is saved yet. {ELSEWHERE}"
    return f"{NoModel(cached[1].discovery if cached else None, host_running(project)).text} {ELSEWHERE}"


def _discovered(m, strategy: str) -> None:
    """A discovered model's summary: its stocks, how each balances, and what was left out."""
    print(f"{strategy}, over the last {m.discovery['window_s'] / 60:g} min in {m.discovery['step_s']:g} s steps: {len(m.stocks)} stocks, "
          f"{len(m.flows)} flows, {len(m.machines)} machines")
    for st in m.stocks:
        tr = st.evidence.get("trust") or {}
        trust = f"; trust {tr['score']:.2f} ({tr['level']}, weakest: {tr.get('weakest') or '—'})" if tr else ""
        if b := tr.get("behaviour"):
            trust += f"; behaviour {b['score']:.2f} ({b['level']}, replay off by {b['error']:.2f}× its spread)"
        if nf := st.evidence.get("net_flow"):
            print(f"  stock {st.id}: no counters; net flow fitted as {nf['form']}   (R² {nf['r2']:.3f} over {nf['stretches']} "
                  f"stretches of {nf['stretch_s']:g} s{trust})")
            continue
        if "balance" not in st.evidence:
            print(f"  stock {st.id}: hidden (found by {strategy}, measured by no series{trust})")
            continue
        terms = " ".join(("+ " if b["sign"] > 0 else "− ") + b["series"] for b in st.evidence["balance"])
        if st.evidence.get("balance_r2") is None:
            why = "exact by definition: a count and its own turnover, so the balance proves nothing" if st.evidence.get("by_construction") else "measured by no series"
            print(f"  stock {st.id}: Δ = {terms}   ({why}{trust})")
            continue
        print(f"  stock {st.id}: Δ = {terms}   (R² {st.evidence['balance_r2']:.3f}, exact in {st.evidence['exact_steps']:.0%} of steps{trust})")
    print("left out:")
    for k, why in m.discovery["left_out"].items():
        print(f"  {k}: {why}")


def cmd_sd(args) -> int:
    """The system dynamics model: discover it, show it, list its versions."""
    from .metrics import for_project as metrics_for
    from .sd.store import ModelStore

    if args.action == "discover" and args.replay:
        from .sd.snapshot import replay

        m = replay(args.replay, strategy=args.strategy)
        if args.json:
            print(json.dumps(m.to_json()))
        else:
            _discovered(m, m.discovery.get("strategy") or "")
            print(f"replayed from {args.replay}: nothing saved")
        return 0
    project = _project(args)
    models = ModelStore.for_state(project.state_dir)
    if args.action == "snapshot":
        from .sd.rediscover import snapshot

        if not args.dir:
            sys.exit("orchestra sd snapshot: name the directory to write to")
        d = snapshot(project, metrics_for(project), args.dir, strategy=args.strategy,
                     window_s=args.minutes * 60 if args.minutes else None, step_s=args.step_s)
        man = json.loads((d / "manifest.json").read_text())
        print(f"{len(man['series'])} series over {(man['window']['end'] - man['window']['start']) / 60:g} min in "
              f"{man['step']:g} s steps written to {d}; replay with orchestra sd discover --from {d}")
        return 0
    if args.action == "discover":
        from .sd.rediscover import rediscover

        r = rediscover(project, metrics_for(project), strategy=args.strategy, window_s=args.minutes * 60 if args.minutes else None,
                       step_s=args.step_s, note="discovered with orchestra sd discover", events=Events.for_project(project),
                       snapshot=args.snapshot)
        m = r.model
        _discovered(m, r.strategy)
        if m.era:
            print(f"era {m.era} (from {_when(m.discovery.get('era_start'))}); the Dynamics page compares it with its prior")
        if err := m.discovery.get("plugins_error"):
            print(f"plugins could not be loaded: {err}; their simulated instruments are unknown, so no version is saved")
        else:
            print(f"saved as version {r.version}" if r.version else "structure unchanged: no new version")
        if args.snapshot:
            print(f"what it read is in {args.snapshot}; replay with orchestra sd discover --from {args.snapshot}")
        args.version = None
    if args.action == "predictions":
        return _predictions(models, args)
    if args.action == "versions":
        if not models.versions():
            print(f"no versions yet. {_why_no_model(project, models)}")
            return 0
        for v in models.versions():
            era = f"  era {v['era']}" if v.get("era") else ""
            print(f"v{v['version']:<4} {_when(v['saved_at'])}  {v['stocks']} stocks, {v['flows']} flows ({v['fitted']} fitted){era}  {v['note']}")
        return 0
    m = models.load(args.version)
    if m is None:
        if args.version is not None:
            print(f"there is no version {args.version}")
            return 1
        print(_why_no_model(project, models))
        return 0
    store = metrics_for(project)
    print(f"{m.name} (version {args.version or models.current_version()})")
    print("\nstocks (latest level):")
    from .sources.catalogue import Catalogue
    cat = Catalogue(project, store, infer=False)
    now = time.time()
    remote = cat.reader(now - 900, now, project.config.discovery_step)
    for s in m.stocks:
        last, why = None, ""
        if s.series and s.series.source not in (None, "own"):
            last = (remote(s.series) or [None])[-1]
            if s.series.source in cat.errors:
                last, why = ("unavailable",), f"  ({s.series.source}: {cat.errors[s.series.source]})"
        elif s.series:
            last = store.latest(s.series.name, s.series.labels)
        print(f"  {s.id:<24} {last[-1] if last else '-':>8}{why}")
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
    print("\nmachines (flows guessed from timing: their events match a flow's counter in time; nothing says they cause it):")
    for mc in m.machines:
        print(f"  {mc.id:<20} {mc.kind:<8} flows: {', '.join(mc.attributed) or '-'}")
    return 0


def cmd_sources(args) -> int:
    """Other time-series stores: check them, infer what to read from them, preview a query."""
    from .metrics import for_project as metrics_for
    from .sources import report
    from .sources.catalogue import Catalogue

    project = _project(args)
    if args.action == "explore":
        return _explore(project, args)
    cat = Catalogue(project, metrics_for(project), by="cli")
    if args.action == "check":
        lines = report.check(cat)
    elif args.action == "infer":
        lines = report.infer(cat, project, args.source)
    else:
        if not args.query:
            print("preview needs a query")
            return 2
        lines = report.preview(cat, args.query, args.source, args.minutes or project.config.discovery_window / 60,
                               args.step_s or project.config.discovery_step)
    print("\n".join(lines))
    return 0


def _explore(project, args) -> int:
    """``sources explore``: the bounded survey of a source's explore scope beyond its match."""
    from .sources import exploring
    from .sources.spec import for_project

    specs = for_project(project)
    spec = next((s for s in specs.sources if s.name == args.source), None)
    if spec is None:
        why = specs.refused.get(args.source or "") or f"no usable source {args.source!r} (sources: {', '.join(s.name for s in specs.sources) or 'none'})"
        print(f"orchestra: {args.source or 'explore needs --source'}: {why}", file=sys.stderr)
        return 1
    out = exploring.explore(project.state_dir, spec, family=args.family, limit=args.limit, minutes=args.minutes)
    print(json.dumps(out, indent=2, default=str) if args.json else "\n".join(exploring.table(out)))
    return 1 if out.get("refused") else 0


def cmd_explorer(args) -> int:
    """The explorer's experiment log: add one, judge one by discovery's runs since, list them."""
    from .sd.explorer import ExperimentError
    from .sd.store import ModelStore

    log = ModelStore.for_state(_project(args).state_dir).explorer()
    try:
        if args.action == "add":
            e = log.add(args.change, args.expect, args.by)
            print(json.dumps(e, default=str) if args.json else f"recorded {e['id']}" + (f" (before: run {e['before']['id']})" if e["before"] else " (no discovery run yet)"))
            return 0
        if args.action == "judge":
            e = log.judge(args.id, args.verdict, args.why, args.by)
            print(json.dumps(e, default=str) if args.json else f"{e['id']}: {e['verdict']}, after {len(e['rounds'])} run(s)"
                  + (f"; effect {', '.join(f'{k} {v:+g}' for k, v in (e['effect'] or {}).items())}" if e.get("effect") else ""))
            return 0
    except ExperimentError as err:
        print(f"orchestra: {err}", file=sys.stderr)
        return 1
    entries = log.recent(0)
    if args.json:
        print(json.dumps(entries, indent=2, default=str))
        return 0
    if not entries:
        print(f"no experiments recorded ({log.path})")
    for e in entries:
        eff = ", ".join(f"{k} {v:+g}" for k, v in (e.get("effect") or {}).items())
        print(f"{e['id']}  {_when(e.get('t'))}  {e.get('by', '?'):<10} {e.get('verdict') or 'pending':<12} {json.dumps(e.get('change'))}")
        print(f"    expect: {e.get('expect')}" + (f"\n    why: {e['why']} ({len(e.get('rounds') or [])} run(s); {eff or 'no effect measured'})" if e.get("verdict") else ""))
    return 0


def cmd_events(args) -> int:
    """The event log: where it lives, how much it holds, where machines reach it over HTTP, and
    copying it to another backend."""
    import shlex

    from . import endpoint
    from .bus import open_bus

    project = _project(args)
    if args.action == "endpoint":
        rec = endpoint.recorded(project)
        if rec is None:
            print("no events endpoint: `orchestra run` is not running for this project, or [events] listen is off",
                  file=sys.stderr)
            return 1
        if args.env:
            print(f"export {endpoint.ENV_URL}={shlex.quote(rec['url'])}")
            print(f"export {endpoint.ENV_TOKEN}={shlex.quote(endpoint.token(project))}")
        else:
            print(f"url:   {rec['url']}  (POST /events, GET /events?after=<offset>)\ntoken: {endpoint.token_file(project)}")
        return 0
    events = Events.for_project(project)
    if args.action == "info":
        print(f"{events.bus.name}: {events.end()} events")
        if rec := endpoint.recorded(project):
            print(f"endpoint: {rec['url']}")
        return 0
    if not args.to:
        print("copy needs --to URL (redis://, amqp://, kafka://, or file)")
        return 2
    target = open_bus(args.to, project_key=project.key, file_path=project.events_file.with_name("events.copy.jsonl"))
    if target.end() and not args.force:
        print(f"{args.to} already holds {target.end()} events for this project; use --force to append anyway")
        return 1
    offset, n, had = 0, 0, target.end()
    while offset < (end := events.end()):         # forward, a bounded page at a time, from the start
        batch, offset = events.page(offset, COPY_PAGE)
        for ev in batch:
            target.append(ev)
        n += len(batch)
    held = target.end()
    target.close()
    if held - had != n or n != end:
        print(f"orchestra: copied {n} events from {events.bus.name} to {target.name}, but the source holds {end} "
              f"(unreadable lines are skipped) and the target took {held - had}: check both before switching")
        return 1
    print(f"copied {n} events from {events.bus.name} to {target.name}: it now holds {held}")
    print(f"to use it, set [events] url = \"{args.to}\" in orchestra.toml")
    return 0


def build_parser(plugin_help: dict[str, str] | None = None) -> argparse.ArgumentParser:
    """Orchestra's own subcommands, and a line in the help for each plugin command (``plugin_help``:
    name -> one line; they are run before parsing, by ``main``)."""
    p = argparse.ArgumentParser(prog="orchestra", description="Orchestra: an event bus, a metrics store, and a "
                                "system dynamics model of the machines that use them",
                                epilog="plugin commands: orchestra <plugin> [args...] runs the command an installed "
                                "plugin declares (entry point group orchestra.commands); orchestra <plugin> --help for its own")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--repo", help="repository root (default: ORCHESTRA_REPO or cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="register this repository and write orchestra.toml")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="run the bootstrap host: its event collector, discovery, and the processes the project and plugins declare")
    s.add_argument("--once", action="store_true", help="start, record one heartbeat, stop")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("web", help="serve the web UI (behind the project's web token), or print the token")
    s.add_argument("action", nargs="?", choices=["serve", "token"], default="serve",
                   help="serve (default), or token: print the token the web UI asks for")
    s.add_argument("--port", type=int, default=8000, help="the port to serve on (default 8000)")
    s.add_argument("--host", default="127.0.0.1", help="the address to serve on (default 127.0.0.1, this computer only)")
    s.add_argument("--rotate", action="store_true", help="for token: replace it; every session ends")
    s.set_defaults(fn=cmd_web)

    s = sub.add_parser("metrics", help="the metrics store: list the project's series")
    s.add_argument("action", choices=["series"], help="series: list every series the store holds for this project "
                   "(the host replays the whole event log into orchestra_events_total at every start)")
    s.set_defaults(fn=cmd_metrics)

    s = sub.add_parser("sd", help="the system dynamics model: discover it from the metrics, show it, list its versions, "
                       "and list the predictions and their verdicts (predictions). Machines read the model through the events "
                       "endpoint's HTTP API, or sd.reads.ModelReads (SPEC.md §3.1, §4.5)")
    s.add_argument("action", choices=["show", "versions", "discover", "snapshot", "predictions"], help="show: the model "
                   "and its stocks' latest levels; versions: every saved version; discover: discover the model now and print it; "
                   "snapshot: write every series discovery would read to a directory; "
                   "predictions: the predictions recorded and their verdicts")
    s.add_argument("dir", nargs="?", help="for snapshot: the directory to write every series discovery would read to")
    s.add_argument("--minutes", type=float, help="for discover and snapshot: the window, in minutes back from now (default: [discovery] window)")
    s.add_argument("--step-s", dest="step_s", type=float, help="for discover and snapshot: seconds per step (default: [discovery] step)")
    s.add_argument("--strategy", help="for discover: conservation or an SD Lab strategy (default: [discovery] strategy; "
                   "with --from, the one the snapshot records)")
    s.add_argument("--snapshot", help="for discover: also write every series it read to this directory, to replay later")
    s.add_argument("--from", dest="replay", help="for discover: discover from a snapshot directory instead of the store; saves nothing")
    s.add_argument("--version", type=int, help="for show: this past version (default: the current one)")
    s.add_argument("--json", action="store_true", help="for predictions, and discover --from: the answer as JSON")
    s.set_defaults(fn=cmd_sd)

    s = sub.add_parser("sources", help="other time-series stores ([[sources]]): check them, infer what to read, preview a query")
    s.add_argument("action", choices=["check", "infer", "preview", "explore"], help="check: probe each source's endpoints and "
                   "credentials; infer: run an inference round, what to read from each; preview: read a query's fan-out; "
                   "explore: a bounded survey of the source's explore scope beyond its match (families, labels, kinds)")
    s.add_argument("query", nargs="?", help="for preview: a PromQL query")
    s.add_argument("--source", help="for infer, preview and explore: one source by name (preview default: the own store)")
    s.add_argument("--family", help="for explore: only the metric names this glob matches (e.g. 'gcp_pubsub_*')")
    s.add_argument("--limit", type=int, help="for explore: families surveyed, at most (default 10, at most 50)")
    s.add_argument("--json", action="store_true", help="for explore: the survey as JSON")
    s.add_argument("--minutes", type=float, help="for preview: the window (default: [discovery] window); for explore (default 60)")
    s.add_argument("--step-s", dest="step_s", type=float, help="for preview: seconds per step (default: [discovery] step)")
    s.set_defaults(fn=cmd_sources)

    s = sub.add_parser("explorer", help="the explorer's experiment log (<state>/model/explorer.jsonl): one change at a time, "
                       "its expected effect first, judged by discovery's next runs")
    es = s.add_subparsers(dest="what", required=True)
    log = es.add_parser("log", help="add, judge or list experiments")
    ls = log.add_subparsers(dest="action", required=True)
    a = ls.add_parser("add", help="record an experiment before its effect is known")
    a.add_argument("--change", required=True, help="a JSON object: what changes (a source's match, split, kinds or names, an expected flow)")
    a.add_argument("--expect", required=True, help="the effect expected, in words")
    j = ls.add_parser("judge", help="judge one by the discovery runs since it was recorded")
    j.add_argument("id")
    j.add_argument("--verdict", required=True, choices=["kept", "reverted", "inconclusive"])
    j.add_argument("--why", required=True, help="what in discovery's runs decided it")
    ls.add_parser("list", help="every experiment, oldest first")
    for x in (a, j, ls.choices["list"]):
        x.add_argument("--by", default="explorer", help="who records it (default explorer)")
        x.add_argument("--json", action="store_true", help="the answer as JSON")
    s.set_defaults(fn=cmd_explorer)

    s = sub.add_parser("events", help="the event log: info, the HTTP endpoint machines use, or copy it to another bus backend")
    s.add_argument("action", choices=["info", "endpoint", "copy"], help="info: the backend and how many events it holds; "
                   "endpoint: where the events endpoint is; copy: copy the log to another backend (--to)")
    s.add_argument("--env", action="store_true", help="for endpoint: print export lines for a shell "
                   "(eval \"$(orchestra events endpoint --env)\")")
    s.add_argument("--to", help="for copy: the target bus URL")
    s.add_argument("--force", action="store_true", help="for copy: append even if the target already has events")
    s.set_defaults(fn=cmd_events)

    for name, line in (plugin_help or {}).items():
        sub.add_parser(name, help=f"(plugin) {line}" if line else "(plugin)", add_help=False)
    return p


def _command_word(argv: list[str]) -> tuple[int, str | None]:
    """The index of the subcommand in ``argv`` and the ``--repo`` given before it; (-1, repo) when
    an option other than ``--repo`` comes first (``--help``, ``--version``) or there is none."""
    i, repo = 0, None
    while i < len(argv):
        a = argv[i]
        if a == "--repo" and i + 1 < len(argv):
            repo, i = argv[i + 1], i + 2
        elif a.startswith("--repo="):
            repo, i = a.split("=", 1)[1], i + 1
        elif a.startswith("-"):
            return -1, repo
        else:
            return i, repo
    return -1, repo


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    found = commands.installed()
    i, repo = _command_word(argv)
    if i >= 0 and argv[i] in found.commands:
        return commands.run(argv[i], found.commands[argv[i]], argv[i + 1:], repo)
    for w in found.warnings:
        print(f"orchestra: warning: {w}", file=sys.stderr)
    wants_help = i < 0 and any(a in ("-h", "--help") for a in argv)
    lines = {n: commands.summary(ep) if wants_help else "" for n, ep in found.commands.items()}
    args = build_parser(lines).parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
