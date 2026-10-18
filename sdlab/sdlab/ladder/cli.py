"""The ladder's command line: uv run sdlab-ladder <command> (or python -m sdlab.ladder).

    run    [--strategies a,b|all] [--cases ids|tag:x|level:n] [--variants none,long,counts-short]
                                  run those now, current or not (a new row in the history)
    sync   [--strategies ...]     run every stale (case, variant, strategy): new or changed cases, new or
                                  changed strategies or discovery code; a scorer change re-scores stored flows
    status [--strategies ...] [--variant V]
                                  the strategy x case matrix, per-tag summaries, and what is stale
    show   CASE [--strategy S] [--variant V]
                                  true and found equations side by side, part by part, with the scores
    watch  [--every 3]            sync now, then again whenever a case, a strategy or discovery changes
    check  [--cases ...]          the case checks (bounded, moving, every flow moves)

Common: --jobs N (default CPU cores - 1), --timeout S (per item, default 120).
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_var, "1")                           # one numpy thread per worker, set before numpy loads

import argparse  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from . import api, catalog, checks, runner, score  # noqa: E402
from . import cases as casemod  # noqa: E402

LETTER = {"pass": "P", "equivalent": "E", "fail": "F", "error": "X", "timeout": "T", None: "."}


def pct(v) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def with_ci(v, ci) -> str:
    return pct(v) + (f" [{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]" if ci and v is not None else "")


def _progress(item, row, n, total) -> None:
    extra = f" {row['error']}" if row.get("error") else ""
    print(f"  [{n}/{total}] {item['case']} {item['variant']} {item['strategy']}: {row['status']}"
          + (f" ({row['seconds']:.2f} s)" if row.get("seconds") is not None else "") + extra, file=sys.stderr)


def do_run(a, force: bool, command: str) -> int:
    strategies, skipped = runner.select_strategies(a.strategies)
    for s in skipped:
        print(f"skipping strategy {s['name']}: {s['reason']}", file=sys.stderr)
    variants = [v.strip() for v in (a.variants or "").split(",") if v.strip()] or None
    items = runner.plan(runner.select_cases(a.cases), strategies, variants, force=force)
    if not items:
        print("Nothing to run: every result is current.")
        return 0
    runs = sum(i["mode"] == "run" for i in items)
    print(f"{command}: {len(items)} items ({runs} to run, {len(items) - runs} to re-score) on {a.jobs or (os.cpu_count() or 2) - 1} workers", file=sys.stderr)
    began = time.perf_counter()
    rows = runner.execute(items, a.jobs, a.timeout, command, on_done=None if a.quiet else _progress)
    took = time.perf_counter() - began
    counts = {k: sum(r["status"] == k for r in rows) for k in api.STATUSES}
    print(f"{command}: {len(rows)} done in {took:.1f} s: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
    return 0


def status(a) -> int:
    names = [n.strip() for n in a.strategies.split(",")] if a.strategies and a.strategies != "all" else None
    s = api.summary(names)
    strats = [x["name"] for x in s["strategies"]]
    cells = {(c["case"], c["variant"], c["strategy"]): c for c in s["cells"]}
    for x in s["strategies"]:
        if not x["available"]:
            print(f"strategy {x['name']}: skipped ({x['reason']})")
    variants = list(dict.fromkeys(v for c in s["cases"] for v in c["variants"]))
    print("Cells: one letter per variant (" + ", ".join(variants) + "): P pass, E equivalent, F fail, X error, T timeout, . not run;"
          " * after a cell: stale. recall: mean over variants.\n")
    width = max(len(c["id"]) for c in s["cases"]) if s["cases"] else 10
    print(f"{'case':{width}s}  " + "  ".join(f"{n:>16s}" for n in strats))
    for c in s["cases"]:
        row = []
        for n in strats:
            cs = [cells[(c["id"], v, n)] for v in c["variants"]]
            letters = "".join(LETTER.get(x["status"], "?") for x in cs) + ("*" if any(x["stale"] and x["status"] for x in cs) else " ")
            rec = [x["recall"] for x in cs if x.get("recall") is not None]
            row.append(f"{letters} {pct(sum(rec) / len(rec)) if rec else '-':>6s}".rjust(16))
        print(f"{c['id']:{width}s}  " + "  ".join(row))
    for n in strats:
        t = s["totals"][n]
        print(f"\n{n}: {t['pass']} pass, {t['equivalent']} equivalent, {t['fail']} fail, {t['error']} error, {t['timeout']} timeout,"
              f" {t['missing']} not run, {t['stale']} stale, of {t['total']}; discovery {t['seconds']:.1f} s in all")
    detail = [v for v in variants if not a.variant or v == a.variant]
    for n in strats if len(strats) == 1 or a.detail else []:
        print(f"\n{n}, per variant: status, recall, right/of, skill@20 [95% CI], fresh skill@20")
        for v in detail:
            print(f"\n  {v}")
            for c in s["cases"]:
                x = cells.get((c["id"], v, n))
                if not x or not x["status"]:
                    continue
                print(f"    {c['id']:{width}s} {x['status']:10s} recall {pct(x['recall']):>6s}  {x.get('right') or 0}/{x.get('of') or 0}"
                      f"  skill@20 {with_ci(x['skill20'], x['skill20_ci']):>24s}  fresh {pct(x['fresh20']):>7s}" + ("  stale" if x["stale"] else "")
                      + (f"  {x['error'][:80]}" if x.get("error") else ""))
    print("\nBy tag (pass + equivalent of total):")
    print(f"  {'tag':16s} " + "  ".join(f"{n:>16s}" for n in strats))
    for tag in sorted(s["by_tag"]):
        g = s["by_tag"][tag]
        print(f"  {tag:16s} " + "  ".join(f"{g[n]['pass']}+{g[n]['equivalent']} of {g[n]['total']}".rjust(16) for n in strats))
    return 0


def _eq(flow: dict) -> str:
    """One flow as an equation."""
    a, b = flow.get("from") or "outside", flow.get("to") or "outside"
    if flow.get("via"):
        b = f"(hidden, delay {flow['via'].get('delay')}) -> {b}"
    r = flow.get("rate") or {}
    form = r.get("form")
    if form == "constant":
        rate = f"{r.get('value'):.4g}"
    elif form == "proportional":
        rate = f"{r.get('k'):.4g} * {r.get('stock')}"
    elif form == "gap":
        rate = f"({r.get('goal')} - {r.get('stock')}) / {r.get('time')}"
    elif form == "linear":
        rate = " + ".join([f"{r.get('c') or 0:.4g}"] * bool(r.get("c")) + [f"{t.get('k'):.4g} * {t.get('stock')}" for t in r.get("terms") or []]) or "0"
    else:
        rate = str(r)
    for e in flow.get("effects") or []:
        rate += f" x {e.get('shape', 'linear')}({e.get('stock')})"
    for u in flow.get("uses") or []:
        rate += f"; uses {u.get('per')} {u.get('stock')} per unit"
    extra = ""
    if flow.get("inflow"):
        extra = f" (mean; {len(flow['inflow'])} pieces)"
    elif flow.get("byTime"):
        extra = f" (varies: {len(flow['byTime'])} segments)"
    return f"{a} -> {b} = {rate}{extra}"


def show(a) -> int:
    cid = runner.select_cases(a.case)[0]
    c = casemod.load(cid)
    print(f"{cid}: {c['title']} (level {c['level']}; {', '.join(c['tags'])})\n  tests: {c['tests']}\n")
    print("True equations:")
    for f in c["model"]["flows"]:
        print("  " + _eq(f) + ("" if all(s.get("measured", True) for s in c["model"]["stocks"] if s["id"] in (f.get("from"), f.get("to"))) else "   [touches a hidden stock]"))
    if c["model"].get("schedule"):
        print(f"  schedule: every {c['model']['schedule'].get('every')}: " + "; ".join(
            f"t={x['t']} {x.get('label')}{' (announced)' if x.get('announce') else ''}" for x in c["model"]["schedule"]["changes"]))
    strategies = [a.strategy] if a.strategy else [s["name"] for s in catalog.listing(check=False)]
    for sname in strategies:
        for v in c["variants"]:
            if a.variant and v["name"] != a.variant:
                continue
            r = api.result(cid, v["name"], sname)
            if not r:
                continue
            s = r.get("scores") or {}
            beh = (s.get("behaviour") or {})
            print(f"\n== {sname}, {v['name']}: {r['status'].upper()}" + (f" ({r['error']})" if r.get("error") else "")
                  + (f"; recall {pct(s.get('recall'))}, precision {pct(s.get('precision'))}, {s.get('right')}/{s.get('of')} parts right" if s else "")
                  + (f"; discovery {r['seconds']:.2f} s" if r.get("seconds") is not None else "") + f"; {r['at']}")
            for where in ("in_sample", "fresh"):
                b = beh.get(where) or {}
                if b:
                    print(f"   {where.replace('_', '-')}: " + ", ".join(f"skill@{h} {with_ci(x.get('skill'), x.get('ci'))}" for h, x in b.items()))
            print("   Found equations:")
            for f in r.get("found") or []:
                print("     " + _eq(f))
            if s.get("parts"):
                print("   Parts (true vs found):")
                for p in s["parts"]:
                    err = p.get("error")
                    print(f"     {'ok ' if p['ok'] else 'X  '} {p['key']:34s} {p['kind']:16s} true {_num(p.get('true')):>12s}  found {_num(p.get('found_value')):>12s}"
                          + (f"  error {100 * err:.1f}%" if isinstance(err, (int, float)) else ""))
                for p in s.get("spurious") or []:
                    print(f"     +   {p['key']:34s} {p['kind']:16s} spurious: {_num(p.get('value'))} (size {p['size']:.3g} per step)")
                for n in s.get("notes") or []:
                    print(f"     note: {n}")
    return 0


def _num(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"{v:.4g}"
    if isinstance(v, dict) and "mean" in v:
        return f"{v['mean']:.4g} (mean)"
    if isinstance(v, dict) and "k_in" in v:
        return f"k {v['k_in']:.3g}, delay {v['delay']:.3g}"
    return str(v)[:30]


def fingerprint() -> tuple:
    return (tuple((i, casemod.load(i)["hash"]) for i in casemod.case_ids()),
            tuple((n, catalog.strategy_hash(n)) for n in catalog.names()), score.score_hash())


def watch(a) -> int:
    last = None
    print(f"Watching {casemod.CASES} and {catalog.STRATEGIES.parent} (every {a.every:g} s; ctrl-c to stop)", file=sys.stderr)
    try:
        while True:
            try:
                fp = fingerprint()
            except Exception as e:                            # noqa: BLE001  (a case being edited may not parse yet)
                print(f"waiting: {e}", file=sys.stderr)
                fp = last
            if fp != last:
                last = fp
                do_run(a, False, "watch")
            time.sleep(a.every)
    except KeyboardInterrupt:
        return 0


def check(a) -> int:
    bad = 0
    for cid in runner.select_cases(a.cases):
        p = checks.problems(casemod.load(cid))
        bad += bool(p)
        print(f"{cid}: " + ("ok" if not p else "; ".join(p)))
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sdlab-ladder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, cases=True):
        p.add_argument("--strategies", default="all")
        if cases:
            p.add_argument("--cases")
            p.add_argument("--variants")
        p.add_argument("--jobs", type=int)
        p.add_argument("--timeout", type=float, default=runner.TIMEOUT)
        p.add_argument("--quiet", action="store_true")

    common(sub.add_parser("run", help="run strategies on cases, current or not"))
    common(sub.add_parser("sync", help="run everything stale (optionally only some strategies, cases, variants)"))
    st = sub.add_parser("status", help="the strategy x case matrix")
    st.add_argument("--strategies", default="all")
    st.add_argument("--variant")
    st.add_argument("--detail", action="store_true", help="per-variant tables for every strategy")
    sh = sub.add_parser("show", help="true vs found equations for a case")
    sh.add_argument("case")
    sh.add_argument("--strategy")
    sh.add_argument("--variant")
    w = sub.add_parser("watch", help="sync whenever cases or strategies change")
    common(w)
    w.add_argument("--every", type=float, default=3.0)
    ck = sub.add_parser("check", help="check the cases are sane")
    ck.add_argument("--cases")
    a = ap.parse_args(argv)
    if a.command == "run":
        return do_run(a, True, "run")
    if a.command == "sync":
        return do_run(a, False, "sync")
    if a.command == "status":
        return status(a)
    if a.command == "show":
        return show(a)
    if a.command == "watch":
        return watch(a)
    if a.command == "check":
        return check(a)
    return 2


if __name__ == "__main__":
    sys.exit(main())
