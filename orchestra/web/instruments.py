"""The Instruments page's data: what measures the system, apart from the machines that work in it.

An instrument (``[[collect]]``, ``[[scrape]]`` or ``[[sources]]``) measures the running system and
never acts on it, so it is not a machine (AGENTS.md rule 7). For each one: its name, what kind it
is (a script, a URL, a source), its target, how often it is read, when it last wrote and how many
points, its failures and last error, its log, and its flags: ``simulated`` (a placeholder's
numbers), ``draft`` (an option being tried, left out of discovery) and ``expires`` (unix seconds,
when its plugin removes it; null). All of it is read from files, never by running or querying an
instrument:

- a script or a URL (or a plugin's collector): every name ``collect.kinds.instrument_kinds``
  gives, the one list an attachment is checked against. One the running host records
  (``orchestra.collect.runner``) is read from the record; the rest, declared in ``orchestra.toml``
  or in the last record only, are marked not running;
- a source: ``[[sources]]`` in ``orchestra.toml`` (its server, never its credentials), with how
  the latest discovery found it (``Model.discovery["sources"]``). A source is read at each
  discovery, not on an interval of its own, and writes nothing to the metrics store.

Each row also gains ``hung_on`` (``web/measured.py``, added by the route): the declared machines
the instrument is attached to, from the declared layer and the background read of what each
attachment selects, never from a read made for the page."""

from __future__ import annotations

from .. import runtime
from ..collect.kinds import instrument_kinds
from ..collect.spec import from_toml
from ..config import ConfigError


def _declared(project) -> tuple[list, list[str]]:
    try:
        raw = project.read_config().raw
    except (OSError, ValueError, ConfigError) as e:
        return [], [f"cannot read the configuration: {e}"]
    return from_toml(raw)


def _row(c) -> dict:
    return {"name": c.name, "kind": c.what, "target": c.shown, "every_s": c.every_s, "owner": c.owner, **c.flags()}


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
    """Every instrument, scripts and URLs first, then sources; and why any entry was left out. The
    names are ``collect.kinds.instrument_kinds``', as an attachment's check has them: one the
    running host records is running; one only declared, or only in the last record (a plugin's
    collector while no host runs), is not."""
    record = runtime.read(project)
    running = runtime.launcher(record) is not None
    recorded = record.get("instruments") or {}
    found, errors = _declared(project)
    declared = {c.name: _row(c) for c in found}
    unflagged = {"simulated": False, "draft": False, "expires": None}          # a record written before the flags
    collectors = []
    for name, kind in instrument_kinds(recorded, found).items():
        r = recorded.get(name) or {}
        if running and name in recorded:
            collectors.append({"name": name, **unflagged, **r, "running": True})
        else:
            collectors.append({**unflagged, **r, "kind": kind, **declared.get(name, {"name": name}), "running": False})
    sources, more = _sources(project, discovery)
    return {"ok": True, "host_running": running, "instruments": collectors + sources, "errors": errors + more}
