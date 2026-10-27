"""A source's preset: a TOML file of series definitions for one kind of store's exporter (RabbitMQ's
``rabbitmq_prometheus``, Cloud Monitoring's Pub/Sub metrics), named by ``preset`` in a
``[[sources]]`` table so the definitions need not be copied into every ``orchestra.toml``.

```toml
[source]                  # defaults for the source table; orchestra.toml's own keys win
infer = false
[[series]]                # definitions, as in orchestra.toml, without "source": they read this source
name = "published_total"
select = '{__name__="rabbitmq_detailed_channel_messages_published_total"}'
by = ["exchange"]
kind = "counter"
traffic = { direction = "out", channel = "{exchange}" }
```

The path is relative to the repository root, or absolute (``~`` is the home directory). Presets
are configuration, so they ship with whatever reads that store (``~/orchestra-bridges``), never
with Orchestra (AGENTS.md rule 1; decision D10)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def path_of(preset: str, repo_root: Path) -> Path:
    p = Path(preset).expanduser()
    return p if p.is_absolute() else Path(repo_root) / p


def apply(raw: dict, repo_root: Path) -> tuple[dict, list[dict]]:
    """The source table with the preset's defaults filled in, and the preset's series, each
    reading this source. Raises ``ValueError`` when the preset cannot be read."""
    name = raw.get("preset")
    if not name:
        return raw, []
    p = path_of(str(name), repo_root)
    try:
        doc = tomllib.loads(p.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValueError(f"preset {name!r}: {e}") from None
    defaults = doc.get("source") or {}
    if not isinstance(defaults, dict) or not isinstance(doc.get("series") or [], list):
        msg = f"preset {name!r}: [source] is a table and [[series]] an array of tables"
        raise ValueError(msg)  # noqa: TRY004 - a refusal of the source, like every other in spec.py
    out = {**defaults, **raw}
    if isinstance(defaults.get("labels"), dict) and isinstance(raw.get("labels"), dict):
        out["labels"] = {**defaults["labels"], **raw["labels"]}
    series = [{**s, "source": raw.get("name"), "preset": str(name)} for s in doc.get("series") or [] if isinstance(s, dict)]
    return out, series
