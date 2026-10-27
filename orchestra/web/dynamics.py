"""The Dynamics page's data: the system dynamics model (there is one), as the host last discovered
it or at a past version, with each flow's equation and the machines attributed to it. Nothing here
queries the metrics store or discovers anything: it reads files and the web server's caches.

Version 1 renders the model and steps through its history. Simulation, prospective versions,
comparisons with observed metrics, collectors and sub-models come later
(docs/proposals/orchestra-kernel.md)."""

from __future__ import annotations

from ..sd.store import ModelStore

EARLY = ("Orchestra's own", "named orchestra_", "no longer written")   # the reasons a series is left out before it is considered (sd.discover)


def looked_at(discovery: dict) -> int:
    """How many series a discovery looked at: every one sampled (``sampled``), of which ``series``
    were considered and the rest left out at once (Orchestra's own, or no longer written).
    Discoveries before 2026-10-26 recorded only ``series``: the ones left out at once are counted
    from their reasons."""
    if "sampled" in discovery:
        return int(discovery["sampled"])
    early = sum(1 for why in (discovery.get("left_out") or {}).values() if why.startswith(EARLY))
    return int(discovery.get("series") or 0) + early


def model_view(project, version: int | None = None, levels: dict | None = None, levels_error: str | None = None) -> dict:
    """The model to show: a past version when asked; otherwise the host's latest discovery (cached
    by ``orchestra run``; nothing is discovered here), else the current version. ``levels`` are the
    stocks' current levels, read in the background by the web server. With no model yet, the
    error comes with the latest discovery's ``discovery`` block, so the page can say which series
    it looked at and why each was left out."""
    store = ModelStore.for_state(project.state_dir)
    versions = store.versions()
    current = versions[-1]["version"] if versions else None
    as_of, live = None, False
    if version is not None:
        model = store.load(version)
        if model is None:
            return {"ok": False, "error": f"there is no version {version}"}
    else:
        cached = store.latest_discovery()
        if cached and not cached[1].stocks and not versions:
            d = cached[1].discovery
            n = looked_at(d)
            return {"ok": False, "error": f"There is no model yet: the host's last discovery found no stocks among the "
                                          f"{n} series it looked at (nothing balances yet). It looks again every few minutes; "
                                          "`orchestra sd discover` does it now.",
                    "discovery": {**{k: d[k] for k in ("left_out", "series", "step", "start", "end", "min_r2") if k in d}, "looked_at": n}}
        if cached:
            as_of, model = cached
            live = True
        else:
            model = store.load()
    if model is None:
        return {"ok": False, "error": "There is no model yet. The bootstrap host (`orchestra run`) discovers it from the "
                                      "metrics store every few minutes; `orchestra sd discover` does it now."}
    out = model.to_json()
    out["stored"] = bool(versions)
    out["version"] = version or current
    out["current"] = current
    out["versions"] = versions
    out["live"] = live                       # the latest discovery, which may be newer than any version
    out["as_of"] = as_of
    owner = {f: m.id for m in model.machines for f in m.attributed}
    for f in out["flows"]:
        f["machine"] = owner.get(f["id"])
        f["current"] = f["equations"][-1] if f["equations"] else None
    if model.discovery:
        out["discovery"]["looked_at"] = looked_at(model.discovery)
    out["levels"] = levels or {}
    out["levels_error"] = levels_error
    return {"ok": True, "model": out}
