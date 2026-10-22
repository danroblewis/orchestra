"""Re-grade stored results as runner.run_item grades them, before and after 5dca817 (score._levels_at adds a step's announced
injections; the old function is swapped back in for "before"; 2026-10-22). Rows: [id, case, variant, strategy, set] (as
study_rescore_input.py rows makes them, filtered to the cases with announced injections). Nothing is written to the store.

    uv run python tests/study_rescore_input.py rows all.json      # then keep the rows of the injection cases (rows.json)
    OLD_LEVELS=1 .venv/bin/python tests/study_rescore_injections.py rows.json old.json 8
    .venv/bin/python tests/study_rescore_injections.py rows.json new.json 8
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ[k] = "1"

def _old_levels_at(data: dict) -> list[dict]:          # score._levels_at before 5dca817 (no injections)
    lv = data.get("all_levels") or data["levels"]
    n = len(data["t"])
    ins = {k: v for k, v in (data.get("inputs") or {}).items() if k not in lv}
    return [{**{s: v[i] for s, v in lv.items()}, **{k: v[i + 1] for k, v in ins.items() if i + 1 < len(v)}} for i in range(n - 1)]


def grade(batch):
    from sdlab.ladder import cases as casemod, data, score, store
    if os.environ.get("OLD_LEVELS"):
        score._levels_at = _old_levels_at
    out = {}
    for rid, cid, var, strat, _ in batch:
        try:
            r = store.get(rid, found=True); c = casemod.load(cid)
            noise = casemod.variant(c, var)["noise"]; model = casemod.truth_model(c, var)
            d = {**data.load(c, var), **casemod.announced(c)}; fresh = data.load(c, var, fresh=True)
            flows = r.get("found") or []
            if d.get("clean"):
                s = {**score.equations(c, noise, model, flows, d)}
            else:
                s = score.score(c, noise, model, flows, d, fresh, None)
            out[rid] = s["status"]
        except Exception as e:  # noqa: BLE001
            out[rid] = f"error: {type(e).__name__}: {e}"[:200]
    return out

if __name__ == "__main__":
    rows = json.load(open(sys.argv[1])); jobs = int(sys.argv[3])
    import sdlab; print("sdlab from", sdlab.__file__, flush=True)
    batches = [rows[i::jobs * 4] for i in range(jobs * 4)]
    res = {}
    with ProcessPoolExecutor(jobs) as ex:
        for got in ex.map(grade, batches):
            res.update(got)
    json.dump(res, open(sys.argv[2], "w")); print(len(res), "graded")
