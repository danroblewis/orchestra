"""The declared boundary (2026-10-20, docs/LADDER.md "The boundary"): re-score every stored result's
status, offline (nothing written to the store), with whichever scorer is importable, then compare two
outputs. The change touches score.py and parts.py, so every row's score hash changes; with no case
declaring a boundary, no status may change.

    git archive HEAD sdlab | tar -x -C <old>                          # the scorer before the change
    PYTHONPATH=<old> uv run python tests/study_rescore_boundary.py score old.json --jobs 4
    uv run python tests/study_rescore_boundary.py score new.json --jobs 4
    uv run python tests/study_rescore_boundary.py compare old.json new.json

`score` grades every latest row that is not an error or a timeout, the way runner.run_item grades it,
without behaviour (skill@h never sets a ladder status): a ladder case by score.equations (on the
reported data for a noise of noise.py), a real case by real/score.py, a physics or particle case by its
own scorer. Output: {row id: [set, status]} (status "error: ..." when grading raised).
"""

from __future__ import annotations

import collections
import json
import os
import random
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"


def _rows():
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    q = "SELECT id, case_id, variant, strategy FROM results WHERE latest = 1 AND status NOT IN ('error', 'timeout') ORDER BY case_id, variant"
    return [list(r) for r in con.execute(q)]


def _found(rid: int) -> list[dict]:
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    (found,) = con.execute("SELECT found FROM results WHERE id = ?", (rid,)).fetchone()
    return json.loads(found or "[]")


def _grade(batch: list[list]) -> dict:
    from sdlab.ladder import cases as casemod, data, leaderboard, particles, physics, score
    from sdlab.ladder.real import data as real_data, score as real_score
    score.behaviour = lambda *a, **k: {}                       # not part of any ladder status
    out = {}
    for rid, cid, variant, _ in batch:
        kind = "?"
        try:
            c = casemod.load(cid)
            kind = leaderboard.kind_of(c) + ("/particles" if particles.is_particles(c) else "")
            flows = _found(rid)
            model = casemod.truth_model(c, variant)
            noise = casemod.variant(c, variant)["noise"]
            if c.get("real"):
                d = real_data.load(c, variant)
                s = real_score.score(c, variant, model, flows, d, real_data.load(c, variant, full=True), None)
            elif particles.is_particles(c):
                d = data.load(c, variant)
                s = particles.score_found(c, variant, model, flows, d, data.load(c, variant, fresh=True), None)
            elif physics.is_physics(c):
                d = data.load(c, variant)
                s = physics.score_found(c, variant, flows, d, data.load(c, variant, fresh=True), None)
            else:
                s = score.equations(c, noise, model, flows, data.load(c, variant))
            out[str(rid)] = [kind, s["status"]]
        except Exception as e:                                 # noqa: BLE001
            out[str(rid)] = [kind, f"error: {type(e).__name__}: {e}"[:300]]
    return out


def score_all(path: str, jobs: int, limit: int | None = None) -> None:
    rows = _rows()[:limit] if limit else _rows()
    batches = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    random.Random(0).shuffle(batches)                          # the slow cases (realistic, physics) spread over the workers
    out, began = {}, time.time()
    with ProcessPoolExecutor(jobs) as ex:
        futs = [ex.submit(_grade, b) for b in batches]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out.update(f.result())
            except Exception:                                  # noqa: BLE001
                traceback.print_exc()
            if i % 20 == 0:
                print(f"{len(out)}/{len(rows)} rows, {time.time() - began:.0f} s", flush=True)
    with open(path, "w") as fh:
        json.dump(out, fh)
    print(f"{len(out)} rows in {time.time() - began:.0f} s -> {path}")


def compare(old_path: str, new_path: str) -> None:
    old, new = json.load(open(old_path)), json.load(open(new_path))
    per: dict = collections.defaultdict(collections.Counter)
    flips = []
    for rid in sorted(set(old) | set(new), key=int):
        o, n = old.get(rid), new.get(rid)
        kind = (n or o)[0]
        if o is None or n is None:
            per[kind]["missing on one side"] += 1
            continue
        per[kind]["rows"] += 1
        if o[1] != n[1]:
            per[kind][f"{o[1]} -> {n[1]}"] += 1
            flips.append((rid, kind, o[1], n[1]))
        else:
            per[kind]["same"] += 1
            if o[1].startswith("error"):
                per[kind]["error on both sides"] += 1
    for kind in sorted(per):
        print(kind, dict(per[kind]))
    print(f"flips: {len(flips)}")
    for f in flips[:50]:
        print("  ", *f)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "score":
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 1
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        score_all(sys.argv[2], jobs, limit)
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3])
