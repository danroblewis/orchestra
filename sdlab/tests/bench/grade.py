"""Grading a discovery result against the true model of a ground-truth example.

parts: parts of the true model recovered in the right form (truth.json, "sd_structure"). A
relationship is an ordered pair of stocks: a move (things go from A to B), a link (B's arrivals
follow A's level), a hidden stock (things leave A and arrive in B later) or an echo (things come back
into B some time after arriving in A); each flow to or from outside counts on its own.

skill@H (same_behaviour): from ~150 moments in the run, the found and the true model are both run H
steps from every stock's true level, fed the same outside inflows (the truth's schedule replaces the
found model's outside inflow into every stock the truth feeds from outside), so only their own
dynamics differ. skill = 1 - (spread between them / how far the truth moved)^2: 1 = behaves as the
truth, 0 = no better than assuming nothing changes, below 0 = worse.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sdlab.discovery.simulate import Model, levels_array, starts_for

EXAMPLES = Path(__file__).resolve().parents[2] / "sdlab" / "examples"


def _from_hospital(t: dict) -> dict:
    """The hospital's answer key predates the shared format: its flows, with hidden stocks by name."""
    measured = set(t["measured"]["stocks"])
    sd = {"moves": [], "outside": [], "hidden": [], "links": [], "echoes": []}
    for f in t["flows"].values():
        if f.get("from") in measured and f.get("to") in measured:
            sd["moves"].append({"from": f["from"], "to": f["to"]})
        elif not f.get("from") and f.get("to") in measured:
            sd["outside"].append({"to": f["to"]})
        elif f.get("from") in measured and not f.get("to"):
            sd["outside"].append({"from": f["from"]})
    for h in t["hidden_stocks"].values():
        for to in h["between"]["into"]:
            sd["hidden"].append({"from": h["between"]["out_of"], "to": to})
    return sd


def truth_of(example: str) -> dict:
    t = json.loads((EXAMPLES / example / "truth.json").read_text())
    sd = t.get("sd_structure") or _from_hospital(t)
    rel: dict[str, str] = {}

    def put(a, b, kind):
        if a and b and f"{a}>{b}" not in rel:
            rel[f"{a}>{b}"] = kind

    for m in sd.get("moves") or [f for f in sd.get("flows", []) if f.get("from") and f.get("to")]:
        put(m["from"], m["to"], "move")
    for link in sd.get("links") or [{"driver": d["driver"], "into": d["into"]} for d in sd.get("driven_inflows", [])]:
        put(link["driver"], link["into"], "link")
    for h in sd.get("hidden", []):
        put(h["from"], h["to"], "hidden")
    for e in sd.get("echoes", []):
        put(e["source"], e["into"], "echo")
    more = sd.get("in_long_runs") or {}
    for m in more.get("moves", []):
        put(m["from"], m["to"], "move")
    for link in more.get("links", []):
        put(link["driver"], link["into"], "link")
    outside = set()
    for o in sd.get("outside") or [f for f in sd.get("flows", []) if not f.get("from") or not f.get("to")]:
        if o.get("from") and not o.get("to"):
            outside.add(f"{o['from']}>out")
        if o.get("to") and not o.get("from"):
            outside.add(f"in>{o['to']}")
    return {"rel": rel, "outside": outside}


def found(result: dict) -> dict:
    rel, outside = {}, []
    for f in result["flows"]:
        a, b, kind = None, f.get("to"), None
        if f.get("driver"):
            a, kind = f["driver"], "link"
        elif f.get("via"):
            a = f.get("from") or f["via"].get("echo")
            kind = "hidden" if f.get("from") else "echo"
        elif f.get("from") and f.get("to"):
            a, kind = f["from"], "move"
        if a and b:
            rel[f"{a}>{b}"] = kind
        else:
            outside.append(f"{f['from']}>out" if f.get("from") else f"in>{f.get('to')}")
    return {"rel": rel, "outside": outside}


def grade(result: dict, truth: dict) -> dict:
    f = found(result)
    hits = [k for k in f["rel"] if k in truth["rel"]]
    kind_right = [k for k in hits if truth["rel"][k] == f["rel"][k]]
    parts = len(truth["rel"]) + len(truth["outside"])
    right = len(kind_right) + len({k for k in f["outside"] if k in truth["outside"]})
    return {"parts": parts, "right": right, "rightShare": right / parts if parts else None, "flows": len(result["flows"])}


def truth_flows_at(truth_model: dict, t: int) -> list[dict]:
    """The truth's flows with its schedule applied up to step t: last period's later changes still
    hold, then this period's so far override them."""
    sch = truth_model.get("schedule") or {"every": 0, "changes": []}
    flows = [dict(f) for f in truth_model["flows"]]
    by_id = {f.get("id"): f for f in flows}
    every = int(sch.get("every") or 0)
    within = ((t - 1) % every) + 1 if every else t
    changes = sch.get("changes") or []
    applied = sorted((c for c in changes if c["t"] > within), key=lambda c: c["t"]) if every and t > every else []
    applied += sorted((c for c in changes if c["t"] <= within), key=lambda c: c["t"])
    for c in applied:
        for fid, rate in (c.get("set") or {}).items():
            if fid in by_id:
                by_id[fid]["rate"] = rate
    return flows


def truth_by_time(truth_model: dict, times: list) -> tuple[list[dict], set]:
    """The truth over the run as flows whose rate follows the schedule (byTime), and the stocks it
    feeds with a constant outside inflow."""
    per_t = [truth_flows_at(truth_model, int(t)) for t in times]
    flows = []
    for i, f in enumerate(truth_model["flows"]):
        segs = []
        for t, fl in zip(times, per_t):
            rate = fl[i]["rate"]
            if segs and segs[-1]["rate"] == rate:
                segs[-1]["to"] = t
            else:
                segs.append({"from": t, "to": t, "rate": rate})
        flows.append({**f, "byTime": segs})
    fed = {f["to"] for f in truth_model["flows"] if not f.get("from") and f.get("to") and (f.get("rate") or {}).get("form") == "constant"}
    return flows, fed


def same_behaviour(result: dict, truth_model: dict, data: dict, horizon: int = 20, starts: int = 150) -> dict:
    t = data["t"]
    measured = list(data["levels"])
    all_levels = data.get("all_levels") or data["levels"]
    ids = list(all_levels)
    truth, fed = truth_by_time(truth_model, t)
    const = lambda r: r if (r or {}).get("form") == "constant" else {"form": "constant", "value": 0}  # noqa: E731
    exo = [{**f, "byTime": [{**g, "rate": const(g["rate"])} for g in f["byTime"]]} for f in truth if not f.get("from") and f.get("to") in fed]
    own = [f for f in result["flows"] if not (not f.get("from") and f.get("to") in fed and not f.get("driver") and (f.get("rate") or {}).get("form") == "constant")]
    A = levels_array(all_levels, ids)
    s0 = starts_for(A.shape[1], horizon, starts)
    times = np.asarray(t, dtype=float)[s0[None, :] + np.arange(horizon)[:, None]]
    found_end = Model(own + exo, ids).run(A[:, s0 - 1], times)
    truth_end = Model(truth, ids).run(A[:, s0 - 1], times)
    m = [ids.index(k) for k in measured]
    apart = float(((found_end[m] - truth_end[m]) ** 2).sum())
    moved = float(((truth_end[m] - A[m][:, s0 - 1]) ** 2).sum())
    ratio = (apart / max(1e-9, moved)) ** 0.5
    # how much there was to predict: the truth's movement over the horizon, in each stock's level
    # spread (rms over stocks and starts); near 0 the skill's denominator is small and the grade fragile
    sd = A[m].std(axis=1)
    sd[sd == 0] = 1
    spread = float(np.sqrt((((truth_end[m] - A[m][:, s0 - 1]) / sd[:, None]) ** 2).mean()))
    return {"horizon": horizon, "apart": ratio, "skill": 1 - ratio * ratio, "moved": spread}
