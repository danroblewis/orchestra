"""Basic models: the ladder's cases (sdlab/ladder) as read-only models the editor can open.

A case `003-chain-2` is the model `ladder-003-chain-2`. Its stocks and flows are the case's true
model (laid out by the page, as the ladder page lays it out); it has no programs, so it cannot run
live. Instead its run is the case's recorded data in one variant (default counts-long): the
measured stocks' levels, played back as the model's history, so Discover can be run on it in the
editor and compared with the truth. Everything comes through the ladder's read API (cases(),
case(), case_data()), never from the case files, so any case format the ladder reads works here.
"""

from __future__ import annotations

from .ladder import api as ladder

PREFIX = "ladder-"
DEFAULT_VARIANT = "counts-long"
DRAW_SEP = "~"


def case_id(model_id: str) -> str | None:
    """The case behind a basic model's id (None if it is not one). A parametric case's draw
    `043-x#2` is the model `ladder-043-x~2` ("#" would end a URL's path)."""
    if not model_id.startswith(PREFIX):
        return None
    cid = model_id[len(PREFIX):].replace(DRAW_SEP, "#")
    return cid if ladder.case(cid) is not None else None


def model_id_of(cid: str) -> str:
    return PREFIX + cid.replace("#", DRAW_SEP)


def is_basic(model_id: str) -> bool:
    return case_id(model_id) is not None


def listing() -> list[dict]:
    """Every case as a model row, simplest first: {id, name, case, level, tags, tests}."""
    cs = sorted((c for c in ladder.cases() if not c.get("draw") and not c.get("example")), key=lambda c: (c["level"], c["id"]))   # draws stay on the ladder page; realistic cases are the sd-* examples, already in the editor
    return [{"id": PREFIX + c["id"], "name": c["title"], "case": c["id"], "level": c["level"], "tags": c["tags"], "tests": c["tests"]} for c in cs]


def draw_listing() -> list[dict]:
    """Every parametric case's draws as model rows (the page lists them only when asked)."""
    cs = sorted((c for c in ladder.cases() if c.get("draw")), key=lambda c: (c["level"], c["id"].split("#")[0], c["draw"].get("i", 0)))
    return [{"id": model_id_of(c["id"]), "name": f"{c['title']} #{c['draw'].get('i')}", "case": c["id"], "level": c["level"], "tags": c["tags"],
             "tests": c["tests"], "draw": True} for c in cs]


def variant_of(c: dict, variant: str | None) -> str:
    names = [v["name"] for v in c["variants"]]
    if variant in names:
        return variant
    return DEFAULT_VARIANT if DEFAULT_VARIANT in names else names[-1]


def model(model_id: str) -> dict:
    """The case's true model in the editor's format (no positions: the page lays it out)."""
    c = ladder.case(case_id(model_id))
    m = c["model"]
    stocks = [{"id": s["id"], "name": s.get("name") or s["id"], "unit": s.get("unit") or "things", "initial": s.get("initial", 0),
               **({"measured": False} if s.get("measured") is False else {})} for s in m["stocks"]]
    flows = []
    for f in m["flows"]:
        g = {"id": f["id"], "name": f.get("name") or f["id"], "from": f.get("from"), "to": f.get("to"), "rate": f["rate"], "machine": "environment"}
        for k in ("effects", "uses", "ratio"):
            if f.get(k) is not None:
                g[k] = f[k]
        flows.append(g)
    return {"id": model_id, "name": f"{c['id'][:3]} {c['title']}{' #' + c['id'].split('#')[1] if '#' in c['id'] else ''}", "description": f"Ladder case {c['id']}: {c['tests']}", "time_unit": "step",
            "stocks": stocks, "flows": flows, "machines": [], "recorded": True,
            "basic": {"case": c["id"], "level": c["level"], "tags": c["tags"], "tests": c["tests"], "variants": [v["name"] for v in c["variants"]],
                      "variant": variant_of(c, None), **({"schedule": m["schedule"]} if m.get("schedule") else {})}}


def snapshot(model_id: str, variant: str | None = None, since: int = 0) -> dict:
    """The recorded run in the shape of a live snapshot (runner.LiveRun.snapshot): the measured
    stocks' levels, every true flow's amount per step (what happened; Discover uses only the
    levels), the announced eras; never running."""
    cid = case_id(model_id)
    c = ladder.case(cid)
    v = variant_of(c, variant)
    d = ladder.case_data(cid, v, flows=True)
    t = d["t"]
    k = next((i for i, x in enumerate(t) if x > since), len(t))
    page = model(model_id)
    eras = d.get("eras") or [{"start": t[0] if t else 1, "label": "Start"}]
    return {"running": False, "t": t[-1] if t else 0, "seconds_per_tick": 0, "length": len(t), "variant": v,
            "series": {"t": t[k:], "levels": {s: col[k:] for s, col in d["levels"].items()}, "rates": {f: col[k:] for f, col in d["flows"].items()}, "load": {}},
            "recent": [], "stopped": None, "errors": [],
            "eras": [{"n": i + 1, "start": e["start"], "label": e.get("label") or ("Start" if i == 0 else f"era {i + 1}"), "equations": [],
                      **({"model": page} if since == 0 else {})} for i, e in enumerate(eras)]}
