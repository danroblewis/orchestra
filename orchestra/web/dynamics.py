"""The Dynamics page's data: the system dynamics model (there is one), as the host last discovered
it or at a past version, with each flow's equation and the machines associated with it, as
hypotheses (``sd.attribute``). Nothing here
queries the metrics store or discovers anything: it reads files and the web server's caches.

Eras (``sd.eras``): the page shows the current era's model by default, and any past era's last
saved version when asked (``era``), with every era recorded, for its timeline, and what changed
at the current era's boundary (``discovery["era_comparison"]``, ``sd.compare``), and the
predictions made of the change that began the era shown, with their verdicts (``sd.predictions``,
``sd.judge``).

Version 1 renders the model and steps through its history. Simulation, prospective versions,
comparisons with observed metrics, collectors and sub-models come later
(docs/proposals/orchestra-kernel.md)."""

from __future__ import annotations

from ..sd import eras as era_record
from ..sd import predictions as prediction_record
from ..sd.store import ModelStore

NONE = "no machine associated yet"
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


def era_eras(project) -> list:
    """Every era recorded for the project, by start."""
    return era_record.recorded(ModelStore.for_state(project.state_dir))


def predictions_view(project, era: str | None = None) -> dict:
    """Every prediction recorded, with the era its change began (None: not yet matched); ``era``
    keeps one era's (``"none"``: the unmatched)."""
    store = ModelStore.for_state(project.state_dir)
    by_cause = {e.cause: e.id for e in era_record.recorded(store) if e.cause}
    out = [{**p, "era": by_cause.get(p.get("change"))} for p in prediction_record.recorded(store)]
    if era is not None:
        out = [p for p in out if (p["era"] or "none") == era]
    return {"ok": True, "predictions": out}


def model_view(project, version: int | None = None, levels: dict | None = None, levels_error: str | None = None,
               era: str | None = None) -> dict:
    """The model to show: a past version when asked; otherwise the host's latest discovery (cached
    by ``orchestra run``; nothing is discovered here), else the current version. ``levels`` are the
    stocks' current levels, read in the background by the web server. With no model yet, the
    error comes with the latest discovery's ``discovery`` block, so the page can say which series
    it looked at, why each was left out, and which sources were missing or refused."""
    store = ModelStore.for_state(project.state_dir)
    versions = store.versions()
    current = versions[-1]["version"] if versions else None
    as_of, live = None, False
    cached = store.latest_discovery()
    if era is not None and version is None and not (cached and (cached[1].era or "none") == era):
        found = store.of_era(None if era == "none" else era)
        if found is None:
            return {"ok": False, "error": f"no saved version of era {era}"}
        version = found[0]
    if version is not None:
        model = store.load(version)
        if model is None:
            return {"ok": False, "error": f"there is no version {version}"}
    else:
        if cached and not cached[1].stocks and not versions:
            d = cached[1].discovery
            n = looked_at(d)
            why = (f"a source was missing ({d['not_saved']})" if d.get("not_saved") else "nothing balances yet")
            return {"ok": False, "error": f"There is no model yet: the host's last discovery found no stocks among the "
                                          f"{n} series it looked at ({why}). It looks again every few minutes; "
                                          "`orchestra sd discover` does it now.",
                    "discovery": {**{k: d[k] for k in ("left_out", "series", "step", "start", "end", "min_r2", "sources", "not_saved",
                                                       "since_last_s") if k in d}, "looked_at": n}}
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
    out["eras_recorded"] = [vars(e) for e in era_record.recorded(store)]
    out["current_era"] = cached[1].era if cached else None
    preds = predictions_view(project)["predictions"]           # the shown era's, and with the current era those still waiting for their change
    out["predictions"] = [p for p in preds if (p["era"] is not None and p["era"] == out.get("era"))
                          or (p["era"] is None and out.get("era") == out["current_era"])]
    owners: dict[str, list[str]] = {}
    for m in model.machines:
        for fid in m.attributed:
            owners.setdefault(fid, []).append(m.id)
    for f in out["flows"]:
        # the machines associated with it, as hypotheses (sd.attribute); a version saved before
        # 2026-10-27 has only the machine its counter's label named
        assoc = (f.get("evidence") or {}).get("machines")
        f["machines"] = assoc["hypotheses"] if assoc else [{"machine": m, "origin": "label (before 2026-10-27)", "confidence": None}
                                                           for m in owners.get(f["id"], [])]
        f["association"] = (assoc or {}).get("why") or (None if f["machines"] else NONE)
        f["machine"] = f["machines"][0]["machine"] if f["machines"] else None     # the colour it is drawn in
        f["current"] = f["equations"][-1] if f["equations"] else None
    if model.discovery:
        out["discovery"]["looked_at"] = looked_at(model.discovery)
    out["levels"] = levels or {}
    out["levels_error"] = levels_error
    return {"ok": True, "model": out}
