"""An item's expected peak memory (MB), for admission: 1.2 x the largest peak RSS recorded for its case and
strategy, else for its case under any strategy, else a conservative default by tag. An earlier run of 20
workers of sd-k8s-small (~10 GB each) ran node2 (62 GB) out of memory and crashed every run: the
defaults assume the worst of a tag until a peak is measured."""

from __future__ import annotations

import sqlite3

FACTOR = 1.2
MARGIN_MB = 1024           # kept free beyond the expected peaks
DEFAULTS = (("heavy", 16000.0), ("realistic", 10000.0), ("physics", 3000.0), ("particles", 3000.0),
            ("canonical", 3000.0), ("real", 3000.0))
DEFAULT_MB = 1000.0


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
