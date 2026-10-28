"""Plugin commands: `orchestra <name> [args...]`, run by another package.

A plugin's command line is a subcommand of `orchestra`, not a console script of its own. The
package declares it as a Python entry point in the group ``orchestra.commands``, named for the
plugin, naming a callable that takes the arguments after the name::

    [project.entry-points."orchestra.commands"]
    tasks = "tasking.cli:main"          # def main(argv: list[str]) -> int | None

It is a group of its own, apart from ``orchestra.plugins``, because a command must work before a
project exists (``orchestra tasks init``): it is given argv, never a project.

``orchestra tasks add "x" --to y`` calls ``main(["add", "x", "--to", "y"])`` and exits with what it
returns (``None`` is 0). Before the call, ``ORCHESTRA_PROG`` is set to ``orchestra tasks`` and so is
``sys.argv[0]``, so an ``argparse.ArgumentParser()`` without a ``prog`` shows ``orchestra tasks``
in its usage; ``orchestra --repo PATH tasks ...`` sets ``ORCHESTRA_REPO`` to PATH. ``orchestra
--help`` lists the commands with one line each: the callable's ``help`` attribute if it has one,
else the first line of its module's docstring.

A command that fails to load fails alone, with an error naming its entry point; the rest of the
CLI works. A name that is one of Orchestra's own subcommands is refused, with a warning, and of
two entry points with one name the first is kept."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points

GROUP = "orchestra.commands"
PROG_ENV = "ORCHESTRA_PROG"
BUILTIN = frozenset({"init", "run", "web", "metrics", "sd", "sources", "events"})


@dataclass
class Installed:
    commands: dict[str, object] = field(default_factory=dict)   # name -> entry point
    warnings: list[str] = field(default_factory=list)


def installed(builtin: frozenset[str] = BUILTIN) -> Installed:
    """The plugin commands installed beside Orchestra, without importing any of them."""
    out = Installed()
    try:
        found = list(entry_points(group=GROUP))
    except Exception as e:  # noqa: BLE001 - broken metadata must not take the CLI down
        out.warnings.append(f"plugin commands could not be listed: {type(e).__name__}: {e}")
        return out
    for ep in found:
        where = getattr(ep, "value", "?")
        if ep.name in builtin:
            out.warnings.append(f"plugin command {ep.name!r} ({where}) is refused: {ep.name!r} is one of "
                                "Orchestra's own subcommands")
        elif ep.name in out.commands:
            out.warnings.append(f"plugin command {ep.name!r} ({where}) is left out: the name is taken by "
                                f"{getattr(out.commands[ep.name], 'value', '?')}")
        else:
            out.commands[ep.name] = ep
    return out


def summary(ep) -> str:
    """One line of help: the callable's ``help`` attribute, else its module's docstring's first
    line. A command that fails to load says so instead."""
    try:
        fn = ep.load()
    except Exception as e:  # noqa: BLE001 - listing must survive a broken command
        return f"(broken: {type(e).__name__}: {e})"
    text = getattr(fn, "help", None)
    if not isinstance(text, str) or not text.strip():
        text = getattr(sys.modules.get(getattr(fn, "__module__", "") or ""), "__doc__", None) or ""
    lines = [s.strip() for s in text.strip().splitlines()]
    return lines[0] if lines else ""


def run(name: str, ep, argv: list[str], repo: str | None = None) -> int:
    """Load the command and call it with ``argv``; its exit code. Fails alone if it cannot load."""
    where = getattr(ep, "value", "?")
    try:
        fn: Callable = ep.load()
        if not callable(fn):
            raise TypeError(f"{where} is a {type(fn).__name__}, not a callable")
    except Exception as e:  # noqa: BLE001 - a broken plugin fails only itself
        print(f"orchestra: plugin command {name!r} ({where}) failed to load: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    prog = f"orchestra {name}"
    os.environ[PROG_ENV] = prog
    if repo:
        os.environ["ORCHESTRA_REPO"] = repo
    saved = sys.argv
    sys.argv = [prog, *argv]
    try:
        rc = fn(list(argv))
    finally:
        sys.argv = saved
    return 0 if rc is None else rc
