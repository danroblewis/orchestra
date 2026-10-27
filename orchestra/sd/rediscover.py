"""Rediscover the model: discover it from the metrics store over a recent window, with the
configured strategy, cache the result for readers, and save it as a new version when its structure
changed.

One code path for every caller: the bootstrap host (every ``[discovery] every``), ``orchestra sd
discover``, and the Dynamics page's "rediscover" button, which may name another strategy or other
options for that one run. One discovery runs at a time per project, across processes (a lock file
in the state directory): the host skips a scheduled run while another holds it, the others wait.
An SD Lab strategy is given a deadline below ``[discovery] every``, so one run cannot outlast the
interval. The window's ends are on multiples of the step (``aligned``), so runs a few seconds
apart sample the same grid: on a grid shifted by a few seconds a state that lasts a moment is
seen in a different number of steps, and a borderline stock comes and goes between runs.

The series come through one catalogue (``orchestra.sources.catalogue``): the own store's as they
are, and each remote source's read for exactly this window and step. When a source is missing
(refused, unreachable, failing), the model is discovered from what arrived and cached for the
page with the reason, but never saved as a version: a version without a source would delete its
stocks and churn versions with every outage. A run long after the previous one (the machine
slept) reads the whole window again like any other and records the gap."""

from __future__ import annotations

import fcntl
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..metrics import MetricsStore
from ..sources.catalogue import Catalogue
from .discover import structure
from .model import Model
from .provenance import annotate
from .store import ModelStore
from .strategies import CONSERVATION, DEFAULT, discover_with, sd_installed

_lock = threading.Lock()       # one rediscovery at a time per process
DEADLINE_SHARE = 0.8           # of [discovery] every: what an SD Lab strategy may take


class Busy(Exception):
    """Another process is discovering this project's model."""


@dataclass
class Result:
    model: Model
    at: float
    version: int | None        # the new version, when the structure changed
    strategy: str


def configured_strategy(project) -> str:
    s = project.config.discovery_strategy or (DEFAULT if sd_installed() else CONSERVATION)
    return s if s == CONSERVATION or sd_installed() else CONSERVATION


@contextmanager
def discovery_lock(state_dir: Path, *, wait: bool):
    """The project's cross-process discovery lock, held while discovering; ``Busy`` when another
    process holds it and this caller would rather not wait."""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(state_dir) / "discovery.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise Busy("another discovery is running for this project") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def aligned(start: float, end: float, step: float) -> tuple[float, float]:
    """The window ``[start, end]`` moved back to end on the last multiple of ``step`` at or
    before ``end``, as long as it was (to the nearest step)."""
    last = math.floor(end / step) * step
    return last - round((end - start) / step) * step, last


def rediscover(project, metrics: MetricsStore, *, strategy: str | None = None, options: dict | None = None,
               window_s: float | None = None, step_s: float | None = None,
               note: str = "discovered: the structure changed", skip_if_busy: bool = False) -> Result:
    cfg = project.config
    strategy = strategy or configured_strategy(project)
    options = cfg.discovery_options if options is None else options
    window_s = window_s or cfg.discovery_window
    step_s = step_s or cfg.discovery_step
    with _lock, discovery_lock(project.state_dir, wait=not skip_if_busy):
        store = ModelStore.for_state(project.state_dir)
        now = time.time()
        start, end = aligned(now - window_s, now, step_s)
        reading = Catalogue(project, metrics).read(start, end, step_s)
        m = discover_with(reading.dump, start=start, end=end, step=step_s, strategy=strategy, options=options,
                          deadline=DEADLINE_SHARE * cfg.discovery_every, kinds=reading.kinds)
        annotate(m, reading.provenance)
        m.discovery.update(window_s=window_s, step_s=step_s)
        if len(reading.status) > 1 or reading.missing:
            m.discovery["sources"] = reading.status
        if reading.missing:
            m.discovery["not_saved"] = "missing " + "; ".join(f"{k}: {v}" for k, v in reading.missing.items())
        prev = store.latest_discovery()
        if prev and now - prev[0] > 2 * cfg.discovery_every:
            m.discovery["since_last_s"] = round(now - prev[0])      # the machine slept, or nothing ran: this window was read whole, as always
        store.write_discovery(m, at=now)
        cur = store.load()
        changed = m.stocks and (cur is None or structure(cur) != structure(m))
        version = store.save(m, note=f"{note} ({strategy})") if changed and not reading.missing else None
        return Result(m, now, version, strategy)
