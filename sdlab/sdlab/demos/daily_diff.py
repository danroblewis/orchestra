"""Demo 2, daily model diff (docs/demos/daily-diff.md; ideas 1 and 7 of OPERATIONALIZATION.md).

A service on two "days". Day 1 is a stored found model (a strategy's passing result on a kubernetes ladder case).
Day 2 has other traffic and, on top, a real change applied to an in-memory copy of the true model (or no change: the
quiet day, the baseline). Day 2's model was discovered once by the same strategy (precompute(), cached in
~/.cache/sdlab/demos/daily-diff/<scenario>-<key>.json) and scored against day 2's own true model. The demo diffs the
two FOUND models against each other, truth-free, and only then holds the diff beside the true change: each edit is
right (the true change found), false (an edit where nothing really changed), or the true change is missed.

Scenarios: two-services (313, lna: day 2 discovered in under a second) and memory-oom (310, engine_forms: about a
minute a run, and it fails every day 2 tried, so its diffs show what a failed day does to a diff).

The found-vs-found diff works per edge (a pair of ends, from -> to, outside as None; flows a model splits between the
same ends are summed). An edge's amount is computed by the scorer's simulator for found models (ladder/sim.found_model)
on the states of both days, so a flow written differently but moving the same amounts is "redrawn", not a change. An
edge counts as changed when its mean difference, relative to its size, is beyond its tolerance: 3x what the same
comparison gives on the quiet day (same service, other traffic, nothing changed), and never below 2%. An edge added
or removed on the quiet day too is not counted again on a change day.

Regenerate the cache (single-threaded; two-services takes seconds, memory-oom about 7 CPU-minutes):
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \\
        nice -n 19 uv run python -m sdlab.demos.daily_diff precompute [two-services|memory-oom] [key ...] [--force]

Nothing here changes a case, a simulation, a strategy or the result store."""

from __future__ import annotations

import copy
import functools
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException

from . import engine as E

router = APIRouter()

NAME = "daily-diff"
TOL_FLOOR, TOL_TIMES = 0.02, 3.0          # an edge changed: relative difference > max(2%, 3 x the quiet day's)
TINY = 1e-6                               # an edge whose mean amount is below this on both days moves nothing
TIMEOUT = 600                             # seconds a precompute run may take
CACHE = Path(os.environ.get("SDLAB_DEMO_CACHE") or Path.home() / ".cache" / "sdlab" / "demos") / NAME
COMMAND = ("OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 "
           "nice -n 19 uv run python -m sdlab.demos.daily_diff precompute")

# day 2's traffic: a different, busier day (day 1's is 400 + 220 sin(period 288, phase 96)); the same on every day 2
DAY2_TRAFFIC = {"terms": [{"fn": "constant", "value": 430}, {"fn": "sin", "amplitude": 250, "period": 288, "phase": 60},
                          {"fn": "pulse_train", "height": -120, "first": 1440, "width": 576, "every": 2016}]}
DAY2_ABOUT = "day 2's traffic is busier and peaks earlier: 430 + 250 sin(…) requests a step, against day 1's 400 + 220 sin(…)"
QUIET = {"label": "nothing changed, only the traffic (the baseline for the tolerance)", "edits": {}, "add": []}
P = lambda s, k: {"form": "proportional", "stock": s, "k": k}          # noqa: E731

SCENARIOS = {
    "two-services": {
        "title": "Two services, frontend calling catalog (ladder case 313), found by lna",
        "case": "313-k8s-two-services", "variant": "none-short", "strategy": "lna",
        "changes": {
            "quiet": QUIET,
            "more-calls": {"label": "a frontend release calls catalog 50% more per request",
                           "edits": {"catalog_calls": P("frontend_inflight", 0.45)}, "add": []},
            "slow-catalog": {"label": "a slow catalog database: catalog finishes 40% fewer requests a step",
                             "edits": {"catalog_completed": P("catalog_inflight", 0.3)}, "add": []},
            "client-retry": {"label": "a new client retry: 5% of frontend's requests in flight go back to its queue (a new flow)",
                             "edits": {}, "add": [{"id": "client_retry", "name": "client_retry", "from": "frontend_inflight",
                                                   "to": "frontend_queue", "rate": P("frontend_inflight", 0.05)}]},
            "frontend-cache": {"label": "a new frontend cache answers 10% of the waiting requests a step (a new flow)",
                               "edits": {}, "add": [{"id": "cached", "name": "cached", "from": "frontend_queue",
                                                     "to": "frontend_responses_total", "rate": P("frontend_queue", 0.1)}]},
        },
    },
    "memory-oom": {
        "title": "An API service with a memory leak and OOM kills (ladder case 310), found by engine_forms",
        "case": "310-k8s-memory-oom", "variant": "none-short", "strategy": "engine_forms",
        "changes": {
            "quiet": QUIET,
            "retries": {"label": "a client release retries more and gives up less",
                        "edits": {"retried": P("retries", 0.8), "gave_up": P("retries", 0.2)}, "add": []},
            "slow-starts": {"label": "a new base image makes pods start more slowly",
                            "edits": {"started": P("pending", 0.2)}, "add": []},
            "cache": {"label": "a new response cache answers 10% of the waiting requests a step (a new flow)", "edits": {},
                      "add": [{"id": "cached", "name": "cached", "from": "queue", "to": "responses_total", "rate": P("queue", 0.1)}]},
        },
    },
}


def _sc(scen: str) -> dict:
    if scen not in SCENARIOS:
        raise KeyError(scen)
    return SCENARIOS[scen]


# ---- the two days' true models (in-memory copies; the case is never changed) ----

def _case_truth(scen: str) -> tuple[dict, dict]:
    sc = _sc(scen)
    return E.case_and_truth(sc["case"], sc["variant"])


def day2_truth(scen: str, change: str) -> dict:
    """The true model of day 2: day 2's traffic, and the change's edits (flow id -> new rate) and added flows."""
    _, truth = _case_truth(scen)
    ch = _sc(scen)["changes"][change]
    m = copy.deepcopy(truth)
    m["inputs"] = {**m.get("inputs", {}), "traffic": copy.deepcopy(DAY2_TRAFFIC)}
    for f in m["flows"]:
        if f["id"] in ch["edits"]:
            f["rate"] = copy.deepcopy(ch["edits"][f["id"]])
    m["flows"] += copy.deepcopy(ch["add"])
    return m


def true_change(scen: str, change: str) -> list[dict]:
    """The true change as edges: {ends, from, to, kind (changed / added), flow, before, after}."""
    _, truth = _case_truth(scen)
    ch = _sc(scen)["changes"][change]
    by = {f["id"]: f for f in truth["flows"]}
    out = [{"from": by[i].get("from"), "to": by[i].get("to"), "kind": "changed", "flow": i,
            "before": _rate_text(by[i]), "after": _rate_text({**by[i], "rate": r})} for i, r in ch["edits"].items()]
    out += [{"from": f.get("from"), "to": f.get("to"), "kind": "added", "flow": f["id"], "before": None, "after": _rate_text(f)}
            for f in ch["add"]]
    for x in out:
        x["ends"] = _ends(x["from"], x["to"])
    return out


# ---- precompute: day 2's found models (and day 1 re-run at this commit), cached ----

def _discover_and_score(sc: dict, case: dict, model: dict, d: dict, fresh: dict) -> dict:
    import signal

    from ..discovery.api import jsonable
    from ..ladder import provenance, score
    from ..ladder.runner import discover

    def fire(*_):
        raise TimeoutError(f"took longer than {TIMEOUT} s")
    signal.signal(signal.SIGALRM, fire)
    signal.alarm(TIMEOUT)
    began = time.perf_counter()
    try:
        r = discover(sc["strategy"], model, d)
    finally:
        signal.alarm(0)
    seconds = round(time.perf_counter() - began, 2)
    flows = jsonable(r.get("flows") or [])
    noise = E.casemod.variant(case, sc["variant"])["noise"]
    case2 = {**case, "model": {**case["model"], "flows": model["flows"], "inputs": model.get("inputs")}}
    try:
        s = score.score(case2, noise, model, flows, d, fresh, r.get("inferred_levels"))
        status, hm = s.get("status"), s.get("hidden_match")
    except Exception as e:                                         # noqa: BLE001  (reported, not hidden)
        status, hm = f"not scored: {e}", None
    prov = provenance.loaded(sc["strategy"])
    return {"flows": flows, "seconds": seconds, "status": status, "hidden_match": jsonable(hm),
            "commit": prov.get("code_commit"), "dirty": prov.get("code_dirty"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def precompute(scen: str, force: bool = False, only: list[str] | None = None) -> None:
    """Day 1 re-run at this commit (day1-again) and every change's day 2, each discovered once and scored against
    its own true model; written to CACHE/<scenario>-<key>.json."""
    from ..ladder import data as ladder_data
    sc = _sc(scen)
    case, truth = _case_truth(scen)
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [("day1-again", truth)] + [(k, day2_truth(scen, k)) for k in sc["changes"]]
    for key, model in todo:
        if only and key not in only:
            continue
        path = CACHE / f"{scen}-{key}.json"
        if path.exists() and not force:
            print(f"{scen} {key}: cached ({path})")
            continue
        if key == "day1-again":                                    # day 1's own data, as the ladder ran it
            d, fresh = E.data_for(case, sc["variant"]), ladder_data.load(case, sc["variant"], fresh=True)
        else:
            seed = int(model["seed"])
            d, fresh = ladder_data.simulate(model, seed), ladder_data.simulate(model, seed + 1)
        d = {**d, **E.casemod.announced(case)}
        print(f"{scen} {key}: discovering with {sc['strategy']}…", flush=True)
        try:
            out = _discover_and_score(sc, case, model, d, fresh)
        except Exception as e:                                     # noqa: BLE001
            out = {"flows": None, "error": str(e)[:500], "status": "error"}
        out.update(key=key, case=sc["case"], variant=sc["variant"], strategy=sc["strategy"],
                   change=sc["changes"].get(key, {}).get("label"))
        path.write_text(json.dumps(out, indent=1))
        print(f"{scen} {key}: {out.get('status')} in {out.get('seconds')} s, {len(out.get('flows') or [])} flows", flush=True)


def _cached(scen: str, key: str) -> dict | None:
    p = CACHE / f"{scen}-{key}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


# ---- the found-vs-found diff ----

def _ends(a, b) -> str:
    return f"{a or 'outside'} → {b or 'outside'}"


def _rename(flows: list[dict], names: dict[str, str]) -> list[dict]:
    if not names:
        return copy.deepcopy(flows)
    text = json.dumps(flows)
    for old, new in names.items():
        if old != new:
            text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, text)
    return json.loads(text)


def _own(flows: list[dict], measured: list[str]) -> list[str]:
    return [s for s in E.found_ids(flows, measured) if s not in measured]


def _signature(flows: list[dict], h: str, measured: list[str]) -> set:
    """What a hidden stock touches: the measured stocks its flows reach and the flows that read it (truth-free)."""
    sig = set()
    for f in flows:
        ends = (f.get("from"), f.get("to"))
        text = json.dumps(f.get("rate")) + json.dumps(f.get("effects") or [])
        if h in ends:
            sig |= {("end", s) for s in ends if s in measured}
            sig |= {("reads", s) for s in measured if re.search(rf"(?<![A-Za-z0-9_]){s}(?![A-Za-z0-9_])", text)}
        elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(h)}(?![A-Za-z0-9_])", text):
            sig.add(("read_by", _ends(*ends)))
    return sig


def match_hidden(a: list[dict], b: list[dict], measured: list[str]) -> dict[str, str]:
    """Day 2's hidden stocks named as day 1's they match (most shared signature first; truth-free): {b's: a's}."""
    ha, hb = _own(a, measured), _own(b, measured)
    sa = {h: _signature(a, h, measured) for h in ha}
    sb = {h: _signature(b, h, measured) for h in hb}
    pairs = sorted(((len(sa[x] & sb[y]) / max(1, len(sa[x] | sb[y])), x, y) for x in ha for y in hb), reverse=True)
    out, used = {}, set()
    for score, x, y in pairs:
        if score > 0 and x not in used and y not in out:
            out[y] = x
            used.add(x)
    return out


def _states(flows: list[dict], measured: list[str], d: dict) -> dict:
    """A day's states as a model sees them: the measured levels, and the model's own hidden stocks as it carries them
    (one step ahead on that day's measured levels)."""
    o = E.one_step(flows, measured, d["t"], d["levels"], d.get("inputs") or {})
    return {"t": list(d["t"]), "levels": {**{s: list(d["levels"][s]) for s in measured}, **o["hidden"]},
            "inputs": d.get("inputs") or {}}


def edge_amounts(flows: list[dict], ids: list[str], st: dict) -> np.ndarray:
    """The amount the flows (all between the same two ends) move each step from the day's states: one step of a found
    model made of just them, read off the receiving stock (the giving one for an outflow). Steps the states lack (a
    stock the day's model does not carry) read 0."""
    t = st["t"]
    L = np.array([[float(x) for x in st["levels"].get(s, [0.0] * len(t))] for s in ids])
    inputs = {"t": list(t), "values": st["inputs"]} if st["inputs"] else None
    from ..ladder import sim as ladder_sim
    mdl = ladder_sim.found_model(flows, ids, inputs=inputs)
    nxt = mdl.step(L, np.array(t, float))
    f = flows[0]
    if f.get("to"):
        k = ids.index(f["to"])
        return nxt[k] - L[k]
    k = ids.index(f["from"])
    return L[k] - nxt[k]


def _skeleton(flows: list[dict]) -> str:
    """How an edge is written, without its numbers (a redrawing changes this; a number change does not)."""
    def one(f):
        r = json.dumps({"rate": f.get("rate"), "effects": [{k: v for k, v in e.items() if k != "points"} for e in f.get("effects") or []]},
                       sort_keys=True)
        return re.sub(r"-?\d+\.?\d*(e[-+]?\d+)?", "#", r)
    return " + ".join(sorted(one(f) for f in flows))


def _rate_text(f: dict) -> str:
    from .demos import _flow_text
    if isinstance(f.get("rate"), dict) and f["rate"].get("form") in ("constant", "proportional", "linear", "expr"):
        return _flow_text(f).split(": ", 1)[1]
    return json.dumps(f.get("rate"))


def _numbers(flows: list[dict]) -> list[float]:
    return [n["value"] for n in E.numbers(flows)]


def diff_models(a: list[dict], b: list[dict], measured: list[str], days: list[dict], tol: dict | None = None,
                baseline: dict | None = None) -> dict:
    """Day 1's found flows a against day 2's b, edge by edge (see the module docstring). days: each day's data
    ({t, levels, inputs}); a's states come from a on each day, b's from b. tol: {ends: relative tolerance} (from the
    quiet day; missing: TOL_FLOOR); baseline: the quiet day's diff, whose added / removed edges are not counted again.
    {edges: [...], hidden: {b's: a's}, stat}."""
    names = match_hidden(a, b, measured)
    b = _rename(b, names)
    ids = list(measured) + [s for s in _own(a, measured) + _own(b, measured) if s not in measured]
    ids = list(dict.fromkeys(ids))
    groups: dict[tuple, dict[str, list]] = {}
    for side, flows in (("a", a), ("b", b)):
        for f in flows:
            groups.setdefault((f.get("from"), f.get("to")), {"a": [], "b": []})[side].append(f)
    # every day's states, as each model carries its own hidden stocks; an edge is evaluated on both models' states
    states = [_states(m, measured, d) for d in days for m in (a, b)]
    base_kind = {e["ends"]: e["kind"] for e in (baseline or {}).get("edges", [])}
    edges = []
    for (fr, to), g in groups.items():
        ends = _ends(fr, to)
        amt = {s: (np.concatenate([edge_amounts(g[s], ids, st) for st in states]) if g[s] else None) for s in ("a", "b")}
        size = {s: (float(np.mean(np.abs(v))) if v is not None else 0.0) for s, v in amt.items()}
        e = {"ends": ends, "from": fr, "to": to, "size_a": size["a"], "size_b": size["b"],
             "a": [_rate_text(f) for f in g["a"]], "b": [_rate_text(f) for f in g["b"]], "tol": (tol or {}).get(ends, TOL_FLOOR)}
        if g["a"] and g["b"]:
            rel = float(np.mean(np.abs(amt["a"] - amt["b"]))) / max(size["a"], size["b"], 1e-12)
            if max(size["a"], size["b"]) < TINY:
                rel = 0.0
            e["rel"] = rel
            e["mean_change"] = (size["b"] - size["a"]) / size["a"] if size["a"] > 1e-12 else None
            redrawn = _skeleton(g["a"]) != _skeleton(g["b"])
            if rel > e["tol"]:
                e["kind"] = "changed"
            else:
                e["kind"] = "redrawn" if redrawn else "same"
            if not redrawn and len(g["a"]) == len(g["b"]) == 1:
                na, nb = _numbers(g["a"]), _numbers(g["b"])
                if len(na) == len(nb):
                    e["numbers"] = [{"label": n["label"], "a": x, "b": y} for n, x, y in zip(E.numbers(g["a"]), na, nb)]
        else:
            e["kind"] = "added" if g["b"] else "removed"
            e["rel"] = None
            if max(size["a"], size["b"]) < TINY:
                e["kind"] = "same"                                   # a flow that never moves anything on either day
                e["note"] = "moves nothing on either day"
        if e["kind"] in ("added", "removed") and base_kind.get(ends) == e["kind"]:
            e["note"] = f"also {e['kind']} on the quiet day: how this strategy redraws the model, not a change"
            e["kind"] = "redrawn"
        edges.append(e)
    order = {"changed": 0, "added": 1, "removed": 2, "redrawn": 3, "same": 4}
    edges.sort(key=lambda e: (order[e["kind"]], e["ends"]))
    stat = {k: sum(e["kind"] == k for e in edges) for k in order}
    return {"edges": edges, "hidden": names, "stat": stat}


def judge(edges: list[dict], truth_edges: list[dict], hidden_truth: dict[str, str] | None = None) -> dict:
    """The found edits beside the true change: right (an edit at the ends of a true change), false (an edit where
    nothing really changed), missed (a true change with no edit at its ends). hidden_truth: {found hidden name: the
    truth's} (day 1's scorer match), so an edit at a found hidden stock is compared with the truth's."""
    ht = hidden_truth or {}
    key = lambda fr, to: (ht.get(fr, fr), ht.get(to, to))          # noqa: E731
    true_at = {(x["from"], x["to"]): x for x in truth_edges}
    edits = [e for e in edges if e["kind"] in ("changed", "added", "removed")]
    right, false = [], []
    for e in edits:
        t = true_at.get(key(e["from"], e["to"]))
        (right if t else false).append({"ends": e["ends"], "kind": e["kind"], "true": t})
    hit = {key(e["from"], e["to"]) for e in edits}
    missed = [x for k, x in true_at.items() if k not in hit]
    for e in edges:
        k = key(e["from"], e["to"])
        e["verdict"] = ("right" if k in true_at else "false") if e in edits else ("missed" if k in true_at else None)
        if e["verdict"] == "false":                                # an edit beside a missed change: the change, drawn elsewhere?
            near = [x["ends"] for x in missed if {x["from"], x["to"]} & ({k[0], k[1]} - {None})]
            if near:
                e["near"] = near
    return {"right": right, "false": false, "missed": missed}


# ---- the demo's answers ----

@functools.lru_cache(maxsize=4)
def _base(scen: str) -> dict:
    sc = _sc(scen)
    case, truth = _case_truth(scen)
    r = E.stored_model(sc["case"], sc["variant"], sc["strategy"])
    if r is None:
        raise LookupError(f"no stored passing result of {sc['strategy']} on {sc['case']} {sc['variant']}")
    d = E.data_for(case, sc["variant"])
    hm = (r.get("scores") or {}).get("hidden_match") or {}
    hidden_truth = {m["found"]: t for t, m in hm.items() if isinstance(m, dict) and m.get("found")}
    return {"sc": sc, "case": case, "truth": truth, "result": r, "data": d, "measured": list(d["levels"]), "hidden_truth": hidden_truth}


@functools.lru_cache(maxsize=16)
def _day2_data(scen: str, change: str) -> dict:
    from ..ladder import data as ladder_data
    m = day2_truth(scen, change)
    return ladder_data.simulate(m, int(m["seed"]))


def _source(b: dict) -> dict:
    r, sc = b["result"], b["sc"]
    return {"case": sc["case"], "variant": sc["variant"], "strategy": sc["strategy"], "result": r.get("id"), "status": r.get("status"),
            "commit": (r.get("code_commit") or "")[:9], "at": r.get("at")}


def _day2(scen: str, key: str) -> dict:
    got = _cached(scen, key)
    if got is None:
        raise LookupError(f"day 2 ({scen} {key}) has not been discovered yet; run: {COMMAND} {scen}")
    if not got.get("flows"):
        raise LookupError(f"day 2 ({scen} {key}): discovery gave no model ({got.get('status')}: {got.get('error', '')})")
    return got


def _worst(edges: list[dict]) -> float:
    return max([e["rel"] or 0 for e in edges if e.get("rel") is not None], default=0.0)


@functools.lru_cache(maxsize=16)
def _diff(scen: str, change: str, stamp: float) -> dict:
    b = _base(scen)
    sc, a, meas = b["sc"], b["result"]["found"], b["measured"]
    quiet = _day2(scen, "quiet")
    q = diff_models(a, quiet["flows"], meas, [b["data"], _day2_data(scen, "quiet")])
    tol = {e["ends"]: max(TOL_FLOOR, TOL_TIMES * (e["rel"] or 0.0)) for e in q["edges"] if e.get("rel") is not None}
    if change == "quiet":
        out, day2 = q, quiet
        for e in out["edges"]:
            e["tol"] = tol.get(e["ends"], TOL_FLOOR)
    else:
        day2 = _day2(scen, change)
        out = diff_models(a, day2["flows"], meas, [b["data"], _day2_data(scen, change)], tol=tol, baseline=q)
    truth = true_change(scen, change)
    verdict = judge(out["edges"], truth, b["hidden_truth"])
    again = _cached(scen, "day1-again")
    return {"scenario": scen, "title": sc["title"], "source": _source(b),
            "change": {"key": change, "label": sc["changes"][change]["label"]}, "day2_about": DAY2_ABOUT,
            "day2": {k: day2.get(k) for k in ("status", "seconds", "commit", "dirty", "at")},
            "quiet_status": quiet.get("status"),
            "day1_again": again and {"status": again.get("status"), "commit": (again.get("commit") or "")[:9],
                                     "same_as_stored": _same(a, again.get("flows"), meas, b["data"])},
            "tolerance": {"floor": TOL_FLOOR, "times": TOL_TIMES, "quiet_worst": _worst(q["edges"]),
                          "quiet_edits": sum(q["stat"][k] for k in ("changed", "added", "removed"))},
            "truth": truth, "verdict": verdict, "hidden": out["hidden"], "hidden_truth": b["hidden_truth"], "stat": out["stat"],
            "edges": _jsonable(out["edges"]), "measured": meas,
            "hidden_stocks": sorted({s for e in out["edges"] for s in (e["from"], e["to"]) if s and s not in meas})}


def _same(a: list[dict], again: list[dict] | None, measured: list[str], d: dict) -> dict | None:
    """Day 1 re-run at this commit beside the stored day 1: the largest relative edge difference (a check that the
    stored model is what this code finds on day 1's data)."""
    if not again:
        return None
    r = diff_models(a, again, measured, [d])
    return {"worst": _worst(r["edges"]), "stat": r["stat"]}


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_jsonable(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    return x


def _stamp() -> float:
    return max([p.stat().st_mtime for p in CACHE.glob("*.json")], default=0.0)


def diff(scen: str, change: str) -> dict:
    if change not in _sc(scen)["changes"]:
        raise KeyError(change)
    return _diff(scen, change, _stamp())


def changes() -> dict:
    out = []
    for scen, sc in SCENARIOS.items():
        try:
            src = _source(_base(scen))
        except LookupError as e:
            src = {"error": str(e)}
        rows = []
        for k, ch in sc["changes"].items():
            got = _cached(scen, k) or {}
            rows.append({"key": k, "label": ch["label"], "ready": bool(got.get("flows")) and "error" not in src, "status": got.get("status")})
        out.append({"key": scen, "title": sc["title"], "source": src, "changes": rows})
    return {"scenarios": out, "command": COMMAND, "day2_about": DAY2_ABOUT}


@router.get("/daily-diff/changes")
def api_changes() -> dict:
    return changes()


@router.get("/daily-diff/diff")
def api_diff(change: str, scenario: str = "two-services") -> dict:
    try:
        return diff(scenario, change)
    except KeyError as e:
        raise HTTPException(404, f"unknown: {e}") from None
    except LookupError as e:
        raise HTTPException(409, str(e)) from None


if __name__ == "__main__":
    if sys.argv[1:2] == ["precompute"]:
        rest = sys.argv[2:]
        names = [x for x in rest if not x.startswith("--")]
        scens = [x for x in names if x in SCENARIOS] or ["two-services"]
        for scen in scens:
            precompute(scen, force="--force" in rest, only=[x for x in names if x not in SCENARIOS] or None)
    else:
        print(__doc__)
