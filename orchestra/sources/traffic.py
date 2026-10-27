"""Counted traffic: a series that counts what a machine produced into, or consumed from, a channel
on another system's bus, or the backlog waiting in that channel (docs/proposals/event-sources.md
§1). The count is the observation: Orchestra never turns it into events.

A ``[[series]]`` definition says so in ``traffic``:

```toml
traffic = { direction = "in", channel = "{exchange}", machine = "{consumer}" }
```

- ``direction``: ``out`` (produced into the channel), ``in`` (consumed from it), both counts, or
  ``backlog``, a level: what waits in the channel for its consumer;
- ``channel`` and ``machine``: templates over each result series' labels (``{label}``, the
  canonical spellings after the source's label aliases), or plain text. A template naming a label
  the series lacks renders to nothing.

This is metadata on the definition, never a label convention: a store's own ``channel`` label
means nothing here. A channel is named ``<prefix>:<channel>`` and a machine ``<prefix>.<machine>``,
like every machine a source names. A count with no machine is **unattributed**. The source's
``producers`` table (channel → machine) is the owner's declaration of who produces into a channel
whose out-counts name no producer (a broker's counts rarely do)."""

from __future__ import annotations

import re

DIRECTIONS = {"out": "produced into the channel", "in": "consumed from the channel", "backlog": "waiting in the channel"}
FIELD = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def parse(raw, kind: str) -> dict:
    """A definition's ``traffic`` table, checked; raises ``ValueError`` with the reason."""
    if not isinstance(raw, dict):
        raise ValueError("traffic = { direction = ..., channel = ..., machine = ... }")  # noqa: TRY004 - refuses the series, with why
    direction, channel, machine = raw.get("direction"), raw.get("channel"), raw.get("machine")
    if direction not in DIRECTIONS:
        raise ValueError(f"traffic direction {direction!r}: one of {', '.join(DIRECTIONS)}")
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("traffic needs a channel (a label template such as \"{queue}\", or a name)")
    if machine is not None and not isinstance(machine, str):
        raise ValueError("traffic machine: a label template such as \"{service}\", or a name")
    if (direction == "backlog") != (kind == "level"):
        raise ValueError(f"traffic {direction} needs kind = {'level' if direction == 'backlog' else 'counter or rate'}, not {kind}")
    if unknown := set(raw) - {"direction", "channel", "machine"}:
        raise ValueError(f"traffic: unknown keys {', '.join(sorted(unknown))}")
    return {"direction": direction, "channel": channel, **({"machine": machine} if machine else {})}


def render(template: str | None, labels: dict[str, str]) -> str | None:
    """The template with each ``{label}`` replaced by the series' value; None when a label it
    names is missing or empty, or nothing is left."""
    if not template:
        return None
    missing = False

    def sub(m: re.Match) -> str:
        nonlocal missing
        v = labels.get(m.group(1))
        missing = missing or not v
        return v or ""
    out = FIELD.sub(sub, template).strip()
    return None if missing or not out else out


def resolve(traffic: dict, labels: dict[str, str], prefix: str, producers: dict[str, str] | None = None) -> dict:
    """What one result series counts: its direction, channel and machine (None: unattributed),
    named as the source names them, with how the machine was known."""
    raw_channel = render(traffic["channel"], labels)
    machine, how = render(traffic.get("machine"), labels), "from its labels"
    if machine is None and traffic["direction"] == "out" and raw_channel and raw_channel in (producers or {}):
        machine, how = producers[raw_channel], "declared in [sources.producers]"
    return {"direction": traffic["direction"], "channel": f"{prefix}:{raw_channel or '?'}",
            "machine": f"{prefix}.{machine}" if machine else None, "attributed": how if machine else "unattributed"}
