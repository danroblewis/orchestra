"""The ladder's command line: uv run sdlab-ladder <command> (or python -m sdlab.ladder).

    run    [--strategies a,b|all] [--cases ids|tag:x|level:n|machine:m] [--exclude-cases SPEC] [--variants none,long,counts-short] [--local]
                                  run those now, current or not (a new row in the history); --exclude-cases (the
                                  --cases syntax) leaves cases out, also for sync and watch. Small runs only: above
                                  40 items or 2 CPU-minutes (sdlab-ladder cost) it is refused and names the submit
                                  command (CLAUDE.md rule 15c); --local runs it here anyway, logged
    sync   [--strategies ...] [--local]
                                  run every stale (case, variant, strategy): new or changed cases, new or
                                  changed strategies or discovery code; a scorer change re-scores stored flows;
                                  the same size limit as run
    submit [--strategies ...] [--cases ...] [--exclude-cases ...] [--variants ...] [--stale] [--ref BRANCH] [--by NAME]
                                  the CPU pool runs it at a committed ref (default this checkout's branch): prints
                                  the estimate and the job id; --stale: only what is stale, as sync (pool/agent.py)
    job    ID [--wait] [--json]   a pool job's progress; --wait: each item as it finishes, then run's summary
    status [--strategies ...] [--variant V]
                                  the strategy x case matrix, per-tag summaries, and what is stale
    show   CASE [--strategy S] [--variant V]
                                  true and found equations side by side, part by part, with the scores
    diff   CASE --strategy S [--variant V] [--json] | CASES --summary [--strategies roster:NAME] [--variants ...]
           | CASE --strategy S --variant V --between REF_A REF_B | --ids A,B
                                  the found model as a git diff of the truth (diff.py; what the page draws): per
                                  result, the most common lines across a rung, or what changed between two results
    watch  [--every 3]            sync now, then again whenever a case, a strategy or discovery changes
    check  [--cases ...]          every case file compiles, then the case checks (bounded, moving, every flow moves)
    new    SLUG [--title T] [--level N]
                                  write the next case, cases/NNN-SLUG.yaml, from a template to edit
    freeze CASE#i [--slug S]      write draw i of a parametric case as an ordinary case (the next NNN)
    longrun [--strategies ...] [--cases ...] [--variants ...] [--jobs N]
                                  long-horizon metrics (longrun.py) of the latest results not yet known
    analyse CASE [--variant V] [--json] | --all [--cases ...] | --validate CASE --variant V [--seeds N]
                                  what the data can deliver (identifiability, the Cramér-Rao bound; analysis.py)
    cost   [--strategies ...] [--cases ...] [--variants ...] [--rescore] [--stale] [--jobs N]
                                  the wall time re-testing them would take, from stored per-cell times and the
                                  watcher's pace (cost.py)
    strict [--strategies ...] [--cases ...] [--all] [--no-fill] [--set tests|realistic|all] [--top N]
                                  fill strict pass's long-run metrics and per-cell references (strict.py), then
                                  pass against strict pass per strategy (strict_report.py)
    prune  [--dry-run]            latest results whose case or variant no longer exists: list them (--dry-run)
                                  or archive them (latest = 0, listed in the archived table; prune.py)
    export [--since-id N] [--out FILE]
                                  the results made here since id N (default: since the last export) to a
                                  gzipped JSONL file, with the code patches they refer to (exchange.py)
    backup [--dir D]              a consistent snapshot of the store (SQLite's backup API), compressed, rotated
                                  (24 h hourly, 14 days daily, 8 weeks weekly; backup.py)
    restore [FILE] [--to PATH] [--replace]
                                  a backup decompressed and its row counts checked against when it was taken
    import FILE... | --high-water MACHINE
                                  add exported results to this store (new ids, skipped when already here; latest:
                                  the newest `at` per cell); --high-water: the newest id imported from MACHINE

    pool   submit|status|results|cancel ...
                                  the CPU pool's job queue (docs/pool.md): submit a job at a committed ref,
                                  follow it, read its results (`sdlab-ladder pool --help`)
    worker --server URL --slots N [--home DIR] [--max-mem-gb G] ...
                                  a CPU pool worker: pulls items, runs each in its slot's own checkout at
                                  the item's commit, posts the results (pool/worker.py; `sdlab-ladder worker --help`)

Common: --jobs N (default CPU cores - 1), --timeout S (per item, default 120).
"""

from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS"):
    os.environ.setdefault(_var, "1")                           # one numpy thread per worker, set before numpy loads
# JAX (the unified objective) ignores those and starts a thread pool per core: 142 threads a worker
os.environ.setdefault("XLA_FLAGS", "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1")

import argparse  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from . import api, catalog, checks, longrun_cache, runner, score  # noqa: E402
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
    strategies, skipped = runner.select_strategies(a.strategies, parked_too=command == "sync")   # sync: stale parked cells too
    for s in skipped:
        print(f"skipping strategy {s['name']}: {s['reason']}", file=sys.stderr)
    variants = [v.strip() for v in (a.variants or "").split(",") if v.strip()] or None
    from .real.data import missing_notes
    cids = runner.select_cases(a.cases, getattr(a, "exclude_cases", None))
    for note in missing_notes(cids):
        print(f"skipping {note}", file=sys.stderr)                  # real cases whose data are not downloaded: not run
    items = runner.plan(cids, strategies, variants, force=force, every_variant=getattr(a, "every_variant", False))
    if not items:
        print("Nothing to run: every result is current.")
        return 0
    if command in ("run", "sync"):                               # small tests here; larger ones go to the pool (rule 15c)
        from .pool import agent as pool_agent
        if not pool_agent.guard(a, items, command):
            return 3
    backlog = len(items)
    batch = getattr(a, "batch", 0) or 0
    if batch and len(items) > batch:
        # a batch at a time, so cases and strategies added meanwhile are planned within minutes:
        # never-run pairs first, then cheap re-scores, then re-runs of changed code
        order = {"new": 0, "score_only": 1}
        items = sorted(items, key=lambda i: order.get(i["reason"], 2))
        print(f"{command}: {len(items)} items stale; this batch takes {batch}", file=sys.stderr)
        a._more = True
        items = items[:batch]
    runs = sum(i["mode"] == "run" for i in items)
    print(f"{command}: {len(items)} items ({runs} to run, {len(items) - runs} to re-score) on {a.jobs or (os.cpu_count() or 2) - 1} workers", file=sys.stderr)
    began = time.perf_counter()
    rows = runner.execute(items, a.jobs, a.timeout, command, on_done=None if a.quiet else _progress, backlog=backlog)
    took = time.perf_counter() - began
    counts = {k: sum(r["status"] == k for r in rows) for k in dict.fromkeys([*api.STATUSES, *(r["status"] for r in rows)])}   # real cases: agrees / differs
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
        if t.get("achievable") or t.get("data_limited") or t.get("unidentifiable"):
            print(f"  over the cells the data allow (sdlab-ladder analyse): {t['achievable_pass']} pass of {t['achievable']} achievable"
                  f" ({pct(t['achievable_pass'] / t['achievable']) if t['achievable'] else '-'}); {t['data_limited']} data-limited,"
                  f" {t['unidentifiable']} unidentifiable, {t['total'] - t['achievable'] - t['data_limited'] - t['unidentifiable']} not analysed")
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
    if s.get("parametric"):
        print("\nParametric cases (draws.py): pass rate over draws x variants; draws passing in every variant")
        print(f"  {'case':{width}s} " + "  ".join(f"{n:>16s}" for n in strats))
        for base, g in s["parametric"].items():
            row = []
            for n in strats:
                t = g["strategies"].get(n) or {}
                row.append((f"{pct(t['rate'])} {t['draws_passing']}/{len(g['draws'])}" if t.get("total") and t["total"] > t["missing"] else "-").rjust(16))
            print(f"  {base:{width}s} " + "  ".join(row))
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
    if c.get("draw"):
        d = c["draw"]
        print(f"Draw {d['i']} of {d['of']} (seed {d['seed']}, attempt {d['attempt']}"
              + (f"; {len(d['rejected'])} attempts rejected by the checks" if d["rejected"] else "") + "):")
        for x in d["values"]:
            print(f"  {x['label']:40s} {x['value']:<10g} drawn from [{x['lo']:g}, {x['hi']:g}]" + (" log" if x["log"] else "") + (" int" if x["int"] else ""))
        print(f"  (sdlab-ladder freeze {cid} writes it as a fixed case)\n")
    print("True equations:")
    for f in c["model"]["flows"]:
        print("  " + _eq(f) + ("" if all(s.get("measured", True) for s in c["model"]["stocks"] if s["id"] in (f.get("from"), f.get("to"))) else "   [touches a hidden stock]"))
    if c["model"].get("schedule"):
        print(f"  schedule: every {c['model']['schedule'].get('every')}: " + "; ".join(
            f"t={x['t']} {x.get('label')}{' (announced)' if x.get('announce') else ''}" for x in c["model"]["schedule"]["changes"]))
    from . import analysis
    for v in c["variants"]:
        if not a.variant or v["name"] == a.variant:
            an = analysis.get(cid, v["name"])
            print(f"  analysis {v['name']}: {an['label']}" + ("" if an.get("p") is None else f" (p {an['p']:.2f})")
                  + "".join(f"; {w}" for w in an.get("why") or [])[:200] + f"   (sdlab-ladder analyse {cid})")
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
                  + (f"; discovery {r['seconds']:.2f} s" if r.get("seconds") is not None else "") + f"; {r['at']}"
                  + (f"; code {r['code_commit'][:10]}" + (f" + patch {r['code_dirty']}" if r.get("code_dirty") else "") if r.get("code_commit") else ""))
            for where in ("in_sample", "fresh"):
                b = beh.get(where) or {}
                if b:
                    print(f"   {where.replace('_', '-')}: " + ", ".join(f"skill@{h} {with_ci(x.get('skill'), x.get('ci'))}" for h, x in b.items()))
            lr = longrun_cache.of_result(r, compute_missing=True)
            if lr and not lr.get("error"):
                print(f"   {_longrun_line(lr)}\n   graph: /ladder/run?id={r['id']}")
            cx = r.get("complexity")
            if cx:
                print(f"   complexity: true {cx['true']}, found {cx['found']} (extra {cx['extra']:+d}: "
                      + ", ".join(f"{k} {v:+d}" for k, v in cx["by"].items()) + f"; {cx['ratio']:.2f}x the truth)")
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
                    print(f"     +   {p['key']:34s} {p['kind']:16s} spurious: {_num(p.get('value'))} (size {_size(p.get('size'))} per step)")
                for n in s.get("notes") or []:
                    print(f"     note: {n}")
    return 0


def _size(v) -> str:
    """A spurious part's size per step (stored as null when it is infinite, e.g. an effect part)."""
    return f"{v:.3g}" if isinstance(v, (int, float)) else "unbounded"


def _longrun_line(lr: dict) -> str:
    """One result's long-run metrics (longrun.py), on one line."""
    err = ", ".join(f"@{k} {_num(v)}" for k, v in (lr.get("err") or {}).items())
    tau = f"tau true {_num(lr.get('tau_true'))}, found {_num(lr.get('tau_found'))}"
    return (f"long run: error {err}; equilibrium error {_num(lr.get('eq_err'))}; {tau}; rho true {_num(lr.get('rho_true'))}, "
            f"found {_num(lr.get('rho_found'))}" + (f"; {lr['flag'].upper()}" if lr.get("flag") else ""))


def longrun(a) -> int:
    """Compute the long-run metrics of the latest results that do not have them yet."""
    from . import store
    names = set(catalog.names()) if a.strategies in (None, "all") else set(a.strategies.split(","))
    cids = set(runner.select_cases(a.cases)) if a.cases else None
    rows = [r for r in store.latest() if r["strategy"] in names and (cids is None or r["case"] in cids)
            and (not a.variants or any(x in r["variant"] for x in a.variants.split(",")))]
    t0 = time.time()
    n = longrun_cache.fill(rows, a.jobs or max(1, (os.cpu_count() or 2) - 1),
                           None if a.quiet else lambda d, n: print(f"\r{d}/{n} results", end="", flush=True))
    print(f"\n{n} results graded in {time.time() - t0:.1f} s")
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
    if isinstance(v, dict) and "delay" in v:
        return f"delay {v['delay']:.3g}"
    return str(v)[:30]


def fingerprint() -> tuple:
    return (tuple((i, casemod.load(i)["hash"]) for i in casemod.case_ids()),
            tuple((n, catalog.strategy_hash(n)) for n in catalog.names()), score.score_hash())


def _harness_hash() -> str:
    """The ladder's own code (sdlab/ladder/*.py and the engine): when it changes, a long-running
    watcher restarts itself, so it never plans or scores with code older than the files."""
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for p in sorted([*root.glob("*.py"), *root.parent.glob("sdtruth*.py"), root / "machines.yaml"]):
        h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


def _restart(why: str) -> None:
    print(f"watch: restarting with the current code ({why})", file=sys.stderr, flush=True)
    os.execv(sys.executable, [sys.executable, *sys.argv])


def watch(a) -> int:
    last = None
    code = _harness_hash()
    print(f"Watching {casemod.CASES} and {catalog.STRATEGIES.parent} (every {a.every:g} s; ctrl-c to stop)", file=sys.stderr)
    try:
        while True:
            if _harness_hash() != code:
                _restart("the ladder's code changed")
            try:
                fp = fingerprint()
            except Exception as e:                            # noqa: BLE001  (a case being edited may not parse yet)
                print(f"waiting: {e}", file=sys.stderr)
                fp = last
            a._more = False
            if fp != last or getattr(a, "_was_more", False):
                last = fp
                try:
                    do_run(a, False, "watch")
                except Exception as e:                        # noqa: BLE001  (never die: wait, then restart on fresh code)
                    print(f"watch: a pass failed: {e!r}; retrying after {a.every:g} s", file=sys.stderr, flush=True)
                    time.sleep(a.every)
                    _restart("a pass failed")
            a._was_more = a._more                           # a batch left work: plan again at once
            if not a._more:
                time.sleep(a.every)
    except KeyboardInterrupt:
        return 0


def check(a) -> int:
    try:
        casemod.case_files()                                       # one id written twice is an error
    except casemod.CaseError as e:
        print(e)
        return 1
    bad = 0
    for cid in runner.select_cases(a.cases) if a.cases else casemod.case_ids():
        rejected = []
        try:
            c = casemod.load(cid)
            p = checks.problems(c)
            rejected = (c.get("draw") or {}).get("rejected") or []
        except casemod.CaseError as e:
            p = [str(e)]
        bad += bool(p)
        print(f"{cid}: " + ("ok" if not p else "; ".join(p))
              + (f" (drawn again {len(rejected)}x: " + "; ".join(", ".join(r["problems"]) for r in rejected)[:300] + ")" if rejected else ""))
    return 1 if bad else 0


TEMPLATE = """\
title: {title}
level: {level}
tags: [chain]
tests: one sentence on what discovery must recover
stocks: {{A: 0, B: 0}}
flows:
  outside -> A: 20
  A -> B: 0.5 * A
  B -> outside: 0.2 * B
"""


def new(a) -> int:
    slug = a.slug.strip().lower().replace(" ", "-")
    files = casemod.case_files()
    number = max((int(i[:3]) for i in files), default=0) + 1
    cid = f"{number:03d}-{slug}"
    if not casemod.ID_RE.match(cid):
        print(f"{slug!r} is not a slug (lower-case letters, digits, -)", file=sys.stderr)
        return 2
    levels = [casemod.load(i)["level"] for i in casemod.case_ids()]
    path = casemod.CASES / f"{cid}.yaml"
    path.write_text(TEMPLATE.format(title=a.title or slug.replace("-", " ").capitalize(), level=a.level if a.level is not None else max(levels, default=1)))
    print(path)
    print(f"Edit it (format: docs/LADDER.md), then: uv run sdlab-ladder check --cases {number:03d}", file=sys.stderr)
    return 0


def freeze(a) -> int:
    """Write a draw of a parametric case as an ordinary case file: a failing draw kept as a fixed
    regression case."""
    from . import draws

    cids = [i for i in runner.select_cases(a.case) if "#" in i]
    if len(cids) != 1:
        print(f"freeze takes one draw (NNN#i or NNN-slug#i), not {a.case!r}" + (f" ({len(cids)} match)" if cids else ""), file=sys.stderr)
        return 2
    cid = cids[0]
    base, i = casemod.split(cid)
    c = casemod.load(cid)
    path = casemod.case_files()[base]
    text = draws.frozen(path.read_text(), path.name, i, c["draw"]["attempt"], base, casemod.spec(cid).get("title") or base, c["tests"])
    number = max(int(x[:3]) for x in casemod.case_files()) + 1
    out_id = f"{number:03d}-{(a.slug or f'{base[4:]}-draw-{i}').strip().lower()}"
    if not casemod.ID_RE.match(out_id):
        print(f"{out_id!r} is not a case id (NNN-lower-case-slug)", file=sys.stderr)
        return 2
    if casemod.compile_case(text, out_id)["model"] != casemod.spec(cid)["model"]:
        print("internal error: the frozen case is not the draw's model", file=sys.stderr)
        return 1
    out = casemod.CASES / f"{out_id}.yaml"
    out.write_text(text)
    print(out)
    print(f"{cid} written as {out_id}; check it: uv run sdlab-ladder check --cases {number:03d}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sdlab-ladder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, cases=True):
        p.add_argument("--strategies", default="all")
        if cases:
            p.add_argument("--cases")
            p.add_argument("--variants")
            p.add_argument("--every-variant", action="store_true", help="also none-long where none-short has not passed (it only confirms a short pass by default)")
        p.add_argument("--jobs", type=int)
        p.add_argument("--timeout", type=float, default=runner.TIMEOUT)
        p.add_argument("--quiet", action="store_true")

    def exclude(p):
        p.add_argument("--exclude-cases", help="cases to leave out (the --cases syntax), e.g. machine:node2: what another machine runs")
        return p

    for name, text in (("run", "run strategies on cases, current or not (small tests: larger ones are submitted)"),
                       ("sync", "run everything stale (optionally only some strategies, cases, variants; small tests only)")):
        p = sub.add_parser(name, help=text)
        common(exclude(p))
        p.add_argument("--local", action="store_true", help="run here even above the local limit (40 items, 2 CPU-minutes); logged")
    from .pool import agent as pool_agent
    pool_agent.add_parsers(sub)
    ex = sub.add_parser("export", help="results made here since an id (or the last export) to a gzipped JSONL file (exchange.py)")
    ex.add_argument("--since-id", type=int, help="export results with a larger id (default: since the last export)")
    ex.add_argument("--out", help="the file (default $SDLAB_LADDER_CACHE/exports/<machine>-<since>-<upto>.jsonl.gz)")
    im = sub.add_parser("import", help="add another machine's exported results to this store (exchange.py); idempotent")
    im.add_argument("files", nargs="*")
    im.add_argument("--high-water", metavar="MACHINE", help="print the newest remote id imported from MACHINE (0: none) and stop")
    bk = sub.add_parser("backup", help="a consistent, compressed snapshot of the result store, then rotation (backup.py)")
    bk.add_argument("--dir", help="where (default $SDLAB_BACKUPS or ~/.sdlab/backups)")
    rs = sub.add_parser("restore", help="decompress a backup to a file and check its row counts (backup.py)")
    rs.add_argument("file", nargs="?", help="a backup file (default: the newest)")
    rs.add_argument("--dir", help="where the backups are")
    rs.add_argument("--to", help="the store file to write (default: next to the backup, .restored.sqlite)")
    rs.add_argument("--replace", action="store_true", help="overwrite --to even if it exists (the live store only with the watcher and server stopped)")
    st = sub.add_parser("status", help="the strategy x case matrix")
    st.add_argument("--strategies", default="all")
    st.add_argument("--variant")
    st.add_argument("--detail", action="store_true", help="per-variant tables for every strategy")
    sh = sub.add_parser("show", help="true vs found equations for a case")
    sh.add_argument("case")
    sh.add_argument("--strategy")
    sh.add_argument("--variant")
    w = sub.add_parser("watch", help="sync whenever cases or strategies change")
    common(exclude(w))
    w.add_argument("--every", type=float, default=3.0)
    w.add_argument("--batch", type=int, default=0, help="run at most N stale items per pass, then plan again (new pairs first); 0: all")
    ck = sub.add_parser("check", help="check the cases are sane")
    ck.add_argument("--cases")
    nw = sub.add_parser("new", help="write the next case file from a template")
    nw.add_argument("slug")
    nw.add_argument("--title")
    nw.add_argument("--level", type=int)
    fz = sub.add_parser("freeze", help="write a draw of a parametric case (NNN#i) as an ordinary case file")
    fz.add_argument("case")
    fz.add_argument("--slug", help="the new case's slug (default: the parametric case's, with -draw-i)")
    common(sub.add_parser("longrun", help="long-horizon metrics of the latest results (cached by result id)"))
    sp = sub.add_parser("strict", help="strict pass: fill its caches (strict.py), then pass against strict pass")
    common(sp)
    sp.add_argument("--all", action="store_true", help="references for every cell of the cases picked, not only those a pass needs")
    sp.add_argument("--no-fill", action="store_true", help="only the report")
    sp.add_argument("--set", default="tests", choices=("tests", "realistic", "all"))
    sp.add_argument("--top", type=int, default=10)
    ev = sub.add_parser("evidence", help="evidence beside the pass per latest result, and a confidence score from NO-TRUTH checks (evidence.py)")
    common(ev)
    ev.add_argument("--reference", type=int, default=3, help="the push test's refits of the truth's own structure per cell")
    ev.add_argument("--no-fill", action="store_true", help="only the report, from the cache")
    ev.add_argument("--out", help="write every report and the confidence model's report as JSON")
    co = sub.add_parser("cost", help="the wall time to re-test strategies or cases, from stored per-cell times (cost.py)")
    co.add_argument("--strategies", default="all")
    co.add_argument("--cases")
    co.add_argument("--variants")
    co.add_argument("--jobs", type=int, help="workers (default: the watcher's)")
    co.add_argument("--rescore", action="store_true", help="the cost of re-scoring them (a scorer change), not of running them")
    co.add_argument("--stale", action="store_true", help="only what is stale now, each run or re-scored as it is stale")
    co.add_argument("--server", default="http://127.0.0.1:8020", help="where the runs panel (the watcher's backlog) is read")
    pr = sub.add_parser("prune", help="archive latest results whose case or variant no longer exists (prune.py)")
    pr.add_argument("--dry-run", action="store_true", help="only list them")
    an = sub.add_parser("analyse", help="what a case's data can deliver: identifiability and the Cramér-Rao bound")
    an.add_argument("case", nargs="?")
    an.add_argument("--variant")
    an.add_argument("--json", action="store_true")
    an.add_argument("--all", action="store_true", help="analyse every case (or --cases) into the cache")
    an.add_argument("--cases")
    an.add_argument("--jobs", type=int)
    an.add_argument("--validate", action="store_true", help="the bound against ML refits on fresh seeds (CASE, --variant)")
    an.add_argument("--seeds", type=int, default=20)
    ot = sub.add_parser("objective-test", help="does the true model score best under the unified objective (objective_test.py)?")
    ot.add_argument("--cases", help="the --cases syntax")
    ot.add_argument("--sets", help="named sets: " + ", ".join(("p0", "p1", "p2", "p3", "p4", "p5")))
    ot.add_argument("--variants")
    ot.add_argument("--cells", help="an exact cell list: case@variant,... (e.g. 007@counts-short,081@meas-short)")
    ot.add_argument("--cells-from", metavar="FOLDER", help="the cells cached in this objective_test folder (e.g. a baseline's)")
    ot.add_argument("--out", help="write the cells and the summary as JSON")
    ot.add_argument("--jobs", type=int, default=2, help="workers (at most 4; JAX's CPU runtime uses ~2 cores each)")
    ot.add_argument("--timeout", type=float, default=900.0, help="seconds per cell; a cell that runs out is resumable")
    ot.add_argument("--max-groups", type=int, default=40, help="distinct stored structures per cell (the rest: not run)")
    ot.add_argument("--report-only", action="store_true", help="only the report, from the cache")
    ot.add_argument("--code-table", metavar="NAME", help="the objective's code table (unified/codetable.py): v1 (default), or "
                    "v2-<option>[+<option>...] with options eta-lean, eta-joint, phi-lean, phi-joint, tau-priced, phi-prior[=width]")
    ot.add_argument("--relabel", metavar="FOLDERS", help="re-label the cached cells of these cache folders (comma list, later wins) into the current one, no refitting")
    from . import z3_ident_report
    z3_ident_report.add_parser(sub)
    from . import diff_report
    diff_report.add_parser(sub)
    pl = sub.add_parser("pool", help="the CPU pool's job queue: submit, status, results, cancel (docs/pool.md)", add_help=False)
    pl.add_argument("rest", nargs=argparse.REMAINDER)
    wk = sub.add_parser("worker", help="a CPU pool worker (docs/pool.md, Workers)", add_help=False)
    wk.add_argument("rest", nargs=argparse.REMAINDER)
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["pool"]:                                     # its own parser (pool/cli.py), --help included
        from .pool import cli as pool_cli
        return pool_cli.main(args[1:])
    if args[:1] == ["worker"]:                                   # its own parser (pool/worker.py)
        from .pool import worker as pool_worker
        return pool_worker.main(args[1:])
    a = ap.parse_args(argv)
    if a.command == "ident":
        from . import z3_ident_report
        return z3_ident_report.main(a)
    if a.command == "objective-test":
        from . import objective_test
        return objective_test.main(a)
    if a.command == "run":
        return do_run(a, True, "run")
    if a.command == "sync":
        return do_run(a, False, "sync")
    if a.command in ("submit", "job"):
        return getattr(pool_agent, a.command)(a)
    if a.command == "export":
        from . import exchange
        got = exchange.export(a.since_id, a.out)
        print(f"export: {got['count']} results (ids {got['since_id']}..{got['upto_id']}], {got['patches']} patches", file=sys.stderr)
        print(got["path"])
        return 0
    if a.command == "import":
        from . import exchange
        if a.high_water:
            print(exchange.high_water(a.high_water))
            return 0
        for f in a.files:
            got = exchange.import_file(f)
            print(f"import {f}: from {got['machine']}: {got['added']} added ({got['latest']} now latest), {got['skipped']} already here,"
                  f" {got['patches']} patches")
        return 0
    if a.command in ("backup", "restore"):
        from . import backup
        return backup.main(a)
    if a.command == "diff":
        from . import diff_report
        return diff_report.main(a)
    if a.command == "status":
        return status(a)
    if a.command == "show":
        return show(a)
    if a.command == "watch":
        return watch(a)
    if a.command == "check":
        return check(a)
    if a.command == "new":
        return new(a)
    if a.command == "freeze":
        return freeze(a)
    if a.command == "longrun":
        return longrun(a)
    if a.command == "evidence":
        from . import evidence
        return evidence.main(a)
    if a.command == "cost":
        from . import cost
        return cost.main(a)
    if a.command == "strict":
        from . import strict_report
        return strict_report.main(a)
    if a.command == "prune":
        from . import prune
        return prune.main(a)
    if a.command == "analyse":
        from . import analysis_report
        if a.all:
            return analysis_report.run_all(runner.select_cases(a.cases) if a.cases else casemod.case_ids(), a.jobs)
        if not a.case:
            print("analyse takes a CASE (or --all)", file=sys.stderr)
            return 2
        if a.validate:
            return analysis_report.validate(runner.select_cases(a.case)[0], a.variant or "counts-long", a.seeds)
        return analysis_report.run(runner.select_cases(a.case), a.variant, a.json)
    return 2


if __name__ == "__main__":
    sys.exit(main())
