"""Proven equivalence (2026-10-21, the user; docs/LADDER.md "Status"): re-score the stored results of the
numbered ladder cases offline (nothing written to the store), with whichever scorer is importable, then
compare two outputs: pass -> equivalent, equivalent -> fits, equivalent -> pass (the conserving drawing),
fail -> ..., by set and strategy, with examples.

    git archive HEAD sdlab | tar -x -C <old>                          # the scorer before the change
    PYTHONPATH=<old> uv run python tests/study_rescore_algebra.py score old.json --jobs 8
    PYTHONPATH=tests uv run python tests/study_rescore_algebra.py score new.json --jobs 8
    uv run python tests/study_rescore_algebra.py compare old.json new.json

`--where old.json equivalent` grades only the rows that output gave that status (the change acts only
where the older equivalence held, so the other rows cannot change). `score` grades every latest row of a numbered case (id starting with a digit) that is not an error or a
timeout, by score.equations on the stored found flows (behaviour never sets a status). --only-status
equivalent grades only the rows stored with that status (the change cannot move a pass or a fail: it acts
only where the older equivalence held). Output: {row id: [set, case, variant, strategy, status, note]}.
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


def _rows(only: str | None):
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    q = ("SELECT id, case_id, variant, strategy FROM results WHERE latest = 1 AND status NOT IN ('error', 'timeout')"
         " AND substr(case_id, 1, 1) BETWEEN '0' AND '9'" + (" AND status = ?" if only else "") + " ORDER BY case_id, variant")
    return [list(r) for r in con.execute(q, (only,) if only else ())]


def _found(con, rid: int) -> list[dict]:
    (found,) = con.execute("SELECT found FROM results WHERE id = ?", (rid,)).fetchone()
    return json.loads(found or "[]")


def _note(s: dict) -> str:
    for n in s.get("notes") or []:
        if n.startswith(("fits, not proven", "fits, not robust", "equivalent (proven)", "pass by the conserving", "units:")):
            if s.get("algebra", {}).get("conserving"):
                n = "[conserving] " + n
            return n[:400]
    for n in s.get("notes") or []:                             # (study_rescore_hidden.py) a found hidden stock matched
        if " matched to the truth's " in n:
            return n[:400]
    return ""


def _grade(batch: list[list]) -> dict:
    from sdlab.ladder import cases as casemod, data, leaderboard, particles, physics, score, store
    score.behaviour = lambda *a, **k: {}                       # not part of any ladder status
    con = sqlite3.connect(str(store.path()))
    out = {}
    for rid, cid, variant, strat in batch:
        kind = "?"
        began = time.time()
        try:
            c = casemod.load(cid)
            kind = leaderboard.kind_of(c) + ("/particles" if particles.is_particles(c) else "")
            if c.get("real") or particles.is_particles(c) or physics.is_physics(c):
                continue
            flows = _found(con, rid)
            model = casemod.truth_model(c, variant)
            noise = casemod.variant(c, variant)["noise"]
            s = score.equations(c, noise, model, flows, data.load(c, variant))
            out[str(rid)] = [kind, cid, variant, strat, s["status"], _note(s), round(time.time() - began, 3)]
        except Exception as e:                                 # noqa: BLE001
            out[str(rid)] = [kind, cid, variant, strat, f"error: {type(e).__name__}: {e}"[:300], "", round(time.time() - began, 3)]
    return out


def score_all(path: str, jobs: int, limit: int | None = None, only: str | None = None, where: tuple | None = None) -> None:
    rows = _rows(only)
    if where:                                                  # only the rows another output gave this status
        prev = json.load(open(where[0]))
        rows = [r for r in rows if (prev.get(str(r[0])) or [None] * 5)[4] == where[1]]
    rows = rows[:limit] if limit else rows
    batches = [rows[i:i + 20] for i in range(0, len(rows), 20)]
    random.Random(0).shuffle(batches)
    out, began = {}, time.time()
    with ProcessPoolExecutor(jobs, max_tasks_per_child=1) as ex:
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


def compare(old_path: str, new_path: str, examples: int = 3) -> None:
    old, new = json.load(open(old_path)), json.load(open(new_path))
    flips: dict = collections.defaultdict(list)
    per_set: dict = collections.defaultdict(collections.Counter)
    per_strat: dict = collections.defaultdict(collections.Counter)
    same = collections.Counter()
    for rid in sorted(set(old) & set(new), key=int):
        o, n = old[rid], new[rid]
        if o[4] == n[4]:
            same[o[4]] += 1
            continue
        key = f"{o[4]} -> {n[4]}"
        flips[key].append((rid, *n[:4], n[5]))
        per_set[key][n[0]] += 1
        per_strat[key][n[3]] += 1
    print(f"rows compared: {len(set(old) & set(new))} (only old {len(set(old) - set(new))}, only new {len(set(new) - set(old))})")
    print("unchanged:", dict(same))
    for key in sorted(flips, key=lambda k: -len(flips[k])):
        print(f"\n{key}: {len(flips[key])}")
        print("  by set:", dict(per_set[key].most_common()))
        print("  by strategy:", dict(per_strat[key].most_common()))
        cases = collections.Counter(x[2] for x in flips[key])
        print("  top cases:", dict(cases.most_common(12)))
        seen = set()
        for x in flips[key]:
            if x[2] in seen:
                continue
            seen.add(x[2])
            print(f"  e.g. #{x[0]} {x[2]} {x[3]} {x[4]}: {x[5][:300]}")
            if len(seen) >= examples:
                break
    slow = sorted(new.values(), key=lambda r: -r[6])[:5]
    print("\nslowest (new):", [(r[1], r[2], r[3], r[6]) for r in slow])


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "score":
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 1
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        only = sys.argv[sys.argv.index("--only-status") + 1] if "--only-status" in sys.argv else None
        where = tuple(sys.argv[sys.argv.index("--where") + 1:sys.argv.index("--where") + 3]) if "--where" in sys.argv else None
        score_all(sys.argv[2], jobs, limit, only, where)
    elif cmd == "compare":
        compare(sys.argv[2], sys.argv[3], int(sys.argv[sys.argv.index("--examples") + 1]) if "--examples" in sys.argv else 3)
