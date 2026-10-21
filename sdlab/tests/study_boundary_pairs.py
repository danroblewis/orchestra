"""Paired before/after for the declared boundary (read-only on the store).

Run with the HEAD export first on the path:
    PYTHONPATH=<export of the commit>/sdlab .venv/bin/python tests/study_boundary_pairs.py before JOB OUT.json   # re-grade pre-change rows
    PYTHONPATH=<export of the commit>/sdlab .venv/bin/python tests/study_boundary_pairs.py report JOB BEFORE.json

before: every item of pool job JOB (its cells and the hashes HEAD promises) -> the latest stored row with
at < CUTOFF (the commit that made cases declare their boundary), its stored status, and its found flows
re-graded by HEAD's scorer against the declared boundary (status, invented-boundary count).
report: the after side is the job's own result, or the stored row it reused; pairs and counts per set.
"""
import collections
import json
import os
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"
CUTOFF = "2026-10-21T00:06:09"          # 9827eaa, cases declare their boundary (2026-10-20T17:06:09-07:00)
DB = os.path.expanduser("~/.cache/sdlab/ladder/results.sqlite")


def con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)


def items(job):
    q = "SELECT id, case_id, variant, strategy, state, result_id, reused_id, reused_pool_id, error FROM pool_items WHERE job_id = ?"
    return [dict(zip(("id", "case", "variant", "strategy", "state", "result_id", "reused_id", "reused_pool_id", "error"), r))
            for r in con().execute(q, (job,))]


def _grade(batch):
    from sdlab.ladder import cases as casemod, data, score
    score.behaviour = lambda *a, **k: {}
    out = {}
    for key, found in batch:
        cid, variant, _ = key.split("|")
        try:
            c = casemod.load(cid)
            s = score.equations(c, casemod.variant(c, variant)["noise"], casemod.truth_model(c, variant), found, data.load(c, variant))
            out[key] = [s["status"], s.get("invented_boundary", 0)]
        except Exception as e:  # noqa: BLE001
            out[key] = [f"error: {type(e).__name__}: {e}"[:200], None]
    return out


def before(job, path, jobs=4):
    c = con()
    rows, todo = {}, []
    for it in items(job):
        key = f"{it['case']}|{it['variant']}|{it['strategy']}"
        r = c.execute("SELECT id, status, found, at, code_commit FROM results WHERE case_id=? AND variant=? AND strategy=? AND at < ? "
                      "ORDER BY at DESC, id DESC LIMIT 1", (it["case"], it["variant"], it["strategy"], CUTOFF)).fetchone()
        if r is None:
            rows[key] = None
            continue
        rows[key] = {"id": r[0], "status": r[1], "at": r[3], "commit": r[4]}
        if r[1] not in ("error", "timeout"):
            todo.append((key, json.loads(r[2] or "[]")))
    batches = [todo[i:i + 25] for i in range(0, len(todo), 25)]
    with ProcessPoolExecutor(jobs) as ex:
        for res in ex.map(_grade, batches):
            for k, v in res.items():
                rows[k]["regraded"], rows[k]["invented"] = v
    json.dump(rows, open(path, "w"))
    print(len(rows), "cells;", sum(v is None for v in rows.values()), "with no stored row before", CUTOFF)


def after_of(it, c):
    if it["state"] == "done" or it["result_id"]:
        r = c.execute("SELECT status, row FROM pool_results WHERE item_id=?", (it["id"],)).fetchone()
        if r:
            sc = (json.loads(r[1]).get("scores") or {})
            return r[0], sc.get("invented_boundary", 0)
    if it["state"] == "reused":
        if it["reused_id"]:
            r = c.execute("SELECT status, scores FROM results WHERE id=?", (it["reused_id"],)).fetchone()
            if r:
                return r[0], (json.loads(r[1] or "{}") or {}).get("invented_boundary", 0)
        if it["reused_pool_id"]:
            r = c.execute("SELECT status, row FROM pool_results WHERE id=?", (it["reused_pool_id"],)).fetchone()
            if r:
                return r[0], (json.loads(r[1]).get("scores") or {}).get("invented_boundary", 0)
    return "not run: " + it["state"], None


def report(job, bpath):
    from sdlab.ladder import cases as casemod
    b = json.load(open(bpath))
    c = con()
    cnt = collections.Counter()
    tab = collections.defaultdict(collections.Counter)
    flips = []
    for it in items(job):
        key = f"{it['case']}|{it['variant']}|{it['strategy']}"
        bs = b.get(key)
        a, ainv = after_of(it, c)
        bst = bs["status"] if bs else "not run"
        tab["before"][bst] += 1
        tab["after"][a] += 1
        if ainv:
            cnt["after: invented boundary"] += 1
        if bs and bs.get("invented"):
            cnt["before: contained invented outside flows"] += 1
            if bst != "pass":
                cnt["before: failing (not pass) with invented flows"] += 1
                if a == "pass":
                    cnt["  ... now pass"] += 1
                elif a == "equivalent":
                    cnt["  ... now equivalent"] += 1
        if bs and bs.get("regraded") and bs["regraded"].startswith("fail") and bs.get("invented"):
            cnt["before regraded by HEAD scorer: fail for invented boundary"] += 1
        if bst != "not run" and not a.startswith("not run") and bst != a:
            flips.append((bst, a, it["strategy"], it["case"], it["variant"], bool(bs.get("invented"))))
    print("before:", dict(tab["before"]))
    print("after: ", dict(tab["after"]))
    for k, v in cnt.items():
        print(f"{k}: {v}")
    rank = {"pass": 0, "equivalent": 1, "fail": 2, "timeout": 3, "error": 3}
    paired = [f for f in flips]
    print("flips (before -> after):", collections.Counter((f[0], f[1]) for f in paired))
    worse = [f for f in paired if rank.get(f[1], 9) > rank.get(f[0], 9)]
    print("regressions by strategy:", collections.Counter(f[2] for f in worse).most_common())
    print("regressions by case:", collections.Counter(f[3] for f in worse).most_common(15))
    json.dump(paired, open(bpath.replace(".json", ".flips.json"), "w"))
    for f in sorted(worse, key=lambda f: (f[3], f[2]))[:400]:
        print("  REG", *f)


if __name__ == "__main__":
    cmd, job = sys.argv[1], int(sys.argv[2])
    if cmd == "before":
        before(job, sys.argv[3])
    else:
        report(job, sys.argv[3])
