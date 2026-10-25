"""Rediscover the model: discover it from the metrics store over a recent window, cache the
result for readers, and save it as a new version when its structure changed.

One code path for every caller: the bootstrap host (every few minutes), ``orchestra sd
discover``, and the Dynamics page's "rediscover now" button."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from ..metrics import MetricsStore
from .discover import discover, structure
from .model import Model
from .store import ModelStore

WINDOW_S = 3600.0
STEP_S = 30.0
_lock = threading.Lock()       # one rediscovery at a time per process


@dataclass
class Result:
    model: Model
    at: float
    version: int | None        # the new version, when the structure changed


def rediscover(project, metrics: MetricsStore, *, window_s: float = WINDOW_S, step_s: float = STEP_S,
               note: str = "discovered: the structure changed") -> Result:
    with _lock:
        store = ModelStore.for_state(project.state_dir)
        end = time.time()
        m = discover(metrics.dump("", {"project": project.key}), start=end - window_s, end=end, step=step_s)
        store.write_discovery(m, at=end)
        cur = store.load()
        version = store.save(m, note=note) if m.stocks and (cur is None or structure(cur) != structure(m)) else None
        return Result(m, end, version)
