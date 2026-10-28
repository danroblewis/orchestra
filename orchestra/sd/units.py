"""The unit a series is measured in, so a balance never adds seconds to bytes.

A balance adds and subtracts counters with coefficients of +1 or −1 (``sd.balance``), so every
term must be in the level's own unit: a queue of messages is not drained by CPU seconds, nor a
disk's free bytes by a count of requests, however well their changes happen to line up. The unit
is read, most trusted first, from:

1. a ``unit`` label on the series (``kube_pod_container_resource_requests{unit="byte"}``);
2. the unit its source declared for it (the store's metadata, or a view's own: a count of pods);
3. its name, by Prometheus' naming convention: the base unit is the last unit word before the
   suffixes ``_total``, ``_sum`` (and an aggregation a recording rule appended, ``sum_irate``); a
   name ending in ``_count`` counts observations (``http_request_duration_seconds_count`` counts
   requests, not seconds).

A name with no unit word counts things (messages, requests, connections, pods): ``count``. Units
are compared exactly, scale included: bytes and KiB are different units to a ±1 balance. Nothing
here says two counts measure the same kind of thing (messages and requests are both ``count``);
that the balance and its evidence decide."""

from __future__ import annotations

import re

COUNT = "count"
# unit words, as they appear in names or metadata, to one spelling each
WORDS = {
    "seconds": "seconds", "second": "seconds", "milliseconds": "milliseconds", "ms": "milliseconds",
    "microseconds": "microseconds", "nanoseconds": "nanoseconds",
    "bytes": "bytes", "byte": "bytes", "kibibytes": "kibibytes", "kib": "kibibytes", "kilobytes": "kilobytes", "kb": "kilobytes",
    "mebibytes": "mebibytes", "mib": "mebibytes", "megabytes": "megabytes", "mb": "megabytes", "gb": "gigabytes",
    "bits": "bits", "cores": "cores", "core": "cores", "celsius": "celsius", "joules": "joules", "watts": "watts",
    "volts": "volts", "amperes": "amperes", "meters": "meters", "grams": "grams", "ratio": "ratio", "percent": "percent",
    "hertz": "hertz",
}
# words a name may carry after its unit: a counter's suffix, an aggregation a rule appended, a window
SKIP = {"total", "sum", "irate", "rate", "increase", "deriv", "delta", "avg", "max", "min", "mean", "last", "over", "time"}
WINDOW = re.compile(r"^\d+[smhdw]$")


def from_name(name: str) -> str:
    """The unit a name says, by Prometheus' convention; ``count`` when it says none."""
    words = [w for w in re.split(r"[:_]", name.lower()) if w]
    for w in reversed(words):
        if w == "count":
            return COUNT
        if w in WORDS:
            return WORDS[w]
        if w in SKIP or WINDOW.match(w):
            continue
        return COUNT
    return COUNT


def normal(unit: str | None) -> str | None:
    """A declared unit in this module's spelling, or None when it names no unit this module knows
    (a view's ``pods`` is a count of things: ``count``)."""
    if not unit:
        return None
    u = unit.strip().lower()
    if u in WORDS:
        return WORDS[u]
    return COUNT if re.fullmatch(r"[a-z]+s", u) else None


def unit_of(name: str, labels: dict[str, str], declared: str | None = None) -> str:
    """The series' unit: its ``unit`` label, the unit declared for it, or its name's."""
    return normal(labels.get("unit")) or normal(declared) or from_name(name)


def mixed(level_unit: str, counter_unit: str) -> bool:
    """Whether a counter cannot be a term of a level's balance: their units differ."""
    return level_unit != counter_unit
