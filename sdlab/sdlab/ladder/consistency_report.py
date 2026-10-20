"""The consistency checks (consistency.py) over stored results: how many passes the data reject, how many
fails they cannot tell from the truth, and the bound's verdicts, per cell. Reads the store; writes nothing.

    uv run python -m sdlab.ladder.consistency_report --cases 300-k8s-requests-in-flight,... [--variants a,b] [--strategies x,y] [--json out.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

from . import cases as casemod
from . import consistency as C
from . import store


def evaluate(case_ids: list[str], variants: list[str] | None = None, strategies: list[str] | None = None) -> list[dict]:
    """One row per stored latest result: {case, variant, strategy, id, status, bound_ok, worst_z, joint_p, kinds,
    lik (verdict), LR, df, p, where (the stock the misfit is worst in and its kinds), why (not covered)}."""
    out = []
    for cid in case_ids:
        case = casemod.load(cid)
        rows = [r for r in store.latest(case=cid) if (not variants or r["variant"] in variants) and (not strategies or r["strategy"] in strategies)]
        by_var = collections.defaultdict(list)
        for r in rows:
            by_var[r["variant"]].append(r)
        for var, rs in sorted(by_var.items()):
            try:
                cell = C.Cell(case, var)
            except Exception as e:  # noqa: BLE001 - a cell that cannot be built is reported, not skipped silently
                out += [{"case": cid, "variant": var, "strategy": r["strategy"], "id": r["id"], "status": r["status"], "why": f"cell: {e!r}"[:200]} for r in rs]
                continue
            for r in rs:
                row = {"case": cid, "variant": var, "strategy": r["strategy"], "id": r["id"], "status": r["status"]}
                found = (store.get(r["id"]) or {}).get("found")
                if found is None:
                    row["why"] = "no found model stored (error or timeout)"
                    out.append(row)
                    continue
                try:
                    res = C.check(case, var, found, cell=cell)
                except Exception as e:  # noqa: BLE001
                    row["why"] = f"check: {e!r}"[:200]
                    out.append(row)
                    continue
                if not res["covered"]:
                    row["why"] = res["why"]
                b, lk = res["bound"], res["likelihood"]
                if b:
                    row.update(bound_ok=b["ok"], worst_z=b["worst_z"], joint_p=(b.get("joint") or {}).get("p"), kinds=b["kinds"],
                               entries_ok=(b["entries"] or {}).get("ok"))
                if lk:
                    if lk["covered"]:
                        w = (lk.get("where") or [None])[0]
                        row.update(lik=lk["verdict"], LR=lk["LR"], LR_truth=lk["LR_truth"], df=lk["df"], p=lk["p"], extra=lk["numbers"]["extra"],
                                   where=(w and {"stock": w["stock"], "loss": w["loss"], "kinds": w["kinds"]}))
                    else:
                        row["lik"] = "not covered: " + lk["why"]
                out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    """Counts per (case, variant): status x bound, status x likelihood verdict."""
    out: dict = {}
    for r in rows:
        c = out.setdefault(f"{r['case'][:3]} {r['variant']}", collections.Counter())
        st = r["status"]
        c[f"{st}"] += 1
        if "bound_ok" in r:
            c[f"{st}, bound {'ok' if r['bound_ok'] else 'outside'}"] += 1
        lik = r.get("lik")
        if lik:
            short = "rejected" if lik.startswith("the data reject") else "better than truth" if lik.startswith("the found model fits better") \
                else "cannot tell" if lik.startswith("the data cannot") else "not covered"
            c[f"{st}, likelihood {short}"] += 1
        elif r.get("why"):
            c[f"{st}, not covered"] += 1
    return {k: dict(v) for k, v in out.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", required=True)
    ap.add_argument("--variants")
    ap.add_argument("--strategies")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    sp = lambda x: [s for s in x.split(",") if s] if x else None  # noqa: E731
    rows = evaluate(sp(a.cases), sp(a.variants), sp(a.strategies))
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rows, f, indent=1, default=str)
    json.dump(summary(rows), sys.stdout, indent=1)
    print()
    for r in rows:
        lik = r.get("lik") or ""
        if (r["status"] == "pass" and lik.startswith("the data reject")) or (r["status"] != "pass" and lik.startswith("the data cannot")) \
                or (r["status"] == "pass" and r.get("bound_ok") is False):
            print(f"{r['case'][:3]} {r['variant']:13s} {r['strategy']:24s} {r['status']:10s} bound {'ok' if r.get('bound_ok') else 'outside'} "
                  f"z {r.get('worst_z') or 0:.1f} jointp {r.get('joint_p')} | LR {r.get('LR') or 0:.1f} df {r.get('df')} p {r.get('p')} "
                  f"{lik[:40]} | {r.get('kinds')} | {r.get('where')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
