"""Offline studies behind combined_misfit and combined_lean (docs/research/ideas-2026-10-18.md). They read
the ladder's result store (each specialist's latest stored model and its stored grades); nothing is
written to the store and no discovery runs. The truth is read only to grade (the lean replay).

    uv run python tests/study_combined_r2.py judges OUT.jsonl   combined's candidates on every cell combined
                                                                 ran, with what each judge reads: BIC, in-data
                                                                 multi-step error (own pieces), the same with
                                                                 inflows frozen at each start (prequential),
                                                                 fed every other candidate's inflows (cross),
                                                                 residual dispersion and Ljung-Box z, change places
    uv run python tests/study_combined_r2.py rules OUT.jsonl    tests passed and realistic skill@20 under each
                                                                 selection rule (combined's own first)
    uv run python tests/study_combined_r2.py lean OUT.jsonl [--real]
                                                                 combined's stored models made leaner (prune.py),
                                                                 graded as the ladder grades them

Env: JOBS (3), ONLY (case-id prefixes), CP, FP, FLOWS (the lean replay's prices).
A rule's outcome is the chosen specialist's stored grade (its own numbers, not combined's refit), so
the absolute numbers differ a little from combined's; the rules are compared with each other.
"""

from __future__ import annotations

import json
import math
import os
import statistics as st
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

SPEC = ["censored", "effect_hats", "lna", "hidden_transit", "periodic_inflows", "gap_prior", "lna_pulses", "lna_stack", "common_cause"]
PREF = ["lna", "gap_prior", "lna_pulses", "lna_stack", "censored", "effect_hats", "hidden_transit", "periodic_inflows", "common_cause"]


def _cell(case_id, variant):
    from sdlab.discovery.strategies.combined import judge as J
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data as ldata
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = ldata.load(c, variant)
    stocks = casemod.page_stocks(model)
    inj = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d.get("injections") or []] or None
    run = {"t": d["t"], "levels": d["levels"]}
    return c, model, d, run, J.Data(stocks, run, inj, d.get("inputs"))


def _cells():
    from sdlab.ladder import api
    sm = api.summary()
    cells = sorted({(x["case"], x["variant"]) for x in sm["cells"] if x["strategy"] == "combined" and x["status"]
                    and (x["case"][:1].isdigit() or x["case"].startswith("sd-"))})      # the tests and the realistic runs
    only = os.environ.get("ONLY")
    if only:
        cells = [k for k in cells if k[0].startswith(tuple(only.split(",")))]
    return sorted(cells, key=lambda k: (k[0].startswith("sd-"), k))


def _pool(fn, cells, out):
    with ProcessPoolExecutor(int(os.environ.get("JOBS", "3"))) as ex, open(out, "w") as fh:
        fut = {ex.submit(fn, *k): k for k in cells}
        for f in as_completed(fut):
            try:
                j = f.result()
            except Exception:                                # noqa: BLE001
                j = {"case": fut[f][0], "variant": fut[f][1], "error": traceback.format_exc()[-500:]}
            if j:
                fh.write(json.dumps(j, default=float) + "\n")
                fh.flush()


# ---- judges: what each candidate looks like to each judge ----

def _is_exo(f):
    return not f.get("from") and f.get("to") and (f.get("rate") or {}).get("form") == "constant" and not f.get("driver")


def _exo_series(flows, ids, t):
    from sdlab.discovery.simulate import _Segments
    tt = np.asarray(t, float)
    out = np.zeros((len(ids), len(tt)))
    for f in flows:
        if not _is_exo(f) or f["to"] not in ids:
            continue
        i = ids.index(f["to"])
        segs = f.get("inflow")
        if segs:
            out[i] += np.array([float(segs[k]["value"]) for k in _Segments(segs)(tt)])
        else:
            out[i] += float(f["rate"].get("value") or 0)
    return out


def _with_exo(flows, ids, t, series):
    own = [f for f in flows if not _is_exo(f)]
    tt = list(map(float, t))
    for i, s in enumerate(ids):
        v = series[i]
        if not np.any(v):
            continue
        segs = []
        for k, x in enumerate(v):
            if segs and segs[-1]["value"] == float(x):
                segs[-1]["to"] = tt[k]
            else:
                segs.append({"from": tt[k], "to": tt[k], "value": float(x)})
        own.append({"from": None, "to": s, "rate": {"form": "constant", "value": float(v.mean())}, "inflow": segs})
    return own


def _beh(flows, D, run, inferred, hs, starts=80):
    from sdlab.discovery.simulate import behaviour_error
    return sum(behaviour_error(flows, D.ids, run["t"], run["levels"], horizon=h, injections=D.injections, starts=starts,
                               inferred=inferred or None, inputs=D.inputs or None) for h in hs) / len(hs)


def _frozen(flows, D, run, inferred, hs, starts=80):
    """Prequential: from each start, the outside inflows held at their value at the start."""
    from sdlab.discovery.simulate import Model, levels_array, starts_for
    S = len(D.ids)
    A = levels_array({**run["levels"], **(inferred or {})}, D.ids + list(inferred or {}))
    tt = np.asarray(run["t"], float)
    ex = _exo_series(flows, D.ids, run["t"])
    own = [f for f in flows if not _is_exo(f)]
    sd = A[:S].std(axis=1)
    sd[sd == 0] = 1
    tot = []
    for h in hs:
        groups: dict = {}
        for s in starts_for(A.shape[1], h, starts):
            groups.setdefault(tuple(np.round(ex[:, s - 1], 9)), []).append(s)
        e = moved = 0.0
        for key, ss in groups.items():
            ss = np.array(ss)
            fl = own + [{"from": None, "to": D.ids[i], "rate": {"form": "constant", "value": float(v)}} for i, v in enumerate(key) if v]
            end = Model(fl, D.ids + list(inferred or {}), inputs={"t": run["t"], "values": D.inputs} if D.inputs else None).run(
                A[:, ss - 1], tt[ss[None, :] + np.arange(h)[:, None]], D.injections)[:S]
            obs = A[:S, ss + h - 1]
            r = ((end - obs) / sd[:, None]) ** 2
            r[~np.isfinite(r)] = 1e6
            e += r.sum()
            moved += (((obs - A[:S, ss - 1]) / sd[:, None]) ** 2).sum()
        tot.append(e / max(1e-9, moved))
    return float(np.mean(tot))


def judges_one(case_id, variant):
    from sdlab.discovery.strategies.combined import judge as J
    from sdlab.discovery.strategies.combined_lean.prune import change_places
    from sdlab.discovery.strategies.combined_misfit.fitcheck import goodness
    from sdlab.ladder import store
    _, _, _, run, D = _cell(case_id, variant)
    hs = [h for h in (5, 20, 100) if h < len(D.t) / 4]
    cands, seen = [], {}
    for s in SPEC:
        r = next(iter(store.latest(case_id, variant, s, found=True)), None)
        if not r or r["status"] in ("error", "timeout") or r.get("found") is None:
            continue
        b = ((r.get("scores") or {}).get("behaviour") or {}).get("in_sample", {})
        rec = {"name": s, "status": r["status"], "skill20": (b.get("20") or {}).get("skill"), "id": r["id"],
               "cp": change_places(r["found"])}
        key = json.dumps(r["found"], sort_keys=True, default=repr)
        rec["dup"] = seen.get(key)
        seen.setdefault(key, s)
        try:
            jsc = J.score(r["found"], D, 1.0, 0.0, None)
            rec.update(nll=jsc["nll"], k=jsc["k"], bic=jsc["bic"])
            g = goodness(r["found"], D)
            rec.update(mz=g["dispersion"], lb=g["whiteness"])
        except Exception as e:                               # noqa: BLE001
            rec["err"] = repr(e)[:200]
            cands.append(rec)
            continue
        if rec["dup"] is None and hs:
            try:
                fl, inferred = J.hidden_estimate(r["found"], D, None)
                rec.update(beh=_beh(fl, D, run, inferred, hs), frozen=_frozen(fl, D, run, inferred, hs), _fl=fl, _inf=inferred)
            except Exception as e:                           # noqa: BLE001
                rec["beh_err"] = repr(e)[:200]
        cands.append(rec)
    uniq = [x for x in cands if "_fl" in x]
    ser = {x["name"]: _exo_series(x["_fl"], D.ids, run["t"]) for x in uniq}
    for x in uniq:
        x["cross"] = {}
        for y in uniq:
            if y is not x:
                try:
                    x["cross"][y["name"]] = _beh(_with_exo(x["_fl"], D.ids, run["t"], ser[y["name"]]), D, run, x["_inf"], hs, starts=40)
                except Exception:                            # noqa: BLE001
                    x["cross"][y["name"]] = None
    for x in cands:
        x.pop("_fl", None)
        x.pop("_inf", None)
    for x in cands:
        if x.get("dup"):
            o = next(y for y in cands if y["name"] == x["dup"])
            for k in ("beh", "frozen", "cross"):
                if k in o:
                    x[k] = o[k]
    return {"case": case_id, "variant": variant, "T": int(D.T), "counts": bool(D.counts), "cands": cands}


# ---- rules: which candidate each selection rule picks ----

def _clip(v):
    return -1.0 if v is None or not math.isfinite(v) else max(-1.0, v)


def _rank(x):
    return (round(x["bic"], 6), x["k"], PREF.index(x["name"]) if x["name"] in PREF else 99)


def choose(r, rule):
    """rule: (kind, factor, floor). Every rule first applies combined's guard (4x the best in-data
    multi-step error, floor 0.1), then: "bic" combined's rule; "own" / "frozen" / "cross" a tighter
    guard on that measure (cross: median over the other candidates' inflows); "fair" a candidate is
    set aside only by one with no more change places that behaves `factor` times better; "misfit"
    (z, factor): where the BIC winner fails the fit test at z (counts), the lowest in-data error
    (within factor), BIC breaking ties."""
    c = [x for x in r["cands"] if "bic" in x and x.get("beh") is not None and math.isfinite(x["bic"])]
    if not c:
        return None
    lim = max(4 * min(x["beh"] for x in c), 0.1)
    c = [x for x in c if x["beh"] <= lim] or c
    kind, f, floor = rule
    if kind == "bic":
        return min(c, key=_rank)
    if kind == "misfit":
        w = min(c, key=_rank)
        if not (r.get("counts") and ((w.get("mz") or 0) > f or (w.get("lb") or 0) > f)):
            return w
        b = min(x["beh"] for x in c)
        return min([x for x in c if x["beh"] <= floor * b], key=lambda x: (x["beh"], x["bic"]) if floor == 1 else _rank(x))
    if kind == "fair":
        c = [x for x in c if not any(y["cp"] <= x["cp"] and x["beh"] > max(f * y["beh"], floor) for y in c)] or c
        return min(c, key=_rank)

    def m(x):
        if kind == "own":
            return x["beh"]
        if kind == "frozen":
            return x["frozen"]
        v = [1e6 if y is None else y for k, y in (x.get("cross") or {}).items()]
        return float(np.median(v)) if v else x["beh"]
    best = min(m(x) for x in c)
    c = [x for x in c if m(x) <= max(f * best, floor)] or c
    return min(c, key=_rank)


RULES = [("bic", 0, 0), ("own", 2, 0.1), ("own", 1.5, 0.1), ("frozen", 2, 0.1), ("frozen", 1.5, 0.1), ("cross", 4, 0.1), ("cross", 2, 0.1),
         ("fair", 1.25, 0.1), ("misfit", 4, 1), ("misfit", 5, 1), ("misfit", 6, 1), ("misfit", 8, 1), ("misfit", 5, 1.25), ("misfit", 5, 1.5)]


def rules(path):
    rows = [json.loads(line) for line in open(path)]
    real = [r for r in rows if r["case"].startswith("sd-") and "cands" in r]
    tests = [r for r in rows if not r["case"].startswith("sd-") and "cands" in r]
    base = {(r["case"], r["variant"]): choose(r, RULES[0]) for r in tests}
    print(f"{len(tests)} test cells, {len(real)} realistic runs")
    print(f"{'rule':24s} {'tests pass':>10s} {'lost':>5s} {'won':>4s} {'realistic skill@20':>19s}")
    for rule in RULES:
        P = lost = won = 0
        for r in tests:
            x, b = choose(r, rule), base[(r["case"], r["variant"])]
            p, pb = bool(x and x["status"] == "pass"), bool(b and b["status"] == "pass")
            P += p
            lost += pb and not p
            won += p and not pb
        sk = [_clip(choose(r, rule)["skill20"]) for r in real]
        print(f"{str(rule):24s} {P:10d} {lost:5d} {won:4d} {100 * st.mean(sk):18.1f}%")


# ---- lean: combined's stored models made leaner, graded ----

def lean_one(case_id, variant):
    import time

    from sdlab.discovery.strategies.combined_lean.prune import lean
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import complexity, score, store
    from sdlab.ladder import data as ldata
    c, model, d, run, D = _cell(case_id, variant)
    r = next(iter(store.latest(case_id, variant, "combined", found=True)), None)
    if not r or r["status"] in ("error", "timeout"):
        return None
    t0 = time.time()
    new, rep = lean(r["found"], D, run, cp=float(os.environ.get("CP", "1.5")), fp=float(os.environ.get("FP", "1.0")),
                    flows_pass=bool(int(os.environ.get("FLOWS", "1"))))
    true, meas = complexity.of_truth(c, variant), complexity.measured(c)
    out = {"case": case_id, "variant": variant, "old": r["status"], "secs": time.time() - t0, "rep": rep,
           "old_extra": complexity.compare(true, complexity.count(r["found"], meas))["extra"]}
    if new is r["found"]:
        return {**out, "same": True}
    noise = casemod.variant(c, variant)["noise"]
    fresh = ldata.load(c, variant, fresh=True)
    if d.get("clean"):
        s = {**score.equations(c, noise, model, new, d), "behaviour": score.behaviour(model, new, d["clean"], fresh["clean"])}
    else:
        s = score.score(c, noise, model, new, d, fresh)
    b = s.get("behaviour", {})
    ob = (r.get("scores") or {}).get("behaviour", {})
    return {**out, "new": s["status"], "new_extra": complexity.compare(true, complexity.count(new, meas))["extra"],
            "new_s20": (b.get("in_sample", {}).get("20") or {}).get("skill"), "old_s20": (ob.get("in_sample", {}).get("20") or {}).get("skill")}


def lean_report(path):
    rows = [json.loads(line) for line in open(path) if line.strip()]
    rows = [r for r in rows if not r.get("error") and (r["case"][:1].isdigit() or r["case"].startswith("sd-"))]

    def st_(r, new):
        return (r["old"], r["old_extra"]) if r.get("same") or not new else (r["new"], r["new_extra"])
    for new in (False, True):
        P = sum(st_(r, new)[0] == "pass" for r in rows)
        L = sum(st_(r, new)[0] == "pass" and st_(r, new)[1] <= 0 for r in rows)
        print(("lean   " if new else "stored ") + f"pass {P}, pass with no extra complexity {L} (of {len(rows)})")
    for r in rows:
        if not r.get("same") and (r["old"] != r["new"]):
            print("  ", r["case"], r["variant"], r["old"], "->", r["new"], "extra", r["old_extra"], "->", r["new_extra"])
    real = [r for r in rows if r["case"].startswith("sd-") and not r.get("same")]
    if real:
        print(f"realistic runs changed: {len(real)}; mean skill@20 {100 * st.mean(_clip(r['old_s20']) for r in real):.1f}% ->"
              f" {100 * st.mean(_clip(r['new_s20']) for r in real):.1f}%")


if __name__ == "__main__":
    cmd, out = sys.argv[1], sys.argv[2]
    if cmd == "judges":
        _pool(judges_one, _cells(), out)
    elif cmd == "rules":
        rules(out)
    elif cmd == "lean":
        cells = _cells()
        if "--real" not in sys.argv:
            cells = [k for k in cells if not k[0].startswith("sd-")]
        _pool(lean_one, cells, out)
        lean_report(out)
