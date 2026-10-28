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
  ``[[machines]]`` and knows nothing else of them. One that reads its settings once, when it
  starts, names them in ``config_keys`` (``["bridges.github"]``), and is restarted when they change;
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
  nothing in it;
- its ``check``, optionally: ``(raw, repo_root) -> list[str]``, what it says against a merged
  configuration (empty when nothing). ``project.config_edit`` runs every plugin's check on every
  change, so a change any plugin refuses is refused, with the plugin's name. A check judges only
  the plugin's own sections, and a section's absence is no problem (removing it must be allowed).

A machine belongs to a package when its announcement says so (``package`` in
``orchestra.machine.started``) or the package declares it. The package's every-page script may
then draw that machine's card and its dialog (``Orchestra.machineCards`` in ``static/app.js``);
any other machine gets Orchestra's own.

**A project's own plugins** (``.orchestra/plugins/<name>/__init__.py``, or
``.orchestra/plugins/<name>.py``) are loaded after the installed ones, with the same contract: the
module's ``plugin(project)`` returns a ``Plugin``. They are loaded by file location as
``orchestra_local.<name>`` (``importlib.util.spec_from_file_location``, a package with its own
directory as its search path), never by adding to ``sys.path`` (AGENTS.md rule 10), and loaded
again only when a file of theirs changed. Before any plugin is made, the project's overrides are
applied (``orchestra.overrides``). Both are reported in ``Loaded.local`` (``/api/plugins``, shown on
the Core page): each one's name, file, status and error, and an override's target, package, the
version installed and the issue.

A plugin that fails to load, one whose name an earlier plugin took, a page whose path Orchestra
already serves, or a script or stylesheet not in its ``static``, is left out and reported
(``Loaded.errors``, ``/api/plugins``), never fatal: the core stays up (rule 8)."""

from __future__ import annotations

import logging
import sys
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
    check: Callable[[dict, Path | None], list[str]] | None = None   # (merged raw, repo root) -> problems with its sections


@dataclass
class Loaded:
    plugins: list[Plugin]
    errors: list[dict]
    local: list[dict] = field(default_factory=list)   # the project's own plugins and overrides, as loaded


LOCAL_DIR = Path(".orchestra") / "plugins"


@dataclass
class _LocalEntry:
    """A project's plugin, found by file, standing where an entry point would."""
    name: str
    init: Path
    package_dir: Path | None
    _cache: dict = field(default_factory=dict)

    def stamp(self) -> tuple:
        files = sorted(self.package_dir.rglob("*.py")) if self.package_dir else [self.init]
        return tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)

    def load(self):
        from .overrides import load_file
        stamp, key = self.stamp(), f"orchestra_local.{self.name}"
        kept = _LOCAL_MODULES.get(key)
        if kept is None or kept[0] != stamp:
            for m in [m for m in sys.modules if m == key or m.startswith(key + ".")]:
                sys.modules.pop(m, None)
            kept = (stamp, load_file(key, self.init, self.package_dir))
            _LOCAL_MODULES[key] = kept
        fn = getattr(kept[1], "plugin", None)
        if not callable(fn):
            raise TypeError(f"{self.init} defines no plugin(project) function")
        return fn


_LOCAL_MODULES: dict[str, tuple] = {}


def local_entries(repo_root: Path | None) -> list[_LocalEntry]:
    """The project's own plugins: each directory with an ``__init__.py``, and each ``.py`` file, in
    ``.orchestra/plugins/``."""
    d = Path(repo_root) / LOCAL_DIR if repo_root else None
    if d is None or not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.name.startswith(("_", ".")):
            continue
        if p.is_dir() and (p / "__init__.py").is_file():
            out.append(_LocalEntry(p.name, p / "__init__.py", p))
        elif p.is_file() and p.suffix == ".py":
            out.append(_LocalEntry(p.stem, p, None))
    return out


def load(project, found: Callable[[], list] | None = None) -> Loaded:
    """Every plugin installed with Orchestra, then the project's own, made for ``project``, after
    the project's overrides are applied. ``found`` stands in for the installed entry points
    (tests). Of two plugins with one name, the first is kept and the second reported."""
    from . import overrides
    root = getattr(project, "repo_root", None)
    try:
        local = overrides.apply(root)
    except Exception as e:  # noqa: BLE001 - the overrides never take the plugins down
        local = [{"kind_of": "override", "name": "*", "status": "failed", "error": f"{type(e).__name__}: {e}"}]
    mine = local_entries(root)
    plugins, errors, by = [], [], {}
    for ep in [*(found or (lambda: list(entry_points(group=GROUP))))(), *mine]:
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
    for ep in mine:
        failed = next((e["error"] for e in errors if e["plugin"] == ep.name), None)
        local.append({"kind_of": "plugin", "name": ep.name, "file": str(ep.init.relative_to(root)),
                      "status": "failed" if failed else "loaded", "error": failed})
    return Loaded(plugins, errors, local)
