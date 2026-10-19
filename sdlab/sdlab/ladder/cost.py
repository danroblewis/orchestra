"""`sdlab-ladder cost`: what re-testing some strategies or cases would cost in wall time, before making the
change that would mark them stale ("this fix costs ~4 min; this shared change costs ~5 h").

    uv run sdlab-ladder cost --strategies lna                   lna's every cell run again (its code changed)
    uv run sdlab-ladder cost --cases tag:realistic              every strategy on those cases run again
    uv run sdlab-ladder cost --strategies everything --rescore  everything re-scored (a scorer change)
    uv run sdlab-ladder cost --strategies lna --stale           only what is stale now

Each cell's cost comes from the store (timing.Estimator): its own last time (wall seconds, else discovery
seconds plus scoring measured on the cell), else the same cell under other strategies, else the
strategy's median in the cell's set. Wall time is that busy time over the watcher's workers: ideal (every
worker busy), and at the watcher's measured efficiency (runs.pace). The watcher takes a new item after the
stale items before it, so the cost also says when its backlog would be cleared with these added.
"""

from __future__ import annotations

import sys

from . import cases as casemod
from . import runner, runs, store, timing


def cells(case_ids: list[str], strategies: list[str], variants: list[str] | None) -> list[tuple[str, str, str]]:
    out = []
    for cid in case_ids:
        c = casemod.load(cid)
        for v in c["variants"]:
            if variants and v["name"] not in variants and v["noise"] not in variants and v["length"] not in variants:
                continue
            out += [(cid, v["name"], s) for s in strategies]
    return out


def estimate(keys: list[tuple], mode: str, est: timing.Estimator) -> dict:
    """{items, seconds, by_set {set: [items, seconds]}, by_strategy {name: [items, seconds]}, how {how: items}, slowest [(key, s)]}."""
    out = {"items": 0, "seconds": 0.0, "by_set": {}, "by_strategy": {}, "how": {}, "slowest": []}
    each = []
    for case, variant, strategy in keys:
        secs, how = est.estimate(case, variant, strategy, mode)
        out["items"] += 1
        out["seconds"] += secs
        for part, k in (("by_set", est.sets.get(case, "tests")), ("by_strategy", strategy)):
            b = out[part].setdefault(k, [0, 0.0])
            b[0] += 1
            b[1] += secs
        out["how"][how] = out["how"].get(how, 0) + 1
        each.append(((case, variant, strategy), secs))
    out["slowest"] = sorted(each, key=lambda x: -x[1])[:5]
    return out


def main(a) -> int:
    strategies, skipped = runner.select_strategies(a.strategies)
    for s in skipped:
        print(f"skipping strategy {s['name']}: {s['reason']}", file=sys.stderr)
    variants = [v.strip() for v in (a.variants or "").split(",") if v.strip()] or None
    case_ids = runner.select_cases(a.cases)
    mode = "rescore" if a.rescore else "run"
    if a.stale:
        items = runner.plan(case_ids, strategies, variants)
        keys = [(i["case"], i["variant"], i["strategy"]) for i in items]                # each as it is stale: run or re-score
        modes = {(i["case"], i["variant"], i["strategy"]): i["mode"] for i in items}
    else:
        keys = cells(case_ids, [s["name"] for s in strategies], variants)
        modes = None
    print(f"reading the store's times ({store.path()})...", file=sys.stderr)
    t = timing.table()
    est = timing.Estimator(t, timing.case_sets(case_ids + sorted({k[0] for k in t.latest})))
    if modes is not None:
        run_keys = [k for k in keys if modes[k] == "run"]
        res_keys = [k for k in keys if modes[k] == "rescore"]
        e = estimate(run_keys, "run", est)
        r = estimate(res_keys, "rescore", est)
        for k in ("items", "seconds"):
            e[k] += r[k]
        for part in ("by_set", "by_strategy"):
            for name, (n, s) in r[part].items():
                b = e[part].setdefault(name, [0, 0.0])
                b[0] += n
                b[1] += s
        for how, n in r["how"].items():
            e["how"][how] = e["how"].get(how, 0) + n
        e["slowest"] = sorted(e["slowest"] + r["slowest"], key=lambda x: -x[1])[:5]
    else:
        e = estimate(keys, mode, est)
    pc = runs.pace()
    jobs = a.jobs or pc.get("jobs") or 4
    what = ("re-scoring" if mode == "rescore" else "re-running") + (" what is stale of" if a.stale else "")
    names = [s["name"] for s in strategies]
    who = ", ".join(names) if len(names) <= 6 else f"{len(names)} strategies"
    print(f"Cost of {what} {who} on {len(case_ids)} cases: {e['items']} items")
    if not e["items"]:
        return 0
    print(f"  busy time {runs.hours(e['seconds'] / 3600)} ({e['seconds'] / e['items']:.2f} s per item)")
    print(f"  wall time at {jobs} workers: {runs.hours(e['seconds'] / jobs / 3600)} if every worker is busy", end="")
    if pc.get("efficiency"):
        print(f"; {runs.hours(e['seconds'] / (jobs * pc['efficiency']) / 3600)} at the watcher's measured efficiency"
              f" ({100 * pc['efficiency']:.0f}% of its workers' time over its last {pc['batches']} batches)")
    else:
        print(" (the watcher's efficiency is not measured yet: its batches since 2026-10-19 record it)")
    if pc.get("per_hour"):
        print(f"  the watcher's pace: {pc['per_hour']:.0f} results per hour over the last {pc['hours']:.1f} h"
              f" ({e['items'] / pc['per_hour']:.2f} h for these at that pace, whatever they cost)")
    w = _server_watcher(a.server)
    if w and w.get("backlog"):
        bl, eta = w["backlog"], w["eta"]
        best = eta["by_cost"] if eta.get("by_cost") is not None else eta.get("by_pace")
        if best is not None:
            add = e["seconds"] / (jobs * pc["efficiency"]) / 3600 if pc.get("efficiency") else (e["items"] / pc["per_hour"] if pc.get("per_hour") else 0)
            print(f"  behind the watcher's backlog ({bl['items']} stale items, about {runs.hours(best)}): done in about {runs.hours(best + add)}")
    else:
        print(f"  (the watcher's backlog is read from the server's runs panel, {a.server}/api/ladder/runs: not available now)")
    print("  by set: " + "; ".join(f"{k} {n} items, {runs.hours(s / 3600)}" for k, (n, s) in sorted(e["by_set"].items(), key=lambda x: -x[1][1])))
    if len(e["by_strategy"]) > 1:
        top = sorted(e["by_strategy"].items(), key=lambda x: -x[1][1])[:8]
        print("  by strategy (costliest): " + "; ".join(f"{k} {runs.hours(s / 3600)}" for k, (n, s) in top))
    print("  each item's cost from: " + ", ".join(f"{n} {HOW[k]}" for k, n in sorted(e["how"].items(), key=lambda x: -x[1])))
    print("  slowest: " + "; ".join(f"{c} {v} {s} {sec:.0f} s" for (c, v, s), sec in e["slowest"]))
    return 0


def _server_watcher(base: str) -> dict | None:
    """The server's runs panel's watcher part (runs.panel: the backlog is worked out from its cached summary), or None."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/api/ladder/runs", timeout=5) as r:
            return json.loads(r.read()).get("watcher")
    except Exception:                                           # noqa: BLE001  (no server: the backlog is left out)
        return None


HOW = {"measured": "its own stored time", "cell": "other strategies on the cell", "strategy": "the strategy's median in the set",
       "set": "every strategy's median in the set", "unknown": "nothing stored (0)"}
