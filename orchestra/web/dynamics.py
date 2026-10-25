"""The Dynamics page's data: the system dynamics models in the model store, with each stock's
current level from the metrics store and each flow's equation and the machines attributed to it.

Version 1 renders the models. Inference, diffs, comparisons with observed metrics, collectors and
sub-model selection come later (docs/proposals/orchestra-kernel.md)."""

from __future__ import annotations

from ..metrics import for_project as metrics_for
from ..sd.factory import ticket_factory
from ..sd.store import ModelStore


def models_index(project) -> dict:
    store = ModelStore(project.state_dir / "models")
    ids = store.ids()
    return {"models": ids or ["tickets"], "stored": bool(ids)}


def model_view(project, model_id: str) -> dict:
    store = ModelStore(project.state_dir / "models")
    model = store.load(model_id)
    stored = model is not None
    if model is None and model_id == "tickets":
        model = ticket_factory(project.key)
    if model is None:
        return {"ok": False, "error": f"no model {model_id!r}"}
    out = model.to_json()
    out["stored"] = stored
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
