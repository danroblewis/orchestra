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
slept) reads the whole window again like any other and records the gap.

**Eras** (``sd.eras``, ``sd.prior``). The window never reaches back past the start of the current
era: after a machine changed the system, what came before is not evidence for it. Given the bus
(``events``: the host, ``orchestra sd discover``), the eras are brought up to date from it first
and each new one is announced (``orchestra.era.started``); otherwise (the web page's button) the
eras the host recorded are used. When the era is new since the last discovery, that discovery
(the previous era's last model) is saved as a version first, so the past era stays readable. What
was found in the era is then merged with its prior, the latest version of another era
(``sd.prior.merge``), compared with it (``sd.compare``: ``discovery["era_comparison"]``), and
saved as a version when its structure changed or it is the era's first. An era younger than two
steps is not discovered: its model is its prior, carried whole. With no era (no change was ever
announced) nothing of this applies, and discovery is exactly as before."""

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
from . import eras as era_record
from .compare import compare
from .discover import structure
from .model import Model
from .prior import merge
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


def era_window(start: float, end: float, step: float, era_start: float | None) -> float:
    """The window's start, moved forward to the era's start (on the grid) when the era is younger."""
    if era_start is None or era_start <= start:
        return start
    return min(end, math.ceil(era_start / step) * step)


def rediscover(project, metrics: MetricsStore, *, strategy: str | None = None, options: dict | None = None,
               window_s: float | None = None, step_s: float | None = None,
               note: str = "discovered: the structure changed", skip_if_busy: bool = False,
               events=None, now: float | None = None) -> Result:
    cfg = project.config
    strategy = strategy or configured_strategy(project)
    options = cfg.discovery_options if options is None else options
    window_s = window_s or cfg.discovery_window
    step_s = step_s or cfg.discovery_step
    with _lock, discovery_lock(project.state_dir, wait=not skip_if_busy):
        store = ModelStore.for_state(project.state_dir)
        if events is not None:
            eras, _ = era_record.sync(store, events, cfg.eras_from, events.publish)
        else:
            eras = era_record.recorded(store)
        now = time.time() if now is None else now
        era = era_record.current(eras, now)
        start, end = aligned(now - window_s, now, step_s)
        start = era_window(start, end, step_s, era.start if era else None)
        if era is None or end - start >= 2 * step_s:
            reading = Catalogue(project, metrics).read(start, end, step_s)
            m = discover_with(reading.dump, start=start, end=end, step=step_s, strategy=strategy, options=options,
                              deadline=DEADLINE_SHARE * cfg.discovery_every, kinds=reading.kinds)
            annotate(m, reading.provenance)
        else:                                   # the era is too young to read: its prior, carried whole
            reading = None
            m = Model("system", "The system", "The era is too young to discover: its prior, carried.")
            m.discovery = {"start": start, "end": end, "step": step_s, "left_out": {}, "too_young": True}
        m.discovery.update(window_s=window_s, step_s=step_s)
        m.eras, m.era = eras, era.id if era else None
        for f in m.flows:
            for e in f.equations:
                e.era = m.era
        prev = store.latest_discovery()
        if era is not None:
            if prev and prev[1].era != m.era and prev[1].stocks and not prev[1].discovery.get("not_saved"):
                store.save(prev[1], note=f"the last model of {'era ' + prev[1].era if prev[1].era else 'the time before any era'}")
            prior = store.prior_for(m.era)
            if prior is not None:
                m = merge(m, prior, age_s=now - era.start, keep_s=cfg.prior_for or window_s)
                m.discovery["era_comparison"] = compare(prior, m)
            m.discovery["era_start"] = era.start
        if reading is None:
            store.write_discovery(m, at=now)
            cur = store.load()
            version = store.save(m, note=f"era {m.era} began: its prior") if m.stocks and (cur is None or cur.era != m.era) else None
            return Result(m, now, version, strategy)
        if len(reading.status) > 1 or reading.missing:
            m.discovery["sources"] = reading.status
        if reading.missing:
            m.discovery["not_saved"] = "missing " + "; ".join(f"{k}: {v}" for k, v in reading.missing.items())
        prev = store.latest_discovery()
        if prev and now - prev[0] > 2 * cfg.discovery_every:
            m.discovery["since_last_s"] = round(now - prev[0])      # the machine slept, or nothing ran: this window was read whole, as always
        store.write_discovery(m, at=now)
        cur = store.load()
        changed = m.stocks and (cur is None or structure(cur) != structure(m) or cur.era != m.era)
        version = store.save(m, note=f"{note} ({strategy})") if changed and not reading.missing else None
        return Result(m, now, version, strategy)
