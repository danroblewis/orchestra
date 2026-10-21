"""Same-pair flows are one flow (2026-10-20, sdlab/ladder/merge.py, docs/LADDER.md "Same-pair flows"):
re-score stored results offline (nothing written to the store) with whichever scorer is importable,
then compare two outputs by set and strategy, with the found model's complexity.

Only a result whose found model has two flows with the same (from, to) can change: for any other the
merge returns the flows unchanged and the scorer runs exactly as before. So `score` grades those rows
only (`--all` grades every row, as a check of that claim). `--numbered` takes the numbered ladder cases
(ids starting with a digit); `--others` the rest (realistic, physics, particles, real), each row in a
subprocess with a time limit (`--timeout`, 60 s), a row over it reported as not re-scored.

    git archive HEAD sdlab | tar -x -C <old>                          # the scorer before the change
    PYTHONPATH=<old>:tests uv run python tests/study_rescore_merge.py score old.json --jobs 4
    PYTHONPATH=tests uv run python tests/study_rescore_merge.py score new.json --jobs 4
    uv run python tests/study_rescore_merge.py compare old.json new.json

Output: {row id: [set, strategy, case, variant, status, found complexity]} (status "error: ..." when
grading raised). Grading is study_rescore_boundary.py's (score.equations without behaviour; a real
case by real/score.py, a physics or particle case by its own scorer).
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


def _has_pair(found: list) -> bool:
    seen = set()
    for f in found if isinstance(found, list) else []:
        k = (f.get("from") or None, f.get("to") or None)
        if k in seen:
            return True
        seen.add(k)
    return False


def _rows(every: bool, which: str = "all") -> list[list]:
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    q = "SELECT id, case_id, variant, strategy, found FROM results WHERE latest = 1 AND status NOT IN ('error', 'timeout') ORDER BY case_id, variant"
    out = []
    for rid, cid, variant, strategy, found in con.execute(q):
        numbered = cid[:1].isdigit()
        if (which == "numbered" and not numbered) or (which == "others" and numbered):
            continue
        if every or _has_pair(json.loads(found or "[]")):
            out.append([rid, cid, variant, strategy])
    return out


def _found(rid: int) -> list[dict]:
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    (found,) = con.execute("SELECT found FROM results WHERE id = ?", (rid,)).fetchone()
    return json.loads(found or "[]")


def _grade(batch: list[list]) -> dict:
    from sdlab.ladder import cases as casemod, complexity, data, leaderboard, particles, physics, score
    from sdlab.ladder.real import data as real_data, score as real_score
    score.behaviour = lambda *a, **k: {}                       # not part of any ladder status
    out = {}
    for rid, cid, variant, strategy in batch:
        kind, cx = "?", None
        try:
            c = casemod.load(cid)
            kind = leaderboard.kind_of(c) + ("/particles" if particles.is_particles(c) else "")
            flows = _found(rid)
            cx = complexity.count(flows, complexity.measured(c))["total"]
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
            out[str(rid)] = [kind, strategy, cid, variant, s["status"], cx]
        except Exception as e:                                 # noqa: BLE001
            out[str(rid)] = [kind, strategy, cid, variant, f"error: {type(e).__name__}: {e}"[:300], cx]
    return out


def _grade_ids(ids: list[str]) -> None:
    """Grade the rows given by id and print the result as JSON (one subprocess per batch: `--others`)."""
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    q = f"SELECT id, case_id, variant, strategy FROM results WHERE id IN ({','.join('?' * len(ids))})"
    print(json.dumps(_grade([list(r) for r in con.execute(q, ids)])))


def _others(rows: list[list], jobs: int, timeout: float) -> dict:
    """The slow sets (realistic, physics, particles, real): each row in a subprocess with a time limit;
    a row over it is "not re-scored (over N s)"."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def one(r):
        try:
            p = subprocess.run([sys.executable, __file__, "grade", str(r[0])], capture_output=True, text=True, timeout=timeout)
            return json.loads(p.stdout.strip().splitlines()[-1])
        except subprocess.TimeoutExpired:
            return {str(r[0]): ["?", r[3], r[1], r[2], f"not re-scored (over {timeout:.0f} s)", None]}
        except Exception as e:                                 # noqa: BLE001
            return {str(r[0]): ["?", r[3], r[1], r[2], f"error: grading subprocess: {e}"[:300], None]}

    out = {}
    with ThreadPoolExecutor(jobs) as ex:
        for i, got in enumerate(ex.map(one, rows), 1):
            out.update(got)
            if i % 100 == 0:
                print(f"{i}/{len(rows)} rows", flush=True)
    return out


def score_all(path: str, jobs: int, every: bool = False, limit: int | None = None, which: str = "all", timeout: float = 60) -> None:
    rows = _rows(every, which)
    rows = rows[:limit] if limit else rows
    out, began = {}, time.time()
    if which == "others":
        out = _others(rows, jobs, timeout)
        with open(path, "w") as fh:
            json.dump(out, fh)
        print(f"{len(out)} rows in {time.time() - began:.0f} s -> {path}")
        return
    batches = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    random.Random(0).shuffle(batches)
    with ProcessPoolExecutor(jobs, max_tasks_per_child=1) as ex:
        futs = [ex.submit(_grade, b) for b in batches]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out.update(f.result())
            except Exception:                                  # noqa: BLE001
                traceback.print_exc()
            if i % 50 == 0:
                print(f"{len(out)}/{len(rows)} rows, {time.time() - began:.0f} s", flush=True)
    with open(path, "w") as fh:
        json.dump(out, fh)
    print(f"{len(out)} rows in {time.time() - began:.0f} s -> {path}")


def compare(old_path: str, new_path: str) -> None:
    old, new = json.load(open(old_path)), json.load(open(new_path))
    per: dict = collections.defaultdict(collections.Counter)
    flips, cx = [], collections.defaultdict(list)
    for rid in sorted(set(old) | set(new), key=int):
        o, n = old.get(rid), new.get(rid)
        if o is None or n is None:
            per[("?", "?")]["missing on one side"] += 1
            continue
        key = (n[0], n[1])
        per[key]["rows"] += 1
        if o[4] != n[4]:
            per[key][f"{o[4]} -> {n[4]}"] += 1
            flips.append((rid, n[0], n[1], n[2], n[3], o[4], n[4]))
        if o[5] is not None and n[5] is not None:
            cx[n[1]].append(n[5] - o[5])
    print("status flips by set and strategy:")
    for key in sorted(per):
        moved = {k: v for k, v in per[key].items() if "->" in k or k.startswith("missing")}
        if moved:
            print(" ", *key, per[key]["rows"], "rows:", moved)
    print(f"flips: {len(flips)}")
    for f in flips:
        print("  ", *f)
    print("found complexity, new - old, by strategy (rows with a same-pair group): n, mean, min, rows changed")
    for s in sorted(cx, key=lambda s: -len(cx[s])):
        d = cx[s]
        print(f"   {s:28s} {len(d):6d} {sum(d) / len(d):+.2f} {min(d):+d} {sum(1 for x in d if x):6d}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "score":
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 1
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        which = "numbered" if "--numbered" in sys.argv else "others" if "--others" in sys.argv else "all"
        timeout = float(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 60.0
        score_all(sys.argv[2], jobs, "--all" in sys.argv, limit, which, timeout)
    elif cmd == "grade":
        _grade_ids(sys.argv[2:])
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3])
