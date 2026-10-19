"""The known truth behind a model the editor opens, for every model that has one.

A basic model (`ladder-<case>`, basics.py) is its case's true model already. An example `sd-*`
(sdlab/examples) opens as stocks only, but each is also a realistic ladder case of the same id
(sdlab/ladder/realistic.py), so its true model is the case's: read through the ladder's read API,
never from the example's files. The page draws the truth on request and compares an estimate with
it (the ladder's scorer, score.equations) on the data it was found from.

An example's run in the editor (its history or live sensor, livefeed.py) is the truth's engine run
with the example's seed: its first n steps are the first n steps of the case's longest variant. The
page sends the levels of its last step, and a run that does not match (another seed, an edited
copy) is refused rather than compared with data it was not found from.
"""

from __future__ import annotations

import math

from . import basics
from .ladder import api as ladder
from .ladder import cases as casemod


class Mismatch(ValueError):
    """The page's run is not the case's data."""


def case_of(model_id: str) -> str | None:
    """The ladder case behind a model (None if it has no known truth)."""
    cid = basics.case_id(model_id)
    if cid is not None:
        return cid
    c = ladder.case(model_id) if model_id.startswith("sd-") else None      # a realistic case is named after its example
    return model_id if c is not None and c.get("example") == model_id else None


def longest_variant(c: dict) -> dict:
    return max(c["variants"], key=lambda v: (int(v.get("steps") or 0), v["name"]))


def truth(model_id: str) -> dict | None:
    """The true model in the editor's format: {case, variant (the one compared against), steps, stocks
    (with measured: false for the ones the data hides), flows}; None if the model has no case."""
    cid = case_of(model_id)
    if cid is None:
        return None
    c = ladder.case(cid)
    m = c["model"]
    stocks = [{"id": s["id"], "name": s.get("name") or s["id"], "unit": s.get("unit") or "things", "initial": s.get("initial", 0),
               **({"x": s["x"], "y": s["y"]} if s.get("x") is not None and s.get("y") is not None else {}),
               **({"measured": False} if s.get("measured") is False else {})} for s in m["stocks"]]
    flows = []
    for f in m["flows"]:
        g = {"id": f["id"], "name": f.get("name") or f["id"], "from": f.get("from"), "to": f.get("to"), "rate": f["rate"]}
        for k in ("effects", "uses", "ratio"):
            if f.get(k) is not None:
                g[k] = f[k]
        flows.append(g)
    v = basics.variant_of(c, None) if basics.is_basic(model_id) else longest_variant(c)["name"]
    return {"model": model_id, "case": cid, "title": c["title"], "variant": v, "variants": [x["name"] for x in c["variants"]],
            "steps": int(casemod.variant(casemod.load(cid), v)["steps"]), "stocks": stocks, "flows": flows,
            "hidden": [s["id"] for s in stocks if s.get("measured") is False]}


def example_data(cid: str, steps: int, last: dict | None) -> tuple[str, dict]:
    """The case's data the page's run is made of: the longest variant's first `steps` steps, checked
    against the page's last levels (`last`: {stock: level}). Returns (variant, data)."""
    c = ladder.case(cid)
    v = longest_variant(c)["name"]
    full = ladder.case_data(cid, v)
    n = int(steps) if steps else len(full["t"])
    if n <= 0:
        raise Mismatch("no data yet")
    if n > len(full["t"]):
        raise Mismatch(f"the run has {n} steps; the case's data has {len(full['t'])}")
    for k, x in (last or {}).items():
        col = full["levels"].get(k)
        if col is None:
            continue                                  # a stock the case does not know (added by hand): not compared
        try:
            y = float(x)
        except (TypeError, ValueError):
            raise Mismatch(f"{k}: not a number") from None
        if not math.isclose(y, float(col[n - 1]), rel_tol=1e-6, abs_tol=1e-6):
            raise Mismatch(f"this run is not the case's data ({k} at step {n} is {y:g} here and {float(col[n - 1]):g} in the case)")
    d = {"t": full["t"][:n], "levels": {k: col[:n] for k, col in full["levels"].items()},
         "all_levels": {k: col[:n] for k, col in full["all_levels"].items()}, "eras": full["eras"]}
    if full.get("inputs"):
        d["inputs"] = {k: col[:n] for k, col in full["inputs"].items()}
    return v, d


def compare(cid: str, variant: str, flows: list[dict], data: dict) -> dict:
    """Found flows against the case's truth on `data` (as basic_live.compare, for any case)."""
    from .ladder import score

    case = casemod.load(cid)
    noise = casemod.variant(case, variant)["noise"]
    eq = score.equations(case, noise, casemod.truth_model(case, variant), flows, data)
    try:
        from .ladder.repairs import repairs
        rep = repairs(eq)
    except Exception:  # noqa: BLE001 - the parts alone are enough for the page
        rep = None
    return {"status": eq.get("status"), "parts": eq.get("parts") or [], "spurious": eq.get("spurious") or [],
            "negligible": eq.get("negligible") or [], "recall": eq.get("recall"), "precision": eq.get("precision"),
            "repairs": rep, "steps": len(data["t"]), "variant": variant}
