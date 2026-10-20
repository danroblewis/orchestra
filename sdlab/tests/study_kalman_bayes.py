"""Study (not a test): kalman_bayes against kalman_lna on the cells both have, paired, from the result
store; and whether the posterior explains the borderline numbers (docs/research/kalman_bayes.md).

    uv run python tests/study_kalman_bayes.py [--cases SPEC] [--json OUT]

For every true number part of every kalman_bayes cell (the scorer's parts, its latest stored flows):
the posterior median's error against the scorer's allowed error, the 95% interval (each number's
2.5% and 97.5% posterior quantiles written into the flows, scored as flows), and the posterior sd.
A part's interval and sd are read by scoring the flows with every number set to its quantile (or sd):
a part that sums several numbers gets the sum, so its interval and sd are upper bounds.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from collections import Counter

import numpy as np

from sdlab.discovery.strategies.kalman_bayes.eiv import slots
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score, store


def _with(flows: list[dict], what: str) -> list[dict]:
    out = copy.deepcopy(flows)
    for d, k in slots(out):
        p = d.get(f"{k}_post")
        d[k] = float(p[what]) if p else (0.0 if what == "sd" else d[k])
    return out


def _allowed(row: dict, s: dict, means: dict) -> float:
    tol, scale = s["tolerance"], s["scale"]
    reader = row["key"].split("[")[-1].rstrip("]") if "[" in row["key"] else None
    level = 1.0 if reader in (None, "const", "1") else max(1e-9, means.get(reader, 0.0))
    se = row.get("se") if isinstance(row.get("se"), (int, float)) and math.isfinite(row.get("se") or math.nan) else 0.0
    return max(tol["rel"] * abs(row["true"]), tol["floor"] * scale / level, tol["z"] * se)


def parts(case: str, variant: str, flows: list[dict]) -> list[dict]:
    c = casemod.load(case)
    noise = casemod.variant(c, variant)["noise"]
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    if c.get("real"):
        return []
    lv = d.get("all_levels") or d["levels"]
    means = {s: float(np.mean(v)) for s, v in lv.items()}
    means.update({k: float(np.mean(v)) for k, v in (d.get("inputs") or {}).items()})
    sc = {w: score.equations(c, noise, model, _with(flows, w) if w != "median" else flows, d) for w in ("median", "lo", "hi", "sd")}
    by = {w: {r["key"]: r for r in sc[w]["parts"]} for w in sc}
    out = []
    for r in sc["median"]["parts"]:
        if not r.get("found") or not isinstance(r.get("true"), (int, float)) or not isinstance(r.get("found_value"), (int, float)):
            continue
        if r.get("compared"):                                    # compared as a whole flow: no single number
            continue
        lo, hi, sd = (by[w].get(r["key"], {}).get("found_value") for w in ("lo", "hi", "sd"))
        if lo is None or hi is None or sd is None:
            continue
        lo, hi = min(lo, hi), max(lo, hi)
        allowed = _allowed(r, sc["median"], means)
        out.append({"case": case, "variant": variant, "key": r["key"], "true": r["true"], "median": r["found_value"], "ok": r["ok"],
                    "err": abs(r["found_value"] - r["true"]), "allowed": allowed, "lo": lo, "hi": hi, "sd": abs(sd),
                    "inside": lo <= r["true"] <= hi, "status": sc["median"]["status"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    want = set(runner.select_cases(a.cases)) if a.cases else None
    mine = {(r["case"], r["variant"]): r for r in store.latest(strategy="kalman_bayes", found=True) if not want or r["case"] in want}
    base = {(r["case"], r["variant"]): r for r in store.latest(strategy="kalman_lna") if (r["case"], r["variant"]) in mine}
    good = {"pass"}
    flips = Counter()
    lines = []
    for k, r in sorted(mine.items()):
        b = base.get(k)
        bs = b["status"] if b else "not run"
        flips[(bs, r["status"])] += 1
        if bs != r["status"]:
            lines.append(f"  {k[0]} {k[1]}: {bs} -> {r['status']}")
    print(f"cells: {len(mine)} (kalman_lna has {len(base)})")
    for (x, y), n in sorted(flips.items(), key=lambda kv: -kv[1]):
        print(f"  {x:>11} -> {y:<11} {n}")
    up = sum(n for (x, y), n in flips.items() if x not in good and y in good)
    down = sum(n for (x, y), n in flips.items() if x in good and y not in good)
    print(f"pass gained {up}, lost {down}")
    print("\n".join(lines))
    sec = [(r.get("seconds"), base[k].get("seconds")) for k, r in mine.items() if k in base and r.get("seconds") and base[k].get("seconds")]
    if sec:
        s1, s0 = np.array(sec).T
        print(f"seconds: kalman_bayes median {np.median(s1):.1f} p90 {np.percentile(s1, 90):.1f} max {s1.max():.1f} total {s1.sum():.0f}; "
              f"kalman_lna median {np.median(s0):.1f} p90 {np.percentile(s0, 90):.1f} max {s0.max():.1f} total {s0.sum():.0f}; "
              f"ratio median {np.median(s1 / s0):.1f}")
    print("timeouts/errors:", Counter(r["status"] for r in mine.values() if r["status"] in ("timeout", "error")))
    rows = []
    for (case, variant), r in sorted(mine.items()):
        if r["status"] in ("timeout", "error") or not r.get("found"):
            continue
        try:
            rows += parts(case, variant, r["found"])
        except Exception as e:                                   # noqa: BLE001
            print(f"  {case} {variant}: {type(e).__name__}: {e}"[:200])
    post = [x for x in rows if x["sd"] > 0]
    print(f"\nnumber parts with a posterior: {len(post)} (of {len(rows)})")
    if post:
        cov = np.mean([x["inside"] for x in post])
        print(f"truth inside the 95% interval: {cov:.3f}")
        miss = [x for x in post if not x["ok"]]
        print(f"parts the median misses (outside the scorer's tolerance): {len(miss)}; truth inside the 95% interval for "
              f"{sum(x['inside'] for x in miss)}")
        ratio = np.array([x["allowed"] / (1.96 * x["sd"]) for x in post])
        print(f"scorer's allowed error / posterior 95% half-width: median {np.median(ratio):.2f}, quartiles "
              f"{np.percentile(ratio, 25):.2f}-{np.percentile(ratio, 75):.2f}; below 1 (tolerance tighter than the posterior) "
              f"{np.mean(ratio < 1):.3f}")
        zs = np.array([(x["median"] - x["true"]) / x["sd"] for x in post])
        print(f"z = (median - truth)/sd: |z| median {np.median(np.abs(zs)):.2f} (0.67 if calibrated), |z|>1.96 share {np.mean(np.abs(zs) > 1.96):.3f}")
        for x in miss:
            print(f"  miss {x['case']} {x['variant']} {x['key']}: true {x['true']:.4g} median {x['median']:.4g} "
                  f"[{x['lo']:.4g}, {x['hi']:.4g}] sd {x['sd']:.3g} allowed {x['allowed']:.3g} inside {x['inside']}")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh)


if __name__ == "__main__":
    main()
