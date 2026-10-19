"""Scoring a found model on a real case: held-out prediction, agreement with the published structure,
measured flows (BLS), and on the twin, the ladder's own equation scoring.

**Held-out prediction** (both variants). Discovery saw the first `train` samples. From the last of them,
the found model runs free to the end of the series (announced injections made; its own unmeasured
stocks start from its estimate of them, `inferred_levels` or the observer), and so do the published
model refitted on the same samples (its hidden stocks from its own free run) and persistence (the last
seen level held). Error = the sum over held-out samples and measured stocks of (prediction - measured)^2,
each stock scaled by its spread over the training samples. skill = 1 - error / persistence's error (1:
exact; 0: no better than persistence; negative: worse); the published model gets the same number, and
`beats_published` says whether the found model's error is at most the published model's.

**Agreement** (both variants). The found and the published models cut into parts as the ladder's
scorer cuts them (score.py: a move, an outside inflow, a link, an outside outflow, an effect, a hidden
stock; an end or a reader that no one measures is "hidden"). recall = published parts the found model
has; precision = found parts (larger than 5% of the published parts' median size) the published model
has. It is reported as agreement, never as a pass: the published structure is a hypothesis that fitted
the data. The real variant's status is "agrees" (recall and precision 1) or "differs".

**Measured flows** (where the data have them: BLS's six gross flows). The found flows between two
stocks, evaluated on the measured levels of the training months, against the measured flow: found (a
flow between those stocks exists), the relative error of the mean amount per month, and whether it is
within 25% ("matched"). The net flow between two stocks (A->B minus B->A), which levels alone can
show, is compared too.

**The twin** is scored as a ladder case (sdlab/ladder/score.py, the equations, against the published
model the twin was made from), so its status is pass / equivalent / fail as on the tests; it is never
counted in the Tests pass rate (the real cases are a separate set).
"""

from __future__ import annotations

import math

import numpy as np

from ...discovery.observer import observe, unmeasured
from ...discovery.simulate import Model
from ...runner import multiplier
from ...skill import truth_by_time
from ..parts import ONE, form_over, kind, label
from . import fit

SPURIOUS = 0.05
MATCH = 0.25


def score(case: dict, variant: str, model: dict, flows: list[dict], d: dict, full: dict, inferred: dict | None = None) -> dict:
    out = {"kind": variant, "train": len(d["t"]), "points": len(full["t"]),
           "heldout": heldout(model, flows, d, full, inferred), "agreement": agreement(model, flows, d)}
    ag = out["agreement"]
    if variant == "twin":
        from .. import score as ladder_score
        try:
            eq = ladder_score.equations(case, "counts", model, flows, d)
        except Exception as e:                                         # noqa: BLE001  (a 10-point run can defeat the oracle)
            eq = {"status": "fail", "recall": ag["recall"], "precision": ag["precision"], "parts": [], "spurious": [], "notes": [f"equation scoring failed: {type(e).__name__}: {e}"]}
        out.update(eq)
        return out
    if d.get("flows"):
        out["flows"] = measured_flows(flows, d)
    out.update(status="agrees" if ag["agrees"] else "differs", recall=ag["recall"], precision=ag["precision"],
               right=len(ag["matched"]), of=len(ag["published"]), parts=ag["rows"], spurious=ag["extra_rows"])
    return out


# ---- held-out prediction ----

def heldout(model: dict, flows: list[dict], d: dict, full: dict, inferred: dict | None = None) -> dict:
    ids = list(full["levels"])
    n0, n = len(d["t"]), len(full["t"])
    s = n0 - 1
    if n - n0 < 1:
        return {"points": 0}
    Y = np.array([np.asarray(full["levels"][k], dtype=float) for k in ids])
    sd = np.array([max(float(np.std(Y[i, :n0])), 1e-9 * max(1.0, float(np.max(np.abs(Y[i]))))) for i in range(len(ids))])
    times = np.asarray(full["t"], dtype=float)
    inj = full.get("injections") or []

    def err(P):
        e = ((P - Y[:, n0:]) / sd[:, None]) ** 2
        e[~np.isfinite(e)] = 1e6
        return e

    persist = np.repeat(Y[:, s:s + 1], n - n0, axis=1)
    found = _free_run(flows, ids, d, Y[:, s], times, s, n, inj, inferred)
    pub = _published_run(model, ids, Y[:, s], n0, n)
    ep, ef, eb = err(persist), err(found), err(pub)

    def skill(e):
        den = float(ep.sum())
        return None if den <= 0 else _finite(1 - float(e.sum()) / den)

    per = {k: {"skill": None if ep[i].sum() <= 0 else _finite(1 - ef[i].sum() / ep[i].sum()),
               "published": None if ep[i].sum() <= 0 else _finite(1 - eb[i].sum() / ep[i].sum())} for i, k in enumerate(ids)}
    return {"points": n - n0, "from": int(full["t"][s]), "skill": skill(ef), "published": skill(eb),
            "beats_published": bool(ef.sum() <= eb.sum()), "rmse": _finite(math.sqrt(float(ef.mean()))),
            "rmse_published": _finite(math.sqrt(float(eb.mean()))), "rmse_persistence": _finite(math.sqrt(float(ep.mean()))),
            "per_stock": per, "forecast": {k: [_finite(x) for x in found[i]] for i, k in enumerate(ids)},
            "forecast_published": {k: [_finite(x) for x in pub[i]] for i, k in enumerate(ids)}}


def _free_run(flows, ids, d, start, times, s, n, inj, inferred) -> np.ndarray:
    hidden = list(dict.fromkeys(unmeasured(flows, ids) + list(inferred or {})))
    est = {}
    if hidden:
        est = {h: v[-1] for h, v in (inferred or {}).items() if v}
        if any(h not in est for h in hidden):
            try:
                obs = observe(flows, ids, d["t"], d["levels"], [h for h in hidden if h not in est], {})
                est.update({h: v[-1] for h, v in obs.items() if len(v)})
            except Exception:                                          # noqa: BLE001  (an observer that cannot run: start at 0)
                pass
    allids = ids + hidden
    L = np.array([[float(x)] for x in start] + [[float(est.get(h, 0.0) or 0.0)] for h in hidden])
    m = Model(flows, allids)
    out = []
    try:
        for k in range(s + 1, n):
            L = m.run(L, np.array([[times[k]]]), inj)
            out.append(L[: len(ids), 0].copy())
    except Exception:                                                  # noqa: BLE001  (a model that cannot run predicts nothing)
        return np.full((len(ids), n - s - 1), np.nan)
    return np.array(out).T


def _published_run(model, ids, start, n0, n) -> np.ndarray:
    free = fit.run(model, n0)
    st = {k: float(v[-1]) for k, v in free.items()}
    st.update({k: float(x) for k, x in zip(ids, start)})
    run = fit.run(model, n, start=st, from_t=n0 - 1)
    return np.array([run[k][1:] for k in ids])


def _finite(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# ---- agreement with the published structure ----

HID = "hidden"


def keys(flows: list[dict], measured: set, window: tuple[int, int]) -> dict[tuple, float]:
    """{part key: number} as score.py's parts, with unmeasured ends and readers kept as "hidden"."""
    out: dict[tuple, float] = {}
    end = lambda x: None if not x else (x if x in measured else HID)  # noqa: E731
    for f in flows:
        a, b = end(f.get("from")), end(f.get("to"))
        if f.get("via"):
            out[("hidden", a, b)] = 1.0
            continue
        lf = form_over(f, *window)
        if lf is None:
            out[("flow", a, b, "?")] = 1.0
            continue
        c, ks = lf
        if c:
            out[("flow", a, b, ONE)] = out.get(("flow", a, b, ONE), 0.0) + c
        for j, k in ks.items():
            r = j if j in measured else HID
            out[("flow", a, b, r)] = out.get(("flow", a, b, r), 0.0) + k
        for e in f.get("effects") or []:
            out[("effect", a, b, e.get("stock") if e.get("stock") in measured else HID)] = 1.0
        for u in f.get("uses") or []:
            out[("uses", a, b, u.get("stock") if u.get("stock") in measured else HID)] = 1.0
    return out


def _size(key: tuple, v: float, means: dict) -> float:
    if key[0] != "flow":
        return math.inf
    r = key[3]
    return abs(v) * (1.0 if r == ONE else means.get(r, math.inf))


def agreement(model: dict, flows: list[dict], d: dict) -> dict:
    measured = set(d["levels"])
    t = d["t"]
    w = (t[1] if len(t) > 1 else t[0], t[-1])
    truth, _ = truth_by_time({"flows": model["flows"], "schedule": model.get("schedule")}, t)
    pub, got = keys(truth, measured, w), keys(flows, measured, w)
    means = {s: float(np.mean(v)) for s, v in d["levels"].items()}
    sizes = [_size(k, v, means) for k, v in pub.items()]
    fin = [x for x in sizes if math.isfinite(x) and x > 0]
    scale = float(np.median(fin)) if fin else 0.0
    big = {k for k, v in got.items() if _size(k, v, means) > SPURIOUS * scale}
    matched = [k for k in pub if k in got]
    extra = [k for k in big if k not in pub]
    recall = len(matched) / len(pub) if pub else 1.0
    precision = len([k for k in big if k in pub]) / len(big) if big else (1.0 if not pub else 0.0)
    rows = [{"key": label(k), "kind": kind(k) if k[0] != "flow" or HID not in k[1:3] else "hidden", "found": k in got, "ok": k in got,
             "true": _num(pub[k]), "found_value": _num(got.get(k)), "error": None, "compared": "structure (agreement)"} for k in pub]
    extra_rows = [{"key": label(k), "kind": kind(k) if k[0] != "flow" or HID not in k[1:3] else "hidden", "value": _num(got[k]),
                   "size": _finite(_size(k, got[k], means))} for k in extra]
    return {"published": [label(k) for k in pub], "found": [label(k) for k in got], "matched": [label(k) for k in matched],
            "missing": [label(k) for k in pub if k not in got], "extra": [label(k) for k in extra],
            "recall": recall, "precision": precision, "agrees": bool(recall == 1.0 and precision == 1.0),
            "parts_published": len(pub), "parts_found": len(big), "rows": rows, "extra_rows": extra_rows}


def _num(v):
    return _finite(v) if isinstance(v, (int, float)) else None


# ---- measured flows ----

def amounts(flows: list[dict], a: str, b: str, d: dict) -> np.ndarray:
    """The found flows from a to b: the amount moved in each step to sample i (i = 1 .. n-1), on the measured levels."""
    lv = d["levels"]
    t = d["t"]
    out = np.zeros(len(t) - 1)
    for f in flows:
        if f.get("from") != a or f.get("to") != b or f.get("via"):
            continue
        for i in range(len(t) - 1):
            level = {s: v[i] for s, v in lv.items()}
            lf = form_over(f, t[i + 1], t[i + 1])
            if lf is None:
                continue
            rate = max(0.0, lf[0] + sum(k * level.get(j, 0.0) for j, k in lf[1].items()))
            out[i] += rate * multiplier(f, level)
    return out


def measured_flows(flows: list[dict], d: dict) -> dict:
    rows = {}
    for name, series in d["flows"].items():
        if "outside" in name:
            continue
        a, b = name.split("->")
        meas = np.array([x for x in series[1:]], dtype=float)
        got = amounts(flows, a, b, d)
        present = any(f.get("from") == a and f.get("to") == b for f in flows) and float(got.mean()) > 0
        rel = abs(float(got.mean()) - float(meas.mean())) / max(1e-9, float(meas.mean()))
        back = np.array([x for x in d["flows"][f"{b}->{a}"][1:]], dtype=float)
        got_back = amounts(flows, b, a, d)
        net_true, net_found = float((meas - back).mean()), float((got - got_back).mean())
        corr = float(np.corrcoef(got, meas)[0, 1]) if got.std() > 0 and meas.std() > 0 else None
        rows[name] = {"found": bool(present), "measured_mean": float(meas.mean()), "found_mean": float(got.mean()), "error": rel,
                      "matched": bool(present and rel <= MATCH), "net_measured": net_true, "net_found": net_found, "corr": _finite(corr)}
    errs = [r["error"] if r["found"] else 1.0 for r in rows.values()]
    return {"rows": rows, "of": len(rows), "found": sum(r["found"] for r in rows.values()), "matched": sum(r["matched"] for r in rows.values()),
            "median_error": float(np.median(errs)) if errs else None, "tolerance": MATCH}


# ---- one line per cell (api.summary) and per strategy ----

def cell(row: dict | None) -> dict:
    """The numbers a real cell carries: held-out skill (found, published), agreement, flows."""
    if not row or not row.get("scores"):
        return {}
    s = row["scores"]
    h, ag, fl = s.get("heldout") or {}, s.get("agreement") or {}, s.get("flows") or {}
    out = {"heldout": h.get("skill"), "heldout_published": h.get("published"), "beats_published": h.get("beats_published"),
           "heldout_points": h.get("points"), "agree_recall": ag.get("recall"), "agree_precision": ag.get("precision"), "agrees": ag.get("agrees"),
           "parts_found": ag.get("parts_found"), "parts_published": ag.get("parts_published")}
    if fl:
        out.update(flows_matched=fl.get("matched"), flows_found=fl.get("found"), flows_of=fl.get("of"), flows_error=fl.get("median_error"))
    return out


def aggregate(cells: list[dict]) -> dict:
    """One strategy over the real cells: per variant (real, twin) {cells, run, heldout (mean skill, each clipped at -100%),
    heldout_published, beats (runs at least as good as the published model), graded, agree (mean recall, precision; runs
    agreeing), flows (BLS: matched of), and on the twin: pass, equivalent, fail}; error and timeout counted, never graded."""
    out = {}
    for v in ("real", "twin"):
        cs = [c for c in cells if c["variant"] == v]
        ran = [c for c in cs if c.get("status")]
        clip = lambda key: [max(-1.0, c[key]) for c in ran if c.get(key) is not None]  # noqa: E731
        hs, hp = clip("heldout"), clip("heldout_published")
        rec = [c["agree_recall"] for c in ran if c.get("agree_recall") is not None]
        pre = [c["agree_precision"] for c in ran if c.get("agree_precision") is not None]
        g = {"cells": len(cs), "run": len(ran), "heldout": sum(hs) / len(hs) if hs else None, "heldout_published": sum(hp) / len(hp) if hp else None,
             "graded": len(hs), "beats": sum(bool(c.get("beats_published")) for c in ran), "agrees": sum(bool(c.get("agrees")) for c in ran),
             "agree_recall": sum(rec) / len(rec) if rec else None, "agree_precision": sum(pre) / len(pre) if pre else None,
             **{k: sum(c.get("status") == k for c in ran) for k in ("pass", "equivalent", "fail", "error", "timeout", "agrees", "differs")}}
        fl = [c for c in ran if c.get("flows_of")]
        if fl:
            g["flows_matched"], g["flows_of"], g["flows_found"] = sum(c["flows_matched"] for c in fl), sum(c["flows_of"] for c in fl), sum(c["flows_found"] for c in fl)
        out[v] = g
    return out
