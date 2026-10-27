"""The instruments ``orchestra.toml`` declares, ``[[collect]]`` (a command) and ``[[scrape]]`` (a
URL), and those the plugins declare (``Plugin.collectors``).

::

    [[collect]]
    name = "disk"                    # the instrument's id: letters, digits, . _ -
    command = "machines/disk.sh"     # split like a shell would, not run by one
    every = "60s"                    # how often (default 60 s)
    timeout = "20s"                  # how long one round may take (default 10 s, never more than every)

    [[scrape]]
    name = "app"
    url = "http://127.0.0.1:9100/metrics"
    every = "30s"

An instrument's name is its own: it may share a ``[[machines]]`` entry's name (a scrape of the
program that entry runs, say) without being that machine. A plugin's collector is named ``<plugin>.<name>``; a project entry of that name takes its place. An entry that cannot be
used is left out, with the reason; the others stand."""

from __future__ import annotations

import shlex
from collections.abc import Iterable
from dataclasses import dataclass, replace

from ..config import ConfigError, parse_duration
from ..events import HOST
from ..launcher import NAME

EVERY_S = 60.0
TIMEOUT_S = 10.0
MIN_EVERY_S = 1.0
KINDS = ("collect", "scrape")


@dataclass(frozen=True)
class Collector:
    name: str
    kind: str                  # "collect" (a command) or "scrape" (a URL)
    target: str                # the command, or the URL
    every_s: float = EVERY_S
    timeout_s: float = TIMEOUT_S
    owner: str = "project"     # "project", or the plugin that declared it

    @classmethod
    def scrape(cls, name: str, url: str, **kw) -> Collector:
        return cls(name, "scrape", url, **kw)

    @classmethod
    def collect(cls, name: str, command: str, **kw) -> Collector:
        return cls(name, "collect", command, **kw)

    @property
    def what(self) -> str:
        """What kind of instrument it is, in a word: a script, or a URL."""
        return "script" if self.kind == "collect" else "URL"

    def argv(self) -> list[str]:
        return shlex.split(self.target)


def check(c: Collector, accepted: Iterable[Collector]) -> str | None:
    """Why ``c`` cannot be run beside the collectors already ``accepted``, or None."""
    if not isinstance(c.name, str) or not NAME.match(c.name):
        return f"bad name {c.name!r}: use letters, digits, '.', '_' and '-'"
    if c.name == HOST or any(o.name == c.name for o in accepted):
        return f"{c.name}: the name is taken (by Orchestra's host or another instrument)"
    if c.kind not in KINDS:
        return f"{c.name}: kind must be collect or scrape, not {c.kind!r}"
    field = "command" if c.kind == "collect" else "url"
    if not isinstance(c.target, str) or not c.target.strip():
        return f"{c.name}: needs a {field}"
    if c.kind == "collect":
        try:
            if not shlex.split(c.target):
                return f"{c.name}: empty command"
        except ValueError as e:
            return f"{c.name}: bad command: {e}"
    elif not c.target.startswith(("http://", "https://")):
        return f"{c.name}: url must start with http:// or https://"
    for what, v in (("every", c.every_s), ("timeout", c.timeout_s)):
        if isinstance(v, bool) or not isinstance(v, int | float):
            return f"{c.name}: {what} must be a number of seconds, not {v!r}"
    if c.every_s < MIN_EVERY_S:
        return f"{c.name}: every must be at least {MIN_EVERY_S:g} s"
    if c.timeout_s <= 0:
        return f"{c.name}: timeout must be more than 0"
    return None


def _one(kind: str, entry: object) -> Collector:
    if not isinstance(entry, dict):
        raise ConfigError("is not a table")
    every = parse_duration(entry.get("every"), EVERY_S)
    timeout = parse_duration(entry.get("timeout"), TIMEOUT_S)
    return Collector(entry.get("name"), kind, entry.get("command" if kind == "collect" else "url"), every,
                     min(timeout, every) if timeout > 0 else timeout)


def from_toml(raw: dict, plugins: Iterable[Collector] = ()) -> tuple[list[Collector], list[str]]:
    """The collectors of a parsed ``orchestra.toml`` and of the plugins (each named
    ``<owner>.<name>``), and why any entry was left out. A project entry wins over a plugin's of the
    same name."""
    out: list[Collector] = []
    errors: list[str] = []
    for kind in KINDS:
        entries = raw.get(kind) or []
        if not isinstance(entries, list):
            errors.append(f"{kind} must be an array of tables: write each one as [[{kind}]]")
            continue
        for i, entry in enumerate(entries):
            try:
                c = _one(kind, entry)
                if (why := check(c, out)) is not None:
                    raise ConfigError(why)
            except ConfigError as e:
                errors.append(f"[[{kind}]] entry {i + 1}: {e}; left out")
                continue
            out.append(c)
    project = {c.name for c in out}
    for c in plugins:
        c = replace(c, name=f"{c.owner}.{c.name}")
        if c.name in project:
            errors.append(f"plugin {c.owner}: its collector {c.name} is replaced by the project's entry of that name")
            continue
        if isinstance(c.every_s, int | float) and isinstance(c.timeout_s, int | float) and c.timeout_s > c.every_s:
            c = replace(c, timeout_s=c.every_s)
        if (why := check(c, out)) is not None:
            errors.append(f"plugin {c.owner}: {why}; left out")
            continue
        out.append(c)
    return out, errors
