"""The web server's background reads, so no page request does expensive work.

One thread keeps three caches warm:
- the **machine index** (``machines.MachineIndex``), following the bus every few seconds;
- the project's **series list** from the metrics store (an export on VictoriaMetrics), every
  minute, with the latest write of each machine's series, which the Machines page counts as
  seeing the machine;
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
is read through the sources' catalogue (``orchestra.sources.catalogue``) for the same window.

Endpoints read the caches and report how old they are. The model itself is rediscovered by the
bootstrap host, not here (``orchestra.host``); this only reads what the host cached."""

from __future__ import annotations

import threading
import time
from itertools import pairwise

from ..metrics import step_sample
from ..sd.model import SeriesRef
from ..sd.store import ModelStore
from ..sources.catalogue import Catalogue
from .machines import MachineIndex, last_writes
from .traffic import READ_S, READ_STEP_S, summarise

INDEX_EVERY_S = 5.0
SERIES_EVERY_S = 60.0
COUNTED_EVERY_S = 60.0
LEVELS_EVERY_S = 15.0
HISTORY_EVERY_S = 15.0
HISTORY_S = 3600.0
STOCK_STEP_S = 15.0          # at most: finer when the project's discovery step is
FLOW_STEP_S = 30.0


class Refresher:
    def __init__(self, project, events, metrics):
        self.project = project
        self.metrics = metrics
        self.index = MachineIndex(events)
        self.models = ModelStore.for_state(project.state_dir)
        self.series: list[tuple[str, dict]] = []
        self.written: dict[tuple[str, str], float] = {}     # (machine, instance) -> its latest write
        self.levels: dict[str, dict] = {}
        self.history: dict = {}
        self.counted: dict | None = None                    # counted traffic, summarised (traffic.summarise)
        self.at: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        self.catalogue = Catalogue(project, metrics)
        self._stop = threading.Event()
        threading.Thread(target=self._run, name="web-refresher", daemon=True).start()

    def _do(self, name: str, every: float, fn) -> None:
        if time.time() - self.at.get(name, 0.0) < every:
            return
        try:
            fn()
            self.errors.pop(name, None)
        except Exception as e:  # noqa: BLE001 - shown on the page; tried again next round
            self.errors[name] = f"{type(e).__name__}: {e}"
        self.at[name] = time.time()

    def _series(self) -> None:
        if self.metrics is not None:
            dumped = self.metrics.dump("", {"project": self.project.key})
            self.series = [(name, labels) for name, labels, _ in dumped]
            self.written = last_writes(dumped)

    def _counted(self) -> None:
        if not self.catalogue.specs.sources:
            return
        now = time.time()
        got, failed = self.catalogue.counted(now - READ_S, now, READ_STEP_S)
        self.counted = {**summarise(got, now), "failed": failed}

    def model(self):
        cached = self.models.latest_discovery()
        return cached[1] if cached and cached[1].stocks else self.models.load()

    def _history(self) -> None:
        """Each stock's level every ``stock_step``, and each flow's rate (per the model's time
        unit) every FLOW_STEP_S, over the last HISTORY_S."""
        model = self.model()
        if model is None or self.metrics is None:
            self.history = {}
            return
        self.history = history(model, self.raw, time.time(), stock_step(self.project.config.discovery_step))

    def raw(self, ref, start: float, end: float) -> list[tuple[float, float]]:
        """A series' points in [start, end]: from the own store, or through its source."""
        if ref.source and ref.source != "own":
            return self.catalogue.read_ref(ref, start, end, stock_step(self.project.config.discovery_step))
        return self.metrics.raw(ref.name, ref.labels, start=start, end=end)

    def _levels(self) -> None:
        model = self.model()
        out = {}
        if model is not None and self.metrics is not None:
            now = time.time()
            for s in model.stocks:
                if s.series:
                    pts = self.raw(s.series, now - 900, now) if s.series.source not in (None, "own") else None
                    last = (pts[-1] if pts else None) if pts is not None else self.metrics.latest(s.series.name, s.series.labels)
                    if last:
                        out[s.id] = {"t": last[0], "v": last[1]}
        self.levels = out

    def _run(self) -> None:
        while not self._stop.is_set():
            self._do("index", INDEX_EVERY_S, self.index.update)
            self._do("series", SERIES_EVERY_S, self._series)
            self._do("counted", COUNTED_EVERY_S, self._counted)
            self._do("levels", LEVELS_EVERY_S, self._levels)
            self._do("history", HISTORY_EVERY_S, self._history)
            self._stop.wait(1.0)

    def ready(self, name: str) -> bool:
        return name in self.at

    def stop(self) -> None:
        self._stop.set()


def stock_step(discovery_step: float) -> float:
    """How often the history samples a level: discovery's own grid when it is finer."""
    return min(STOCK_STEP_S, discovery_step) if discovery_step > 0 else STOCK_STEP_S


def history(model, raw, end: float, stock_step: float = STOCK_STEP_S) -> dict:
    """The model's history over the HISTORY_S before ``end``: each stock's level every
    ``stock_step``, each flow's rate every FLOW_STEP_S, and the measured inputs the equations read.
    ``raw(ref, start, end)`` reads one series' points."""
    start = end - HISTORY_S
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
            t0 = start - start % FLOW_STEP_S
            for a, b in pairwise(step_sample(pts, t0, end, FLOW_STEP_S)):
                total[round(b[0])] = total.get(round(b[0]), 0.0) + ((b[1] - a[1]) if b[1] >= a[1] else b[1]) * unit / FLOW_STEP_S
        if refs:
            flows[f.id] = [[t, v] for t, v in sorted(total.items())]
    # measured inputs the model's equations read (levels that are not stocks)
    inputs = {}
    for name, ref in (model.discovery.get("inputs") or {}).items():
        pts = raw(SeriesRef(ref["name"], ref["labels"], source=ref.get("source")), start - 300, end)
        t0 = start - start % stock_step
        inputs[name] = [[round(t), v] for t, v in step_sample(pts, t0, end, stock_step)]
    return {"at": end, "start": start, "stock_step": stock_step, "flow_step": FLOW_STEP_S,
            "time_unit": model.time_unit, "stocks": stocks, "flows": flows, "inputs": inputs}
