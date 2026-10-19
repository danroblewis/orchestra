"""Scoring changes, before and after (docs/LADDER.md, "The scoring changes of 19 October 2026"):
re-score every latest stored result's equations offline (no discovery, nothing written to the
store) with whichever scorer is importable, then compare two outputs cell by cell.

    PYTHONPATH=<a copy of the old sdlab package> uv run python tests/study_rescore.py old.json --jobs 10
    uv run python tests/study_rescore.py new.json --jobs 10 [--cases 104,125] [--ids ids.json]
    uv run python tests/study_rescore.py --compare old.json new.json [flips.json]

A row is {row id: [case, variant, strategy, status, error, stored status]}. The comparison matches
(case, variant, strategy) and keeps a pair whose rows differ (the watcher re-scored in between)
only if their stored found flows are identical. Physics cases and a real case's `real` variant are
not scored by score.equations and are left out; particle cases only where their tier has equations.
"""

from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"


def _cell(job):
    (cid, variant), rows = job
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data, particles, physics, score, store
    from sdlab.ladder.real import data as real_data
    out = {}
    try:
        c = casemod.load(cid)
        if physics.is_physics(c) and not particles.is_particles(c):
            return {r: None for r in rows}
        if (c.get("real") and variant != "twin") or (particles.is_particles(c) and not c["particles"]["equations"]):
            return {r: None for r in rows}
        noise = "counts" if c.get("real") or particles.is_particles(c) else casemod.variant(c, variant)["noise"]
        model = casemod.truth_model(c, variant)
        d = real_data.load(c, variant) if c.get("real") else data.load(c, variant)
    except Exception as e:  # noqa: BLE001  (a case that is gone or renamed)
        return {r: ["error", f"cell: {type(e).__name__}: {e}"] for r in rows}
    for rid in rows:
        try:
            flows = (store.get(rid, found=True) or {}).get("found") or []
            out[rid] = [score.equations(c, noise, model, flows, d)["status"], None]
        except Exception:  # noqa: BLE001
            out[rid] = ["error", " ".join(traceback.format_exc().strip().splitlines()[-2:])[:300]]
    return out


def rescore(out_path: str, jobs: int, only: set | None, ids: set | None) -> None:
    from sdlab.ladder import store
    rows = [r for r in store.latest() if r["status"] not in ("error", "timeout")]
    if only:
        rows = [r for r in rows if any(r["case"].startswith(o) for o in only)]
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    meta = {r["id"]: (r["case"], r["variant"], r["strategy"], r["status"]) for r in rows}
    cells: dict = {}
    for r in rows:
        cells.setdefault((r["case"], r["variant"]), []).append(r["id"])
    work = sorted(((k, v[i:i + 40]) for k, v in cells.items() for i in range(0, len(v), 40)), key=lambda j: -len(j[1]))
    res, t0 = {}, time.time()
    with ProcessPoolExecutor(jobs) as ex:
        for n, f in enumerate(as_completed([ex.submit(_cell, j) for j in work])):
            for rid, v in f.result().items():
                if v is not None:
                    res[rid] = [*meta[rid][:3], v[0], v[1], meta[rid][3]]
            if n % 50 == 0:
                print(f"{n}/{len(work)} cells, {len(res)} rows, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    json.dump(res, open(out_path, "w"))
    print("done", len(res), f"{time.time() - t0:.0f}s", file=sys.stderr)


def compare(pa: str, pb: str, out: str | None = None) -> list:
    from sdlab.ladder import store
    a, b = json.load(open(pa)), json.load(open(pb))
    con = sqlite3.connect(str(store.path()))

    def found(rid):
        return con.execute("SELECT found FROM results WHERE id = ?", (int(rid),)).fetchone()[0]

    ka = {tuple(v[:3]): (rid, v) for rid, v in a.items()}
    kb = {tuple(v[:3]): (rid, v) for rid, v in b.items()}
    flips, common, rerun, errors = [], 0, 0, 0
    for k, (ra, va) in ka.items():
        if k not in kb:
            continue
        rb, vb = kb[k]
        if ra != rb and found(ra) != found(rb):
            rerun += 1
            continue
        if "error" in (va[3], vb[3]):
            errors += 1
            continue
        common += 1
        if va[3] != vb[3]:
            flips.append((*k, va[3], vb[3]))
    print("compared", common, "re-run in between (left out)", rerun, "errors", errors, "flips", len(flips),
          dict(collections.Counter((f[3], f[4]) for f in flips)))
    for case, n in sorted(collections.Counter(f[0] for f in flips).items()):
        print(f"  {case}: {n}")
    if out:
        json.dump(flips, open(out, "w"))
    return flips


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[0] == "--compare":
        compare(*args[1:4])
    else:
        opt = lambda name: args[args.index(name) + 1] if name in args else None  # noqa: E731
        rescore(args[0], int(opt("--jobs") or 8), set(opt("--cases").split(",")) if opt("--cases") else None,
                set(json.load(open(opt("--ids")))) if opt("--ids") else None)
