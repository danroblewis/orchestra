"""The web server's background reads, so no page request does expensive work.

One thread keeps three caches warm:
- the **machine index** (``machines.MachineIndex``), following the bus every few seconds;
- the project's **series list** from the metrics store (an export on VictoriaMetrics), every
  minute;
- the **current levels** of the model's stocks, every few seconds.

Endpoints read the caches and report how old they are. The model itself is rediscovered by the
bootstrap host, not here (``orchestra.host``); this only reads what the host cached."""

from __future__ import annotations

import threading
import time

from ..sd.store import ModelStore
from .machines import MachineIndex

INDEX_EVERY_S = 5.0
SERIES_EVERY_S = 60.0
LEVELS_EVERY_S = 15.0


class Refresher:
    def __init__(self, project, events, metrics):
        self.project = project
        self.metrics = metrics
        self.index = MachineIndex(events)
        self.models = ModelStore.for_state(project.state_dir)
        self.series: list[tuple[str, dict]] = []
        self.levels: dict[str, dict] = {}
        self.at: dict[str, float] = {}
        self.errors: dict[str, str] = {}
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
            self.series = [(n, lab) for n, lab in self.metrics.series("") if lab.get("project") == self.project.key]

    def _levels(self) -> None:
        cached = self.models.latest_discovery()
        model = cached[1] if cached else self.models.load()
        out = {}
        if model is not None and self.metrics is not None:
            for s in model.stocks:
                if s.series:
                    last = self.metrics.latest(s.series.name, s.series.labels)
                    if last:
                        out[s.id] = {"t": last[0], "v": last[1]}
        self.levels = out

    def _run(self) -> None:
        while not self._stop.is_set():
            self._do("index", INDEX_EVERY_S, self.index.update)
            self._do("series", SERIES_EVERY_S, self._series)
            self._do("levels", LEVELS_EVERY_S, self._levels)
            self._stop.wait(1.0)

    def ready(self, name: str) -> bool:
        return name in self.at

    def stop(self) -> None:
        self._stop.set()
