"""Rediscover the model: discover it from the metrics store over a recent window, with the
configured strategy, cache the result for readers, and save it as a new version when its structure
changed.

One code path for every caller: the bootstrap host (every ``[discovery] every``), ``orchestra sd
discover``, and the Dynamics page's "rediscover" button, which may name another strategy or other
options for that one run."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..metrics import MetricsStore
from .discover import structure
from .model import Model
from .store import ModelStore
from .strategies import CONSERVATION, DEFAULT, discover_with, sd_installed

_lock = threading.Lock()       # one rediscovery at a time per process


@dataclass
class Result:
    model: Model
    at: float
    version: int | None        # the new version, when the structure changed
    strategy: str


def configured_strategy(project) -> str:
    s = project.config.discovery_strategy or (DEFAULT if sd_installed() else CONSERVATION)
    return s if s == CONSERVATION or sd_installed() else CONSERVATION


def rediscover(project, metrics: MetricsStore, *, strategy: str | None = None, options: dict | None = None,
               window_s: float | None = None, step_s: float | None = None,
               note: str = "discovered: the structure changed") -> Result:
    cfg = project.config
    strategy = strategy or configured_strategy(project)
    options = cfg.discovery_options if options is None else options
    window_s = window_s or cfg.discovery_window
    step_s = step_s or cfg.discovery_step
    with _lock:
        store = ModelStore.for_state(project.state_dir)
        end = time.time()
        m = discover_with(metrics.dump("", {"project": project.key}), start=end - window_s, end=end, step=step_s,
                          strategy=strategy, options=options)
        m.discovery.update(window_s=window_s, step_s=step_s)
        store.write_discovery(m, at=end)
        cur = store.load()
        version = store.save(m, note=f"{note} ({strategy})") if m.stocks and (cur is None or structure(cur) != structure(m)) else None
        return Result(m, end, version, strategy)
