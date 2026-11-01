"""Mounting the installed plugins into the web app: their pages, static files, routes, every-page
scripts and stylesheets, and the machines they declare (orchestra/plugins.py)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import Project
from .pages import render


def _part(errors: list[dict], plugin: str, what: str, add) -> bool:
    """Add one part of a plugin; on failure report it and leave only that part out."""
    try:
        add()
        return True
    except Exception as e:  # noqa: BLE001 - a broken plugin is reported, never fatal (rule 8)
        errors.append({"plugin": plugin, "error": f"{what} left out: {type(e).__name__}: {e}"})
        return False


def mount_plugins(app: FastAPI, project: Project, stylesheets: list[str]):
    """Pages, static files and API routes of the installed plugins (orchestra/plugins.py).
    Adds their every-page stylesheets to ``stylesheets``; returns what adds their declared
    machines to the observed ones, and their collectors (each with its owner), which discovery
    reads the simulated flag from."""
    from .. import plugins as plug
    loaded = plug.load(project)
    taken = {getattr(r, "path", None) for r in app.routes}
    pages, scripts, errors = [], [], list(loaded.errors)
    for p in loaded.plugins:
        for what, files, into in (("script", p.scripts, scripts), ("stylesheet", p.stylesheets, stylesheets)):
            for f in files:
                if p.static and (p.static / f).is_file():
                    into.append(f"/plugins/{p.name}/static/{f}")
                else:
                    errors.append({"plugin": p.name, "error": f"{what} {f} is not a file in its static directory; left out"})
        # each part on its own: a broken one is left out and reported, never fatal (plugins.py),
        # so the core's pages are served whatever a plugin declares
        if p.static:
            if Path(p.static).is_dir():
                _part(errors, p.name, "static files", lambda p=p: app.mount(
                    f"/plugins/{p.name}/static", StaticFiles(directory=str(p.static)), name=f"plugin-{p.name}"))
            else:
                errors.append({"plugin": p.name, "error": f"static directory {p.static} is not a directory; left out"})
        if p.router is not None:
            _part(errors, p.name, "router", lambda p=p: app.include_router(p.router, prefix=f"/api/plugins/{p.name}"))
        for pg in p.pages:
            if pg.path in taken:
                errors.append({"plugin": p.name, "error": f"page {pg.path} is already served"})
                continue

            def serve(f=pg.file) -> str:
                return render(Path(f), stylesheets)
            if _part(errors, p.name, f"page {pg.path}", lambda pg=pg, serve=serve: app.add_api_route(
                    pg.path, serve, methods=["GET"], response_class=HTMLResponse, include_in_schema=False)):
                taken.add(pg.path)
                pages.append({"plugin": p.name, "path": pg.path, "title": pg.title})

    @app.get("/api/plugins")
    def plugin_list() -> dict:
        """The installed plugins' pages (for the navigation), any that failed to load, and the
        project's own plugins and overrides as they were loaded (``local``; the Core page lists them)."""
        return {"ok": True, "pages": pages, "scripts": scripts, "errors": errors, "local": loaded.local}

    @app.get("/api/guides")
    def guides() -> dict:
        """How to configure Orchestra and each installed plugin, for an AI operator: Orchestra's
        guide, then each plugin's (orchestra/guides.py), read now."""
        from .. import guides as g
        return {"ok": True, "guides": g.collect(project, loaded)}

    declared = [(p.name, d) for p in loaded.plugins for d in p.machines]

    def declare(machines: list[dict]) -> None:
        """Observed machines keep what was observed; a declaration names the package and the kind
        of a machine that announced neither, and adds a machine not seen yet (marked so). The first
        plugin to declare an id adds it; a later declaration of that id only fills in what is
        still empty: of an observed machine its package and kind, of a placeholder also its mode
        and what it listens for (added to). A kind of None is unknown: left empty."""
        seen = {m["id"]: m for m in machines}
        for pkg, d in declared:
            m = seen.get(d.id)
            if m is not None:
                m["package"] = m.get("package") or pkg
                m["kind"] = m.get("kind") or d.kind
                if m.get("unseen"):
                    m["mode"] = m.get("mode") or d.mode
                    m["subscribes"] = [*m["subscribes"], *(t for t in d.listens_for if t not in m["subscribes"])]
                continue
            m = {"id": d.id, "bootstrap": False, "mode": d.mode, "kind": d.kind, "package": pkg, "about": {},
                 "unseen": True, "publishes": [], "subscribes": list(d.listens_for), "flows": [], "logs": [],
                 "instances": [], "first_seen": None, "last_seen": None, "active": False}
            machines.append(m)
            seen[d.id] = m
    return declare, [replace(c, owner=p.name) for p in loaded.plugins for c in p.collectors]
