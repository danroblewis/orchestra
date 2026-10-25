"""The Dynamics page's data: the system dynamics model (there is one) at its current version or a
past one, with each stock's current level from the metrics store and each flow's equation and the
machines attributed to it.

Version 1 renders the model and steps through its history. Simulation, prospective versions,
comparisons with observed metrics, collectors and sub-models come later
(docs/proposals/orchestra-kernel.md)."""

from __future__ import annotations

from ..metrics import for_project as metrics_for
from ..sd.factory import ticket_factory
from ..sd.store import ModelStore


def model_view(project, version: int | None = None) -> dict:
    store = ModelStore.for_state(project.state_dir)
    versions = store.versions()
    current = versions[-1]["version"] if versions else None
    model = store.load(version)
    if model is None and version is not None:
        return {"ok": False, "error": f"there is no version {version}"}
    stored = model is not None
    if model is None:
        model = ticket_factory(project.key)
    out = model.to_json()
    out["stored"] = stored
    out["version"] = (version or current) if stored else None
    out["current"] = current
    out["versions"] = versions
    owner = {f: m.id for m in model.machines for f in m.attributed}
    for f in out["flows"]:
        f["machine"] = owner.get(f["id"])
        f["current"] = f["equations"][-1] if f["equations"] else None
    levels, error = {}, None
    try:
        ms = metrics_for(project)
        for s in model.stocks:
            if s.series:
                last = ms.latest(s.series.name, s.series.labels)
                if last:
                    levels[s.id] = {"t": last[0], "v": last[1]}
    except Exception as e:  # noqa: BLE001 - the model still renders without levels
        error = f"{type(e).__name__}: {e}"
    out["levels"] = levels
    out["levels_error"] = error
    return {"ok": True, "model": out}
