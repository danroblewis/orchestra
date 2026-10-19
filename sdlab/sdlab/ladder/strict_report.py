"""`sdlab-ladder strict`: fill what strict pass needs (strict.py), then report pass against strict pass.

    sdlab-ladder strict [--strategies ...] [--cases ...] [--variants ...] [--jobs N] [--all] [--no-fill]
                        [--set tests|realistic|all] [--top 10]

Fills, for the latest results of the strategies picked, (1) the long-run metrics (longrun_cache) of every
pass with no extra complexity, and (2) the reference of every cell such a pass is in (or, with --all,
of every cell of the cases picked). Then prints, per strategy over the set (default: the tests), the
pass rate and the strict pass rate over the cells it has run, how many strict verdicts are known
(coverage), and why its passes fail strict (extra complexity, long run, fresh run). Read from the
summary (api.summary), so it is what the leaderboard shows.
"""

from __future__ import annotations

import os
import time

from . import api, catalog, complexity, longrun_cache, runner, store, strict
from . import cases as casemod


def _rows(a) -> list[dict]:
    names = set(catalog.names()) if a.strategies in (None, "all") else set(a.strategies.split(","))
    cids = set(runner.select_cases(a.cases)) if a.cases else None
    return [r for r in store.latest() if r["strategy"] in names and (cids is None or r["case"] in cids)
            and (not a.variants or any(x in r["variant"] for x in a.variants.split(",")))]


def fill(a) -> None:
    rows = [r for r in _rows(a) if not casemod.is_physics(r["case"])]     # physics cases: graded by physics/, no strict reference
    rows = [r for r in rows if not casemod.is_real(r["case"])]          # real cases: graded by real/, no strict reference
    cx = complexity.for_results(rows)
    jobs = a.jobs or max(1, (os.cpu_count() or 2) - 1)
    passes = [r for r in rows if r["status"] == "pass" and cx.get(r["id"]) and cx[r["id"]]["extra"] <= 0]
    t0 = time.time()
    n = longrun_cache.fill(passes, jobs, None if a.quiet else lambda d, k: print(f"\rlong run: {d}/{k} results", end="", flush=True))
    print(f"\nlong run: {n} results graded in {time.time() - t0:.1f} s")
    if a.all:
        keys = []
        for cid in sorted({r["case"] for r in rows} if a.cases or a.strategies not in (None, "all") else [i for i in casemod.case_ids() if not casemod.is_physics(i)]):
            c = casemod.load(cid)
            keys += [(cid, c["hash"], v["name"]) for v in c["variants"] if not a.variants or any(x in v["name"] for x in a.variants.split(","))]
    else:
        keys = strict.needed(rows, cx)
    t0 = time.time()

    def progress(d, k, key, v):
        if not a.quiet:
            print(f"\rreferences: {d}/{k} ({key[0]} {key[2]}: {v.get('how') or v.get('error')}, {v.get('seconds')} s)".ljust(110)[:110], end="", flush=True)

    n = strict.fill(keys, jobs, progress)
    print(f"\nreferences: {n} cells computed in {time.time() - t0:.1f} s ({len(set(keys))} needed)")


def _is_real(c: dict) -> bool:
    return bool(c.get("example") or "realistic" in (c.get("tags") or []))


def table(set_name: str = "tests", variants: str | None = None) -> list[dict]:
    """Per strategy over the set: ran, pass, strict, known (strict verdicts known), and the reasons passes
    fail strict."""
    sm = api.summary()
    real = {c["id"]: _is_real(c) for c in sm["cases"]}
    phys = {c["id"] for c in sm["cases"] if c.get("physics")}
    by: dict[str, dict] = {}
    for x in sm["cells"]:
        if casemod.is_real(x["case"]):
            continue
        if not x["status"] or x["case"] in phys or (set_name != "all" and (set_name == "realistic") != real.get(x["case"], False)):
            continue
        if variants and not any(v in x["variant"] for v in variants.split(",")):
            continue
        t = by.setdefault(x["strategy"], {"name": x["strategy"], "ran": 0, "pass": 0, "strict": 0, "known": 0, "pending": 0,
                                          "extra": 0, "longrun": 0, "fresh": 0, "pass_fails": 0})
        t["ran"] += 1
        t["pass"] += x["status"] == "pass"
        t["strict"] += x.get("strict") == 1
        t["known"] += x.get("strict") is not None
        t["pending"] += x["status"] == "pass" and x.get("strict") is None
        if x["status"] == "pass" and x.get("strict") == 0:
            t["pass_fails"] += 1
            for r in (x.get("strict_why") or "").split(","):
                if r in strict.REASONS:
                    t[r] += 1
    for t in by.values():
        t["pass_rate"] = t["pass"] / t["ran"]
        t["strict_rate"] = t["strict"] / t["known"] if t["known"] else None
    return list(by.values())


def report(a) -> None:
    rows = [t for t in table(a.set, a.variants) if a.strategies in (None, "all") or t["name"] in a.strategies.split(",")]
    pct = lambda v: "   -  " if v is None else f"{100 * v:5.1f}%"  # noqa: E731
    head = f"{'strategy':28s} {'ran':>5s} {'pass':>6s} {'strict':>6s} {'known':>6s} {'pending':>7s}  passes failing strict: extra / long run / fresh"
    for title, key in (("by pass rate", "pass_rate"), ("by strict pass rate", "strict_rate")):
        print(f"\nTop {a.top} {title} ({a.set}{', variants ' + a.variants if a.variants else ''}; rates over the cells run, strict over the verdicts known):")
        print(head)
        for t in sorted(rows, key=lambda t: (t[key] is not None, t[key] or 0, t["pass_rate"]), reverse=True)[: a.top]:
            print(f"{t['name']:28s} {t['ran']:5d} {pct(t['pass_rate'])} {pct(t['strict_rate'])} {t['known'] / t['ran']:6.0%} {t['pending']:7d}"
                  f"  {t['pass_fails']:4d}: {t['extra']} / {t['longrun']} / {t['fresh']}")


def main(a) -> int:
    if not a.no_fill:
        fill(a)
    report(a)
    return 0
