"""How to make ladder tests faster (docs/research/test-speed.md): measurements only, nothing changed.

    uv run python tests/study_speed.py limits [--out limits.json]
        A lower per-item time limit, read from the store's latest results: for each limit L, the
        discovery hours saved (a result that took s > L would have stopped at L: s - L saved; a timeout
        at its old limit saves limit - L), and the pass/equivalent results lost (they took longer than L),
        overall, by set (timing.set_of) and by strategy.

    uv run python tests/study_speed.py shared --cells cells.json --out shared.json [--jobs 4]
        Shared first fits: each roster:kubernetes strategy is run in-process on each cell with every
        main-line function wrapped (monkeypatched in this process only; strategy code is not changed):
        sdlab.discovery.identify.identify, sdlab.discovery.matrix.identify_one and every `main_line` a
        strategy package defines (its earned.py copy). Each call records its code hash (the source of the
        function's module and every sdlab module it reaches, byte for byte and with comments and
        docstrings stripped), the hash of its inputs (stocks, run, opts), the hash of its output and
        its seconds. One process per cell (all 42 strategies in turn), at most --jobs processes.

    uv run python tests/study_speed.py pick [--n 20]
        The representative cells (several sets, short and long variants), written as JSON to stdout.

    uv run python tests/study_speed.py report shared.json
        The saving if calls were cached by (code hash, input hash) and the risk where copies differ.

    uv run python tests/study_speed.py profile STRATEGY CASE VARIANT [--top 5]
        cProfile of one run: the top functions by own time and by cumulative time (leads only).

Single-threaded (the BLAS thread counts are set to 1 before numpy loads).
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import inspect
import json
import os
import pickle
import re
import signal
import sqlite3
import sys
import time
import types

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"

PASSING = ("pass", "equivalent")
LIMITS = (30, 60, 90, 120, 180, 240, 300)


# ---- 1. per-item limits (from the store) -------------------------------------------------------------

def _latest_times():
    from sdlab.ladder import runner, store, timing
    con = sqlite3.connect(str(store.path()))
    rows = list(con.execute("SELECT case_id, variant, strategy, status, seconds, wall_seconds FROM results WHERE latest = 1"))
    sets = timing.case_sets(sorted({r[0] for r in rows}))
    limits: dict[str, float] = {}
    out = []
    for case, variant, strategy, status, secs, wall in rows:
        if case not in limits:
            limits[case] = runner.case_timeout(case, timing.WATCH_TIMEOUT)
        d = timing.discovery_seconds(case, status, secs, wall)
        if d is None:
            continue
        out.append({"case": case, "variant": variant, "strategy": strategy, "status": status, "s": d,
                    "set": sets.get(case, "gone"), "limit": limits[case]})
    return out


def limits(args) -> None:
    rows = _latest_times()
    if args.strategies:
        from sdlab.ladder import runner
        keep = {x["name"] for x in runner.select_strategies(args.strategies)[0]}
        rows = [r for r in rows if r["strategy"] in keep]
        print(f"strategies: {args.strategies} ({len(keep)})")
    tot_set = collections.defaultdict(lambda: [0.0, 0, 0])
    for r in rows:
        tot_set[r["set"]][0] += r["s"] / 3600
        tot_set[r["set"]][1] += r["status"] in PASSING
        tot_set[r["set"]][2] += 1
    print("by set (discovery h, pass/equivalent, results):", {k: [round(v[0], 2), v[1], v[2]] for k, v in sorted(tot_set.items())})
    total = sum(r["s"] for r in rows)
    npass = sum(r["status"] in PASSING for r in rows)
    res = {"rows": len(rows), "hours": total / 3600, "passing": npass, "limits": {}}
    print(f"{len(rows)} latest results with a time, {total / 3600:.1f} discovery hours, {npass} pass/equivalent")
    print(f"{'limit':>6} {'saved h':>8} {'share':>6} {'lost':>5} {'lost/h':>7} {'over':>6}")
    for L in LIMITS:
        saved, lost, over = 0.0, [], 0
        by_set = collections.defaultdict(lambda: [0.0, 0, 0])      # saved s, lost, over
        by_strat = collections.defaultdict(lambda: [0.0, 0, 0])
        for r in rows:
            if L >= r["limit"]:
                continue
            cut = max(0.0, (r["limit"] if r["status"] == "timeout" else r["s"]) - L)
            if cut <= 0:
                continue
            gone = r["status"] in PASSING
            over += 1
            saved += cut
            for agg, k in ((by_set, r["set"]), (by_strat, r["strategy"])):
                agg[k][0] += cut
                agg[k][1] += gone
                agg[k][2] += 1
            if gone:
                lost.append((r["case"], r["variant"], r["strategy"], round(r["s"], 1)))
        h = saved / 3600
        res["limits"][L] = {"saved_hours": h, "share": saved / total, "lost": len(lost), "over": over,
                            "lost_per_hour": len(lost) / h if h else None,
                            "by_set": {k: {"saved_hours": v[0] / 3600, "lost": v[1], "over": v[2]} for k, v in sorted(by_set.items())},
                            "by_strategy": {k: {"saved_hours": v[0] / 3600, "lost": v[1], "over": v[2]}
                                            for k, v in sorted(by_strat.items(), key=lambda kv: -kv[1][0])},
                            "lost_cells": sorted(lost)}
        print(f"{L:>6} {h:>8.2f} {saved / total:>6.1%} {len(lost):>5} {len(lost) / h if h else 0:>7.1f} {over:>6}")
    # increments: what each step down from 300 costs per hour it saves
    print("step down: extra hours saved, extra passes lost, passes lost per extra hour")
    prev = None
    for L in sorted(LIMITS, reverse=True):
        cur = res["limits"][L]
        if prev is not None:
            dh, dl = cur["saved_hours"] - prev[1]["saved_hours"], cur["lost"] - prev[1]["lost"]
            print(f"  {prev[0]} -> {L}: +{dh:.2f} h, +{dl} lost, {dl / dh if dh else 0:.1f} per h")
        prev = (L, cur)
    for L in (60, 120):
        print(f"\nlimit {L}: by set (saved h, lost, over)")
        for k, v in res["limits"][L]["by_set"].items():
            print(f"  {k:<12} {v['saved_hours']:7.2f} {v['lost']:5} {v['over']:6}")
        print(f"limit {L}: top strategies by hours saved (saved h, lost, over)")
        for k, v in list(res["limits"][L]["by_strategy"].items())[:15]:
            print(f"  {k:<22} {v['saved_hours']:7.2f} {v['lost']:5} {v['over']:6}")
    old = collections.Counter(r["limit"] for r in rows)
    print("\ncurrent limits (results per limit):", dict(old))
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)


# ---- 2. shared first fits (instrumented in-process runs) --------------------------------------------

def pick(args) -> None:
    """Representative cells: per set, cells with a short and a long variant, spread over the median cost
    the 42 survivors paid there (cheap, middling and dear), from the store."""
    from sdlab.ladder import runner, store, timing
    names = [s["name"] for s in runner.select_strategies("roster:kubernetes")[0]]
    con = sqlite3.connect(str(store.path()))
    q = f"SELECT case_id, variant, SUM(seconds), COUNT(*) FROM results WHERE latest = 1 AND seconds IS NOT NULL AND strategy IN ({','.join('?' * len(names))}) GROUP BY case_id, variant"
    cells = [(c, v, s, n) for c, v, s, n in con.execute(q, names) if n >= 38]
    sets = timing.case_sets(sorted({c for c, *_ in cells}))
    want = {"tests": 8, "noisy": 4, "canonical": 3, "realistic": 2, "physics": 2, "real": 1}
    out = []
    for st, n in want.items():
        pool = sorted([x for x in cells if sets.get(x[0]) == st and x[2] < 1800], key=lambda x: x[2])
        if not pool:
            continue
        for i in range(n):
            want_long = i % 2 == 1
            j = int((i + 0.5) / n * len(pool))
            for k in list(range(j, len(pool))) + list(range(j - 1, -1, -1)):
                c, v, s, _ = pool[k]
                if ("long" in v) == want_long or st == "real":
                    if [c, v] not in [o[:2] for o in out]:
                        out.append([c, v, st, round(s, 1)])
                        break
    json.dump(out, sys.stdout, indent=1)
    print(file=sys.stderr)
    print(f"{len(out)} cells, stored total {sum(o[3] for o in out) / 3600:.2f} h over the survivors", file=sys.stderr)


def _strip(src: str) -> str:
    """Source with comments and docstrings removed (ast round trip)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            b = node.body[0]
            if isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant) and isinstance(b.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


_IMPORT = re.compile(r"^(\s*)from\s+[\w.]*?\.?(\w+)\s+import\b", re.M)


def _normalised(src: str) -> str:
    """Stripped source with every `from X.Y.leaf import` read as `from leaf import`: a vendored copy whose
    only change is its imports (rewritten to its own package) and its provenance comment reads the same."""
    return _IMPORT.sub(lambda m: f"{m.group(1)}from {m.group(2)} import", _strip(src))


def norm_hash(label: str) -> str:
    """The normalised code hash of a recorded call's function (from its label; read from disk now)."""
    import importlib
    mod, fname = label.rsplit(".", 1)
    mod = f"sdlab.discovery.{mod}" if mod in ("identify", "matrix") else f"sdlab.discovery.strategies.{mod}"
    fn = getattr(importlib.import_module(mod), fname)
    parts = []
    for m in sorted(_reach(fn.__module__)):
        try:
            parts.append(hashlib.sha1(_normalised(inspect.getsource(sys.modules[m])).encode()).hexdigest())
        except (OSError, TypeError):
            pass
    return hashlib.sha1((fname + "|" + "|".join(sorted(parts))).encode()).hexdigest()[:16]


_closure: dict[str, set] = {}


def _reach(modname: str) -> set:
    """Every sdlab module the module reaches through its globals (modules, and functions/classes defined
    in sdlab modules), itself included: a conservative closure of the code a function can call."""
    if modname in _closure:
        return _closure[modname]
    seen, todo = set(), [modname]
    while todo:
        m = todo.pop()
        if m in seen or m not in sys.modules:
            continue
        seen.add(m)
        for v in vars(sys.modules[m]).values():
            if isinstance(v, types.ModuleType):
                n = v.__name__
            else:
                n = getattr(v, "__module__", None) if isinstance(v, (types.FunctionType, type)) else None
            if n and n.startswith("sdlab") and n not in seen:
                todo.append(n)
    _closure[modname] = seen
    return seen


_hashes: dict[str, tuple] = {}


def _code_hash(fn) -> tuple[str, str]:
    """(bytes hash, stripped hash) over the function's name and the sources of every module it reaches;
    each module is hashed by content, not name, so identical copies in two packages hash the same."""
    key = f"{fn.__module__}.{fn.__qualname__}"
    if key not in _hashes:
        raw, strip = [], []
        for m in sorted(_reach(fn.__module__)):
            try:
                src = inspect.getsource(sys.modules[m])
            except (OSError, TypeError):
                src = ""
            raw.append(hashlib.sha1(src.encode()).hexdigest())
            strip.append(hashlib.sha1(_strip(src).encode()).hexdigest() if src else "")
        raw, strip = sorted(raw), sorted(strip)
        _hashes[key] = (hashlib.sha1((fn.__name__ + "|" + "|".join(raw)).encode()).hexdigest()[:16],
                        hashlib.sha1((fn.__name__ + "|" + "|".join(strip)).encode()).hexdigest()[:16])
    return _hashes[key]


def _canon(x):
    import numpy as np
    if isinstance(x, dict):
        return {str(k): _canon(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple)):
        return [_canon(v) for v in x]
    if isinstance(x, set):
        return sorted(_canon(v) for v in x)
    if isinstance(x, np.ndarray):
        return ["nd", list(x.shape), hashlib.sha1(np.ascontiguousarray(x).tobytes()).hexdigest()]
    if isinstance(x, (np.floating, np.integer, np.bool_)):
        return x.item()
    if isinstance(x, float):
        return repr(x)
    if x is None or isinstance(x, (str, int, bool)):
        return x
    if callable(x):
        return f"callable:{getattr(x, '__module__', '')}.{getattr(x, '__qualname__', repr(x))}"
    return repr(x)


def _h(x) -> str:
    try:
        return hashlib.sha1(json.dumps(_canon(x), sort_keys=True).encode()).hexdigest()[:16]
    except Exception:                                   # noqa: BLE001
        return hashlib.sha1(pickle.dumps(x)).hexdigest()[:16]


TARGETS = ("main_line", "identify", "identify_one")


_LNA_RUN = re.compile(r"(^|\.)lna[a-z_]*\.run$")


def _import_all(strategy: str) -> None:
    """Import every module of the strategy's package, so lazily imported copies are patched too."""
    import importlib
    import pkgutil
    pkg = importlib.import_module(f"sdlab.discovery.strategies.{strategy}")
    for m in pkgutil.walk_packages(getattr(pkg, "__path__", []), pkg.__name__ + "."):
        try:
            importlib.import_module(m.name)
        except Exception:                               # noqa: BLE001  (an optional extra; not ours to fix)
            pass


def _targets(strategy: str) -> dict:
    """{function object: label} for the first-fit functions this strategy's process can reach: the shared
    main line (identify.identify) and its row fit (matrix.identify_one); and inside the strategy's package,
    every `main_line` (the earned.py copies), copies of identify/identify_one (modules named identify or
    matrix), and the lna search's `discover` (modules named lna*.run, the vendored copies included)."""
    import importlib
    ident = importlib.import_module("sdlab.discovery.identify")      # the package's `identify` attribute is the function
    mat = importlib.import_module("sdlab.discovery.matrix")
    out = {ident.identify: "identify.identify", mat.identify_one: "matrix.identify_one"}
    pre = f"sdlab.discovery.strategies.{strategy}"
    for name, m in list(sys.modules.items()):
        if m is None or not name.startswith(pre + "."):             # submodules only: the package's own identify is the strategy
            continue
        short = name.split("strategies.", 1)[1]
        leaf = name.rsplit(".", 1)[-1]
        for attr, v in vars(m).items():
            if not isinstance(v, types.FunctionType) or v.__module__ != name:
                continue
            if attr == "main_line" or (attr in ("identify", "identify_one") and leaf in ("identify", "matrix")) \
                    or (attr == "discover" and _LNA_RUN.search(name)):
                out[v] = f"{short}.{attr}"
    return out


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.depth = 0

    def wrap(self, fn, label: str):
        rec = self

        def wrapper(*a, **k):
            ins = _h([a, k])
            rec.depth += 1
            t0 = time.perf_counter()
            try:
                out = fn(*a, **k)
            finally:
                rec.depth -= 1
            dt = time.perf_counter() - t0
            raw, strip = _code_hash(fn)
            rec.calls.append({"label": label, "depth": rec.depth, "code": raw, "code_stripped": strip, "inputs": ins,
                              "output": _h(out), "seconds": round(dt, 4)})
            return out

        wrapper.__wrapped_study__ = fn
        return wrapper


def _swap(v, wrappers: dict, depth: int = 0):
    """v with every target function in it (lists, tuples and dicts, 3 deep) replaced by its wrapper, or v
    itself when there is none (so the module attribute is left alone)."""
    if isinstance(v, types.FunctionType):
        return wrappers.get(v, v)
    if depth >= 3:
        return v
    if isinstance(v, (list, tuple)):
        new = [_swap(x, wrappers, depth + 1) for x in v]
        if all(a is b for a, b in zip(new, v)):
            return v
        return type(v)(new) if not hasattr(v, "_fields") else type(v)(*new)
    if isinstance(v, dict):
        new = {k: _swap(x, wrappers, depth + 1) for k, x in v.items()}
        return v if all(new[k] is v[k] for k in v) else new
    return v


def _patch(strategy: str, rec: Recorder) -> list:
    """Replace every reference to a target function in the loaded sdlab modules (module attributes and
    module-level lists, tuples and dicts of them); returns the undo list."""
    _import_all(strategy)
    targets = _targets(strategy)
    wrappers = {fn: rec.wrap(fn, label) for fn, label in targets.items()}
    undo = []
    for name, m in list(sys.modules.items()):
        if m is None or not name.startswith("sdlab"):
            continue
        for attr, v in list(vars(m).items()):
            new = _swap(v, wrappers)
            if new is not v:
                undo.append((m, attr, v))
                setattr(m, attr, new)
    return undo


def _run_cell(cell, only=None) -> list[dict]:
    from sdlab.discovery.strategies import load as load_strategy  # noqa: F401
    from sdlab.ladder import cases as casemod, data, runner
    from sdlab.ladder.real import data as real_data
    case, variant = cell[0], cell[1]
    names = [s["name"] for s in runner.select_strategies("roster:kubernetes")[0]]
    c = casemod.load(case)
    model = casemod.truth_model(c, variant)
    d = real_data.load(c, variant) if c.get("real") else data.load(c, variant)
    d = {**d, **casemod.announced(c)}
    out = []
    if only:
        names = [n for n in names if n in only]
    for name in names:
        rec = Recorder()
        undo = _patch(name, rec)
        t0 = time.perf_counter()
        err = None
        armed = runner._alarm(runner.case_timeout(case, 300.0))      # the watcher's limit, as the ladder runs it
        try:
            runner.discover(name, model, d)
        except runner.Timeout as e:
            err = f"timeout: {e}"
        except Exception as e:                          # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
        finally:
            if armed:
                signal.setitimer(signal.ITIMER_REAL, 0)
        total = time.perf_counter() - t0
        for m, attr, v in undo:
            setattr(m, attr, v)
        out.append({"case": case, "variant": variant, "set": cell[2] if len(cell) > 2 else None, "strategy": name,
                    "seconds": round(total, 3), "error": err, "calls": rec.calls})
        print(f"{case} {variant} {name}: {total:.1f}s, {len(rec.calls)} calls", file=sys.stderr, flush=True)
    return out


def shared(args) -> None:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    cells = json.load(open(args.cells))
    res = []
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = [pool.submit(_run_cell, c, args.only.split(",") if args.only else None) for c in cells]
        for f in as_completed(futs):
            res += f.result()
            json.dump(res, open(args.out, "w"))
    print(f"wrote {len(res)} runs to {args.out}")


def _store_hours() -> dict[str, float]:
    """{strategy: its latest results' discovery hours} from the store."""
    from sdlab.ladder import store
    con = sqlite3.connect(str(store.path()))
    return {k: (v or 0.0) / 3600 for k, v in con.execute("SELECT strategy, SUM(seconds) FROM results WHERE latest = 1 GROUP BY strategy")}


def report(args) -> None:
    runs = json.load(open(args.file))
    nh: dict[str, str] = {}
    for r in runs:
        for c in r["calls"]:
            if c["label"] not in nh:
                try:
                    nh[c["label"]] = norm_hash(c["label"])
                except Exception as e:                  # noqa: BLE001  (code moved since the run)
                    nh[c["label"]] = f"?{c['label']}:{type(e).__name__}"
            c["code_normalised"] = nh[c["label"]]
    total = sum(r["seconds"] for r in runs)
    print(f"{len(runs)} runs ({len({(r['case'], r['variant']) for r in runs})} cells), {total / 3600:.2f} h in all, "
          f"{sum(1 for r in runs if r['error'])} errors")
    # outermost wrapped calls only (depth 0 after the call returns): their time is not double counted
    top = [(r, c) for r in runs for c in r["calls"] if c["depth"] == 0]
    in_main = sum(c["seconds"] for _, c in top)
    print(f"time inside outermost main-line calls: {in_main / 3600:.2f} h ({in_main / total:.1%} of all run time)")
    by_label = collections.Counter()
    for _, c in top:
        by_label[c["label"].split(".")[-1] if c["label"].endswith("main_line") else c["label"]] += c["seconds"]
    print("  by function:", {k: round(v / 3600, 3) for k, v in by_label.most_common()})

    for keyname in ("code", "code_stripped", "code_normalised"):
        # a cache keyed by (code, inputs) over each cell: every call after the first with the same key is free
        saved, first, n_hits, own = 0.0, {}, 0, 0.0
        per_strat = collections.defaultdict(lambda: [0.0, 0.0])          # saved, total
        by_fn = collections.Counter()
        for r in runs:
            per_strat[r["strategy"]][1] += r["seconds"]
        for r, c in top:
            k = (r["case"], r["variant"], c[keyname], c["inputs"])
            if k in first:
                saved += c["seconds"]
                per_strat[r["strategy"]][0] += c["seconds"]
                by_fn[c["label"].rsplit(".", 1)[-1]] += c["seconds"]
                n_hits += 1
                if first[k] == r["strategy"]:
                    own += c["seconds"]
            else:
                first[k] = r["strategy"]
        print(f"\ncache keyed by ({keyname}, inputs): {n_hits} hits of {len(top)} outermost calls, saves "
              f"{saved / 3600:.3f} h = {saved / total:.1%} of all run time (repeats within one strategy's run: "
              f"{own / 3600:.3f} h = {own / total:.1%}; across strategies: {(saved - own) / total:.1%})")
        print("  saved by function:", {k: round(v / 3600, 3) for k, v in by_fn.most_common()})
        hours = _store_hours()
        proj = sum(sv / tt * hours.get(st, 0.0) for st, (sv, tt) in per_strat.items() if tt)
        print(f"  projected on the store (each strategy's saved share x its latest discovery hours): "
              f"{proj:.1f} h of {sum(hours.get(st, 0.0) for st in per_strat):.1f} h")
        if keyname == "code":
            print("  per strategy (saved s, share of its time):")
            for s, (sv, tt) in sorted(per_strat.items(), key=lambda kv: -kv[1][0] / max(kv[1][1], 1e-9)):
                print(f"    {s:<20} {sv:8.1f} {sv / tt if tt else 0:6.1%}  (total {tt:.0f} s)")

    # a finer cache: matrix.identify_one (the frozen shared row fit) at any depth, not inside an already
    # saved outermost call: an upper bound on what caching only the shared library's fit would save
    seen, fine = set(), 0.0
    for r in runs:
        for c in r["calls"]:
            if c["label"] != "matrix.identify_one":
                continue
            k = (r["case"], r["variant"], c["code"], c["inputs"])
            if k in seen:
                fine += c["seconds"]
            seen.add(k)
    print(f"\nshared-library matrix.identify_one cached alone (any depth): saves {fine / 3600:.3f} h = {fine / total:.1%}")

    # risk: the same function (by name: main_line, identify, identify_one, discover) on the same inputs,
    # reached through different code (copies that differ). Would a shared cache give the wrong answer?
    _risk(top + [(r, c) for r in runs for c in r["calls"] if c["depth"] > 0], "code")
    _risk(top + [(r, c) for r in runs for c in r["calls"] if c["depth"] > 0], "code_normalised", within=True)
    _tail(runs, top)


def _risk(calls, keyname: str, within: bool = False) -> None:
    """Groups of calls to the same function name on the same inputs reached through different code
    (keyname). within: instead, groups whose normalised code is equal although their byte code differs,
    i.e. what a normalised cache would merge: does their output agree?"""
    groups = collections.defaultdict(list)
    for r, c in calls:
        g = (r["case"], r["variant"], c["label"].rsplit(".", 1)[-1], c["inputs"]) + ((c["code_normalised"],) if within else ())
        groups[g].append((r["strategy"], c))
    same_out, diff_out, multi = 0, 0, 0
    examples = []
    for k, lst in groups.items():
        codes = {c["code"] for _, c in lst}
        if len(codes) < 2:
            continue
        multi += 1
        outs = collections.defaultdict(set)
        for s, c in lst:
            outs[c["output"]].add(f"{s}:{c['label'].split('.', 1)[-1]}")
        if len(outs) == 1:
            same_out += 1
        else:
            diff_out += 1
            if len(examples) < 15:
                examples.append((k[0], k[1], k[2], [sorted(v) for v in outs.values()]))
    what = "equal normalised code but different bytes" if within else "different code"
    print(f"\nrisk ({keyname}): {multi} (cell, function, inputs) groups reached by {what}; output identical in {same_out}, different in {diff_out}")
    for e in examples:
        print("  ", e)


def _tail(runs, top) -> None:
    # determinism: same code and inputs, different output?
    det = collections.defaultdict(set)
    for r, c in top:
        det[(r["case"], r["variant"], c["code"], c["inputs"])].add(c["output"])
    nd = sum(1 for v in det.values() if len(v) > 1)
    print(f"non-deterministic (same code, same inputs, different output): {nd} of {len(det)} keys")
    # who shares with whom: per (code, label) family
    for keyname in ("code", "code_normalised"):
        _families(top, keyname)


def _families(top, keyname: str) -> None:
    fam = collections.defaultdict(set)
    for r, c in top:
        fam[c[keyname]].add(f"{r['strategy']}:{c['label'].split('.', 1)[-1] if '.' in c['label'] else c['label']}")
    print(f"\ncode families of outermost calls by {keyname} (strategies sharing it):")
    for code, members in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        print(f"  {code} ({len(members)}): {', '.join(sorted(members))}")


# ---- 3. hot spots -----------------------------------------------------------------------------------

def profile(args) -> None:
    import cProfile
    import io
    import pstats
    from sdlab.ladder import cases as casemod, data, runner
    c = casemod.load(args.case)
    model = casemod.truth_model(c, args.variant)
    d = {**data.load(c, args.variant), **casemod.announced(c)}
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    runner.discover(args.strategy, model, d)
    pr.disable()
    print(f"{args.strategy} {args.case} {args.variant}: {time.perf_counter() - t0:.1f} s (under cProfile)")
    for key in ("tottime", "cumulative"):
        s = io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats(key).print_stats(args.top if key == "tottime" else 25)
        print(s.getvalue())


def repeats(args) -> None:
    """How often one function is called again with inputs it has already seen in one run (leads for a
    memo inside a strategy): its calls, distinct inputs, and the seconds spent on repeats."""
    import importlib
    from sdlab.ladder import cases as casemod, data, runner
    _import_all(args.strategy)
    fn = getattr(importlib.import_module(args.module), args.function)
    seen: dict = {}
    stat = [0, 0.0, 0.0]                        # calls, seconds, seconds on repeats

    def wrapper(*a, **k):
        key = _h([a, k])
        t0 = time.perf_counter()
        out = fn(*a, **k)
        dt = time.perf_counter() - t0
        stat[0] += 1
        stat[1] += dt
        if key in seen:
            stat[2] += dt
        seen[key] = seen.get(key, 0) + 1
        return out

    undo = []
    for name, m in list(sys.modules.items()):
        if m is not None and name.startswith("sdlab"):
            for attr, v in list(vars(m).items()):
                if v is fn:
                    undo.append((m, attr, v))
                    setattr(m, attr, wrapper)
    c = casemod.load(args.case)
    d = {**data.load(c, args.variant), **casemod.announced(c)}
    t0 = time.perf_counter()
    runner.discover(args.strategy, casemod.truth_model(c, args.variant), d)
    total = time.perf_counter() - t0
    for m, attr, v in undo:
        setattr(m, attr, v)
    print(f"{args.strategy} {args.case} {args.variant}: {total:.1f} s; {args.module}.{args.function}: {stat[0]} calls, "
          f"{len(seen)} distinct inputs, {stat[1]:.1f} s in it, {stat[2]:.1f} s on repeats ({stat[2] / total:.1%} of the run)")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("limits")
    a.add_argument("--out")
    a.add_argument("--strategies", help="a runner.select_strategies spec (e.g. all, roster:kubernetes); default every stored strategy")
    a = sub.add_parser("pick")
    a = sub.add_parser("shared")
    a.add_argument("--cells", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--jobs", type=int, default=4)
    a.add_argument("--only", help="comma list of strategies (default: the roster)")
    a = sub.add_parser("report")
    a.add_argument("file")
    a = sub.add_parser("profile")
    a.add_argument("strategy")
    a.add_argument("case")
    a.add_argument("variant")
    a.add_argument("--top", type=int, default=5)
    a = sub.add_parser("repeats")
    a.add_argument("module")
    a.add_argument("function")
    a.add_argument("strategy")
    a.add_argument("case")
    a.add_argument("variant")
    args = p.parse_args()
    {"repeats": repeats, "limits": limits, "pick": pick, "shared": shared, "report": report, "profile": profile}[args.cmd](args)


if __name__ == "__main__":
    main()
