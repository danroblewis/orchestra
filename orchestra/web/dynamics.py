"""The Dynamics page's data: the system dynamics model (there is one), as the host last discovered
it or at a past version, with each flow's equation and the machines attributed to it. Nothing here
queries the metrics store or discovers anything: it reads files and the web server's caches.

Version 1 renders the model and steps through its history. Simulation, prospective versions,
comparisons with observed metrics, collectors and sub-models come later
(docs/proposals/orchestra-kernel.md)."""

from __future__ import annotations

from ..sd.store import ModelStore


def model_view(project, version: int | None = None, levels: dict | None = None, levels_error: str | None = None) -> dict:
    """The model to show: a past version when asked; otherwise the host's latest discovery (cached
    by ``orchestra run``; nothing is discovered here), else the current version. ``levels`` are the
    stocks' current levels, read in the background by the web server."""
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
            n = len(cached[1].discovery.get("left_out", {}))
            return {"ok": False, "error": f"There is no model yet: the host's last discovery found no stocks among "
                                          f"{n} series (nothing balances yet). It looks again every few minutes; "
                                          "`orchestra sd discover` does it now."}
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
    out["levels"] = levels or {}
    out["levels_error"] = levels_error
    return {"ok": True, "model": out}
