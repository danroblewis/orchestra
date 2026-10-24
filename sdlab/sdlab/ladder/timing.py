"""Time per cell: what each strategy costs per (case, variant), by set and by version, and what re-testing
a cell would cost (cost.py, runs.py). Read from the store's light columns (store.times_after), kept in
memory and topped up with what was stored since; never in a page's request path (timing_routes.py serves
the last snapshot and refreshes it in the background).

    set_of(case)              the set a case counts in: tests, noisy, canonical, realistic, physics or real
    Table                     the results' times: the latest per cell and the last per cell of each version
    table()                   this process's Table for the store, topped up (a few ms once warm; a full read
                              of a large store takes seconds: call it off the request path)
    stats(t, name)            {sets: {set: [median, p95, n]}, score: {set: [median, n]}, trend}: discovery
                              seconds per cell over the strategy's latest results, scoring seconds where measured,
                              and trend: the latest version against the one before over the cells both ran
                              (the median of the paired ratios), {ratio, n, hash, prev}
    versions(t, name)         per version (strategy hash, oldest first): {hash, at (its first result), n (cells),
                              all: [median, p95, n], sets: {set: [median, p95, n]}}
    estimate(t, key, mode, sets)  (seconds, how) to run (mode "run") or re-score ("rescore") one cell again

Discovery seconds of a timeout count as its limit (the case's own timeout, else the watcher's 300 s); an
error with no time is left out. A re-score keeps the discovery seconds of the run it re-scores, so each
version counts a cell once (its last result). Scoring seconds (and wall seconds, the whole item) exist
only for results stored since 2026-10-19; an older result's scoring cost is estimated from the same
cell's measured scoring under other strategies, else the set's median.
"""

from __future__ import annotations

import math
import threading
from statistics import median

from . import cases as casemod
from . import store

SETS = ("tests", "noisy", "canonical", "realistic", "physics", "real")
WATCH_TIMEOUT = 3600.0                 # the watcher's --timeout (CLAUDE.md): an old timeout's discovery seconds
FLOOR = 0.01                          # seconds: a paired ratio reads anything faster as this


def set_of(c: dict) -> str:
    """The set a case counts in (the leaderboard's sets, with the tests split into noisy, canonical and the rest)."""
    tags = c.get("tags") or []
    if c.get("real"):
        return "real"
    if c.get("example") or "realistic" in tags:
        return "realistic"
    if c.get("physics") or c.get("particles"):
        return "physics"
    if "canonical" in tags:
        return "canonical"
    if "noisy" in tags:
        return "noisy"
    return "tests"


def p95(xs: list[float]) -> float | None:
    """The 95th percentile (nearest rank) of xs, or None if there are none."""
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s), max(1, math.ceil(0.95 * len(s)))) - 1]


def _r(x: float | None, d: int = 3) -> float | None:
    return None if x is None else round(float(x), d)


class Table:
    """The results' times, by cell (case, variant, strategy)."""

    def __init__(self) -> None:
        self.last = 0                 # the newest result id read
        self.latest: dict[tuple, tuple] = {}    # cell -> (id, hash, status, seconds, score_seconds, wall_seconds)
        self.by_version: dict[tuple, dict] = {}  # (strategy, hash) -> {"first": id, "cells": {(case, variant): (status, seconds, wall)}}
        self.score_cv: dict[tuple, dict] = {}    # (case, variant) -> {strategy: score_seconds} (the last measured)
        self.changed = 0              # bumped whenever rows are added

    def add(self, rows: list[tuple]) -> None:
        for rid, case, variant, strategy, h, at, status, secs, score_s, wall in rows:
            self.latest[(case, variant, strategy)] = (rid, h, status, secs, score_s, wall)
            v = self.by_version.setdefault((strategy, h), {"first": rid, "at": at, "cells": {}})
            v["cells"][(case, variant)] = (status, secs, wall)
            if score_s is not None:
                self.score_cv.setdefault((case, variant), {})[strategy] = score_s
            self.last = rid
        if rows:
            self.changed += 1


_tables: dict[str, Table] = {}
_lock = threading.Lock()


def table() -> Table:
    """This process's Table for the current store, topped up with the results stored since it last looked."""
    where = str(store.path())
    with _lock:
        t = _tables.get(where)
        if t is None:
            t = _tables[where] = Table()
        if t.last and store.key_of(t.last) is None:      # the store was replaced
            t = _tables[where] = Table()
        t.add(store.times_after(t.last))
        return t


_sets: dict = {}


def case_sets(ids: list[str] | None = None) -> dict[str, str]:
    """{case id: its set} for every case now on the ladder (kept until the case list changes), or for the
    given ids only (cost.py: loading every case is slow in a fresh cache)."""
    if ids is not None:
        known = set(casemod.case_ids())
        return {i: set_of(casemod.load(i)) for i in dict.fromkeys(ids) if i in known}
    ids_now = tuple(casemod.case_ids())
    if _sets.get("ids") != ids_now:
        _sets.update(ids=ids_now, sets={i: set_of(casemod.load(i)) for i in ids_now})
    return _sets["sets"]


def _limit(case: str) -> float:
    from . import runner
    return runner.case_timeout(case, WATCH_TIMEOUT)


def discovery_seconds(case: str, status: str, secs: float | None, wall: float | None) -> float | None:
    """A result's discovery seconds as time per cell counts them (a timeout: its limit; an error with no time: None)."""
    if secs is not None:
        return float(secs)
    if status == "timeout":
        return float(wall) if wall is not None else _limit(case)
    return float(wall) if wall is not None else None


def stats(t: Table, name: str, sets: dict[str, str] | None = None) -> dict:
    """See the module docstring."""
    sets = sets if sets is not None else case_sets()
    disc: dict[str, list] = {}
    score: dict[str, list] = {}
    for (case, variant, strategy), (_rid, _h, status, secs, score_s, wall) in t.latest.items():
        if strategy != name or case not in sets:
            continue
        s = sets[case]
        d = discovery_seconds(case, status, secs, wall)
        if d is not None:
            disc.setdefault(s, []).append(d)
        if score_s is not None:
            score.setdefault(s, []).append(score_s)
    return {"sets": {s: [_r(median(xs)), _r(p95(xs)), len(xs)] for s in SETS if (xs := disc.get(s))},
            "score": {s: [_r(median(xs)), len(xs)] for s in SETS if (xs := score.get(s))},
            "trend": trend(t, name, sets)}


def _ordered(t: Table, name: str) -> list[tuple[str, dict]]:
    return sorted(((h, v) for (n, h), v in t.by_version.items() if n == name), key=lambda x: x[1]["first"])


def trend(t: Table, name: str, sets: dict[str, str] | None = None, least: int = 5) -> dict | None:
    """The latest version's discovery seconds against the newest earlier version that shares at least `least`
    cells with it: the median of new / old over the shared cells (each read as at least FLOOR seconds)."""
    sets = sets if sets is not None else case_sets()
    vs = _ordered(t, name)
    if len(vs) < 2:
        return None
    h, new = vs[-1]
    for ph, old in reversed(vs[:-1]):
        ratios = []
        for (case, variant), (st, secs, wall) in new["cells"].items():
            if case not in sets or (case, variant) not in old["cells"]:
                continue
            a = discovery_seconds(case, st, secs, wall)
            ost, osecs, owall = old["cells"][(case, variant)]
            b = discovery_seconds(case, ost, osecs, owall)
            if a is not None and b is not None:
                ratios.append(max(a, FLOOR) / max(b, FLOOR))
        if len(ratios) >= least:
            return {"ratio": _r(median(ratios)), "n": len(ratios), "hash": h[:10], "prev": ph[:10]}
    return None


def versions(t: Table, name: str, sets: dict[str, str] | None = None, keep: int = 40) -> list[dict]:
    """See the module docstring (the newest `keep` versions)."""
    sets = sets if sets is not None else case_sets()
    out = []
    for h, v in _ordered(t, name)[-keep:]:
        by: dict[str, list] = {}
        for (case, _variant), (st, secs, wall) in v["cells"].items():
            if case in sets and (d := discovery_seconds(case, st, secs, wall)) is not None:
                by.setdefault(sets[case], []).append(d)
        allx = [x for xs in by.values() for x in xs]
        out.append({"hash": h[:10], "at": v["at"], "n": len(v["cells"]),
                    "all": [_r(median(allx)), _r(p95(allx)), len(allx)] if allx else None,
                    "sets": {s: [_r(median(xs)), _r(p95(xs)), len(xs)] for s in SETS if (xs := by.get(s))}})
    return out


class Estimator:
    """What re-testing a cell costs, from the stored times (built once per Table state; see estimate)."""

    def __init__(self, t: Table, sets: dict[str, str], timeout: float = WATCH_TIMEOUT):
        self.t, self.sets, self.timeout, self._limits = t, sets, timeout, {}
        disc_cv: dict[tuple, list] = {}
        disc_ss: dict[tuple, list] = {}
        disc_s: dict[str, list] = {}
        score_s: dict[str, list] = {}
        for (case, variant, strategy), (_rid, _h, status, secs, sc, wall) in t.latest.items():
            if case not in sets:
                continue
            d = discovery_seconds(case, status, secs, wall)
            if d is not None:
                disc_cv.setdefault((case, variant), []).append(d)
                disc_ss.setdefault((strategy, sets[case]), []).append(d)
                disc_s.setdefault(sets[case], []).append(d)
            if sc is not None:
                score_s.setdefault(sets[case], []).append(sc)
        self.disc_cv = {k: median(v) for k, v in disc_cv.items()}
        self.disc_ss = {k: median(v) for k, v in disc_ss.items()}
        self.disc_s = {k: median(v) for k, v in disc_s.items()}
        self.score_s = {k: median(v) for k, v in score_s.items()}
        self.score_cv = {k: median(v.values()) for k, v in t.score_cv.items()}

    def scoring(self, case: str, variant: str, strategy: str) -> tuple[float, str]:
        row = self.t.latest.get((case, variant, strategy))
        if row and row[4] is not None:
            return row[4], "measured"
        if (case, variant) in self.score_cv:
            return self.score_cv[(case, variant)], "cell"
        s = self.sets.get(case)
        if s in self.score_s:
            return self.score_s[s], "set"
        return 0.0, "unknown"

    def estimate(self, case: str, variant: str, strategy: str, mode: str = "run") -> tuple[float, str]:
        """(seconds, how): how is "measured" (this cell's own stored times), "cell" (other strategies on
        the cell), "strategy" (this strategy's median in the set), "set" (every strategy's median in the
        set) or "unknown" (nothing to go by: 0). A run costs discovery (at most the item's timeout, as the
        watcher runs it: the case's own, else WATCH_TIMEOUT) + scoring; a re-score, scoring."""
        sc, show = self.scoring(case, variant, strategy)
        if mode == "rescore":
            return sc, show
        cap = self.limit(case)                  # the watcher stops discovery at the item's timeout
        row = self.t.latest.get((case, variant, strategy))
        if row:
            _rid, _h, status, secs, sc_own, wall = row
            if wall is not None:
                return min(float(wall), cap + (sc_own or 0.0)), "measured"
            d = discovery_seconds(case, status, secs, wall)
            if d is not None:
                return min(d, cap) + sc, "measured"
        s = self.sets.get(case)
        for how, got in (("cell", self.disc_cv.get((case, variant))), ("strategy", self.disc_ss.get((strategy, s))), ("set", self.disc_s.get(s))):
            if got is not None:
                return min(got, cap) + sc, how
        return sc, "unknown"

    def limit(self, case: str) -> float:
        if case not in self._limits:
            self._limits[case] = _limit(case) if case in self.sets else self.timeout
        return self._limits[case]


_estimators: dict = {}


def estimator(t: Table | None = None) -> Estimator:
    """An Estimator for the table now (kept until a result is added or the case list changes)."""
    t = t or table()
    sets = case_sets()
    key = (id(t), t.changed, t.last, id(sets))
    got = _estimators.get("e")
    if got is None or got[0] != key:
        got = _estimators["e"] = (key, Estimator(t, sets))
    return got[1]
