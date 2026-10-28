"""What a family's samples say it is, where its type and name may not: a metric's type comes from
the store's metadata, checked against how its raw samples behave; a name is only a hint.

- A **counter typed a gauge** (or untyped): every sampled series never falls except by a few
  **resets** (a drop to at most ``RESET_FRACTION`` of the value before, at most ``RESETS`` of the
  intervals: a process restarting from about zero now and then, not a queue drained in batches),
  and rises in at least ``RISING`` of its sample intervals. Data alone cannot tell a counter from
  an amount that only grew in the window (a disk filling, a queue nobody consumes), so the name
  breaks the tie, by Prometheus' convention that a name ends with what it measures: an amount held
  (``…_used_bytes``, ``…_size``, ``…_lag``, ``…_active``: its last word in ``AMOUNT``) stays a
  gauge whatever its samples do; otherwise it is a counter when a reset was seen or its name says
  events (``…_offset``, ``…_processed_messages``, ``…_ActiveOpens``: a word in ``EVENTS``), and a
  gauge when neither (``rabbitmq_queue_messages`` that only grew in an incident). A counter's
  level is its whole history, never a stock of the system, and its increments are the flow the
  level hides (a Kafka topic's offsets are its messages produced).
- A **gauge typed a counter**: a typed counter that falls ``PARTIAL_DROPS`` times or more by less
  than half (not to about zero) is not counting anything (a ``…_pending_total`` that is a queue).
- A **timestamp**: values that are Unix times (seconds or milliseconds, from twenty years before
  the sample to a day after it) and a name or help that says time (``…_created``,
  ``…_start_time_seconds``, ``…_timestamp…``, help "Unix …"). A sum of timestamps means nothing.
- A **clock**: a gauge in seconds rising by one a second (``…_uptime_seconds``): its level is the
  time since something started, its increments are the clock's.
- An **info** metric: every value in the window is exactly 1 (``…_info``, ``kube_pod_owner``):
  its sum is only how many series report, which the count of reporters already says.

The last three are kept readable (their family is listed, and a query or a script may read them)
but are never read as levels or flows."""

from __future__ import annotations

import re
from itertools import pairwise

from . import Points

RESET_FRACTION = 0.1
RESETS = 0.02           # of the intervals, at most (and one in any case)
RISING = 0.2
PARTIAL_DROPS = 3
AMOUNT = {"bytes", "size", "used", "usage", "avail", "available", "free", "capacity", "limit", "limits", "memory", "length",
          "depth", "active", "inflight", "flight", "pending", "lag", "backlog", "temperature", "celsius", "ratio", "percent",
          "utilisation", "utilization", "load", "replicas", "latency", "duration", "seconds", "level", "ready", "waiting"}
EVENTS = {"offset", "offsets", "processed", "sent", "received", "consumed", "produced", "handled", "published", "delivered",
          "acknowledged", "acked", "completed", "failed", "failures", "errors", "requests", "opens", "closes", "accepted", "rejected",
          "dropped", "retries", "restarts", "events", "calls", "hits", "misses", "writes", "reads", "evictions", "total"}
CLOCK_NAME = re.compile(r"(?i)seconds|uptime|_age")
TIME_NAME = re.compile(r"(?i)timestamp|_time_seconds$|_time$|_created$|_creation|start_time|boot_time|_seen_seconds$|^last_|_last_.*seconds$|_epoch")
TIME_HELP = re.compile(r"(?i)\bunix\b|\bepoch\b|timestamp")
YEAR = 365.25 * 86400


def words(name: str) -> list[str]:
    """A name's words, split at ``_`` and at camel case, lower case."""
    return [w.lower() for part in name.split("_") for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part)]


def amount(name: str) -> bool:
    """Whether a name names an amount held: its last word (``_total`` aside) is in ``AMOUNT``. A
    name ends with what it measures."""
    ws = [w for w in words(name) if w != "total"]
    return bool(ws) and ws[-1] in AMOUNT


def events(name: str) -> bool:
    """Whether a name says it counts events: one of its words is in ``EVENTS``."""
    return bool(set(words(name)) & EVENTS)


def counter_like(series: list[Points]) -> tuple[bool, bool, int]:
    """(it never fell but by a few resets, a reset was seen, how many intervals it rose in): over
    every series; False when it never moved."""
    rises = drops = seen = 0
    few = True
    for pts in series:
        resets = 0
        for (_, a), (_, b) in pairwise(pts):
            if b > a:
                rises += 1
            elif b < a and b <= RESET_FRACTION * a:
                resets += 1
            elif b < a:
                drops += 1
        few = few and resets <= max(1, RESETS * (len(pts) - 1))
        seen += resets
    return rises > 0 and drops == 0 and few, seen > 0, rises


def intervals(series: list[Points]) -> int:
    return sum(max(0, len(p) - 1) for p in series)


def partial_drops(series: list[Points]) -> int:
    """How many times the series fell by less than half: no reset does that."""
    return sum(1 for pts in series for (_, a), (_, b) in pairwise(pts) if a > b > 0.5 * a)


def epoch(t: float, v: float) -> bool:
    """Whether ``v`` reads as a Unix time (seconds or milliseconds) near the sample's time ``t``."""
    return t - 20 * YEAR <= v <= t + 86400 or t - 20 * YEAR <= v / 1000 <= t + 86400


def clock(series: list[Points]) -> bool:
    """Whether every moving series rises by about one a second, in almost every interval."""
    n = good = 0
    for pts in series:
        for (t0, a), (t1, b) in pairwise(pts):
            if t1 > t0:
                n += 1
                good += 0.9 <= (b - a) / (t1 - t0) <= 1.1
    return n >= 5 and good >= 0.8 * n


def classify(name: str, typ: str | None, help_: str | None, series: list[Points], *, low: float | None = None,
             high: float | None = None) -> tuple[str | None, str]:
    """A family's kind from its samples (``series``: raw samples of a few of its series) and, when
    read, the least and largest value of all its series in the window (``low``, ``high``):
    ``counter``, ``gauge``, ``timestamp``, ``clock``, ``info``, or None when the samples do not
    contradict the type; and why."""
    pts = [p for s in series for p in s]
    if not pts:
        return None, ""
    if all(epoch(t, v) for t, v in pts) and (TIME_NAME.search(name) or TIME_HELP.search(help_ or "") or name.endswith("_seconds")):
        return "timestamp", "its values are Unix times: a sum or a change of them means nothing"
    if typ != "counter" and CLOCK_NAME.search(name) and clock(series):
        return "clock", "it rises by one a second: a clock, the time since something started"
    if low == 1.0 and high == 1.0 and all(v == 1.0 for _, v in pts):
        return "info", "every value is 1: its sum is only how many series report"
    n = intervals(series)
    if typ == "counter":
        if (k := partial_drops(series)) >= PARTIAL_DROPS:
            return "gauge", f"typed a counter, but it fell by less than half {k} times: a level"
        return None, ""
    if typ not in (None, "", "gauge", "unknown", "untyped") or n < 10:
        return None, ""
    ok, reset, rises = counter_like(series)
    if not ok or rises < RISING * n or amount(name) or not (reset or events(name)):
        return None, ""
    said = f"typed {typ}" if typ else "untyped"
    how = "it never fell except by resets" if reset else "it only rose"
    return "counter", f"{said}, but {how} (in {rises} of {n} intervals) and its name names no amount held: a counter"
