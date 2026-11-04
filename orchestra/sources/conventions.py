"""What a family is by its name and the store's metadata, before its samples are asked: most
metrics say it, so ``kinds`` (``kinds.py``) is needed only for the exceptions. Google Cloud
Monitoring's metrics exported through Chronosphere or Prometheus carry their kind in their names
(a DELTA count is ``…_count``, a per-minute value pushed as a gauge; a GAUGE is a level such as
``num_undelivered_messages``), and a store's ``/api/v1/metadata`` (asked metric by metric, under
``match`` only: ``survey.py``) gives a type and a help text.

| Says | Read as |
|---|---|
| metadata ``type=counter`` | a counter (its increments a flow); its samples overrule it only by falling part way, which no counter does (``behaviour.py``) |
| a gauge or untyped whose help says per interval (``delta``, ``per interval``, ``in the interval``, ``in the sampling period``, ``since the last sample``) | a flow, each sample the count of its interval |
| a gauge or untyped named ``…_count`` or ``…_total`` (not a count of things held: ``pod_count``, ``…_pending_total``) | a flow: each sample the count of its interval, or cumulative when its samples never fell but by resets |
| a level by name: ``num_…``, ``oldest_…_age``, ``…undelivered…``, ``…outstanding…``, ``…unacked…``, ``…backlog…``, ``…retained…`` (Pub/Sub's ``num_undelivered_messages``, ``oldest_unacked_message_age``, ``backlog_bytes``) | a level, whatever its samples do (an age that rises by one a second is no clock) |
| recording rules ``:count``, ``:sum``, ``:rate`` | as ``views.py`` reads them: a ``:count`` beside a ``:sum`` a flow, a ``:rate`` a rate |

When a convention speaks, the samples decide only a flow's form (per interval or cumulative);
when none does, behaviour decides (``behaviour.classify``). ``kinds`` on the source overrules
both."""

from __future__ import annotations

import re

from . import Points
from .behaviour import AMOUNT, RISING, amount, counter_like, intervals, words

PER_INTERVAL = re.compile(r"(?i)\bdelta\b|per[ -](?:sampling[ -])?interval|in the (?:sampling )?(?:interval|period)"
                          r"|since the (?:last|previous) (?:sample|scrape|report|export|collection)")
LEVEL_NAME = re.compile(r"(?i)(?:^|_)num_|(?:^|_)oldest_\w*_age(?:_seconds)?$|undelivered|outstanding|unacked|backlog|retained")
FLOW_NAME = re.compile(r"_(?:count|total)$")
HELD = {"pod", "pods", "node", "nodes", "instance", "instances", "replica", "replicas", "container", "containers", "thread",
        "threads", "connection", "connections", "worker", "workers", "member", "members", "subscription", "subscriptions",
        "topic", "topics", "partition", "partitions", "item", "items", "key", "keys", "object", "objects", "file", "files",
        "goroutine", "goroutines", "process", "processes", "session", "sessions", "client", "clients", "consumer", "consumers",
        "host", "hosts", "target", "targets", "entry", "entries", "series", "vm", "vms", "cpu", "cpus", "core", "cores"}
UNTYPED = (None, "", "gauge", "unknown", "untyped")


def held_count(name: str) -> bool:
    """Whether a ``…_count`` or ``…_total`` counts things held (``pod_count``, ``…_pending_total``),
    not events: the word before it names a thing or an amount."""
    ws = [w for w in words(name) if w not in ("count", "total")]
    return amount(name) or bool(ws) and (ws[-1] in HELD or ws[-1] in AMOUNT)


def cumulative(series: list[Points]) -> bool:
    """Whether a flow's samples are cumulative: they never fell but by resets, and rose often."""
    ok, _, rises = counter_like(series)
    return ok and rises >= RISING * max(1, intervals(series))


def convention(name: str, typ: str | None, help_: str | None, series: list[Points]) -> tuple[str, str, str] | None:
    """(kind, counter_form, why) by the table above: ``counter`` with form ``""`` (cumulative) or
    ``delta`` (per interval), or ``gauge`` (a level); None when name and metadata are silent (or
    the type is the store's own and settles it: a counter, a histogram)."""
    if typ not in UNTYPED:
        return None
    said = f"typed {typ}" if typ else "untyped"
    if help_ and PER_INTERVAL.search(help_):
        return "counter", "delta", f"{said}, but its help says per interval: a flow, each sample the count of its interval (by convention)"
    if LEVEL_NAME.search(name) and not FLOW_NAME.search(name):
        return "gauge", "", "its name says a level held (num_…, oldest_…_age, a backlog): read as a level, whatever its samples do (by convention)"
    if FLOW_NAME.search(name) and not held_count(name):
        if cumulative(series):
            return "counter", "", f"{said}, named a count, its samples never fell but by resets: a counter (by convention)"
        return "counter", "delta", f"{said}, named a count: a flow, each sample the count of its interval (by convention)"
    return None
