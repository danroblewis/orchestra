"""Two strategies' stored models on the same cells, scored again by the scorer as it is now, in one
process (docs/research/realistic-hats.md). The store's rows can carry different scorer hashes while
the scorer is being changed; this puts both on the same one. Nothing is written to the store and no
discovery runs.

    uv run python tests/study_rescore_pair.py A B CASES OUT.jsonl     CASES: a runner spec ("tag:realistic", "001,002")

Each line: case, variant, and per strategy its stored status, the status now, recall and in-sample /
fresh skill@20 and skill@100 now, and whether a realistic run meets the goal. Env JOBS (2).
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed


def _cell(case_id: str, variant: str, rows: dict) -> dict:
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data as datamod
    from sdlab.ladder import realistic, score

    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = datamod.load(c, variant)
    fresh = datamod.load(c, variant, fresh=True)
    noise = casemod.variant(c, variant)["noise"]
    out = {"case": case_id, "variant": variant}
    for name, r in rows.items():
        if r["status"] in ("error", "timeout"):
            out[name] = {"stored": r["status"], "now": r["status"]}
            continue
        flows = r.get("found") or []
        if d.get("clean"):
            s = {**score.equations(c, noise, model, flows, d), "behaviour": score.behaviour(model, flows, d["clean"], fresh["clean"])}
        else:
            s = score.score(c, noise, model, flows, d, fresh)
        b = s["behaviour"]
        g = lambda w, h: ((b.get(w) or {}).get(h) or {}).get("skill")  # noqa: E731
        out[name] = {"stored": r["status"], "now": s["status"], "recall": s.get("recall"), "skill20": g("in_sample", "20"),
                     "skill100": g("in_sample", "100"), "fresh20": g("fresh", "20"), "fresh100": g("fresh", "100")}
        if realistic.is_realistic(c):
            out[name]["goal"] = realistic.meets_goal(s["status"], g("in_sample", "20"), g("in_sample", "100"))
    return out


def main(argv: list[str]) -> None:
    from sdlab.ladder import runner, store

    a, b, spec, out_path = argv[:4]
    ids = set(runner.select_cases(spec))
    rows: dict = {}
    for name in (a, b):
        for r in store.latest(strategy=name, found=True):
            if r["case"] in ids:
                rows.setdefault((r["case"], r["variant"]), {})[name] = r
    cells = {k: v for k, v in rows.items() if len(v) == 2}
    with open(out_path, "w") as fh, ProcessPoolExecutor(int(os.environ.get("JOBS", "2"))) as ex:
        futs = {ex.submit(_cell, k[0], k[1], v): k for k, v in cells.items()}
        for f in as_completed(futs):
            try:
                fh.write(json.dumps(f.result()) + "\n")
                fh.flush()
            except Exception as e:                                       # noqa: BLE001
                print("failed", futs[f], repr(e)[:300], file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
