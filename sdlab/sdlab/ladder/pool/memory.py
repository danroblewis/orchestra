"""An item's expected peak memory (MB), for admission: 1.2 x the largest peak RSS recorded for its case and
strategy, else for its case under any strategy, else a conservative default by tag. An earlier run of 20
workers of sd-k8s-small (~10 GB each) ran node2 (62 GB) out of memory and crashed every run: the
defaults assume the worst of a tag until a peak is measured."""

from __future__ import annotations

import sqlite3

FACTOR = 1.2
MARGIN_MB = 1024           # kept free beyond the expected peaks
RETRY_FACTOR = 1.25        # a crashed item's retry needs this much more memory than it had (accept.py)
DEFAULTS = (("heavy", 16000.0), ("realistic", 10000.0), ("physics", 3000.0), ("particles", 3000.0),
            ("canonical", 3000.0), ("real", 3000.0))
DEFAULT_MB = 1000.0
CAP_SHARE = 0.9            # no item is expected to need more than this share of the biggest worker's budget


def biggest_budget(con: sqlite3.Connection) -> float | None:
    """The largest budget (MB) any registered worker promises (its heartbeat's budget_mb, else 85% of its memory)."""
    return con.execute("SELECT MAX(CAST(COALESCE(json_extract(info, '$.budget_mb'), 0.85 * json_extract(info, '$.mem_total_mb')) AS REAL))"
                       " FROM pool_workers").fetchone()[0]


def capped(mb: float, biggest: float | None) -> float:
    """An expectation no worker could ever admit (a peak recorded by an item killed at a big machine's limit, say)
    would leave its item queued for ever: it is capped where the biggest worker can take it (and its hard limit
    stops it there)."""
    return min(mb, CAP_SHARE * biggest) if biggest else mb


class Peaks:
    """The recorded peaks, read once (per claim)."""

    def __init__(self, con: sqlite3.Connection):
        self.cell: dict[tuple[str, str], float] = {}
        self.case: dict[str, float] = {}
        for cid, strategy, mb in con.execute("SELECT case_id, strategy, MAX(peak_rss_mb) FROM pool_results"
                                             " WHERE peak_rss_mb IS NOT NULL GROUP BY case_id, strategy"):
            self.cell[(cid, strategy)] = mb
            self.case[cid] = max(self.case.get(cid, 0.0), mb)

    def expected(self, case: str, strategy: str, tags: list[str] | None) -> float:
        got = self.cell.get((case, strategy)) or self.case.get(case)
        if got:
            return round(FACTOR * got, 1)
        return default(tags)


def default(tags: list[str] | None) -> float:
    t = set(tags or [])
    for tag, mb in DEFAULTS:
        if tag in t:
            return mb
    return DEFAULT_MB
