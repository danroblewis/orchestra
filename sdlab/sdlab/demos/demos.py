"""The four built demos (docs/DEMOS.md): residual watch, what-if, hidden stock, leverage. Each returns plain JSON for
the /demos page. They read a scenario (scenarios.py), its case's true model and a stored found model; they change
nothing on disk."""

from __future__ import annotations

import functools
import math

import numpy as np

from . import engine as E
from . import scenarios as S


@functools.lru_cache(maxsize=8)
def _base(name: str) -> dict:
    sc = S.get(name)
    case, truth = E.case_and_truth(sc["case"], sc["variant"])
    r = E.stored_model(sc["case"], sc["variant"], sc["strategy"])
    if r is None:
        raise LookupError(f"no stored passing result of {sc['strategy']} on {sc['case']} {sc['variant']}")
    # a hidden stock the scorer matched to the truth's takes the truth's name (as the ladder's diff draws it), so its
    # flows have true counterparts; the found model's own name is kept for the hidden-stock demo
    from ..ladder.diff import matched_names
    hm = (r.get("scores") or {}).get("hidden_match") or {}
    r = {**r, "found": matched_names(r.get("found") or [], r.get("scores")),
         "own_names": {t: m.get("found") for t, m in hm.items() if isinstance(m, dict)}}
    d = E.data_for(case, sc["variant"])
    measured = list(d["levels"])
    units = {s["id"]: s.get("unit") for s in truth["stocks"]}
    return {"sc": sc, "case": case, "truth": truth, "result": r, "data": d, "measured": measured, "units": units}


def _source(b: dict) -> dict:
    r = b["result"]
    return {"case": b["sc"]["case"], "variant": b["sc"]["variant"], "strategy": b["sc"]["strategy"], "result": r.get("id"),
            "status": r.get("status"), "commit": (r.get("code_commit") or "")[:9], "at": r.get("at")}


def _round(xs, nd=4):
    return [None if (x is None or not math.isfinite(x)) else round(float(x), nd) for x in xs]


def _thin(xs, every):
    return xs[::every]


def overview() -> dict:
    out = []
    for name, sc in S.SCENARIOS.items():
        try:
            b = _base(name)
            src = _source(b)
        except LookupError as e:
            src = {"error": str(e)}
        out.append({"name": name, "title": sc["title"], "about": sc["about"], "source": src,
                    "changes": {k: v["label"] for k, v in sc["changes"].items()}, "goals": {k: v["label"] for k, v in sc["goals"].items()}})
    return {"scenarios": out}


# ---- 1. residual watch ----

K_ALLOW, H_MIN, BURN = 0.5, 8.0, 20      # CUSUM allowance and least threshold (standard units); steps for hidden stocks to settle


def _levels(run: dict, measured: list[str], noise: bool, seed: int) -> dict:
    lv = {s: np.asarray(run["levels"][s], float) for s in measured}
    if noise:                                                  # counted (Poisson) measurements, as the counts variants
        rng = np.random.default_rng(seed)
        lv = {s: rng.poisson(np.maximum(0.0, v)).astype(float) for s, v in lv.items()}
    return lv


def _residuals(b: dict, run: dict, lv: dict) -> tuple[dict, dict]:
    o = E.one_step(b["result"]["found"], b["measured"], run["t"], {s: list(v) for s, v in lv.items()}, run["inputs"])
    pred = {s: np.asarray(o["predicted"][s], float) for s in b["measured"]}
    res = {s: np.nan_to_num(lv[s] - pred[s]) for s in b["measured"]}
    for v in res.values():
        v[:BURN] = 0.0
    return pred, res


def _cusum(z: np.ndarray) -> np.ndarray:
    hi = lo = 0.0
    out = np.zeros(len(z))
    for i in range(BURN, len(z)):
        hi, lo = max(0.0, hi + z[i] - K_ALLOW), min(0.0, lo + z[i] + K_ALLOW)
        out[i] = max(hi, -lo)
    return out


def residual(name: str, change: str, noise: bool = False, seed: int = 7) -> dict:
    """Yesterday's found model watching today's data, where `change` happens at its t. Calibrated on yesterday (the
    same model on a run without the change, with its own noise): each stock's residual scale (never below 1% of its
    typical step) and its alarm threshold (1.25 x the largest CUSUM yesterday reached, at least H_MIN), so a quiet day
    raises no alarm by construction. Today: one-step residuals, a two-sided CUSUM per stock, the alarms in order, and
    the flows at the first alarmed stock as suspects."""
    b = _base(name)
    ch = b["sc"]["changes"][change]
    meas = b["measured"]
    yest = E.run_truth(b["truth"])
    ylv = _levels(yest, meas, noise, seed + 1)
    _, yres = _residuals(b, yest, ylv)
    scale, limit = {}, {}
    for s in meas:
        floor = 1e-9 + 0.01 * float(np.nanstd(np.diff(ylv[s])) or 1.0)
        scale[s] = max(float(np.std(yres[s][BURN:])), floor)
        limit[s] = max(H_MIN, 1.25 * float(_cusum(yres[s] / scale[s]).max()))
    run = E.run_truth(b["truth"], change=ch)
    t = run["t"]
    lv = _levels(run, meas, noise, seed)
    pred, res = _residuals(b, run, lv)
    T = int(ch["t"])
    stocks, alarms = {}, []
    for s in meas:
        z = res[s] / scale[s]
        cus = _cusum(z)
        hit = np.flatnonzero(cus > limit[s])
        first = int(hit[0]) if len(hit) else None
        stocks[s] = {"observed": lv[s].tolist(), "predicted": pred[s].tolist(), "residual": res[s].tolist(), "cusum": cus.tolist(),
                     "threshold": limit[s], "scale": scale[s], "alarm": None if first is None else t[first], "unit": b["units"].get(s)}
        if first is not None:
            alarms.append((first, s))
    alarms.sort()
    suspects = []
    if alarms:
        s0 = alarms[0][1]
        suspects = [f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'}" for f in b["result"]["found"] if s0 in (f.get("from"), f.get("to"))]
    true_f = next(f for f in b["truth"]["flows"] if f["id"] == ch["flow"])
    every = max(1, len(t) // 600)
    thin = {s: {k: (_round(_thin(v, every)) if isinstance(v, list) else v) for k, v in d.items()} for s, d in stocks.items()}
    return {"source": _source(b), "change": {**ch, "ends": f"{true_f.get('from') or 'outside'} → {true_f.get('to') or 'outside'}",
                                              "before": true_f.get("rate")},
            "noise": noise, "t": _thin(t, every), "stocks": thin,
            "first_alarm": None if not alarms else {"t": t[alarms[0][0]], "stock": alarms[0][1], "after": t[alarms[0][0]] - T,
                                                     "order": [s for _, s in alarms[:6]]},
            "false_alarms": [s for i, s in alarms if t[i] < T],
            "suspects": suspects}


# ---- 3. what-if, and 8. leverage ----

def _start(b: dict) -> dict:
    return {s["id"]: float(s.get("initial") or 0) for s in b["truth"]["stocks"]}


def _free(b: dict, flows: list[dict], steps: int) -> dict:
    """The found model from the case's initial levels (before step 1), each value after its step: aligned with the
    truth's run. free_run's first value is its start, so a step 0 goes first and is dropped."""
    run_t = list(b["data"]["t"])[:steps]
    inputs = {k: [list(v)[0]] + list(v)[:steps] for k, v in b["data"]["inputs"].items()}
    out = E.free_run(flows, b["measured"], [run_t[0] - 1] + run_t, _start(b), inputs)
    return {s: v[1:] for s, v in out.items()}


def _true_edit(b: dict, num: dict, old: float, new: float) -> tuple[str | None, object]:
    """The same change applied to the true model: (true flow id, its new rate), or (None, why not)."""
    f = b["result"]["found"][num["flow"]]
    tf = E.true_flow_between(b["truth"], f.get("from"), f.get("to"))
    if tf is None:
        return None, "the true model has no single flow between the same stocks"
    if not old:
        return None, "the found number is 0"
    rate = tf.get("rate")
    if num["key"].split("/")[1] == "expr":
        txt = rate.get("expr") if isinstance(rate, dict) else None
        if not txt:
            return None, "the true flow is not an expression"
        # the true expression's number closest to the found one (within 5%: 192.5 for a found 192.525), scaled alike
        hits = [(abs(float(m.group(1)) - old) / abs(old), m) for m in E.NUM.finditer(txt) if float(m.group(1)) not in (0.0, 1.0)]
        hits = [h for h in hits if h[0] <= 0.05]
        if not hits:
            return None, f"the true expression has no number near {old:g}"
        m = min(hits, key=lambda h: h[0])[1]
        nv = float(m.group(1)) * new / old
        return tf["id"], {**rate, "expr": txt[: m.start()] + repr(nv) + txt[m.end():], "approximate": hits[0][0] > 1e-9 or len(hits) > 1}
    stock = num["label"][2:] if num["label"].startswith("× ") else None
    nr = E.scale_true_rate(rate, new / old, stock)
    return (tf["id"], nr) if nr is not None else (None, "the true rate's form cannot be scaled")


def _fmt(x: float) -> str:
    return repr(int(x)) if float(x).is_integer() else repr(float(x))


def model(name: str) -> dict:
    b = _base(name)
    return {"source": _source(b), "about": b["sc"]["about"], "numbers": E.numbers(b["result"]["found"]), "measured": b["measured"],
            "units": b["units"], "goals": b["sc"]["goals"], "found": b["result"]["found"], "truth_flows": b["truth"]["flows"]}


def whatif(name: str, key: str, value: float, steps: int = 1000) -> dict:
    b = _base(name)
    flows = b["result"]["found"]
    nums = {n["key"]: n for n in E.numbers(flows)}
    if key not in nums:
        raise KeyError(key)
    num = nums[key]
    base = _free(b, flows, steps)
    edited = _free(b, E.set_number(flows, key, value), steps)
    fid, tr = _true_edit(b, num, num["value"], float(value))
    t_base = E.run_truth(b["truth"], steps=steps)
    t_edit = E.run_truth(b["truth"], steps=steps, edits={fid: tr}) if fid else None
    every = max(1, steps // 500)
    t = list(b["data"]["t"])[:steps]
    out = {}
    for s in b["measured"]:
        out[s] = {"found": _round(_thin(base[s], every)), "found_edited": _round(_thin(edited[s], every)),
                  "truth": _round(_thin(t_base["levels"][s], every)), "truth_edited": _round(_thin(t_edit["levels"][s], every)) if t_edit else None,
                  "unit": b["units"].get(s)}
    return {"source": _source(b), "number": num, "value": float(value), "t": _thin(t, every), "stocks": out,
            "truth_change": {"flow": fid, "rate": tr} if fid else {"flow": None, "why": tr}}


def _goal(levels: dict, g: dict) -> float:
    v = np.asarray(levels[g["stock"]], float)
    return float(v[-1] if g["how"] == "final" else np.mean(v))


@functools.lru_cache(maxsize=32)
def leverage(name: str, goal: str, steps: int = 1000, nudge: float = 0.10, top: int = 5) -> dict:
    """Each number of the found model raised by `nudge` in turn; the change in the goal, ranked by size; the top ones
    applied to the true model too."""
    b = _base(name)
    g = b["sc"]["goals"][goal]
    flows = b["result"]["found"]
    base = _goal(_free(b, flows, steps), g)
    rows = []
    for num in E.numbers(flows):
        if not num["value"]:
            continue
        v = num["value"] * (1 + nudge)
        got = _goal(_free(b, E.set_number(flows, num["key"], v), steps), g)
        rows.append({**num, "new": v, "goal": got, "change": got - base, "relative": (got - base) / base if base else None})
    rows.sort(key=lambda r: -abs(r["change"]))
    t_base = _goal(E.run_truth(b["truth"], steps=steps)["levels"], g)
    for r in rows[:top]:
        fid, tr = _true_edit(b, r, r["value"], r["new"])
        if fid:
            got = _goal(E.run_truth(b["truth"], steps=steps, edits={fid: tr})["levels"], g)
            r["truth"] = {"flow": fid, "goal": got, "change": got - t_base, "relative": (got - t_base) / t_base if t_base else None,
                          "approximate": bool(isinstance(tr, dict) and tr.get("approximate"))}
        else:
            r["truth"] = {"flow": None, "why": tr}
    return {"source": _source(b), "goal": {**g, "key": goal, "base": base, "truth_base": t_base}, "nudge": nudge, "steps": steps,
            "rows": rows, "top": top}


# ---- 7. hidden stock ----

def hidden(name: str) -> dict:
    """The found model's own hidden stocks: each one's level as the model carries it (stepped one step ahead on the
    measured data) beside the truth's hidden stock it was matched to, its flows, the flows that read it, and the
    scenario's reading of what it probably is."""
    b = _base(name)
    flows, meas, d = b["result"]["found"], b["measured"], b["data"]
    o = E.one_step(flows, meas, d["t"], d["levels"], d["inputs"])
    match = (b["result"].get("scores") or {}).get("hidden_match") or {}
    by_found = {tn: {"truth": tn, **m} for tn, m in match.items() if isinstance(m, dict)}       # renamed: keyed by the truth's name
    every = max(1, len(d["t"]) // 600)
    out = []
    for h, lv in o["hidden"].items():
        own = [f for f in flows if h in (f.get("from"), f.get("to"))]
        readers = [f for f in flows if h not in (f.get("from"), f.get("to")) and h in str(f.get("rate")) + str(f.get("effects") or "")]
        m = by_found.get(h)
        truth_lv = d["all_levels"].get(m["truth"]) if m else None
        units = {b["units"].get(f.get("to") or f.get("from")) for f in readers}
        out.append({"id": h, "own_name": b["result"]["own_names"].get(h, h), "level": _round(_thin(lv, every)), "truth": m and {"id": m["truth"], "level": _round(_thin(list(truth_lv), every)),
                                                                                "alpha": m.get("alpha"), "beta": m.get("beta"), "r2": m.get("r2")},
                    "flows": [_flow_text(f) for f in own], "read_by": [_flow_text(f) for f in readers],
                    "unit_guess": sorted(u for u in units if u), "growth_per_step": round(float(np.median(np.diff(lv[: len(lv) // 4]))), 4)})
    return {"source": _source(b), "t": _thin(list(d["t"]), every), "hidden": out, "hint": b["sc"].get("hidden_hint")}


def _flow_text(f: dict) -> str:
    r = f.get("rate") or {}
    form = r.get("form")
    if form == "constant":
        rate = f"{r.get('value'):.4g}"
    elif form == "proportional":
        rate = f"{r.get('k'):.4g} × {r.get('stock')}"
    elif form == "linear":
        rate = " + ".join([f"{r['c']:.4g}"] * bool(r.get("c")) + [f"{x['k']:.4g} × {x['stock']}" for x in r.get("terms") or []])
    elif form == "expr":
        rate = r.get("expr")
    else:
        rate = str(r)
    eff = " × effect of " + ", ".join(e.get("stock") for e in f.get("effects") or []) if f.get("effects") else ""
    return f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'}: {rate}{eff}"
