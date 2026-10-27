"""Edits to the text of a TOML configuration file that keep everything they do not change: a key
set or removed in a table, an entry of an array of tables (``[[machines]]``, ``[[gate.unit]]``)
added, changed or removed. Keys and entries are set through ``tomlkit``, which keeps the file's
comments and layout; a key whose value changes loses its own end-of-line comment, which described
the old value. An entry is removed from the text itself, its header through its last key, so the
comments and blank lines after it, which introduce what follows, stay where they are; the result
is checked against the parsed file with only that entry gone. ``config_edit`` is the API; this is
its text work."""

from __future__ import annotations

import copy
import re
import tomllib
from typing import Any

import tomlkit
from tomlkit.items import AoT
from tomlkit.toml_document import TOMLDocument

from .config import ConfigError


def split(path: str | list[str] | tuple[str, ...]) -> list[str]:
    """``"gate.unit"`` -> ``["gate", "unit"]``; a list is taken as it is (for a key with a dot)."""
    parts = path.split(".") if isinstance(path, str) else list(path)
    if not parts or not all(isinstance(p, str) and p for p in parts):
        raise ConfigError(f"bad key {path!r}: name it as section.key")
    return parts


def table(doc: TOMLDocument, parts: list[str], create: bool):
    """The table at ``parts`` (each level added, set apart by a blank line, when ``create``), or
    None. Raises when a level holds something other than a table."""
    t: Any = doc
    for i, p in enumerate(parts):
        if p not in t:
            if not create:
                return None
            new = tomlkit.table()
            if t is doc:
                new.trivia.indent = "\n"
            t[p] = new
        t = t[p]
        if not isinstance(t, dict):
            raise ConfigError(f"{'.'.join(parts[:i + 1])} is not a table, so nothing can be set under it")
    return t


def set_key(tbl, key: str, value: Any) -> bool:
    """Set ``key``; False when it already had that value (its comment then stays)."""
    if key in tbl and tbl[key] == value:
        return False
    tbl[key] = value
    tbl.item(key).trivia.comment = ""
    tbl.item(key).trivia.comment_ws = ""
    return True


def entries(doc: TOMLDocument, parts: list[str], create: bool = False):
    """The array of tables at ``parts``, or None. Raises when the key holds something else
    (``[gate]`` with ``unit = "make test"``): an entry cannot be added to it or found in it."""
    holder = table(doc, parts[:-1], create)
    key, where = parts[-1], ".".join(parts)
    if holder is None or key not in holder:
        if not create:
            return None
        holder[key] = tomlkit.aot()
    if not isinstance(holder[key], AoT):
        raise ConfigError(f"{where} is not an array of tables; write each entry as [[{where}]]")
    return holder[key]


def find(items, name: str) -> int | None:
    return next((i for i, e in enumerate(items or []) if isinstance(e, dict) and e.get("name") == name), None)


def upsert(doc: TOMLDocument, parts: list[str], entry: dict[str, Any], base: dict | None = None) -> dict | None:
    """Set ``entry``'s fields on the entry of ``[[parts]]`` with its ``name``, adding it (after a
    blank line, starting from ``base``) when there is none; fields not given are left as they were.
    Returns the entry as it was, or None when it was added."""
    items = entries(doc, parts, create=True)
    i = find(items, entry["name"])
    if i is None:
        t = tomlkit.table()
        t.trivia.indent = "\n"
        t["name"] = entry["name"]
        for k, v in {**(base or {}), **entry}.items():
            if k != "name":
                t[k] = v
        items.append(t)
        return None
    before = copy.deepcopy(dict(items[i]))
    for k, v in entry.items():
        set_key(items[i], k, v)
    return before


def replace_entry(doc: TOMLDocument, parts: list[str], entry: dict[str, Any]) -> None:
    """Put ``entry`` whole in place of the entry with its name (added when there is none)."""
    items = entries(doc, parts, create=True)
    i = find(items, entry["name"])
    t = tomlkit.table()
    t.trivia.indent = "\n"
    for k, v in entry.items():
        t[k] = v
    if i is None:
        items.append(t)
    else:
        items[i] = t


def get(raw: dict, parts: list[str]) -> Any:
    v: Any = raw
    for p in parts:
        if not isinstance(v, dict) or p not in v:
            return None
        v = v[p]
    return v


def _without(raw: dict, parts: list[str], i: int) -> dict:
    """``raw`` with entry ``i`` of ``[[parts]]`` gone (and the array, when it was the last)."""
    out = copy.deepcopy(raw)
    holder = out
    for p in parts[:-1]:
        holder = holder[p]
    del holder[parts[-1]][i]
    if not holder[parts[-1]]:
        del holder[parts[-1]]
    return out


def remove(text: str, parts: list[str], name: str) -> str:
    """The text without the ``[[parts]]`` entry named ``name``. Raises when there is none."""
    raw = tomllib.loads(text)
    items = get(raw, parts) or []
    i = find(items if isinstance(items, list) else [], name)
    if i is None:
        raise ConfigError(f"there is no [[{'.'.join(parts)}]] entry named {name!r}")
    want = _without(raw, parts, i)
    lines = text.splitlines(keepends=True)
    pattern = r"\s*\.\s*".join(map(re.escape, parts))
    mine = [k for k, ln in enumerate(lines) if re.match(rf"\s*\[\[\s*{pattern}\s*\]\]\s*(#.*)?$", ln)]
    if len(mine) == len(items):
        start = mine[i]
        nxt = next((k for k in range(start + 1, len(lines)) if lines[k].lstrip().startswith("[")), len(lines))
        end = max(k for k in range(start, nxt) if lines[k].strip() and not lines[k].lstrip().startswith("#"))
        out = lines[:start] + lines[end + 1:]
        if start > 0 and not out[start - 1].strip() and (start == len(out) or not out[start].strip()):
            del out[start - 1]                                  # no doubled blank line where it was
        new = "".join(out)
        try:
            if tomllib.loads(new) == want:
                return new
        except tomllib.TOMLDecodeError:
            pass
    doc = tomlkit.parse(text)                                   # an unusual layout: let tomlkit remove it
    del entries(doc, parts)[i]
    return tomlkit.dumps(doc)


def unset(doc: TOMLDocument, parts: list[str]) -> bool:
    """Remove the key at ``parts``; False when it was not there."""
    holder = table(doc, parts[:-1], create=False)
    if holder is None or parts[-1] not in holder:
        return False
    del holder[parts[-1]]
    return True
