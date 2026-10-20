"""The harness side of the NO-TRUTH checks (notruth.py): it builds the discovery view of a ladder cell
(exactly as runner.discover does) and reads the stored found models, then hands only the view and flows
to the checks. Stored statuses are read for the report only (to see whether the evidence agrees with the
truth's verdict); they never reach a check.

    uv run python -m sdlab.ladder.notruth_run --cases 300,301 --variants counts-short --strategies lna,combined [--jobs 2] [--out f.json]
    uv run python -m sdlab.ladder.notruth_run --cases 007,011 --strategies sample:4    # 4 passing + 4 failing distinct models a cell

No score, status or store row changes. Results go to stdout (and --out).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")


def view(case_id: str, variant: str) -> dict:
    """The discovery view of a cell (runner.discover's opts and run, as one dict)."""
    from . import cases as casemod
    from . import data
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    v = {"stocks": casemod.page_stocks(model), "t": d["t"], "levels": d["levels"]}
    if len(d.get("eras") or []) > 1:
        v["eras"] = d["eras"]
    if d.get("injections"):
        v["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
    if d.get("inputs"):
        v["inputs"] = {k: list(x) for k, x in d["inputs"].items()}
    return v


def resolve(case_id: str) -> str:
    """A case id from its full id or its number prefix ("300")."""
    from .cases import case_ids
    ids = case_ids()
    if case_id in ids:
        return case_id
    hit = [c for c in ids if c.startswith(case_id + "-")]
    if len(hit) != 1:
        raise KeyError(f"no single case for {case_id!r}: {hit[:5]}")
    return hit[0]


def stored(case_id: str, variant: str) -> dict[str, dict]:
    """{strategy: {"flows", "status"}} for the cell's latest stored results with a model."""
    from . import store
    out = {}
    for r in store.latest(case_id, variant, found=True):
        if r.get("status") in ("error", "timeout") or not r.get("found"):
            continue
        out[r["strategy"]] = {"flows": r["found"], "status": r["status"]}
    return out


def one(case_id: str, variant: str, strategy: str, checks: tuple, max_others: int = 12) -> dict:
    from .notruth import evidence
    cid = resolve(case_id)
    rows = stored(cid, variant)
    if strategy not in rows:
        return {"case": cid, "variant": variant, "strategy": strategy, "error": "no stored model"}
    others = {k: v["flows"] for k, v in sorted(rows.items()) if k != strategy}
    others = dict(list(others.items())[:max_others])
    began = time.perf_counter()
    ev = evidence(view(cid, variant), rows[strategy]["flows"], others, checks=checks)
    return {"case": cid, "variant": variant, "strategy": strategy, "status": rows[strategy]["status"],
            "seconds": round(time.perf_counter() - began, 2), **ev}


GOOD = ("pass", "equivalent")


def sample(case_id: str, variant: str, n: int) -> list[str]:
    """Up to n strategies whose stored model passes (or is equivalent) and n whose model fails, distinct
    models only (identical flows evaluated once), in name order: for the report's comparison only."""
    rows = stored(resolve(case_id), variant)
    seen, good, bad = set(), [], []
    for k in sorted(rows):
        key = json.dumps(rows[k]["flows"], sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        (good if rows[k]["status"] in GOOD else bad).append(k)
    return good[:n] + bad[:n]


def summary(res: list[dict]) -> str:
    """Per check: verdict counts among models the scorer passes (or calls equivalent) and among those it fails."""
    out = []
    checks = sorted({k for r in res if not r.get("error") for k in r["checks"]})
    for ch in checks:
        out.append(f"{ch}:")
        for side, test in (("scorer pass/equivalent", lambda st: st in GOOD), ("scorer fail", lambda st: st not in GOOD)):
            rs = [r for r in res if not r.get("error") and ch in r["checks"] and test(r["status"])]
            cnt = {}
            for r in rs:
                v = r["checks"][ch]["verdict"]
                cnt[v] = cnt.get(v, 0) + 1
            out.append(f"  {side:24} n={len(rs):3} " + " ".join(f"{k}={cnt[k]}" for k in sorted(cnt)))
    sc = [(r["status"] in GOOD, r["score"]) for r in res if not r.get("error") and r.get("score") is not None]
    for side in (True, False):
        xs = [x for g, x in sc if g == side]
        if xs:
            out.append(f"evidence score, scorer {'pass/equivalent' if side else 'fail'}: mean {sum(xs) / len(xs):.2f} over {len(xs)}")
    return "\n".join(out)


def _one(args):
    try:
        return one(*args)
    except Exception as e:                                   # noqa: BLE001
        return {"case": args[0], "variant": args[1], "strategy": args[2], "error": f"{type(e).__name__}: {e}"[:300]}


def line(r: dict) -> str:
    if r.get("error"):
        return f"{r['case'][:28]:28} {r['variant']:13} {r['strategy']:16} ERROR {r['error'][:80]}"
    ch = r["checks"]
    v = " ".join(f"{k[:5]}={ch[k]['verdict'][:6]:6}" for k in ch)
    sc = "-" if r["score"] is None else f"{r['score']:.2f}"
    return f"{r['case'][:28]:28} {r['variant']:13} {r['strategy']:16} {r['status'] or '-':12} {v} score={sc} {r['seconds']}s"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="notruth_run")
    p.add_argument("--cases", required=True)
    p.add_argument("--variants", default="counts-short")
    p.add_argument("--strategies", required=True)
    p.add_argument("--checks", default="residuals,invariance,heldout,agreement")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--max-others", type=int, default=12)
    p.add_argument("--out")
    a = p.parse_args(argv)
    jobs = max(1, min(3, a.jobs))
    items = []
    for c in a.cases.split(","):
        for v in a.variants.split(","):
            strats = sample(c, v, int(a.strategies.split(":")[1])) if a.strategies.startswith("sample:") else a.strategies.split(",")
            items += [(c, v, s, tuple(a.checks.split(",")), a.max_others) for s in strats]
    res = []
    if jobs == 1:
        for it in items:
            res.append(_one(it))
            print(line(res[-1]), flush=True)
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as ex:
            for r in ex.map(_one, items):
                res.append(r)
                print(line(r), flush=True)
    print(summary(res))
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1, default=float)
    return 0


if __name__ == "__main__":
    sys.exit(main())
