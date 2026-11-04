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
  the latest discovery found it (``Model.discovery["sources"]``) and the series it read from it
  (``Model.discovery["sourced"]``: each one's selector as the store spells it, and the query the
  Core page's External stores box opens it with), and what its last inference round did (the
  cache the host's round left, ``sources.cache``: probed, kept, demoted and queued, each
  candidate's fate and why, the store's labels by rank). A source is read at each
  discovery, not on an interval of its own, and writes nothing to the metrics store.

Each row also gains ``hung_on`` (``web/measured.py``, added by the route): the declared machines
the instrument is attached to, from the declared layer and the background read of what each
attachment selects, never from a read made for the page."""

from __future__ import annotations

from .. import runtime
from ..collect.kinds import instrument_kinds
from ..collect.runner import RECORD_EVERY_S
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


SOURCE_SERIES = 500          # a source's series listed in its row, at most
EXPLORED = 300               # a source's candidates listed with their fate this round, at most
LABELS = 30                  # ... and its labels ranked across the store


def _round(project, name: str) -> dict:
    """What the source's last inference round did (``sources.explore``): probed, kept, demoted and
    queued, each candidate's fate and why, and the store's labels by rank, read from the cache the
    host's round left (``sources.cache``); {} before any round."""
    from ..sources.cache import cached
    inf = cached(project.state_dir, name)
    if inf is None or not inf.round:
        return {}
    labels = sorted(inf.labels.items(), key=lambda kv: (-kv[1].get("rank", 0.0), kv[0]))
    return {"inference": {"at": inf.at, **inf.round, "requests": inf.requests},
            "explored": inf.explored[:EXPLORED], "explored_more": max(0, len(inf.explored) - EXPLORED),
            "labels": [{"label": k, "rank": v.get("rank"), "why": v.get("why")} for k, v in labels[:LABELS]]}


def _sources(project, discovery: dict | None) -> tuple[list[dict], list[str]]:
    from ..sources.spec import for_project
    try:
        specs = for_project(project)
    except Exception as e:  # noqa: BLE001 - the page shows the rest
        return [], [f"[[sources]]: {type(e).__name__}: {e}"]
    d = discovery or {}
    status, sourced = d.get("sources") or {}, d.get("sourced") or {}
    window = {k: d[k] for k in ("start", "end", "step") if d.get(k) is not None}
    out = []
    for s in specs.sources:
        st = status.get(s.name) or {}
        series = [{"key": k, **{x: v for x, v in p.items() if x != "source"}} for k, p in sourced.items() if p.get("source") == s.name]
        out.append({"name": s.name, "kind": "source", "target": s.where(), "every_s": None, "owner": "project",
                    "type": s.type, "prefix": s.prefix, "status": st or None, "match": list(s.match),
                    "split": list(s.split) if s.split is not None else None,      # the only labels its families are split by
                    # every series the latest discovery read from it, each with its selector as the store spells it
                    "series": series[:SOURCE_SERIES], "series_more": max(0, len(series) - SOURCE_SERIES), "window": window,
                    **({"last_error": st["error"]} if st.get("error") else {}), **_round(project, s.name)})
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
    return {"ok": True, "host_running": running, "instruments": collectors + sources, "errors": errors + more,
            "record_every_s": RECORD_EVERY_S}         # how stale the record of a write may be (collect/runner.py)
