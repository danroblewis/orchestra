"""One round of a collector: its text fetched, parsed, and turned into the points to write.

Every point gets the ``project`` label and ``machine = <the collector's name>``, replacing any the
text gave (the collector is the machine that measured it). A point without a timestamp takes the
time the round began. A series whose name starts with ``orchestra_`` is refused: the prefix is
Orchestra's own. Several values of one series in one round keep only the last."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..collectors import collapse
from ..metrics import Point
from .exposition import parse
from .fetch import Failed, fetch_url, run_command
from .spec import Collector

PREFIX = "orchestra_"


@dataclass
class Round:
    points: list[Point] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)              # names starting with orchestra_, once each
    bad: list[tuple[int, str]] = field(default_factory=list)      # lines not understood: (line number, why)
    left_out: list[str] = field(default_factory=list)             # a histogram's or summary's other series, non-numbers
    error: str | None = None                                      # why the round wrote nothing


def points_of(c: Collector, text: str, project: str, now: float) -> Round:
    parsed = parse(text)
    out = Round(bad=parsed.bad, left_out=parsed.left_out)
    points: list[Point] = []
    for s in parsed.samples:
        if s.name.startswith(PREFIX):
            if s.name not in out.refused:
                out.refused.append(s.name)
            continue
        ts = s.ts_ms / 1000 if s.ts_ms is not None else now
        points.append(Point(s.name, s.value, ts, {**s.labels, "project": project, "machine": c.name}))
    out.points = collapse(points)
    return out


def collect(c: Collector, repo: Path, project: str, log: Path, stop: threading.Event | None = None) -> Round:
    """Run the collector once: its points, or the error that left it with none."""
    now = time.time()
    try:
        text = run_command(c, repo, log, stop) if c.kind == "collect" else fetch_url(c)
    except Failed as e:
        return Round(error=str(e))
    return points_of(c, text, project, now)
