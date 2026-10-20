"""The scoring changes of 19 October 2026, second round (docs/LADDER.md): re-score the stored results each
change can touch, offline (nothing written to the store), with whichever scorer is importable, then compare
two outputs. tests/study_rescore.py is the first round's (equations of every row); this one also grades
behaviour and physics.

    uv run python tests/study_rescore_1019.py select ids.json             # the rows each change can touch (new code)
    PYTHONPATH=<old sdlab copy> uv run python tests/study_rescore_1019.py score ids.json old.json --jobs 8
    uv run python tests/study_rescore_1019.py score ids.json new.json --jobs 8
    uv run python tests/study_rescore_1019.py compare ids.json old.json new.json

Rows per change (`select`):
  1 swap      behaviour: the truth's swapped inflows or the found model's swapped part differ between the
              old rule (every constant outside inflow) and the new (only exogenous ones; a found c + k x
              loses its c)
  3 signed    behaviour (and a physics case's grade): the found model has a two-way flow or a signed stock
  4 smooth    equations: the truth or the found model has a rate reading a smoothing
  2 physics   every physics row (structure against the reference for the thermostat)
`score` grades each selected row: equations status (score.equations, or the physics score's), and skill@20
and @100 in sample and fresh (inferred levels are not stored: both sides start found hidden stocks from the
observer). A realistic run "meets the goal" at skill@20 >= 90% and skill@100 >= 80% (in sample).
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


def _rows():
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    q = "SELECT id, case_id, variant, strategy, status, found FROM results WHERE latest = 1 AND status NOT IN ('error', 'timeout')"
    for rid, case, variant, strategy, status, found in con.execute(q):
        yield rid, case, variant, strategy, status, json.loads(found or "[]")


def _old_own(flows, fed):
    return [f for f in flows if not (not f.get("from") and f.get("to") in fed and not f.get("driver") and (f.get("rate") or {}).get("form") == "constant")]


def select(out_path: str) -> None:
    from sdlab import skill
    from sdlab.ladder import cases as casemod, physics, particles
    from sdlab.ladder.parts import _smoothings
    from sdlab.ladder.sim import says_signed
    per_case: dict = {}
    picked = {"swap": [], "signed": [], "smooth": [], "physics": []}
    for rid, case, variant, strategy, status, flows in _rows():
        if case not in per_case:
            try:
                c = casemod.load(case)
                m = casemod.truth_model(c, c["variants"][0]["name"])
                measured = {s["id"] for s in m["stocks"] if s.get("measured", True)}
                inputs = set(m.get("inputs") or {})
                old_fed = {f["to"] for f in m["flows"] if not f.get("from") and f.get("to") and (f.get("rate") or {}).get("form") == "constant"}
                _, new_fed = skill.truth_by_time(m, [1, 2])
                old_exo = sorted(f["id"] for f in m["flows"] if not f.get("from") and f.get("to") in old_fed)
                new_exo = sorted(f["id"] for f in m["flows"] if not f.get("from") and f.get("to") in new_fed
                                 and not any(f.get(k) for k in skill._READERS))
                per_case[case] = {"phys": physics.is_physics(c) and not particles.is_particles(c), "real": bool(c.get("real")),
                                  "old_fed": old_fed, "new_fed": new_fed, "exo_differs": old_exo != new_exo,
                                  "smooth": bool(_smoothings(m["flows"], measured, inputs, (1, 1))[0]), "measured": measured, "inputs": inputs}
            except Exception:  # noqa: BLE001
                per_case[case] = None
        pc = per_case[case]
        if pc is None:
            continue
        if pc["phys"]:
            picked["physics"].append(rid)
            if says_signed(flows):
                picked["signed"].append(rid)
            continue
        if pc["exo_differs"] or _old_own(flows, pc["old_fed"]) != skill.own_flows(flows, pc["new_fed"]):
            picked["swap"].append(rid)
        if says_signed(flows):
            picked["signed"].append(rid)
        try:
            if pc["smooth"] or _smoothings(flows, pc["measured"], pc["inputs"], (1, 1))[0]:
                picked["smooth"].append(rid)
        except Exception:  # noqa: BLE001
            picked["smooth"].append(rid)
    json.dump(picked, open(out_path, "w"))
    print({k: len(v) for k, v in picked.items()}, file=sys.stderr)


def _cell(job):
    (cid, variant), rows = job
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data, particles, physics, score
    from sdlab.ladder.real import data as real_data
    out = {}
    try:
        c = casemod.load(cid)
        is_phys = physics.is_physics(c) and not particles.is_particles(c)
        if c.get("real") and variant != "twin":
            return {r: None for r, _ in rows}
        noise = "counts" if c.get("real") or particles.is_particles(c) else casemod.variant(c, variant)["noise"]
        model = casemod.truth_model(c, variant)
        d = real_data.load(c, variant) if c.get("real") else data.load(c, variant)
        fresh = real_data.load(c, variant, full=True) if c.get("real") else data.load(c, variant, fresh=True)
    except Exception as e:  # noqa: BLE001
        return {r: {"error": f"cell: {type(e).__name__}: {e}"} for r, _ in rows}
    for rid, (flows, what) in rows:
        try:
            res = {}
            if is_phys:
                s = physics.score_found(c, variant, flows, d, fresh)
                res["status"] = s["status"]
                res["structure_ok"] = s["physics"]["structure_ok"]
                b = s["behaviour"]
            else:
                if "smooth" in what:
                    res["status"] = score.equations(c, noise, model, flows, d)["status"]
                b = score.behaviour(model, flows, d.get("clean") or d, (fresh.get("clean") or fresh), None) if what & {"swap", "signed"} else {}
            res["skill"] = {f"{w}{h}": ((b.get(w) or {}).get(h) or {}).get("skill") for w in ("in_sample", "fresh") for h in ("20", "100")}
            out[rid] = res
        except Exception:  # noqa: BLE001
            out[rid] = {"error": " ".join(traceback.format_exc().strip().splitlines()[-2:])[:300]}
    return out


def score_rows(ids_path: str, out_path: str, jobs: int) -> None:
    picked = json.load(open(ids_path))
    what: dict = collections.defaultdict(set)
    for k, ids in picked.items():
        for r in ids:
            what[r].add(k)
    cells: dict = {}
    meta = {}
    for rid, case, variant, strategy, status, flows in _rows():
        if rid in what:
            cells.setdefault((case, variant), []).append((rid, (flows, what[rid])))
            meta[rid] = [case, variant, strategy, status, sorted(what[rid])]
    work = sorted(((k, v[i:i + 20]) for k, v in cells.items() for i in range(0, len(v), 20)), key=lambda j: -len(j[1]))
    res, t0 = {}, time.time()
    with ProcessPoolExecutor(jobs) as ex:
        for n, f in enumerate(as_completed([ex.submit(_cell, j) for j in work])):
            for rid, v in f.result().items():
                if v is not None:
                    res[rid] = meta[rid] + [v]
            if n % 50 == 0:
                print(f"{n}/{len(work)} cells, {len(res)} rows, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    json.dump(res, open(out_path, "w"))
    print("done", len(res), f"{time.time() - t0:.0f}s", file=sys.stderr)


def _meets(sk):
    a, b = sk.get("in_sample20"), sk.get("in_sample100")
    return a is not None and b is not None and a >= 0.9 and b >= 0.8


def compare(ids_path: str, pa: str, pb: str) -> None:
    a, b = json.load(open(pa)), json.load(open(pb))
    picked = json.load(open(ids_path))
    for change, ids in picked.items():
        ids = [str(r) for r in ids]
        both = [r for r in ids if r in a and r in b and "error" not in a[r][5] and "error" not in b[r][5]]
        errs = [r for r in ids if r in a and r in b and ("error" in a[r][5] or "error" in b[r][5])]
        flips = [(a[r][0], a[r][1], a[r][2], a[r][5].get("status"), b[r][5].get("status")) for r in both
                 if a[r][5].get("status") != b[r][5].get("status")]
        print(f"== change {change}: {len(ids)} rows selected, {len(both)} compared, {len(errs)} errors"
              f" (old {sum('error' in a[r][5] for r in errs if r in a)}, new {sum('error' in b[r][5] for r in errs if r in b)})")
        print("  status flips", len(flips), dict(collections.Counter((f[3], f[4]) for f in flips)))
        for f in sorted(flips)[:40]:
            print("   ", *f)
        if change in ("swap", "signed"):
            moved = [(a[r][0], a[r][1], a[r][2], a[r][5]["skill"].get("in_sample20"), b[r][5]["skill"].get("in_sample20"),
                      a[r][5]["skill"].get("fresh20"), b[r][5]["skill"].get("fresh20")) for r in both]
            ch = [m for m in moved if m[3] is not None and m[4] is not None and abs(m[4] - m[3]) > 0.01]
            up = sum(m[4] > m[3] for m in ch)
            print(f"  skill@20 in sample moved > 1 point: {len(ch)} ({up} up, {len(ch) - up} down)")
            real = [r for r in both if a[r][0].startswith("sd-")]
            goal = [(a[r][0], a[r][1], a[r][2], _meets(a[r][5]["skill"]), _meets(b[r][5]["skill"])) for r in real]
            gf = [g for g in goal if g[3] != g[4]]
            print(f"  realistic runs: {len(real)}; meets-goal flips {len(gf)}", dict(collections.Counter((g[3], g[4]) for g in gf)))
            for g in gf[:20]:
                print("   ", *g)
            by_case = collections.defaultdict(list)
            for m in ch:
                by_case[m[0]].append(m[4] - m[3])
            for case, ds in sorted(by_case.items()):
                print(f"    {case}: {len(ds)} runs, mean change {sum(ds) / len(ds):+.3f}, min {min(ds):+.3f}, max {max(ds):+.3f}")
        if change == "physics":
            sf = [(a[r][0], a[r][1], a[r][2], a[r][5].get("structure_ok"), b[r][5].get("structure_ok")) for r in both
                  if a[r][5].get("structure_ok") != b[r][5].get("structure_ok")]
            print("  structure flips", len(sf), dict(collections.Counter((f[3], f[4]) for f in sf)))


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda name: args[args.index(name) + 1] if name in args else None  # noqa: E731
    if args[0] == "select":
        select(args[1])
    elif args[0] == "score":
        score_rows(args[1], args[2], int(opt("--jobs") or 8))
    else:
        compare(*args[1:4])
