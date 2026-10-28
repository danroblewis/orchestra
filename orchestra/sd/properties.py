"""What a level's name, unit and source say it is when it is no store at all, so discovery never
takes it for a stock:

- **A statistic** of something (``statistic``): a maximum, a minimum, a mean, a median or a
  percentile (a name word in ``STATISTICS``, or ``p50``, ``p95``…), or what its source summarised
  across reporters (``sd.series.Declared.summary``: a ``max by``, an average). It summarises what is
  there and holds nothing. A maximum over partitions is not conserved: when one partition drains
  and another fills, the maximum jumps from one to the other, and no flow carries the jump. It is
  never a stock, by a balance or by a net flow; its series stays readable as anything's driver.
- **A resource a process or host uses** (``resource``): its CPU (in use, a load average, a
  utilisation), its memory, threads, file descriptors or garbage collection (a name word in
  ``RESOURCE``), or any utilisation (a unit of ``ratio`` or ``percent``). It is a property of a
  running process, set at each moment by the work it does, not an accumulation: it holds nothing
  that came in and has yet to leave. A net flow is not tried on it (``sd.netflow``): what moves it
  is the work, so a fit to the work's series explains it as well as any stock's and says nothing.
  A balance may still make it a stock when counters of its own (threads started and ended)
  account for it exactly; that is evidence, which a fitted net flow is not."""

from __future__ import annotations

import re

STATISTICS = {"mean", "avg", "average", "median", "max", "min", "maximum", "minimum", "peak"}
RESOURCE = {"cpu", "cpus", "load1", "load5", "load15", "loadavg", "memory", "heap", "nonheap", "rss", "threads", "fds", "gc",
            "utilisation", "utilization"}
UTILISATION = {"ratio", "percent"}


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[:_]", name.lower()) if w]


def statistic(name: str, summary: bool = False) -> bool:
    """Whether a level is a statistic of something: its source said so (``summary``), or a word of
    its name (a maximum, a mean, a percentile such as ``p95``)."""
    return summary or any(w in STATISTICS or (len(w) in (3, 4) and w[0] == "p" and w[1:].isdigit()) for w in _words(name))


def resource(name: str, unit: str | None = None) -> bool:
    """Whether a level measures a resource a process or host uses (``RESOURCE``, or a utilisation)."""
    return unit in UTILISATION or bool(set(_words(name)) & RESOURCE)
