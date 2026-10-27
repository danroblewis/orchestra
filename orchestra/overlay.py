"""The private overlay: a second configuration file merged over the repository's ``orchestra.toml``.

A project's configuration is the repository's ``orchestra.toml`` with, if there is one, a private
file merged over it (``Project.overlay_file``: ``ORCHESTRA_CONFIG_OVERLAY``, else
``orchestra.local.toml`` in the project's state directory). It keeps what is personal (channels,
templates, identities) out of a repository a team shares (docs/roadmap/decisions.md D10).

The rules (``merge``):

- a table merges key by key, and the overlay's value wins;
- an array of tables (``[[machines]]``, ``[[collect]]``, ``[[scrape]]``, ``[[sources]]``, a
  plugin's ``[[tasks.roles]]``, at any depth) is merged entry by entry: an overlay entry whose
  ``name`` an entry of the repository's has replaces that entry whole, and any other is appended;
- an overlay entry ``{ name = "x", enabled = false }`` removes the repository's entry ``x`` (and is
  itself never part of the result);
- anything else (a string, a number, an array of plain values) is replaced by the overlay's.

``[overlay]`` in the overlay file is the overlay's own and is not merged: ``secret`` lists the
keys (dotted, as ``slack.channels`` or ``machines[pager]``; a key covers what is under it) whose
values are never shown (``describe``), only where they came from. Secret here means private, not
a credential: credentials never go in a configuration file, overlay or not."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REPO, OVERLAY = "repo", "overlay"


@dataclass
class Layers:
    """What the overlay did to the repository's configuration."""

    path: str                                            # the overlay file
    set: set[str] = field(default_factory=set)           # keys whose value is the overlay's (and all under them)
    removed: list[str] = field(default_factory=list)     # entries the overlay removed (enabled = false)
    secret: list[str] = field(default_factory=list)      # keys whose values are not shown


class OverlayError(ValueError):
    pass


def _tables(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(e, dict) for e in v)


def _off(e: dict) -> bool:
    return e.get("enabled") is False


def _entry_key(path: str, e: dict, i: int) -> str:
    name = e.get("name")
    return f"{path}[{name}]" if isinstance(name, str) else f"{path}[{i}]"


def _entries(base: list[dict], over: list[dict], path: str, layers: Layers) -> list[dict]:
    out: list[tuple[dict, bool] | None] = [(e, False) for e in base]
    where = {e["name"]: i for i, e in enumerate(base) if isinstance(e.get("name"), str)}
    for e in over:
        name = e.get("name")
        i = where.get(name) if isinstance(name, str) else None
        if _off(e):
            if i is not None and out[i] is not None:
                out[i] = None
                layers.removed.append(f"{path}[{name}]")
            continue
        if i is not None:
            out[i] = (e, True)
        else:
            out.append((e, True))
    kept = [x for x in out if x is not None]
    for i, (e, mine) in enumerate(kept):
        if mine:
            layers.set.add(_entry_key(path, e, i))
    return [e for e, _ in kept]


def _merge(base: dict, over: dict, path: str, layers: Layers) -> dict:
    out = dict(base)
    for k, v in over.items():
        p = f"{path}.{k}" if path else k
        b = out.get(k)
        if isinstance(v, dict) and isinstance(b, dict | None):
            out[k] = _merge(b or {}, v, p, layers)
            if b is None:
                layers.set.add(p)
        elif _tables(v) and v and (b is None or _tables(b)):
            out[k] = _entries(b or [], v, p, layers)
        else:
            out[k] = v
            layers.set.add(p)
    return out


def merge(repo: dict, overlay: dict, path: str = "") -> tuple[dict, Layers]:
    """The repository's parsed configuration with the overlay's merged over it."""
    overlay = dict(overlay)
    own = overlay.pop("overlay", None) or {}
    if not isinstance(own, dict):
        raise OverlayError("[overlay] must be a table")
    secret = own.get("secret", [])
    if not isinstance(secret, list) or not all(isinstance(s, str) for s in secret):
        raise OverlayError("[overlay] secret must be an array of keys, as [\"slack.channels\"]")
    layers = Layers(path=path, secret=list(secret))
    return _merge(repo, overlay, "", layers), layers


def _under(key: str, prefixes) -> bool:
    return any(key == p or key.startswith((p + ".", p + "[")) for p in prefixes)


def describe(raw: dict, layers: Layers | None) -> list[dict]:
    """Each key of the merged configuration with where it came from (``repo`` or ``overlay``) and
    its value, unless the overlay marks it secret. A table is walked; an array of tables gives one
    row per entry, keyed ``section[name]``; any other value is one row."""
    rows: list[dict] = []

    def row(key: str, value: Any) -> None:
        origin = OVERLAY if layers and _under(key, layers.set) else REPO
        r: dict[str, Any] = {"key": key, "from": origin}
        hidden = layers.secret if layers else []
        if _under(key, hidden):
            r["secret"] = True
        elif isinstance(value, dict) and any(s.startswith(key + ".") for s in hidden):
            r["value"] = {f: v for f, v in value.items() if not _under(f"{key}.{f}", hidden)}
            r["secret_fields"] = sorted(f for f in value if _under(f"{key}.{f}", hidden))
        else:
            r["value"] = value
        rows.append(r)

    def walk(d: dict, path: str) -> None:
        for k, v in d.items():
            p = f"{path}.{k}" if path else k
            if isinstance(v, dict) and v:
                walk(v, p)
            elif _tables(v) and v:
                for i, e in enumerate(v):
                    row(_entry_key(p, e, i), e)
            else:
                row(p, v)

    walk(raw, "")
    return rows
