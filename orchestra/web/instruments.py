"""The Instruments page's data: what measures the system, apart from the machines that work in it.

An instrument (``[[collect]]``, ``[[scrape]]`` or ``[[sources]]``) measures the running system and
never acts on it, so it is not a machine (AGENTS.md rule 7). For each one: its name, what kind it
is (a script, a URL, a source), its target, how often it is read, when it last wrote and how many
points, its failures and last error, and its log. All of it is read from files, never by running
or querying an instrument:

- a script or a URL: the runtime record's ``instruments`` (written by the host that launches,
  ``orchestra.collect.runner``), or, while no host runs, the entries ``orchestra.toml`` declares
  (marked not running);
- a source: ``[[sources]]`` in ``orchestra.toml`` (its server, never its credentials), with how
  the latest discovery found it (``Model.discovery["sources"]``). A source is read at each
  discovery, not on an interval of its own, and writes nothing to the metrics store."""

from __future__ import annotations

from .. import runtime
from ..collect.spec import from_toml
from ..config import ConfigError


def _declared(project) -> tuple[list[dict], list[str]]:
    try:
        raw = project.read_config().raw
    except (OSError, ValueError, ConfigError) as e:
        return [], [f"cannot read the configuration: {e}"]
    found, errors = from_toml(raw)
    return [{"name": c.name, "kind": c.what, "target": c.shown, "every_s": c.every_s, "owner": c.owner} for c in found], errors


def _sources(project, discovery: dict | None) -> tuple[list[dict], list[str]]:
    from ..sources.spec import for_project
    try:
        specs = for_project(project)
    except Exception as e:  # noqa: BLE001 - the page shows the rest
        return [], [f"[[sources]]: {type(e).__name__}: {e}"]
    status = (discovery or {}).get("sources") or {}
    out = []
    for s in specs.sources:
        st = status.get(s.name) or {}
        out.append({"name": s.name, "kind": "source", "target": s.where(), "every_s": None, "owner": "project",
                    "type": s.type, "prefix": s.prefix, "status": st or None,
                    **({"last_error": st["error"]} if st.get("error") else {})})
    return out, [f"[[sources]] {k}: {why}" for k, why in specs.refused.items()]


def instruments_view(project, discovery: dict | None = None) -> dict:
    """Every instrument, scripts and URLs first, then sources; and why any entry was left out."""
    record = runtime.read(project)
    running = runtime.launcher(record) is not None
    recorded = record.get("instruments") or {}
    declared, errors = _declared(project)
    if running and recorded:
        collectors = [{"name": n, **r, "running": True} for n, r in recorded.items()]
    else:
        last = {n: r for n, r in recorded.items()}
        collectors = [{**last.get(d["name"], {}), **d, "running": False} for d in declared]
    sources, more = _sources(project, discovery)
    return {"ok": True, "host_running": running, "instruments": collectors + sources, "errors": errors + more}
