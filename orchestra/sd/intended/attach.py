"""What an attachment selects (docs/proposals/instruments-on-machines.md §2): an instrument's
series, narrowed by an optional **match**, ``{prefix?, labels?: {label: value}}``, where a value is
an equality (``"postgres"``) or, written ``"=~deploy-.*"``, a regular expression that must match
the whole label value (a Jenkins folder of jobs). For a source the labels are its canonical ones,
after ``[sources.labels]`` aliases (``svc`` and ``service`` are one label).

An attachment is declared provenance: what selects here is read by the comparison on read
(``measured.py``), never by discovery and never by ``sd/attribute.py`` (AGENTS.md rule 7)."""

from __future__ import annotations

import re

from ...metrics import MetricsError, matchers_of, matches
from .checks import IntentError

REGEX = "=~"


def parse(match) -> tuple[str, list[tuple[str, str, str]]]:
    """``(prefix, matchers)`` of a stored match; raises ``IntentError`` on a bad one."""
    if match is None:
        return "", []
    if not isinstance(match, dict) or set(match) - {"prefix", "labels"}:
        raise IntentError("match is {prefix?, labels?: {label: value, or =~regex}}")
    prefix = match.get("prefix") or ""
    labels = match.get("labels") or {}
    if not isinstance(prefix, str) or not isinstance(labels, dict):
        raise IntentError("match is {prefix?: a series-name prefix, labels?: {label: value, or =~regex}}")
    out = []
    for k, v in labels.items():
        if not isinstance(k, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", k) or not isinstance(v, str):
            raise IntentError(f"match.labels: {k!r} = {v!r}: a label name and a string value")
        out.append((k, "=~", v[len(REGEX):]) if v.startswith(REGEX) else (k, "=", v))
    try:
        return prefix, matchers_of(out)
    except MetricsError as e:
        raise IntentError(f"match: {e}") from None


def shown(match) -> str:
    """The match as one line: ``pg_*{job="postgres",server=~"db-.*"}``; ``everything`` for none."""
    prefix, ms = parse(match)
    if not prefix and not ms:
        return "everything"
    inner = ",".join(f'{k}{op}"{v}"' for k, op, v in ms)
    return f"{prefix}*" * bool(prefix) + (f"{{{inner}}}" if inner else "")


def canonical(labels: dict[str, str], aliases: dict[str, str] | None) -> dict[str, str]:
    """A source's labels under their canonical names (``SourceSpec.aliases``: spelling ->
    canonical); a label already canonical wins over a spelling of it."""
    if not aliases:
        return labels
    out = dict(labels)
    for k, v in labels.items():
        c = aliases.get(k)
        if c and c != k and c not in labels:
            out.setdefault(c, v)
            out.pop(k, None)
    return out


def selects(name: str, labels: dict[str, str], match, aliases: dict[str, str] | None = None, strip: str = "") -> bool:
    """Whether a series is one an attachment's match selects. ``strip``: a source's ``<prefix>:``,
    left out of the name before the prefix is compared (either spelling of the prefix works)."""
    prefix, ms = parse(match)
    bare = name[len(strip):] if strip and name.startswith(strip) else name
    if prefix and not (name.startswith(prefix) or bare.startswith(prefix)):
        return False
    return matches(canonical(labels, aliases), ms)


__all__ = ["canonical", "parse", "selects", "shown"]
