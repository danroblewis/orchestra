"""The boundary kind "input" and one outside flow per declared side (2026-10-21, docs/LADDER.md "The
boundary"): re-score stored results of the numbered ladder cases offline (nothing written to the store)
with whichever scorer and case files are importable, then compare. The change touches score.py and the
case files (36 sides "measured" -> "input"), so the old side is graded from an export of the commit
before it.

    uv run python tests/study_rescore_input.py rows rows.json                  # freeze the row ids first
    git archive <before> sdlab | tar -x -C <old>
    (cd <old>/sdlab && PYTHONPATH=<this>/tests:. <this>/.venv/bin/python <this>/tests/study_rescore_input.py score rows.json old.json --jobs 4)
    PYTHONPATH=tests uv run python tests/study_rescore_input.py score rows.json new.json --jobs 4
    uv run python tests/study_rescore_input.py compare rows.json old.json new.json

Rows: every latest stored row of a numbered case (an id starting with a digit) that is not an error or
timeout, graded by score.equations as runner.run_item grades it (behaviour left out). Output: {row id:
status} ("error: ..." when grading raised). compare prints the flips by set and by strategy.
"""

from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"


def rows(path: str) -> None:
    from sdlab.ladder import cases as casemod, leaderboard, store
    con = sqlite3.connect(str(store.path()))
    q = "SELECT id, case_id, variant, strategy FROM results WHERE latest = 1 AND status NOT IN ('error', 'timeout')"
    out, kinds = [], {}
    for rid, cid, variant, strategy in con.execute(q):
        if not cid[:1].isdigit():
            continue
        if cid not in kinds:
            try:
                kinds[cid] = leaderboard.kind_of(casemod.load(cid))
            except Exception:                                  # noqa: BLE001  (a case no longer loadable)
                kinds[cid] = None
        if kinds[cid]:
            out.append([rid, cid, variant, strategy, kinds[cid]])
    json.dump(out, open(path, "w"))
    print(f"{len(out)} rows -> {path}")


def _grade(batch: list[list]) -> dict:
    from sdlab.ladder import cases as casemod, data, score, store
    score.behaviour = lambda *a, **k: {}
    con = sqlite3.connect(str(store.path()))
    out = {}
    for rid, cid, variant, _, _ in batch:
        try:
            c = casemod.load(cid)
            (found,) = con.execute("SELECT found FROM results WHERE id = ?", (rid,)).fetchone()
            model = casemod.truth_model(c, variant)
            s = score.equations(c, casemod.variant(c, variant)["noise"], model, json.loads(found or "[]"), data.load(c, variant))
            out[str(rid)] = s["status"] + ("" if not any(n.startswith("input altered") for n in s["notes"]) else " (input altered)") \
                + ("" if not any("one flow per declared side" in n for n in s["notes"]) else " (second outside flow)")
        except Exception as e:                                 # noqa: BLE001
            out[str(rid)] = f"error: {type(e).__name__}: {e}"[:300]
    return out


def score_all(rows_path: str, path: str, jobs: int) -> None:
    rs = json.load(open(rows_path))
    rs.sort(key=lambda r: (r[1], r[2]))
    batches = [rs[i:i + 50] for i in range(0, len(rs), 50)]
    out, began = {}, time.time()
    with ProcessPoolExecutor(jobs) as ex:
        for i, f in enumerate(as_completed([ex.submit(_grade, b) for b in batches]), 1):
            out.update(f.result())
            if i % 50 == 0:
                print(f"{len(out)}/{len(rs)} rows, {time.time() - began:.0f} s", flush=True)
    json.dump(out, open(path, "w"))
    print(f"{len(out)} rows in {time.time() - began:.0f} s -> {path}")


def compare(rows_path: str, old_path: str, new_path: str) -> None:
    rs = {str(r[0]): r for r in json.load(open(rows_path))}
    old, new = json.load(open(old_path)), json.load(open(new_path))
    per_set: dict = collections.defaultdict(collections.Counter)
    per_strategy: dict = collections.defaultdict(collections.Counter)
    per_case: dict = collections.defaultdict(collections.Counter)
    base = lambda s: s.split(" (")[0]  # noqa: E731
    for rid, (_, cid, variant, strategy, kind) in rs.items():
        o, n = old.get(rid), new.get(rid)
        per_set[kind]["rows"] += 1
        if o is None or n is None:
            per_set[kind]["missing"] += 1
            continue
        per_set[kind][f"old {base(o)}"] += 1
        per_set[kind][f"new {base(n)}"] += 1
        if base(o) != base(n):
            key = f"{base(o)} -> {n}"
            per_set[kind][key] += 1
            per_strategy[strategy][key] += 1
            per_case[cid.split("#")[0]][key] += 1
    for title, d in (("by set", per_set), ("by strategy", per_strategy), ("by case", per_case)):
        print(f"== {title}")
        for k in sorted(d):
            print(f"  {k}: {dict(sorted(d[k].items()))}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "rows":
        rows(sys.argv[2])
    elif cmd == "score":
        score_all(sys.argv[2], sys.argv[3], int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 1)
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3], sys.argv[4])
