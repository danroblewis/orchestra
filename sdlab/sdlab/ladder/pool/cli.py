"""`uv run sdlab-ladder pool <command>`: the pool's client for agents (docs/pool.md).

    submit [--ref sdlab] [--strategies S] [--cases C] [--exclude-cases X] [--variants V] [--priority 100]
           [--by NAME] [--note TEXT] [--check-tree all|strategies|none] [--fresh] [--timeout 300] [--every-variant] [--estimate-only]
                     estimate the job (sdlab-ladder cost's busy time; small jobs may run here with
                     `sdlab-ladder run`), then submit it at the ref's commit
    status [JOB]     the pool (workers, queue by job), or one job
    results JOB [--full] [--json]
                     a job's results
    cancel JOB       cancel a job

Common: --server URL (default http://127.0.0.1:8020). The token is read from ~/.sdlab/pool.token.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from . import auth

SMALL_ITEMS = 40          # a job this small (and SMALL_SECONDS of busy time) may run locally (docs/pool.md)
SMALL_SECONDS = 120


def _call(server: str, method: str, path: str, body: dict | None = None, token: bool = True) -> tuple[int, dict]:
    req = urllib.request.Request(server.rstrip("/") + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        t = auth.token(create=False)
        if not t:
            raise SystemExit(f"no pool token at {auth.path()} (the server makes it on its first start)")
        req.add_header(auth.HEADER, t)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": str(e)}
    except urllib.error.URLError as e:
        raise SystemExit(f"cannot reach the server at {server}: {e.reason}") from None


def estimate(a) -> tuple[int, float]:
    """(items, busy seconds) of the job as this checkout sees it (sdlab-ladder cost's estimate)."""
    from .. import cost, runner, timing
    strategies, _ = runner.select_strategies(a.strategies)
    variants = [v.strip() for v in (a.variants or "").split(",") if v.strip()] or None
    case_ids = runner.select_cases(a.cases, a.exclude_cases)
    keys = cost.cells(case_ids, [s["name"] for s in strategies], variants)
    t = timing.table()
    est = timing.Estimator(t, timing.case_sets(case_ids + sorted({k[0] for k in t.latest})))
    e = cost.estimate(keys, "run", est)
    return e["items"], e["seconds"]


def submit(a) -> int:
    try:
        items, secs = estimate(a)
        small = items <= SMALL_ITEMS and secs <= SMALL_SECONDS
        print(f"estimate: {items} items, {secs / 60:.1f} CPU-minutes of busy time (sdlab-ladder cost's estimate)"
              + ("; small enough to run here: uv run sdlab-ladder run --strategies ... --cases ..." if small else ""), file=sys.stderr)
    except SystemExit as e:
        print(f"estimate: not available ({e})", file=sys.stderr)
    if a.estimate_only:
        return 0
    body = {"ref": a.ref, "strategies": a.strategies, "cases": a.cases, "exclude_cases": a.exclude_cases, "variants": a.variants,
            "priority": a.priority, "by": a.by, "note": a.note, "check_tree": a.check_tree, "fresh": a.fresh, "timeout": a.timeout,
            "every_variant": getattr(a, "every_variant", False)}
    code, got = _call(a.server, "POST", "/api/pool/jobs", body)
    if code != 202:
        print(f"refused ({code}): {got.get('error') or got.get('detail')}", file=sys.stderr)
        for f in got.get("files") or []:
            print(f"  {f}", file=sys.stderr)
        return 1
    j = got["job"]
    print(f"job {j['id']} at {j['commit'][:12]} ({j['ref']}): {j['state']}; follow it: uv run sdlab-ladder pool status {j['id']}")
    return 0


def _job_line(j: dict) -> str:
    c = j["counts"]
    done = c["done"] + c["reused"] + c["error"] + c.get("skipped", 0)
    st = ", ".join(f"{k} {v}" for k, v in sorted((j.get("statuses") or {}).items()))
    eta = f", ~{j['eta_seconds'] / 60:.0f} min left" if j.get("eta_seconds") else ""
    who = "main line" if j["kind"] == "mainline" else (j.get("by") or "agent")
    return (f"#{j['id']} {who} p{j['priority']} {(j['commit'] or '')[:10]} {j['state']}: {done}/{j['total']} done"
            f" ({c['reused']} reused, {c['error']} errors" + (f", {c['skipped']} skipped: none-short did not pass" if c.get("skipped") else "")
            + f"), {c['leased']} running, {c['queued']} waiting" + (f", {c['held']} held for their none-short" if c.get("held") else "")
            + eta + (f" [{st}]" if st else "")
            + (f" -- {j['error']}" if j.get("error") else ""))


def status(a) -> int:
    if a.job:
        code, got = _call(a.server, "GET", f"/api/pool/jobs/{a.job}", token=False)
        if code != 200:
            print(got.get("error"), file=sys.stderr)
            return 1
        print(_job_line(got["job"]))
        return 0
    code, s = _call(a.server, "GET", "/api/pool/status", token=False)
    t = s["totals"]
    print(f"main line {s['mainline']['branch']} at {(s['mainline']['head'] or '?')[:12]}; {t['leased']} running, {t['queued']} waiting"
          + (f", {t['held']} held for their none-short" if t.get("held") else "") + (f", {t['skipped']} skipped" if t.get("skipped") else ""))
    for w in s["workers"]:
        print(f"  worker {w['name']} ({w['machine']}): {'live' if w['live'] else 'gone'}, {w['leased']} items of {w.get('slots')} slots,"
              f" load {w.get('load')}, free {w.get('mem_free_mb')} MB")
    for j in s["jobs"]:
        print("  " + _job_line(j))
    return 0


def results(a) -> int:
    code, got = _call(a.server, "GET", f"/api/pool/jobs/{a.job}/results?full={int(a.full)}", token=False)
    if code != 200:
        print(got.get("error"), file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(got, indent=1))
        return 0
    for r in got["results"]:
        where = f"{r.get('machine')}/{r.get('slot')}" if r.get("machine") else r.get("state", "")
        print(f"{r['case']} {r['variant']} {r['strategy']}: {r.get('status')} ({where})"
              + (" [main line's latest]" if r.get("promoted_id") else ""))
    return 0


def cancel(a) -> int:
    code, got = _call(a.server, "DELETE", f"/api/pool/jobs/{a.job}")
    if code != 200:
        print(f"refused ({code}): {got.get('error')}", file=sys.stderr)
        return 1
    print(_job_line(got["job"]))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="sdlab-ladder pool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8020")
    sub = ap.add_subparsers(dest="pool_command", required=True)
    s = sub.add_parser("submit", help="estimate, then submit a job at a committed ref")
    s.add_argument("--ref", default="sdlab")
    s.add_argument("--strategies", default="all")
    s.add_argument("--cases")
    s.add_argument("--exclude-cases")
    s.add_argument("--variants")
    s.add_argument("--priority", type=int, default=100)
    s.add_argument("--by", help="who submits it (the agent's name)")
    s.add_argument("--note")
    s.add_argument("--check-tree", default="all", choices=("all", "strategies", "none"))
    s.add_argument("--fresh", action="store_true", help="run items even when a result with exactly their hashes is stored")
    s.add_argument("--timeout", type=float, default=300)
    s.add_argument("--every-variant", action="store_true", help="also none-long where none-short has not passed (it only confirms a short pass by default)")
    s.add_argument("--estimate-only", action="store_true")
    st = sub.add_parser("status", help="the pool, or one job")
    st.add_argument("job", nargs="?", type=int)
    r = sub.add_parser("results", help="a job's results")
    r.add_argument("job", type=int)
    r.add_argument("--full", action="store_true")
    r.add_argument("--json", action="store_true")
    c = sub.add_parser("cancel", help="cancel a job")
    c.add_argument("job", type=int)
    a = ap.parse_args(argv)
    return {"submit": submit, "status": status, "results": results, "cancel": cancel}[a.pool_command](a)
