"""Paired before/after between two pool jobs over the same cells (read-only on the store).

    .venv/bin/python tests/study_gap_pairs.py BEFORE_JOB AFTER_JOB [--flips]

Each cell (case, variant, strategy) is the job's own result or the stored row it reused; a cell not run
in either job is "not run" and left out of the pairs. Counts per set (kubernetes 300-305, the
gap cases 104/047/083/011/152, the rest), flips by kind, and with --flips each flipped cell.
Used for the gap form (docs/research/declared-boundary.md, cause 3).
"""
import collections
import json
import os
import sqlite3
import sys

DB = os.path.expanduser("~/.cache/sdlab/ladder/results.sqlite")
GAP = ("104-", "047-", "083-", "011-", "152-")
K8S = tuple(f"{n}-" for n in range(300, 306))


def con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)


def cells(job: int) -> dict:
    c = con()
    out = {}
    q = "SELECT id, case_id, variant, strategy, state, result_id, reused_id, reused_pool_id FROM pool_items WHERE job_id = ?"
    for iid, case, variant, strategy, state, result_id, reused_id, reused_pool_id in c.execute(q, (job,)):
        st = None
        if state == "done" or result_id:
            r = c.execute("SELECT status FROM pool_results WHERE item_id=?", (iid,)).fetchone()
            st = r and r[0]
        if st is None and state == "reused":
            if reused_id:
                r = c.execute("SELECT status FROM results WHERE id=?", (reused_id,)).fetchone()
            elif reused_pool_id:
                r = c.execute("SELECT status FROM pool_results WHERE id=?", (reused_pool_id,)).fetchone()
            else:
                r = None
            st = r and r[0]
        out[(case, variant, strategy)] = st or f"not run: {state}"
    return out


def group(case: str) -> str:
    return "kubernetes" if case.startswith(K8S) else "gap" if case.startswith(GAP) else "tests"


def main():
    a, b = cells(int(sys.argv[1])), cells(int(sys.argv[2]))
    tab = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    flips = collections.defaultdict(collections.Counter)
    listed = []
    unpaired = 0
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k, "not run"), b.get(k, "not run")
        if x.startswith("not run") or y.startswith("not run"):
            unpaired += 1
            continue
        g = group(k[0])
        tab[g][0][x] += 1
        tab[g][1][y] += 1
        if x != y:
            flips[g][f"{x} -> {y}"] += 1
            listed.append((g, *k, x, y))
    print(f"unpaired (not run in one job): {unpaired}")
    for g, (bc, ac) in sorted(tab.items()):
        print(f"\n{g}: {sum(bc.values())} paired cells")
        print("  before", dict(sorted(bc.items())))
        print("  after ", dict(sorted(ac.items())))
        print("  flips ", dict(flips[g].most_common()))
    if "--flips" in sys.argv:
        print()
        for row in listed:
            print(*row)
    if "--json" in sys.argv:
        print(json.dumps(listed))


if __name__ == "__main__":
    main()
