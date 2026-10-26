"""Plugins: pages and API routes that another package adds to Orchestra's web app.

Orchestra holds no machines (AGENTS.md rule 2); a package of machines, such as a task system,
may still want its own views inside the web UI. It declares a plugin as a Python entry point in
the group ``orchestra.plugins``, naming a function that takes the project and returns a
``Plugin``::

    [project.entry-points."orchestra.plugins"]
    tasks = "tasking.web:plugin"

The web app mounts what it returns:

- each page at its ``path`` (``/tasks``), linked from the navigation by its ``title``. Its HTML
  may use Orchestra's shared assets (``/static/app.js``, ``/static/style.css``) and ``{{v}}``
  to cache-bust them;
- its ``static`` directory at ``/plugins/<name>/static``;
- its ``scripts`` (files in ``static``) on every page of the web UI, after Orchestra's own
  scripts: for what a package must show wherever the viewer is (a way to reach its agents, a
  notice that something waits on the viewer). Orchestra loads them and knows nothing of them;
- its ``router`` (a FastAPI ``APIRouter``) at ``/api/plugins/<name>``.

A plugin that fails to load, or a page whose path Orchestra already serves, is left out and
reported (``/api/plugins``), never fatal: the core stays up (rule 8)."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

GROUP = "orchestra.plugins"
log = logging.getLogger("orchestra.plugins")


@dataclass
class Page:
    path: str            # where it is served, e.g. "/tasks"
    title: str           # its link in the navigation
    file: Path           # the HTML


@dataclass
class Plugin:
    name: str
    pages: list[Page] = field(default_factory=list)
    static: Path | None = None
    router: Any = None   # a fastapi.APIRouter, mounted at /api/plugins/<name>
    scripts: list[str] = field(default_factory=list)   # files in ``static`` loaded on every page


@dataclass
class Loaded:
    plugins: list[Plugin]
    errors: list[dict]


def load(project, found: Callable[[], list] | None = None) -> Loaded:
    """Every plugin installed with Orchestra, made for ``project``. ``found`` stands in for the
    installed entry points (tests)."""
    plugins, errors = [], []
    for ep in (found or (lambda: list(entry_points(group=GROUP))))():
        try:
            p = ep.load()(project)
            if not isinstance(p, Plugin):
                raise TypeError(f"returned {type(p).__name__}, not a Plugin")
            plugins.append(p)
        except Exception as e:  # noqa: BLE001 - one broken plugin must not take the web app down
            log.warning("plugin %s failed to load: %s", ep.name, e)
            errors.append({"plugin": ep.name, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=4)})
    return Loaded(plugins, errors)
