"""The collectors ``orchestra.toml`` declares: ``[[collect]]`` (a command) and ``[[scrape]]`` (a URL).

::

    [[collect]]
    name = "disk"                    # the machine's id: letters, digits, . _ -
    command = "machines/disk.sh"     # split like a shell would, not run by one
    every = "60s"                    # how often (default 60 s)
    timeout = "20s"                  # how long one round may take (default 10 s, never more than every)

    [[scrape]]
    name = "app"
    url = "http://127.0.0.1:9100/metrics"
    every = "30s"

A ``[[scrape]]`` may take the name of the ``[[machines]]`` entry whose program it reads, so the
program and its measurements are one machine; a ``[[collect]]`` may not. An entry that cannot be
used is left out, with the reason; the others stand."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..config import ConfigError, parse_duration
from ..events import HOST
from ..launcher import NAME

EVERY_S = 60.0
TIMEOUT_S = 10.0
MIN_EVERY_S = 1.0


@dataclass(frozen=True)
class Collector:
    name: str
    kind: str                  # "collect" (a command) or "scrape" (a URL)
    target: str                # the command, or the URL
    every_s: float = EVERY_S
    timeout_s: float = TIMEOUT_S

    @property
    def mode(self) -> str:
        """How the machine is engaged: a command is run by the clock; a scraped program runs on its own."""
        return "scheduled" if self.kind == "collect" else "continuous"

    def argv(self) -> list[str]:
        return shlex.split(self.target)


def _one(kind: str, entry: object, taken: set[str], programs: set[str]) -> Collector:
    if not isinstance(entry, dict):
        raise ConfigError("is not a table")
    name = entry.get("name")
    if not isinstance(name, str) or not NAME.match(name):
        raise ConfigError(f"bad name {name!r}: use letters, digits, '.', '_' and '-'")
    if name == HOST or name in taken:
        raise ConfigError(f"{name}: the name is taken (by Orchestra's host or another collector)")
    if kind == "collect" and name in programs:
        raise ConfigError(f"{name}: a [[machines]] entry has the name (only a [[scrape]] of that program may share it)")
    field = "command" if kind == "collect" else "url"
    target = entry.get(field)
    if not isinstance(target, str) or not target.strip():
        raise ConfigError(f"{name}: needs a {field}")
    if kind == "collect":
        try:
            if not shlex.split(target):
                raise ConfigError(f"{name}: empty command")
        except ValueError as e:
            raise ConfigError(f"{name}: bad command: {e}") from e
    elif not target.startswith(("http://", "https://")):
        raise ConfigError(f"{name}: url must start with http:// or https://")
    every = parse_duration(entry.get("every"), EVERY_S)
    if every < MIN_EVERY_S:
        raise ConfigError(f"{name}: every must be at least {MIN_EVERY_S:g} s")
    timeout = parse_duration(entry.get("timeout"), TIMEOUT_S)
    if timeout <= 0:
        raise ConfigError(f"{name}: timeout must be more than 0")
    return Collector(name, kind, target, every, min(timeout, every))


def from_toml(raw: dict) -> tuple[list[Collector], list[str]]:
    """The collectors of a parsed ``orchestra.toml``, and why any entry was left out."""
    programs = {m.get("name") for m in raw.get("machines") or [] if isinstance(m, dict)}
    taken: set[str] = set()
    out: list[Collector] = []
    errors: list[str] = []
    for kind in ("collect", "scrape"):
        entries = raw.get(kind) or []
        if not isinstance(entries, list):
            errors.append(f"{kind} must be an array of tables: write each one as [[{kind}]]")
            continue
        for i, entry in enumerate(entries):
            try:
                c = _one(kind, entry, taken, programs)
            except ConfigError as e:
                errors.append(f"[[{kind}]] entry {i + 1}: {e}; left out")
                continue
            taken.add(c.name)
            out.append(c)
    return out, errors
