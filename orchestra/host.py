"""The bootstrap host: Orchestra's own machine, started by ``orchestra run``.

In an empty Orchestra it does little, on purpose:
- it registers itself in the runtime record (``hosts``) and writes its log (``<state>/logs/orchestra-host.log``);
- it publishes ``orchestra.host.started`` and ``orchestra.host.stopped``, and writes
  ``orchestra_host_up`` to the metrics store, so the host is observed like any machine;
- it runs Orchestra's event collector: every event on the bus, from any machine, counted by type
  and source (``orchestra.collectors``). The host that launches replays the whole bus once at start,
  in order, so the counters continue from the full history, retrying until the replay succeeds,
  then follows the bus; a second host follows from the bus's end and writes no counters (its state
  says which host keeps them), and takes the launch over, replaying the bus and counting from then
  on, when that host stops. What the collector is doing is in the runtime record
  (``hosts.<pid>.collector``, on the Core page);
- in the host that launches, it says when a machine falls silent past its own cadence on the bus
  (``orchestra.quiet``: ``orchestra.machine.quiet``, subject the machine), so each is said once;
- it records the eras the bus begins (``orchestra.sd.eras``: ``system.changed`` and the events
  ``[discovery] eras_from`` names) as it follows the bus, and announces each
  (``orchestra.era.started``);
- it rediscovers the model in the background (``orchestra.sd.rediscover``, with the strategy,
  window and interval in ``[discovery]``, within the current era), caches the result for
  readers, and saves a new model version when the structure changed or an era began. Runs never
  overlap: each starts the interval after the last one started, or a fifth of the interval after
  it ended when it took longer (``pace``), and its log line says how long it took and whether
  the strategy was stopped at its deadline (``discovery_line``). After each discovery it announces what is due about the model (``orchestra.sd.announce``:
  ``orchestra.model.changed``, ``orchestra.model.diverged``, ``orchestra.model.returned``,
  ``orchestra.model.stalled``, ``orchestra.model.resumed``);
- it announces each accepted call to the intended model's declared layer once
  (``orchestra.intent.changed``, one event per element the call touched, ``orchestra.sd.intended``),
  following its journal, and after each discovery and declaration writes the current comparison's
  structural diff to the cache;
- it records the predictions machines make of their changes as it follows the bus
  (``orchestra.prediction.made``, ``orchestra.sd.predictions``), and after each discovery judges
  those that are due and publishes each verdict (``orchestra.prediction.judged``,
  ``orchestra.sd.judge``);
- it keeps running the commands the project declares (``[[machines]]`` in ``orchestra.toml``) and
  the plugins declare (``Plugin.processes``), through ``orchestra.launcher``, and stops them when
  it stops. Only one host launches for a project (``launcher`` in the runtime record): a second one, started while the
  first runs, launches nothing, says so, leaves the first one's record alone, and tries the claim
  again every beat, taking over when the first one has stopped;
- in the host that launches, it serves the events endpoint (``orchestra.endpoint``): machines
  publish and read events over HTTP on ``[events] listen`` (127.0.0.1 and a port the system picks,
  unless given), with the project's token. Its address is in the runtime record
  (``events_endpoint``) and, with the token, in the environment of what the host launches
  (``ORCHESTRA_EVENTS_ENDPOINT``, ``ORCHESTRA_EVENTS_TOKEN``). It starts before the processes and
  stops after them, so a machine can publish until it is stopped;
- in the host that launches, it runs the instruments the project declares (``[[collect]]``, a
  command, and ``[[scrape]]``, a URL, in ``orchestra.toml``) and the plugins declare
  (``Plugin.collectors``) on their intervals and writes what they print, in the Prometheus text
  format, to the metrics store, labelled ``instrument=<name>`` (``orchestra.collect``). An
  instrument is not a machine: nothing is announced for it; its health is in the runtime record.

Stopping it (SIGTERM, SIGHUP or Ctrl-C) stops what it launched."""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from . import endpoint, plugins, runtime
from .collect.runner import Collecting
from .collect.spec import Collector
from .collectors import EventCollector, backfill, collapse
from .config import Project
from .events import HOST, Events
from .launcher import Launcher, Process
from .metrics import Point
from .metrics import for_project as metrics_for
from .quiet import QUIET, QuietWatch

HOST_LOG_MAX = 5_000_000
ERAS_EVERY_S = 5.0              # how often the collector looks for events that begin an era
PENDING_MAX = 100_000           # counter points kept for the next write while the metrics store fails
REPLAY_PAUSE_MAX = 60.0         # the longest pause between two tries of the collector's replay at start
LEAST_PAUSE = 0.2               # of [discovery] every: the least pause between one discovery's end and the next's start


def pace(every: float, took: float) -> float:
    """The pause before the next discovery: the rest of the interval, so discoveries start every
    ``every`` while they take less; never less than ``LEAST_PAUSE`` of it, so one that takes
    longer than the interval is followed by a pause, never by the next at once. Discoveries never
    overlap: the next starts only after this one ended (and the project's lock keeps the CLI's
    and the page's out too)."""
    return max(every - took, LEAST_PAUSE * every)


SOON_S = 60.0                   # with no model yet and series left out as too new: the next look this soon (at most)
TOO_NEW = ("written for only", "too new", "live in only")     # the left-out reasons that a little more data mends


def soon(model, wait: float) -> float:
    """The pause before the next discovery when this one found no stocks and left series out as too
    new: ``SOON_S`` at most, so a new system gets its first model as soon as its data allows rather
    than a whole interval later; otherwise ``wait`` as it is."""
    left = (model.discovery or {}).get("left_out") or {}
    if model.stocks or not any(str(w).startswith(TOO_NEW) for w in left.values()):
        return wait
    return min(wait, SOON_S)


def discovery_line(r, took: float, every: float) -> str:
    """The host's log line for one discovery: what it found, whether it was saved, how long it
    took, and, when the strategy was stopped at its deadline or the run outlasted the interval,
    that too."""
    not_saved = r.model.discovery.get("not_saved")
    what = f"saved as version {r.version}" if r.version else (f"not saved: {not_saved}" if not_saved else "structure unchanged")
    line = (f"discovery ({r.strategy}): {len(r.model.stocks)} stocks, {len(r.model.flows)} flows"
            f"{', era ' + r.model.era if r.model.era else ''}; {what}; took {took:.0f} s")
    sdlab = str(r.model.discovery.get("sdlab") or "")
    if "deadline" in sdlab:
        line += f"; {r.strategy} {sdlab}"
    if took > every:
        line += f"; longer than [discovery] every ({every:g} s): the next starts {pace(every, took):.0f} s after this one ended"
    return line


class Host:
    def __init__(self, project: Project, interval: float = 15.0, collect_every: float = 2.0,
                 found: Callable[[], list] | None = None, launch_every: float = 1.0):
        self.project = project
        self.collect_every = collect_every
        self.events = Events.for_project(project, source=HOST)
        self.interval = interval
        self.launch_every = launch_every
        self._found = found               # stands in for the installed plugins (tests)
        self._declared: dict[str, tuple[list[Process], list[Collector]]] = {}   # each plugin's, as last loaded
        self._loaded_for: tuple | None = None            # the configuration's stamp they were loaded for
        self._stop = threading.Event()
        self._said_state: str | None = None              # the collector's state as last recorded
        self.skipped = 0                                 # events the quiet watch could not read
        self._launching = threading.Event()              # set while this host holds the launch: it counts and announces quiet
        self._other: int | None = None                   # the host that holds it, when another does

    def log(self, msg: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        path = self.project.logs_dir / "orchestra-host.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > HOST_LOG_MAX:
                path.replace(path.with_suffix(".log.1"))
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _beat(self, up: float) -> None:
        try:
            metrics_for(self.project).write([Point("orchestra_host_up", up, time.time(),
                                                   {"project": self.project.key, "machine": HOST})])
        except Exception as e:  # noqa: BLE001 - the host keeps running without its metric
            self.log(f"metrics: {type(e).__name__}: {e}")

    def _collector_state(self, state: str) -> None:
        """Say in the runtime record what the collector is doing (``replaying``, ``following``,
        ``failing: <why>``), under this host, for the Core page; written only when it changes."""
        if state == self._said_state:
            return
        self._said_state = state

        def put(d: dict) -> None:
            mine = (d.setdefault("hosts", {})).setdefault(str(os.getpid()), runtime.me())
            mine["collector"] = {"state": state, "at": time.time()}
        try:
            runtime.update(self.project, put)
        except Exception as e:  # noqa: BLE001 - the record is for the page; the collector goes on
            self.log(f"collector: cannot record its state: {type(e).__name__}: {e}")

    def _replay(self, counts: bool):
        """The collector's start: with ``counts`` (the host that launches), replay the whole bus in
        order into the counters (``backfill``) and the quiet watch; without, follow from the bus's
        end, writing no counters (the launching host keeps them). Returns (collector or None, quiet
        watch, offset); raises when the bus or the store fails, and the caller retries."""
        quiet = QuietWatch()
        if not counts:
            offset = self.events.end()
            self.log(f"collector: {self._holder_says()} keeps the event counters; following the bus from its end")
            return None, quiet, offset
        self._collector_state("replaying")
        evs, offset = self.events.after(0)
        rep = backfill(evs, project=self.project.key, store=metrics_for(self.project))
        col = EventCollector(self.project.key)
        for ev in evs:
            col.observe(ev)
            self._watch(quiet, ev)
        quiet.settle()
        self.log(f"collector: replayed {rep.events} events into {rep.points} points; following the bus")
        return col, quiet, offset

    def _watch(self, quiet: QuietWatch, ev: dict) -> None:
        """Show one event to the quiet watch; one it cannot read (a malformed announcement written
        past the endpoint's checks) is skipped and counted, never fatal, so neither the replay nor
        the follow loop sticks on it."""
        try:
            quiet.observe(ev)
        except Exception as e:  # noqa: BLE001 - one bad event must not stop the collector
            self.skipped += 1
            if self.skipped == 1:
                self.log(f"collector: skipped an event it could not read ({type(e).__name__}: {e}); "
                         "later ones are only counted")

    def _holder(self) -> int | None:
        """The pid of the host that holds the launch, when it is another one."""
        if self._other is not None:
            return self._other
        try:
            held = runtime.launcher(runtime.read(self.project))
        except Exception:  # noqa: BLE001 - unknown: said so
            return None
        return held["pid"] if held and held.get("pid") != os.getpid() else None

    def _holder_says(self) -> str:
        pid = self._holder()
        return f"host {pid}" if pid else "another orchestra run"

    def _following(self) -> str:
        """The collector's state while it follows: counting, or not (another host keeps the counters)."""
        return "following" if self._launching.is_set() else f"following; {self._holder_says()} keeps the counters"

    def _look(self, quiet: QuietWatch) -> None:
        """What the host looks for every ``ERAS_EVERY_S``, whether or not the replay has landed.
        Quiet machines are announced by the host that launches only, so each is announced once."""
        self._eras()
        if self._launching.is_set():
            self._quiet(quiet)
        self._intent()

    def _collect(self, counts: bool | None = None) -> None:
        """Follow the bus and keep the event counters current. The replay at start is retried,
        with a growing pause, until it succeeds; meanwhile the eras, quiet machines and the
        intended model's announcements are still looked at (quiet with an empty watch until the
        replay lands). Only the host that launches counts (``counts``, or else whether it holds
        the launch); one that takes the launch over later replays the bus then and counts from
        there on."""
        if counts is not None:
            (self._launching.set if counts else self._launching.clear)()
        col, quiet, offset = None, QuietWatch(), None
        pending: list[Point] = []                     # counted but not yet written: retried, never counted twice
        eras_at = retry_at = 0.0
        pause = self.collect_every
        while not self._stop.is_set():
            if time.time() - eras_at >= ERAS_EVERY_S:
                eras_at = time.time()
                self._look(quiet)
            if offset is not None and col is None and self._launching.is_set():
                offset = None                             # this host took the launch over: replay, then count
                retry_at, pause = 0.0, self.collect_every
            if offset is None:
                if time.time() >= retry_at:
                    try:
                        col, quiet, offset = self._replay(self._launching.is_set())
                        self._collector_state(self._following())
                    except Exception as e:  # noqa: BLE001 - retried; the looks go on meanwhile
                        why = f"{type(e).__name__}: {e}"
                        self.log(f"collector: replay failed: {why}; retrying in {pause:.0f} s")
                        self._collector_state(f"failing: replay: {why}")
                        retry_at = time.time() + pause
                        pause = min(pause * 2, REPLAY_PAUSE_MAX)
            else:
                try:
                    new, nxt = self.events.after(offset)
                    for ev in new:
                        self._watch(quiet, ev)
                        if col is not None:
                            pending += col.observe(ev)
                    offset = nxt                          # every event of the batch observed and counted
                    if pending:
                        pending = collapse(pending)[-PENDING_MAX:]
                        metrics_for(self.project).write(pending)
                        pending = []
                    self._collector_state(self._following())
                except Exception as e:  # noqa: BLE001 - keep following; the next read retries
                    self.log(f"collector: {type(e).__name__}: {e}")
                    self._collector_state(f"failing: {type(e).__name__}: {e}")
            self._stop.wait(self.collect_every)

    def _quiet(self, watch: QuietWatch) -> None:
        """Announce the machines that fell silent past their own cadence (``orchestra.quiet``)."""
        try:
            for d in watch.check():
                self.events.publish(QUIET, d, subject=d["machine"])
                self.log(f"machine {d['instance'] or d['machine']} quiet for {d['quiet_for']:.0f} s "
                         f"(its usual gap {d['usual_gap']:.0f} s)")
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"quiet: {type(e).__name__}: {e}")

    def _eras(self) -> None:
        """Record the eras begun since the last look, and announce them (``orchestra.sd.eras``);
        record the predictions made since (``orchestra.sd.predictions``)."""
        from .sd import eras, predictions
        from .sd.store import ModelStore
        store = ModelStore.for_state(self.project.state_dir)
        try:
            _, new = eras.sync(store, self.events, self.project.config.eras_from, self.events.publish)
            for e in new:
                self.log(f"era {e.id} began: {e.label}")
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"eras: {type(e).__name__}: {e}")
        try:
            for p in predictions.sync(store, self.events)[1]:
                self.log(f"prediction {p['id']} from {p['source']} about change {p.get('change')}: {p['status']}"
                         + (f" ({p['why']})" if p.get("why") else ""))
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"predictions: {type(e).__name__}: {e}")

    def _intent(self, after_discovery: bool = False) -> None:
        """Announce each accepted call to the declared layer once (``orchestra.intent.changed``,
        ``sd.intended.announce``), also those the web server wrote while the host was down; after
        a discovery or a declaration, write the current structural diff to the cache
        (``sd.intended.diff``)."""
        from .sd.intended.announce import announce
        intended = self.project.intended
        try:
            announced = announce(intended, self.events.publish)
            for seq in announced:
                self.log(f"intended model: d{seq} announced")
            if (after_discovery or announced) and intended.current_version():
                intended.diff(limit_s=0.0)
        except Exception as e:  # noqa: BLE001 - the next look retries
            self.log(f"intended model: {type(e).__name__}: {e}")

    def _judge(self, at: float) -> None:
        """Judge the predictions that are due (``orchestra.sd.judge``) and publish the verdicts."""
        from .sd.judge import judge_due
        for v in judge_due(self.project, metrics_for(self.project), at, self.events.publish, events=self.events,
                           collectors=self._collectors_run()):
            self.log(f"prediction {v['prediction']} judged: {v['verdict']} (era {v['era']})")

    def _announce(self, r) -> None:
        """What is due about the model after a discovery (``orchestra.sd.announce``)."""
        from .sd.announce import announce
        from .sd.history import history, remote_refs, stock_step
        from .sd.store import ModelStore
        from .sd.strategies import sd_installed
        from .sources.catalogue import Catalogue

        cfg = self.project.config
        hist = None
        if r.model.stocks or r.model.flows:         # reading series: stalls need no simulator, divergence does
            store, cat = metrics_for(self.project), Catalogue(self.project, metrics_for(self.project), infer=False)
            span = max(cfg.diverge_after, 3 * cfg.stall_after, 2 * cfg.discovery_every) + 600
            # the remote series once, at discovery's step, over the whole span: what the discovery
            # just read is in its read cache, so only the steps after it are asked for
            read = cat.reader(r.at - span - 300, r.at, cfg.discovery_step, remote_refs(r.model))

            def raw(ref, start, end):
                if ref.source and ref.source != "own":
                    return [(t, v) for t, v in read(ref) if start <= t <= end]
                return store.raw(ref.name, ref.labels, start=start, end=end)
            hist = history(r.model, raw, r.at, stock_step(cfg.discovery_step), span_s=span)
        said = announce(ModelStore.for_state(self.project.state_dir), self.events.publish, r.model, r.at, hist,
                        hold=cfg.announce_hold, gap_s=cfg.announce_gap, after_s=cfg.diverge_after, every_s=cfg.discovery_every,
                        era_start=r.model.discovery.get("era_start"), stall_after=cfg.stall_after,
                        stall_share=cfg.stall_share, diverge=sd_installed() and bool(r.model.stocks))
        if said:
            self.log(f"announced: {', '.join(said)}")

    def _discover(self) -> None:
        """Rediscover the model every interval (``orchestra.sd.rediscover``), then announce what is
        due about it."""
        from .sd import extra
        from .sd.bounded import Stopped
        from .sd.rediscover import Busy, rediscover

        if not extra.installed():
            self.log("discovery: " + extra.message("behaviour trust, divergence and SD Lab's strategies")
                     + "; discovering by conservation only")
        wait = 5.0                                    # soon after starting, then every interval (pace)
        while not self._stop.wait(wait):
            every = self.project.config.discovery_every
            wait, began = every, time.monotonic()
            try:
                r = rediscover(self.project, metrics_for(self.project), skip_if_busy=True, events=self.events,
                               collectors=self._collectors_run())
                took = time.monotonic() - began
                wait = soon(r.model, pace(every, took))
                self.log(discovery_line(r, took, every))
                self._next_look(time.time() + wait)
                if self._stop.is_set():               # stopping: announce, declare and judge nothing more
                    return
                try:
                    self._announce(r)
                except Exception as e:  # noqa: BLE001 - the next discovery tries again
                    self.log(f"announce: {type(e).__name__}: {e}")
                self._intent(after_discovery=True)
                try:
                    self._judge(r.at)
                except Exception as e:  # noqa: BLE001 - the next discovery tries again
                    self.log(f"predictions: {type(e).__name__}: {e}")
            except Stopped:                           # the host stopped mid-discovery: nothing was saved
                self.log("discovery: stopped mid-run; nothing saved")
                return
            except Busy:                              # the CLI or the web page is discovering: theirs will do
                self.log("discovery: skipped, another process is discovering this project")
            except ImportError as e:
                if not extra.missing(e):
                    raise
                self.log("discovery: skipped from now on, " + extra.message("it") + f" ({e.name})")
                return
            except Exception as e:  # noqa: BLE001 - try again next interval
                self.log(f"discovery: {type(e).__name__}: {e}")

    def _next_look(self, at: float) -> None:
        """Say in the runtime record when the next discovery starts (``discovery_next``), so the
        Dynamics page can say when to look again."""
        def put(data: dict) -> None:
            data["discovery_next"] = {"at": round(at, 1), **runtime.me()}
        try:
            runtime.update(self.project, put)
        except OSError as e:
            self.log(f"discovery: could not record the next look ({e})")

    def _from_plugins(self) -> dict[str, tuple[list[Process], list[Collector]]]:
        """What the plugins ask to have run and collected, loaded again whenever orchestra.toml or
        the private overlay changes (the launcher and the collectors both ask; one load serves both): the project's
        config is read again first, since a plugin reads its own sections there. A plugin that
        fails to load keeps what it last declared; a config that does not parse raises, and the
        launcher and the collectors keep their last lists."""
        mtime = self.project.config_stamp()
        if mtime == self._loaded_for:
            return self._declared
        self.project.reload_config()
        loaded = plugins.load(self.project, self._found)
        now = {plug.name: ([replace(p, owner=plug.name) for p in plug.processes],
                           [replace(c, owner=plug.name) for c in plug.collectors]) for plug in loaded.plugins}
        for err in loaded.errors:
            self.log(f"plugin {err['plugin']} failed to load: {err['error']}; what it last declared, if anything, stands")
        for item in loaded.local:
            if item["status"] not in ("applied", "loaded"):
                self.log(f"local {item['kind_of']} {item['name']}: {item['status']}: {item['error']}")
        if loaded.errors:
            now = {**self._declared, **now}
        self._declared, self._loaded_for = now, mtime
        return now

    def _collectors_run(self) -> list[Collector] | None:
        """The plugins' collectors as last loaded for the launcher (discovery reads which are
        simulated from them, never loading the plugins again); None before the first load."""
        if self._loaded_for is None:
            return None
        return [c for _, cs in self._declared.values() for c in cs]

    def _plugin_processes(self) -> list[Process]:
        return [p for procs, _ in self._from_plugins().values() for p in procs]

    def _plugin_collectors(self) -> list[Collector]:
        return [c for _, cs in self._from_plugins().values() for c in cs]

    def _launch(self) -> None:
        """Keep the declared processes running and the declared collectors collecting until the
        host stops, then stop them."""
        served = self._serve_events()
        env = {endpoint.ENV_URL: served.url, endpoint.ENV_TOKEN: served.token} if served else {}
        launcher = Launcher(self.project, self.events.publish, self.log, self._plugin_processes, env=env)
        collecting = Collecting(self.project, self.log, plugin_collectors=self._plugin_collectors)
        launcher.reap_orphans()
        try:
            while not self._stop.is_set():
                try:
                    launcher.tick()
                except Exception as e:  # noqa: BLE001 - keep launching; the next tick retries
                    self.log(f"launcher: {type(e).__name__}: {e}")
                try:
                    collecting.tick()
                except Exception as e:  # noqa: BLE001 - keep collecting; the next tick retries
                    self.log(f"collect: {type(e).__name__}: {e}")
                self._stop.wait(self.launch_every)
        finally:
            collecting.stop()
            launcher.stop_all()
            if served is not None:
                served.stop()

    def _serve_events(self):
        """Start the events endpoint, or say why there is none; the host runs on without it."""
        from .endpoint.server import EventsEndpoint
        try:
            listen = endpoint.listen_address(self.project.config.events_listen)
            if listen is None:
                self.log("events endpoint: off ([events] listen)")
                return None
            ep = EventsEndpoint(self.project, Events.for_project(self.project), listen, endpoint.token(self.project), self.log)
            self.log(f"events endpoint: {ep.start()} (POST /events, GET /events; token in {endpoint.token_file(self.project)})")
            return ep
        except Exception as e:  # noqa: BLE001 - the core stays up without it
            self.log(f"events endpoint: not started: {type(e).__name__}: {e}")
            return None

    def _claim(self) -> int | None:
        """Take the launch for this project, unless a live host holds it; returns that host's pid,
        or None when this host now launches. Checked and set under the lock, so two hosts
        starting together cannot both take it."""
        mine = runtime.me()

        def take(d: dict) -> int | None:
            held = runtime.launcher(d)
            if held and held["pid"] != mine["pid"]:
                return held["pid"]
            d["launcher"] = mine
            return None
        return runtime.update(self.project, take)

    def _take_launch(self) -> threading.Thread | None:
        """Claim the launch; when this host gets it, start the launcher and count the events from
        now on (``_collect`` replays the bus then). None while another live host holds it."""
        other = self._claim()
        if other:
            self._other = other
            return None
        self._other = None
        self._launching.set()
        t = threading.Thread(target=self._launch, name="launcher")
        t.start()
        return t

    def _register(self, d: dict) -> None:
        d["hosts"] = {k: r for k, r in (d.get("hosts") or {}).items() if runtime.holds(r)}
        d["hosts"][str(os.getpid())] = runtime.me()

    def _unregister(self, d: dict) -> None:
        (d.get("hosts") or {}).pop(str(os.getpid()), None)
        if (d.get("launcher") or {}).get("pid") == os.getpid():
            d.pop("launcher")

    def _tell(self, type_: str, data: dict) -> None:
        """Publish one of the host's own events; a bus that is down is logged, and the host starts
        (the collector's replay retries until the bus is back) and stops (unregistering) anyway."""
        try:
            self.events.publish(type_, data)
        except Exception as e:  # noqa: BLE001 - the host runs without the event
            self.log(f"{type_} not published: {type(e).__name__}: {e}")

    def stop(self, *_):
        self._stop.set()

    def run(self, once: bool = False) -> None:
        runtime.update(self.project, self._register)
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGHUP, self.stop)       # a closed terminal stops the processes too
        self._tell("orchestra.host.started", {"pid": os.getpid()})
        self._tell("orchestra.machine.started", {"mode": "continuous", "listens_for": []})
        self.log(f"host started (pid {os.getpid()}) for {self.project.key}")
        launching = discovering = None
        if not once:
            launching = self._take_launch()
            if launching is None:
                self.log(f"launcher: host {self._other} runs this project: it keeps the processes, the instruments, the event "
                         "counters and the quiet announcements; this one follows the bus and rediscovers, starts nothing, "
                         "and takes over if that one stops")
            threading.Thread(target=self._collect, name="collector", daemon=True).start()
            discovering = threading.Thread(target=self._discover, name="discovery", daemon=True)
            discovering.start()
        try:
            while not self._stop.is_set():
                self._beat(1.0)
                if once:
                    break
                if launching is None:                 # the other host may have stopped: take over
                    was = self._other
                    try:
                        launching = self._take_launch()
                    except Exception as e:  # noqa: BLE001 - the next beat tries again
                        self.log(f"launcher: cannot claim: {type(e).__name__}: {e}")
                    if launching is not None:
                        self.log(f"launcher: host {was} stopped; this one takes over: it launches the processes and "
                                 "instruments, counts the events (replaying the bus first) and announces quiet machines")
                self._stop.wait(self.interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            if discovering is not None:
                from .sd.bounded import kill_running
                kill_running()                        # a strategy mid-discovery runs in a session of its own
                discovering.join(timeout=5)
            if launching is not None:
                launching.join()
            self._beat(0.0)
            self._tell("orchestra.host.stopped", {"pid": os.getpid()})
            runtime.update(self.project, self._unregister)
            self.log("host stopped")
