"""`sdlab-ladder ident CASE [--variant none-short]` and `--cases ...`: Z3's identifiability verdict
(z3_ident.py) per case and variant, beside the analysis label (analysis.py) and the scorer's verdicts
on the stored latest results (how many strategies passed, were judged 'equivalent', failed).

Discovery's side only is given to Z3 (what runner.discover passes a strategy); the truth is read
here only to print it beside the verdict and to name the variant's data. Noise-free variants only
(none-short, none-long): on noisy data the class's tolerance is the rounding, so nothing would fit.
Runs here, single-threaded, one cell after another; above SMALL_ITEMS cells it needs --local and is
logged (CLAUDE.md rule 15c; the pool runs strategies, not this tool).
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import UTC

from . import cases as casemod
from . import data as datamod
from . import z3_ident as zi

NOISE_FREE = ("none-short", "none-long")


def page(case_id: str, variant: str) -> tuple[list[dict], dict, dict, dict]:
    """(stocks, run, opts) as runner.discover builds them, and the case."""
    c = casemod.load(case_id)
    d = {**datamod.load(c, variant), **casemod.announced(c)}
    stocks = casemod.page_stocks(casemod.truth_model(c, variant))
    opts: dict = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    if d.get("injections"):
        opts["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
    if d.get("inputs"):
        opts["inputs"] = {k: list(v) for k, v in d["inputs"].items()}
    run = {"t": d["t"], "levels": d["levels"]}
    if d.get("boundary_declared"):
        run.update(boundary=d["boundary"], boundary_declared=True)
    return stocks, run, opts, c


def scorer_verdicts(case_id: str, variant: str) -> dict:
    from . import store
    return dict(Counter(r["status"] for r in store.latest(case_id, variant)))


def analysis_label(case_id: str, variant: str, compute: bool) -> str | None:
    from . import analysis
    try:
        got = analysis.get(case_id, variant, compute=compute)
    except Exception as e:                                       # noqa: BLE001  (an analysis that fails is reported, not fatal)
        return f"error: {type(e).__name__}"
    return got.get("label") if got else None


def one(case_id: str, variant: str, moves: str = "ends", slack: int = 1, cap: int = 20, budget: float = 120.0,
        hidden: bool = False, compute_analysis: bool = False, boundary: str = "kinds") -> dict:
    stocks, run, opts, _ = page(case_id, variant)
    began = time.perf_counter()
    p = zi.prepare(stocks, run, opts, moves=moves, boundary=boundary)
    prep = time.perf_counter() - began
    r = zi.enumerate_structures(p, slack=slack, cap=cap, budget=budget)
    structures = []
    for sup in r["structures"]:
        k, miss = zi.refit(p, sup)
        structures.append({"size": len(sup), "terms": zi.describe(p, sup, k), "max_residual": miss,
                           "relabelings": zi.relabelings(p, sup)})
    out = {"case": case_id, "variant": variant, "moves": moves, "boundary": boundary, "status": r["status"], "k_min": r.get("k_min"),
           "at_min": r.get("at_min"), "structures": structures, "terms": len(p.terms), "steps": p.steps,
           "decimals": p.decimals, "seconds": round(prep + r["seconds"], 3), "checks": r.get("checks"),
           "verifies": r.get("verifies"), "rejected": r.get("rejected"), "undecided": r.get("undecided"),
           "complete": r.get("complete"), "declared": p.declared, "note": p.note,
           "analysis": analysis_label(case_id, variant, compute_analysis), "scorer": scorer_verdicts(case_id, variant)}
    if hidden and r["status"] == "outside the class":
        out["hidden"] = zi.hidden_fits(p)
    return out


def _guard(a, n: int) -> bool:
    from .pool.cli import SMALL_ITEMS
    if n <= SMALL_ITEMS:
        return True
    from .pool.agent import local_log
    if not a.local:
        print(f"ident: {n} cells, above what runs here without --local ({SMALL_ITEMS}; CLAUDE.md rule 15c). The pool runs "
              f"strategies, not this tool: pass --local to run it here (logged to {local_log()}).", file=sys.stderr)
        return False
    import os
    from datetime import datetime
    entry = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "command": "ident", "argv": sys.argv[1:],
             "items": n, "busy_seconds": None, "cwd": os.getcwd(), "pid": os.getpid(), "user": os.environ.get("USER")}
    try:
        lp = local_log()
        lp.parent.mkdir(parents=True, exist_ok=True)
        with lp.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"ident: could not log the --local run ({e})", file=sys.stderr)
    print(f"ident: {n} cells, running here because of --local (logged to {local_log()})", file=sys.stderr)
    return True


def _line(r: dict) -> str:
    sc = r["scorer"]
    scorer = " ".join(f"{k} {sc[k]}" for k in ("pass", "equivalent", "fail", "error", "timeout") if sc.get(k)) or "no results"
    k = "" if r["k_min"] is None else f" k*={r['k_min']}" + (f" ({r['at_min']} of that size)" if r["at_min"] and r["at_min"] > 1 else "")
    extra = "" if r.get("complete", True) else "; enumeration cut short (budget or cap)"
    rel = (r["structures"][0].get("relabelings") or []) if r.get("structures") else []
    if rel:
        extra += f"; same-row splits the boundary allows: {len(rel)}"
    if r.get("hidden"):
        extra += f"; one hidden linear stock: {'may fit (necessary condition holds)' if r['hidden'].get('fits') else 'does not fit'}"
    return (f"{r['case']} {r['variant']} [{r['moves']}{'' if r.get('boundary', 'kinds') == 'kinds' else ', sides'}]: {r['status']}{k}; {r['seconds']:.2f} s, {r['checks']} checks{extra}"
            f" | analysis: {r['analysis'] or 'not cached'} | scorer: {scorer}")


def main(a) -> int:
    from . import runner
    ids = runner.select_cases(a.cases or a.case)
    variants = [v.strip() for v in (a.variant or "none-short").split(",") if v.strip()]
    if any(v not in NOISE_FREE for v in variants):
        print(f"ident: noise-free variants only ({', '.join(NOISE_FREE)})", file=sys.stderr)
        return 2
    cells = []
    for cid in ids:
        have = {v["name"] if isinstance(v, dict) else v for v in casemod.load(cid)["variants"]}
        cells += [(cid, v) for v in variants if v in have]
    if not cells:
        print("ident: no case has those variants", file=sys.stderr)
        return 2
    if not _guard(a, len(cells) * len(a.moves.split(","))):
        return 2
    results = []
    for cid, v in cells:
        for moves in a.moves.split(","):
            try:
                r = one(cid, v, moves=moves, slack=a.slack, cap=a.cap, budget=a.budget, hidden=a.hidden, compute_analysis=a.analyse,
                        boundary=a.boundary)
            except Exception as e:                               # noqa: BLE001  (one cell's failure is reported, the sweep goes on)
                r = {"case": cid, "variant": v, "moves": moves, "status": f"error: {type(e).__name__}: {e}", "k_min": None,
                     "at_min": None, "structures": [], "seconds": 0.0, "checks": 0, "analysis": None, "scorer": {}}
            results.append(r)
            print(_line(r), flush=True)
            if len(cells) == 1 or a.verbose:
                for s in r["structures"]:
                    print(f"    {s['size']} terms: {s['terms']}  (max residual {s['max_residual']:.2g})")
    if len(results) > 1:
        print("\nsummary (cells):")
        for moves in a.moves.split(","):
            rs = [r for r in results if r["moves"] == moves]
            print(f"  [{moves}] " + ", ".join(f"{k} {n}" for k, n in Counter(r["status"] for r in rs).most_common()))
            secs = sorted(r["seconds"] for r in rs)
            print(f"  [{moves}] seconds: median {secs[len(secs) // 2]:.2f}, max {secs[-1]:.2f}, total {sum(secs):.1f}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(results, f, indent=1, default=str)
        print(f"written {a.json}", file=sys.stderr)
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser("ident", help="Z3 identifiability proof on noise-free data: one structure in the linear class, or several (z3_ident.py)")
    p.add_argument("case", nargs="?")
    p.add_argument("--cases", help="the --cases syntax (instead of CASE)")
    p.add_argument("--variant", default="none-short", help="none-short, none-long, or both (comma list)")
    p.add_argument("--moves", default="ends", help="the move class: ends (a move reads one of its stocks), any (any column), or both: ends,any")
    p.add_argument("--boundary", default="kinds", choices=zi.BOUNDARY_RULES,
                   help="kinds: an outside term only on a declared side of its column's kind (as written; matrix); sides: any declared side (the scorer's rule)")
    p.add_argument("--slack", type=int, default=1, help="also enumerate irreducible structures this many terms larger than the smallest")
    p.add_argument("--cap", type=int, default=20, help="at most this many structures per cell")
    p.add_argument("--budget", type=float, default=120.0, help="seconds per cell (then: unknown (timeout))")
    p.add_argument("--hidden", action="store_true", help="where nothing fits: test the one-hidden-stock necessary condition")
    p.add_argument("--analyse", action="store_true", help="compute the analysis label when it is not cached")
    p.add_argument("--verbose", action="store_true", help="every structure of every cell")
    p.add_argument("--json", help="write every cell's result here")
    p.add_argument("--local", action="store_true", help="run more than 40 cells here (logged)")
