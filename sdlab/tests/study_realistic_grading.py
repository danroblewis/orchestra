"""Does grading, not discovery, make the realistic results look bad? (docs/research/realistic-triage.md)

The behaviour grader (sdlab/skill.py, same_behaviour) runs the found model and the truth from the same
levels, feeding both the truth's outside inflows: in every stock the truth feeds with a constant outside
inflow, the found model's driverless constant outside inflows are dropped and the truth's constant
inflows (its schedule, with any non-constant segment set to 0) are put in their place. This study
re-grades every stored realistic model three ways, in-sample, without changing the scorer:

    graded  as the ladder grades it (recomputed; should equal the stored skill)
    own     the found model as it was found, its own inflows and pieces, nothing swapped in
            (an upper bound: pieces fitted on this run can replay the data)
    replay  no dynamics: each stock's mean change per step, cut where the found model's pieces on that
            stock change, graded as "own": what the found model's piece budget buys by replaying
    full    as graded, but the truth's constant outside inflows into those stocks keep every segment
            of their schedule (a segment that is not constant is not set to 0)

and lists, per run, the found model's outside inflow pieces into the swapped stocks.

    uv run python tests/study_realistic_grading.py OUT.jsonl [strategies] [horizon]

Reads the ladder's result store (latest rows); writes nothing to it. Env JOBS (2).
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

STRATS = ["effect_hats", "censored", "combined", "structures", "matrix", "kalman_lna", "earned_pieces"]


def replay(flows: list[dict], d: dict) -> list[dict]:
    """No dynamics at all: each measured stock's mean change per step, piece by piece, cut where the
    found model's own pieces on that stock change (one piece if it has none). Graded "own", it says
    how much skill@20 the found model's piece budget buys by replaying the run."""
    import numpy as np

    t = list(d["t"])
    out = []
    for sid, lv in d["levels"].items():
        cuts = sorted({int(g["from"]) for f in flows if sid in (f.get("from"), f.get("to")) for g in f.get("inflow") or []} | {int(t[1])})
        x = np.asarray(lv, dtype=float)
        ins, outs = [], []
        for i, a in enumerate(cuts):
            b = cuts[i + 1] - 1 if i + 1 < len(cuts) else int(t[-1])
            ia, ib = t.index(a) if a in t else 1, t.index(b) if b in t else len(t) - 1
            dm = float((x[ib] - x[ia - 1]) / max(1, ib - ia + 1))
            ins.append({"from": a, "to": b, "value": max(dm, 0.0)})
            outs.append({"from": a, "to": b, "value": max(-dm, 0.0)})
        out += [{"from": None, "to": sid, "rate": {"form": "constant", "value": 0}, "inflow": ins},
                {"from": sid, "to": None, "rate": {"form": "constant", "value": 0}, "inflow": outs}]
    return out


def _grade(case_id: str, variant: str, rows: list[dict], horizon: int) -> list[dict]:
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data as datamod
    from sdlab.skill import same_behaviour, truth_runs

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = datamod.load(c, variant)
    tr = truth_runs(model, d, horizon=horizon)
    own_tr = {**tr, "fed": set(), "exo": []}
    # exo is made from the truth's outside flows into the fed stocks, in order; a flow whose base rate is
    # constant keeps its whole schedule here, one that reads stocks (an endogenous inflow) stays at 0
    src = [f for f in tr["flows"] if not f.get("from") and f.get("to") in tr["fed"]]
    full_tr = {**tr, "exo": [f if (f.get("rate") or {}).get("form") == "constant" else z for f, z in zip(src, tr["exo"])]}
    out = []
    for r in rows:
        flows = r.get("found") or []
        res = {"flows": flows}
        rec = {"case": case_id, "variant": variant, "strategy": r["strategy"], "status": r["status"],
               "stored": (((r.get("scores") or {}).get("behaviour") or {}).get("in_sample") or {}).get(str(horizon), {}).get("skill"),
               "fed": sorted(tr["fed"]),
               "swapped": [{"to": f.get("to"), "value": (f.get("rate") or {}).get("value"), "pieces": len(f.get("inflow") or [])}
                           for f in flows if not f.get("from") and f.get("to") in tr["fed"] and not f.get("driver")
                           and (f.get("rate") or {}).get("form") == "constant"],
               "n_flows": len(flows)}
        for name, t, m in (("graded", tr, res), ("own", own_tr, res), ("full", full_tr, res),
                           ("replay", own_tr, {"flows": replay(flows, d)})):
            try:
                rec[name] = same_behaviour(m, model, d, horizon=horizon, truth=t, own_run=True)["skill"]
            except Exception as e:                                      # noqa: BLE001
                rec[name] = None
                rec[name + "_error"] = repr(e)[:200]
        out.append(rec)
    return out


def main(argv: list[str]) -> None:
    from sdlab.ladder import store

    out_path = argv[0]
    strats = argv[1].split(",") if len(argv) > 1 and argv[1] else STRATS
    horizon = int(argv[2]) if len(argv) > 2 else 20
    rows = [r for r in store.latest(found=True) if r["case"].startswith("sd-") and r["strategy"] in strats
            and r["status"] not in ("error", "timeout")]
    cells: dict = {}
    for r in rows:
        cells.setdefault((r["case"], r["variant"]), []).append(r)
    with open(out_path, "w") as fh, ProcessPoolExecutor(int(os.environ.get("JOBS", "2"))) as ex:
        futs = {ex.submit(_grade, k[0], k[1], v, horizon): k for k, v in cells.items()}
        for f in as_completed(futs):
            try:
                for rec in f.result():
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
            except Exception as e:                                       # noqa: BLE001
                print("failed", futs[f], repr(e)[:300], file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
