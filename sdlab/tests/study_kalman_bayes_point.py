"""Study (not a test): kalman_bayes's point answer alone (its copy of kalman_lna, `_point`), run and
scored on the same cells and machine as a kalman_bayes run, so that the posterior step is compared
with exactly the answer it starts from (the store's kalman_lna rows mix versions).

    uv run python tests/study_kalman_bayes_point.py --cases SPEC --out FILE [--jobs 4] [--timeout 600]

FILE gets {"case|variant": {"status", "seconds"}}; tests/study_kalman_bayes.py --point FILE pairs it.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from concurrent.futures import ProcessPoolExecutor

from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score


def one(cell: tuple[str, str], timeout: float) -> tuple[str, dict]:
    from sdlab.discovery.strategies.kalman_bayes import _point

    case, variant = cell
    def fire(*_):
        raise TimeoutError
    signal.signal(signal.SIGALRM, fire)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        c = casemod.load(case)
        noise = casemod.variant(c, variant)["noise"]
        model = casemod.truth_model(c, variant)
        d = data.load(c, variant)
        stocks = casemod.page_stocks(model)
        opts: dict = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
        if d.get("injections"):
            opts["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
        if d.get("inputs"):
            opts["inputs"] = {k: list(v) for k, v in d["inputs"].items()}
        began = time.perf_counter()
        r = _point(stocks, {"t": d["t"], "levels": d["levels"]}, opts)
        took = time.perf_counter() - began
        signal.setitimer(signal.ITIMER_REAL, 0)
        flows = r.get("flows") or []
        if d.get("clean"):
            st = score.equations(c, noise, model, flows, d)["status"]
        else:
            st = score.score(c, noise, model, flows, d, data.load(c, variant, fresh=True), r.get("inferred_levels"))["status"]
        return f"{case}|{variant}", {"status": st, "seconds": round(took, 3)}
    except TimeoutError:
        return f"{case}|{variant}", {"status": "timeout", "seconds": timeout}
    except Exception as e:                                       # noqa: BLE001
        return f"{case}|{variant}", {"status": "error", "error": f"{type(e).__name__}: {e}"[:300]}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args()
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ[v] = "1"
    cells = [(cid, v["name"]) for cid in runner.select_cases(a.cases) for v in casemod.load(cid)["variants"]]
    out = {}
    with ProcessPoolExecutor(a.jobs, max_tasks_per_child=1) as ex:
        for i, (k, v) in enumerate(ex.map(one, cells, [a.timeout] * len(cells))):
            out[k] = v
            print(f"[{i + 1}/{len(cells)}] {k}: {v['status']} ({v.get('seconds')})", flush=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh)


if __name__ == "__main__":
    main()
