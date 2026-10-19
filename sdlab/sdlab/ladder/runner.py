"""Running strategies on cases: what is stale (plan), and running it in parallel (execute).

Each item runs in a worker process with one numpy thread (the CLI sets OMP/OPENBLAS/VECLIB/MKL/NUMBA
thread counts to 1 before the pool starts) under a timeout. Each result records the strategy hash
of the code that actually ran (provenance.py: computed when the worker first imports the strategy,
not when the run was planned), with the git commit and the hash of any uncommitted patch. Discovery is given only what the page
would give it: the measured stocks (id, name, unit, final, group), their levels, the announced eras
and injections. A strategy that raises is recorded as an error, one that runs out of time as a
timeout; neither stops the run.
"""

from __future__ import annotations

import os
import signal
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ..discovery.api import jsonable
from . import cases as casemod
from . import catalog, data, provenance, score, store

TIMEOUT = 120


def select_cases(spec: str | None) -> list[str]:
    """Case ids from a comma list of ids, id prefixes ("003"; a parametric case's prefix is all its
    draws), draws ("039#3"), tags ("tag:loop") or levels ("level:2");
    everything when empty."""
    ids = casemod.case_ids()
    if not spec or spec == "all":
        return ids
    out: list[str] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if part.startswith("tag:"):
            out += [i for i in ids if part[4:] in casemod.load(i)["tags"]]
        elif part.startswith("level:"):
            out += [i for i in ids if str(casemod.load(i)["level"]) == part[6:]]
        else:
            got = [part] if part in ids else [i for i in ids if i.startswith(part + "-") or i.startswith(part)]
            if not got and "#" in part:                        # a draw by number: 039#3
                base, k = part.split("#", 1)
                got = [i for i in ids if "#" in i and i.split("#")[0].startswith(base) and i.split("#")[1] == k]
            if not got:
                raise SystemExit(f"no case matches {part!r}")
            out += got
    return list(dict.fromkeys(out))


PARKED = Path(__file__).with_name("parked.yaml")


def parked() -> dict[str, str]:
    """Strategies skipped by default (slow and no better than the main line): {name: why}."""
    import yaml

    return dict(yaml.safe_load(PARKED.read_text()) or {}) if PARKED.exists() else {}


def select_strategies(spec: str | None) -> tuple[list[dict], list[dict]]:
    """(available, skipped) strategy listings for a comma list, "all" (every strategy except the
    parked ones, parked.yaml) or "everything"."""
    every = {s["name"]: s for s in catalog.listing()}
    if not spec or spec == "all":
        skip = parked()
        names = [n for n in every if n not in skip]
    elif spec == "everything":
        names = list(every)
    else:
        names = [n.strip() for n in spec.split(",") if n.strip()]
    unknown = [n for n in names if n not in every]
    if unknown:
        raise SystemExit(f"unknown strategies: {', '.join(unknown)} (have: {', '.join(every)})")
    chosen = [every[n] for n in names]
    return [s for s in chosen if s["available"]], [s for s in chosen if not s["available"]]


def plan(case_ids: list[str], strategies: list[dict], variants: list[str] | None = None, force: bool = False) -> list[dict]:
    """The items to run: every (case, variant, strategy) that is stale (or every one, with force)."""
    sh = score.score_hash()
    have = {(r["case"], r["variant"], r["strategy"]): r for r in store.latest()}
    items = []
    for cid in case_ids:
        c = casemod.load(cid)
        for v in c["variants"]:
            if variants and v["name"] not in variants and v["noise"] not in variants and v["length"] not in variants:
                continue
            for s in strategies:
                why = "forced" if force else store.staleness(have.get((cid, v["name"], s["name"])), c["hash"], s["hash"], sh)
                if why:
                    items.append({"case": cid, "variant": v["name"], "strategy": s["name"], "case_hash": c["hash"],
                                  "strategy_hash": s["hash"], "score_hash": sh, "reason": why,
                                  "mode": "rescore" if why == "score_only" else "run"})
    return items


class Timeout(Exception):
    pass


def _alarm(seconds: float):
    if seconds and threading.current_thread() is threading.main_thread() and hasattr(signal, "SIGALRM"):
        def fire(*_):
            raise Timeout(f"took longer than {seconds:g} s")
        signal.signal(signal.SIGALRM, fire)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        return True
    return False


def discover(strategy: str, model: dict, d: dict) -> dict:
    from ..discovery.strategies import load as load_strategy
    stocks = casemod.page_stocks(model)
    opts: dict = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None}
    if d.get("injections"):
        opts["injections"] = [{"t": j["t"], "stock": j["stock"], "amount": j["amount"]} for j in d["injections"]]
    return load_strategy(strategy)(stocks, {"t": d["t"], "levels": d["levels"]}, opts)


def run_item(item: dict, timeout: float = TIMEOUT, run_id: int | None = None) -> dict:
    """Run (or re-score) one item: the row to store."""
    if run_id is not None:
        store.mark(run_id, item, "running")
    row = {k: item[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")}
    armed = _alarm(timeout)
    try:
        c = casemod.load(item["case"])
        noise = casemod.variant(c, item["variant"])["noise"]
        model = casemod.truth_model(c, item["variant"])
        d = data.load(c, item["variant"])
        inferred = None
        if item.get("mode") == "rescore":
            prev = next(iter(store.latest(item["case"], item["variant"], item["strategy"], found=True)), None)
            flows, seconds = (prev or {}).get("found") or [], (prev or {}).get("seconds")
            row.update({k: (prev or {}).get(k) for k in ("code_commit", "code_dirty")})     # the flows' code
        else:
            row.update(provenance.loaded(item["strategy"]))      # the code this process runs, not the plan's
            began = time.perf_counter()
            r = discover(item["strategy"], model, d)
            seconds = round(time.perf_counter() - began, 3)
            flows = jsonable(r.get("flows") or [])
            inferred = r.get("inferred_levels")
        fresh = data.load(c, item["variant"], fresh=True)
        s = score.score(c, noise, model, flows, d, fresh, inferred)
        row.update(status=s["status"], seconds=seconds, scores=jsonable(s), found=flows)
    except Timeout as e:
        row.update(status="timeout", error=str(e))
    except Exception:                                          # noqa: BLE001
        row.update(status="error", error=" ".join(traceback.format_exc().strip().splitlines()[-3:])[:2000])
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)
    return row


def execute(items: list[dict], jobs: int | None = None, timeout: float = TIMEOUT, command: str = "", on_done=None) -> list[dict]:
    """Run the items (in a process pool unless jobs == 1), storing each result as it finishes."""
    if not items:
        return []
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    run_id = store.start_run(command, items)
    rows = []
    # a terminated run (SIGTERM, SIGHUP) still marks itself finished in the store, through the finally below
    old = {}
    if threading.current_thread() is threading.main_thread():
        def stop(signum, _frame):
            raise SystemExit(128 + signum)
        for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
            if sig is not None:
                old[sig] = signal.signal(sig, stop)

    def done(item, row):
        store.record(row)
        store.mark(run_id, item, "done", row["status"])
        rows.append(row)
        if on_done:
            on_done(item, row, len(rows), len(items))

    try:
        # one item, or one job, runs here, unless this process holds older code of a strategy in memory
        if (jobs == 1 or len(items) == 1) and not provenance.stale_in_memory([i["strategy"] for i in items]):
            for it in items:
                done(it, run_item(it, timeout, run_id))
        else:
            # slow strategies and long variants first, so the pool's tail is short
            order = sorted(items, key=lambda i: (casemod.variant(casemod.load(i["case"]), i["variant"])["steps"], i["mode"] == "run"), reverse=True)
            with ProcessPoolExecutor(max_workers=min(jobs, len(items))) as pool:
                futures = {pool.submit(run_item, it, timeout, run_id): it for it in order}
                for fut in as_completed(futures):
                    it = futures[fut]
                    try:
                        row = fut.result()
                    except Exception as e:                    # noqa: BLE001  (a worker that died)
                        row = {**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")},
                               "status": "error", "error": f"worker failed: {type(e).__name__}: {e}"}
                    done(it, row)
    finally:
        store.finish_run(run_id)
        for sig, h in old.items():
            signal.signal(sig, h)
    return rows
