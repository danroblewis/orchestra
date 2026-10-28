"""The web server's background reads, so no page request does expensive work.

Two threads keep these caches warm: one the bus, the own store and the levels read from it, the
other everything read from another store (counted traffic, the levels of stocks bound to a
remote series, and the history, which may read remotes), so the index and the own store's
levels never wait on a remote source, which may take up to its timeout:
- the **machine index** (``machines.MachineIndex``), following the bus every few seconds, and
  one for the current era alone (``sd.eras``: its events since the era began), started again
  when an era begins; a past era's is built when first asked for (``era_index``) and kept;
- each machine's **flow hypotheses** from the latest discovery, every minute. The Machines page
  reads no metrics: a machine is seen, and active, by its events alone (``machines.py``);
- the **current levels** of the model's stocks, every few seconds;
- the model's **recent history**: each stock's level and each flow's rate over the last
  ``HISTORY_S``, for the Dynamics page's sparklines, charts and flow animation. Levels are
  sampled at the project's discovery step when that is finer than ``STOCK_STEP_S``, so the
  chart shows the levels discovery saw (a level held for four seconds is a stock on a 5 s grid
  and invisible on a 15 s one).

- **counted traffic** (``traffic.py``): every series a source's definitions mark as traffic, read
  through the catalogue over the last hour every minute, for the Machines page's counted machines,
  channels and edges.

A stock or flow bound to a series in another store (``SeriesRef.source``, from ``[[sources]]``)
is read through the sources' catalogue (``orchestra.sources.catalogue``), and **only while a page
asks for it**: an endpoint that shows remote levels, history or counted traffic calls ``want``,
and the reads go on for ``WANT_S`` after the last ask; with no page open, no other store is read.
Each round reads every bound definition at once (one ``read_many`` per source, at discovery's
step: the levels discovery saw), from the web server's own share of the store's rate and daily
cap under a small budget (``Catalogue(share=True)``), and asks only for what is newer than what it
holds: the host's last discovery's reads first (``readcache.py``), then the steps since its own
last round. Levels and history come from the same round. A round the store throttles (a 429)
doubles the time to the next, up to ``REMOTE_MAX_EVERY_S``; a round without one restores it. A
source that fails leaves its stocks without a level and records why (``errors["source <name>"]``);
every other stock's level and history still update.

Endpoints read the caches and report how old they are. The model itself is rediscovered by the
bootstrap host, not here (``orchestra.host``); this only reads what the host cached, and so are a
source's definitions: the catalogue here never starts an inference round (``sources.cache``)."""

from __future__ import annotations

import threading
import time
from itertools import pairwise

from ..metrics import step_sample
from ..sd import eras as era_record
from ..sd.model import SeriesRef
from ..sd.store import ModelStore
from ..sources.catalogue import Catalogue
from .machines import MachineIndex, flow_hypotheses
from .traffic import READ_S, READ_STEP_S, summarise

INDEX_EVERY_S = 5.0
FLOWS_EVERY_S = 60.0
COUNTED_EVERY_S = 60.0
LEVELS_EVERY_S = 15.0
HISTORY_EVERY_S = 15.0
REMOTE_EVERY_S = 15.0        # remote levels and history, while a page asks for them
REMOTE_MAX_EVERY_S = 300.0   # ... at most this far apart when the store throttles
WANT_S = 120.0               # how long a page's ask keeps remote reads going
HISTORY_S = 3600.0
STOCK_STEP_S = 15.0          # at most: finer when the project's discovery step is
FLOW_STEP_S = 30.0


class Refresher:
    def __init__(self, project, events, metrics):
        self.project = project
        self.metrics = metrics
        self.events = events
        self.index = MachineIndex(events)
        self.era: str | None = None                         # the current era, and its own index (the same as index before any era)
        self.era_idx = self.index
        self.past: dict[str | None, MachineIndex] = {}      # past eras' indexes, built when asked for
        self.models = ModelStore.for_state(project.state_dir)
        self.flows: dict[str, list[dict]] = {}   # each machine's hypothesised flows in the latest discovery
        self.own_levels: dict[str, dict] = {}
        self.remote_levels: dict[str, dict] = {}
        self.history: dict = {}
        self.counted: dict | None = None                    # counted traffic, summarised (traffic.summarise)
        self.at: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        self.catalogue = Catalogue(project, metrics, infer=False, share=True)    # reads the host's inference, never starts one
        self.wanted: dict[str, float] = {}                  # "remote", "counted" -> when a page last asked for them
        self.remote_every = REMOTE_EVERY_S
        self._remote = None                                 # (start, end, read) of the last remote round
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="web-refresher", daemon=True).start()
        threading.Thread(target=self._run_remote, name="web-refresher-sources", daemon=True).start()

    def want(self, what: str = "remote") -> None:
        """A page shows remote levels and history (``remote``) or counted traffic (``counted``):
        read them while it does."""
        self.wanted[what] = time.time()

    def _wanted(self, what: str) -> bool:
        return time.time() - self.wanted.get(what, float("-inf")) < WANT_S

    @property
    def levels(self) -> dict[str, dict]:
        return {**self.own_levels, **self.remote_levels}

    @property
    def levels_error(self) -> str | None:
        """Why some levels are missing: a read of them failing, or a source of the model's series."""
        failed = [f"{k}: {v}" for k, v in list(self.errors.items()) if k in ("levels", "remote_levels") or k.startswith("source ")]
        return "; ".join(failed) or None

    def _do(self, name: str, every: float, fn) -> None:
        if time.time() - self.at.get(name, 0.0) < every:
            return
        try:
            fn()
            self.errors.pop(name, None)
        except Exception as e:  # noqa: BLE001 - shown on the page; tried again next round
            self.errors[name] = f"{type(e).__name__}: {e}"
        self.at[name] = time.time()

    def _index(self) -> None:
        """Follow the bus: the whole of it, and the current era's part."""
        self.index.update()
        cur = era_record.current(era_record.recorded(self.models), time.time())
        if (cur.id if cur else None) != self.era:
            self.era, self.era_idx = (cur.id, MachineIndex(self.events, since=cur.start)) if cur else (None, self.index)
        if self.era_idx is not self.index:
            self.era_idx.update()

    def era_index(self, era: str | None) -> MachineIndex | None:
        """The index of an era's events (``"all"``: every event; None: the current era); None
        when there is no such era. A past era's is read from the bus once, then kept."""
        if era is None or era == self.era:
            return self.era_idx
        if era == "all":
            return self.index
        eras = era_record.recorded(self.models)
        if era == "none":                           # the time before the first era
            key, since, until = None, None, (eras[0].start if eras else None)
        else:
            e = next((x for x in eras if x.id == era), None)
            if e is None:
                return None
            nxt = next((x.start for x in eras if x.start > e.start), None)
            key, since, until = era, e.start, nxt
        if key not in self.past:
            idx = MachineIndex(self.events, since=since, until=until)
            idx.update()
            self.past[key] = idx
        return self.past[key]

    def _flows(self) -> None:
        latest = self.models.latest_discovery()
        self.flows = flow_hypotheses(latest[1] if latest else None)

    def _counted(self) -> None:
        if not self.catalogue.specs.sources:
            return
        now = time.time()
        got, failed = self.catalogue.counted(now - READ_S, now, READ_STEP_S)
        self.counted = {**summarise(got, now), "failed": failed}

    def model(self):
        cached = self.models.latest_discovery()
        return cached[1] if cached and cached[1].stocks else self.models.load()

    def raw_for_round(self):
        """``raw(ref, start, end)``: a series' points in [start, end], from the own store, or, for
        a remote series, from the last remote round (``_remote_round``): never a read of its own."""
        remote = self._remote

        def raw(ref, start: float, end: float) -> list[tuple[float, float]]:
            if ref.source and ref.source != "own":
                if remote is None:
                    return []
                return [(t, v) for t, v in remote[2](ref) if start <= t <= end]
            return self.metrics.raw(ref.name, ref.labels, start=start, end=end)
        return raw

    def _note_sources(self) -> None:
        """The catalogue's source errors, as ``errors["source <name>"]``."""
        for k in [k for k in list(self.errors) if k.startswith("source ")]:
            if k.removeprefix("source ") not in self.catalogue.errors:
                self.errors.pop(k, None)
        for name, why in list(self.catalogue.errors.items()):
            self.errors[f"source {name}"] = why

    def _levels(self) -> None:
        """The levels of the stocks bound to the own store."""
        model = self.model()
        out = {}
        if model is not None and self.metrics is not None:
            for s in model.stocks:
                if s.series and s.series.source in (None, "own") and (last := self.metrics.latest(s.series.name, s.series.labels)):
                    out[s.id] = {"t": last[0], "v": last[1]}
        self.own_levels = out

    def _remote_round(self) -> None:
        """Every remote series the model is bound to, over the history's window, in one round per
        source (``Catalogue.reader`` with the refs), asking only for what is newer than what is
        held; then the levels of the stocks bound to them. A 429 slows the next round."""
        model = self.model()
        refs = remote_refs(model) if model is not None else []
        if not refs:
            self._remote, self.remote_levels = None, {}
            return
        now = time.time()
        before = sum(src.throttled for src in self.catalogue.remotes.values())
        read = self.catalogue.reader(now - HISTORY_S - 300, now, self.project.config.discovery_step, refs)
        self._remote = (now - HISTORY_S - 300, now, read)
        throttled = sum(src.throttled for src in self.catalogue.remotes.values()) - before
        self.remote_every = min(REMOTE_MAX_EVERY_S, 2 * self.remote_every) if throttled else REMOTE_EVERY_S
        out = {}
        raw = self.raw_for_round()
        for s in model.stocks:
            if s.series and s.series.source not in (None, "own") and (pts := raw(s.series, now - 900, now)):
                out[s.id] = {"t": pts[-1][0], "v": pts[-1][1]}
        self._note_sources()
        self.remote_levels = out
        self.at.pop("history", None)                # the history takes the new reads in at once

    def _history(self) -> None:
        """Each stock's level every ``stock_step``, and each flow's rate (per the model's time
        unit) every FLOW_STEP_S, over the last HISTORY_S."""
        model = self.model()
        if model is None or self.metrics is None:
            self.history = {}
            return
        self.history = history(model, self.raw_for_round(), time.time(), stock_step(self.project.config.discovery_step))
        self._note_sources()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._do("index", INDEX_EVERY_S, self._index)
            self._do("flows", FLOWS_EVERY_S, self._flows)
            self._do("levels", LEVELS_EVERY_S, self._levels)
            self._stop.wait(1.0)

    def _run_remote(self) -> None:
        while not self._stop.is_set():
            if self.catalogue.specs.sources and self._wanted("counted"):
                self._do("counted", max(COUNTED_EVERY_S, self.remote_every), self._counted)
            if self.catalogue.specs.sources and self._wanted("remote"):
                self._do("remote_levels", self.remote_every, self._remote_round)
            self._do("history", HISTORY_EVERY_S, self._history)
            self._stop.wait(1.0)

    def ready(self, name: str) -> bool:
        return name in self.at

    def stop(self) -> None:
        self._stop.set()


def remote_refs(model) -> list:
    """The series in other stores the model's stocks, flows and measured inputs are bound to."""
    refs = [s.series for s in model.stocks if s.series]
    for f in model.flows:
        refs += f.measured_by or ([f.counter] if f.counter else [])
    refs += [SeriesRef(r["name"], r["labels"], source=r.get("source")) for r in (model.discovery.get("inputs") or {}).values()]
    return [r for r in refs if r.source and r.source != "own"]


def stock_step(discovery_step: float) -> float:
    """How often the history samples a level: discovery's own grid when it is finer."""
    return min(STOCK_STEP_S, discovery_step) if discovery_step > 0 else STOCK_STEP_S


def history(model, raw, end: float, stock_step: float = STOCK_STEP_S, span_s: float = HISTORY_S,
            flow_step: float | None = None) -> dict:
    """The model's history over the ``span_s`` (HISTORY_S) before ``end``: each stock's level every
    ``stock_step``, each flow's rate every ``flow_step`` (FLOW_STEP_S), and the measured inputs the
    equations read. ``raw(ref, start, end)`` reads one series' points."""
    start = end - span_s
    fstep = float(flow_step or FLOW_STEP_S)
    unit = {"second": 1.0, "minute": 60.0, "hour": 3600.0}.get(model.time_unit, 60.0)
    stocks, flows = {}, {}
    for s in model.stocks:
        if s.series:
            pts = raw(s.series, start - 300, end)
            t0 = start - start % stock_step
            stocks[s.id] = [[round(t), v] for t, v in step_sample(pts, t0, end, stock_step)]
    for f in model.flows:
        refs = f.measured_by or ([f.counter] if f.counter else [])
        total: dict[int, float] = {}
        for c in refs:                     # a flow measured by several counters: their sum
            pts = raw(c, start - 300, end)
            t0 = start - start % fstep
            for a, b in pairwise(step_sample(pts, t0, end, fstep)):
                total[round(b[0])] = total.get(round(b[0]), 0.0) + ((b[1] - a[1]) if b[1] >= a[1] else b[1]) * unit / fstep
        if refs:
            flows[f.id] = [[t, v] for t, v in sorted(total.items())]
    # measured inputs the model's equations read (levels that are not stocks)
    inputs = {}
    for name, ref in (model.discovery.get("inputs") or {}).items():
        pts = raw(SeriesRef(ref["name"], ref["labels"], source=ref.get("source")), start - 300, end)
        t0 = start - start % stock_step
        inputs[name] = [[round(t), v] for t, v in step_sample(pts, t0, end, stock_step)]
    return {"at": end, "start": start, "stock_step": stock_step, "flow_step": fstep,
            "time_unit": model.time_unit, "stocks": stocks, "flows": flows, "inputs": inputs}
