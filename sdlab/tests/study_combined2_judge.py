"""Offline study for combined2's judge (docs/research/combined2.md): every stored model of the
candidate strategies on a cell, scored by combined's judge (one-step likelihood + BIC, numbers
refitted, the 4x runaway guard on in-data behaviour) and by the held-inflow forecast error
(combined2/forecast.py), beside each model's stored status and skill@20. No discovery runs and
nothing is written to the store; rules that pick among the candidates are then compared offline
(`analyse`).

    uv run python tests/study_combined2_judge.py run CASES OUT.jsonl      CASES: a runner spec ("tag:realistic")
    uv run python tests/study_combined2_judge.py analyse OUT.jsonl [OUT2.jsonl ...]

Env JOBS (2), STRATS (comma list; default the combined2 pool).
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

POOL = ["censored", "effect_hats", "lna", "hidden_transit", "periodic_inflows", "gap_prior", "lna_pulses", "lna_stack", "common_cause",
        "realistic_hats", "coflow_hats", "own_tables", "drifting_drain", "odefit"]


def _skill(r: dict, h: str = "20") -> float | None:
    b = ((r.get("scores") or {}).get("behaviour") or {}).get("in_sample") or {}
    return (b.get(h) or {}).get("skill")


def _cell(case_id: str, variant: str, rows: dict) -> dict:
    import math

    from sdlab.discovery.strategies.combined2 import judge as J2
    from sdlab.discovery.strategies.combined2._vendored.combined import judge as J
    from sdlab.discovery.strategies.combined2._vendored.combined.refit import refit
    from sdlab.discovery.strategies.combined2.forecast import held
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data as datamod
    from sdlab.ladder.real import data as real_data

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = real_data.load(c, variant) if c.get("real") else datamod.load(c, variant)
    stocks = casemod.page_stocks(model)
    run = {"t": d["t"], "levels": d["levels"]}
    inj = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d.get("injections") or []] or None
    inputs = {k: list(v) for k, v in (d.get("inputs") or {}).items()} or None
    eras = len(d.get("eras") or []) > 1
    data = J.Data(stocks, run, inj, inputs)
    out = {"case": case_id, "variant": variant, "counts": bool(data.counts), "T": int(data.T), "S": len(data.ids), "cands": {}}
    seen: dict = {}
    for name, r in rows.items():
        flows = r.get("found") or []
        row = {"status": r["status"], "skill20": _skill(r), "skill100": _skill(r, "100"), "seconds": r.get("seconds"), "nflows": len(flows)}
        if r["status"] in ("error", "timeout") or not flows:
            out["cands"][name] = row
            continue
        key = json.dumps(flows, sort_keys=True, default=repr)
        if key in seen:
            out["cands"][name] = {**row, **seen[key], "same_as": seen[key]["name"]}
            continue
        m: dict = {"name": name}
        try:
            s = J.score(flows, data, 1.0, 0.0, None)
            fl = flows
            try:
                f2 = refit(flows, data, J.weights(flows, data))
                s2 = J.score(f2, data, 1.0, 0.0, None) if f2 else None
                if s2 is not None and s2["nll"] < s["nll"] - 1e-9:
                    s, fl = s2, f2
            except Exception:                                            # noqa: BLE001
                pass
            m.update(bic=s["bic"], nll=s["nll"], k=s["k"])
            try:
                m["dbic"] = J2.score(fl, data, 1.0, 0.0, None)["bic"]
            except Exception as e:                                       # noqa: BLE001
                m["dbic_error"] = repr(e)[:200]
            m["own"] = J.behaviour(fl, data, run, None)
            fl2, inferred = J.hidden_estimate(fl, data, None)
            m["held"] = held(fl2, data, run, inferred, eras)
            for k in ("own", "held"):
                if not math.isfinite(m[k]):
                    m[k] = 1e9
        except Exception as e:                                           # noqa: BLE001
            m["judge_error"] = repr(e)[:300]
        seen[key] = m
        out["cands"][name] = {**row, **m}
    return out


def run_study(spec: str, out_path: str) -> None:
    from sdlab.ladder import runner, store

    strats = (os.environ.get("STRATS") or ",".join(POOL)).split(",")
    ids = set(runner.select_cases(spec))
    rows: dict = {}
    for name in strats + ["combined", "kalman_lna", "structures", "archetypes"]:
        for r in store.latest(strategy=name, found=True):
            if r["case"] in ids:
                rows.setdefault((r["case"], r["variant"]), {})[name] = r
    done = set()
    if os.path.exists(out_path):
        for line in open(out_path):
            x = json.loads(line)
            done.add((x["case"], x["variant"]))
    todo = {k: v for k, v in rows.items() if k not in done}
    with open(out_path, "a") as fh, ProcessPoolExecutor(int(os.environ.get("JOBS", "2"))) as ex:
        futs = {}
        for k, v in todo.items():
            cands = {n: r for n, r in v.items() if n in strats}
            refs = {n: {"status": r["status"], "skill20": _skill(r), "skill100": _skill(r, "100")} for n, r in v.items() if n not in strats}
            futs[ex.submit(_cell, k[0], k[1], cands)] = (k, refs)
        for f in as_completed(futs):
            k, refs = futs[f]
            try:
                fh.write(json.dumps({**f.result(), "refs": refs}) + "\n")
                fh.flush()
            except Exception as e:                                       # noqa: BLE001
                print("failed", k, repr(e)[:300], file=sys.stderr)


PREFERENCE = ["lna", "gap_prior", "lna_pulses", "lna_stack", "censored", "realistic_hats", "effect_hats", "coflow_hats", "hidden_transit",
              "periodic_inflows", "own_tables", "drifting_drain", "odefit", "common_cause"]


def kind(case_id: str, variant: str) -> list[str]:
    from sdlab.ladder import cases as casemod

    c = casemod.load(case_id)
    tags = c.get("tags") or []
    if c.get("real"):
        return ["twins"] if variant == "twin" else []
    if c.get("example") or "realistic" in tags:
        return ["realistic"]
    if c.get("particles"):
        return ["particles"]
    if c.get("physics"):
        return ["physics"]
    return ["tests"] + [t for t in ("noisy", "canonical", "distilled") if t in tags]


def pick(cell: dict, pool: list[str], guard=4.0, guard_floor=0.1, held=0.0, held_floor=0.1, bic="bic") -> str | None:
    """The candidate a rule picks: guards set candidates aside, then the lowest price."""
    cs = [(n, c) for n, c in cell["cands"].items() if n in pool and c.get(bic) is not None and c.get("own") is not None]
    if not cs:
        return None
    for key, f, fl in (("own", guard, guard_floor), ("held", held, held_floor)):
        if f:
            good = min(c[key] for _, c in cs)
            kept = [x for x in cs if x[1][key] <= max(f * good, fl)]
            cs = kept or cs
    return min(cs, key=lambda x: (round(x[1][bic], 6), x[1]["k"], PREFERENCE.index(x[0]) if x[0] in PREFERENCE else 99))[0]


def analyse(paths: list[str]) -> None:
    import collections

    cells = [json.loads(line) for p in paths for line in open(p)]
    pool = (os.environ.get("STRATS") or ",".join(POOL)).split(",")
    old = [n for n in pool if n in POOL[:9]]
    rules = {"combined's (old pool)": dict(pool_=old), "combined's judge, new pool": {}, "discrete": dict(bic="dbic")}
    for f in (1.25, 1.5, 2.0, 3.0, 4.0):
        rules[f"held {f}x"] = dict(held=f)
        rules[f"held {f}x + discrete"] = dict(held=f, bic="dbic")
    rules["held 2x, no own guard"] = dict(held=2.0, guard=0)
    rules["held only 1.5x, no own guard"] = dict(held=1.5, guard=0)
    tab: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for cell in cells:
        sets = kind(cell["case"], cell["variant"])
        for S in sets:
            for name, kw in rules.items():
                kw = dict(kw)
                p = kw.pop("pool_", pool)
                got = pick(cell, p, **kw)
                c = cell["cands"].get(got) or {}
                tab[S][name].append((c.get("status") == "pass", c.get("skill20")))
            best = [c for n, c in cell["cands"].items() if n in pool]
            tab[S]["oracle (any candidate passes)"].append((any(c.get("status") == "pass" for c in best),
                                                           max([c["skill20"] for c in best if c.get("skill20") is not None], default=None)))
            ref = cell["refs"].get("combined") or {}
            tab[S]["combined as stored"].append((ref.get("status") == "pass", ref.get("skill20")))
    for S, rows in sorted(tab.items()):
        n = len(next(iter(rows.values())))
        print(f"== {S} ({n} cells)")
        for name, xs in rows.items():
            sk = [max(-1.0, v) for _, v in xs if v is not None]
            print(f"   {name:34s} pass {sum(1 for p, _ in xs if p):4d}   mean skill@20 {100 * sum(sk) / max(1, len(sk)):6.1f}% (n {len(sk)})")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run_study(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "analyse":
        analyse(sys.argv[2:])
