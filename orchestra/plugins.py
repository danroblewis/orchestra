"""Plugins: pages and API routes that another package adds to Orchestra's web app.

Orchestra holds no machines (AGENTS.md rule 2); a package of machines (a bakery's, say) may
still want its own views inside the web UI. It declares a plugin as a Python entry point in
the group ``orchestra.plugins``, naming a function that takes the project and returns a
``Plugin``::

    [project.entry-points."orchestra.plugins"]
    pages = "pkg.web:plugin"

The web app mounts what it returns:

- each page at its ``path`` (``/pages``), linked from the navigation by its ``title``. Its HTML
  may use Orchestra's shared assets (``/static/app.js``, ``/static/style.css``) and ``{{v}}``
  to cache-bust them;
- its ``static`` directory at ``/plugins/<name>/static``;
- its ``scripts`` (files in ``static``) on every page of the web UI, after Orchestra's own
  scripts: for what a package must show wherever the viewer is (a button to its own page, a
  notice that something waits on the viewer). Orchestra loads them and knows nothing of them;
- its ``stylesheets`` (CSS files in ``static``), linked in the head of every page Orchestra
  serves, its own and every plugin's, after Orchestra's stylesheet: the look of what the
  package's pages and every-page scripts draw;
- its ``router`` (a FastAPI ``APIRouter``) at ``/api/plugins/<name>``;
- its ``machines``, optionally: the machines it provides, declared (``Declared``: the id, the
  kind of thing it is, how it is engaged and what it listens for, the same as an announcement
  says), so the Machines page lists one before it is first seen. What is observed always wins: a
  declaration only fills in a machine nobody has seen yet, and names the package a machine
  belongs to. It says nothing about flows: which flows a machine's work relates to is only ever
  inferred (``sd.attribute``);
- its ``processes``, optionally: the commands ``orchestra run`` keeps running for it
  (``orchestra.launcher.Process``: a name, a command, a restart policy, and how long it may take
  to stop), such as a scheduler or
  the host of the programs it runs. Orchestra starts them as it starts the project's own
  ``[[machines]]`` and knows nothing else of them;
- its ``collectors``, optionally: the instruments ``orchestra run`` reads measurements from for
  it (instruments, not machines: their series are labelled ``instrument=<name>`` and nothing is
  announced for them) (``orchestra.collect.spec.Collector``: ``Collector.scrape(name, url, ...)`` or
  ``Collector.collect(name, command, ...)``), run like the project's ``[[scrape]]`` and
  ``[[collect]]`` entries and named ``<plugin>.<name>``; a project entry of that name takes the
  place of the plugin's;
- its ``guide``, optionally: a markdown file shipped in its package, written for an AI operator
  (the Supervisor) that configures the plugin for the owner: what each setting is for, when to
  choose each value, the pitfalls, how to check a setting took, and which choices are the
  human's. Orchestra serves it with its own (``orchestra.guides``, ``/api/guides``) and reads
  nothing in it.

A machine belongs to a package when its announcement says so (``package`` in
``orchestra.machine.started``) or the package declares it. The package's every-page script may
then draw that machine's card and its dialog (``Orchestra.machineCards`` in ``static/app.js``);
any other machine gets Orchestra's own.

A plugin that fails to load, one whose name an earlier plugin took, a page whose path Orchestra
already serves, or a script or stylesheet not in its ``static``, is left out and reported
(``Loaded.errors``, ``/api/plugins``), never fatal: the core stays up (rule 8)."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from .collect.spec import Collector
from .launcher import Process

GROUP = "orchestra.plugins"
log = logging.getLogger("orchestra.plugins")


@dataclass
class Page:
    path: str            # where it is served, e.g. "/pages"
    title: str           # its link in the navigation
    file: Path           # the HTML


@dataclass
class Declared:
    id: str                                   # the machine, as its events' source names it
    kind: str = "program"                     # what the package says it is: program, person, service, ...
    mode: str | None = None                   # continuous | scheduled | ad hoc
    listens_for: list[str] = field(default_factory=list)


@dataclass
class Plugin:
    name: str
    pages: list[Page] = field(default_factory=list)
    static: Path | None = None
    router: Any = None   # a fastapi.APIRouter, mounted at /api/plugins/<name>
    scripts: list[str] = field(default_factory=list)   # files in ``static`` loaded on every page
    stylesheets: list[str] = field(default_factory=list)   # files in ``static`` every page links
    machines: list[Declared] = field(default_factory=list)
    processes: list[Process] = field(default_factory=list)   # what `orchestra run` starts for it
    collectors: list[Collector] = field(default_factory=list)   # what `orchestra run` scrapes or runs for measurements
    guide: Path | None = None   # a markdown file in the package: how to configure the plugin, for an AI operator


@dataclass
class Loaded:
    plugins: list[Plugin]
    errors: list[dict]


def load(project, found: Callable[[], list] | None = None) -> Loaded:
    """Every plugin installed with Orchestra, made for ``project``. ``found`` stands in for the
    installed entry points (tests). Of two plugins with one name, the first is kept and the second
    reported."""
    plugins, errors, by = [], [], {}
    for ep in (found or (lambda: list(entry_points(group=GROUP))))():
        try:
            p = ep.load()(project)
            if not isinstance(p, Plugin):
                raise TypeError(f"returned {type(p).__name__}, not a Plugin")
            if p.name in by:
                log.warning("plugin %s is named %s, as %s is; left out", ep.name, p.name, by[p.name])
                errors.append({"plugin": ep.name, "error": f"its name {p.name!r} is taken by the plugin of entry point "
                                                           f"{by[p.name]!r}; left out", "trace": ""})
                continue
            by[p.name] = ep.name
            plugins.append(p)
        except Exception as e:  # noqa: BLE001 - one broken plugin must not take the web app down
            log.warning("plugin %s failed to load: %s", ep.name, e)
            errors.append({"plugin": ep.name, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=4)})
    return Loaded(plugins, errors)
