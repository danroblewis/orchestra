"""What agents use (CLAUDE.md rule 15c, docs/pool.md "Small tests stay local; sweeps go to the pool"):

    sdlab-ladder submit [--strategies S] [--cases C] [--exclude-cases X] [--variants V] [--stale] [--ref BRANCH] [--by NAME]
                        a job for the pool at a committed ref (default: this checkout's branch): the
                        estimate first, then the job id. Refused while the code the job uses has
                        uncommitted changes here, or while a feature branch lacks the sdlab HEAD.
    sdlab-ladder job ID [--wait] [--json]
                        a job's progress; with --wait each item as it finishes, then the summary
                        `sdlab-ladder run` prints

and the size guard of `sdlab-ladder run` and `sync` (guard): a run above SMALL_ITEMS items or
SMALL_SECONDS of busy time (sdlab-ladder cost's estimate) is refused with the submit command to use
instead; --local runs it anyway and is logged to ~/.sdlab/local-runs.log.

Without --stale a job runs every cell it names again, as `run` does (the server's `fresh`); with --stale it
runs only cells that have no stored result with exactly their hashes, as `sync` does.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .cli import SMALL_ITEMS, SMALL_SECONDS, _call, _job_line

FINAL = ("done", "cancelled", "failed")
ORDER = ("pass", "equivalent", "fail", "error", "timeout")
POLL = 10.0


def local_log() -> Path:
    return Path(os.environ.get("SDLAB_LOCAL_RUNS_LOG") or Path.home() / ".sdlab" / "local-runs.log")


# ---- the size guard of run and sync ----

def busy_seconds(items: list[dict]) -> float:
    """The busy time of runner.plan's items, each run or re-scored as planned (sdlab-ladder cost's estimate)."""
    from .. import cost, timing
    t = timing.table()
    case_ids = sorted({i["case"] for i in items})
    est = timing.Estimator(t, timing.case_sets(case_ids + sorted({k[0] for k in t.latest})))
    total = 0.0
    for mode in ("run", "rescore"):
        keys = [(i["case"], i["variant"], i["strategy"]) for i in items if i["mode"] == mode]
        if keys:
            total += cost.estimate(keys, mode, est)["seconds"]
    return total


def _submit_line(a, command: str) -> str:
    parts = ["uv run sdlab-ladder submit", f"--strategies {a.strategies}"]
    for flag, v in (("--cases", a.cases), ("--exclude-cases", getattr(a, "exclude_cases", None)), ("--variants", a.variants)):
        if v:
            parts.append(f"{flag} {v}")
    if command == "sync":
        parts.append("--stale")
    return " ".join(parts) + " --by <you>"


def guard(a, items: list[dict], command: str) -> bool:
    """May this run go ahead here? False (with the message) when it is above the local limit and --local
    was not given; with --local it goes ahead and is logged."""
    n = len(items)
    secs = None if n > SMALL_ITEMS else busy_seconds(items)
    small = n <= SMALL_ITEMS and secs is not None and secs <= SMALL_SECONDS
    if small:
        return True
    size = f"{n} items" + (f", about {secs / 60:.1f} CPU-minutes" if secs is not None else "")
    limit = f"at most {SMALL_ITEMS} items and {SMALL_SECONDS / 60:g} CPU-minutes"
    if not getattr(a, "local", False):
        print(f"{command}: {size}: above what runs here ({limit}; CLAUDE.md rule 15c). Commit, then submit it to the pool:\n"
              f"  {_submit_line(a, command)}\n"
              f"  then: uv run sdlab-ladder job <ID> --wait\n"
              f"(--local runs it here anyway; it is logged to {local_log()})", file=sys.stderr)
        return False
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "command": command, "argv": sys.argv[1:],
             "items": n, "busy_seconds": None if secs is None else round(secs, 1), "cwd": os.getcwd(), "pid": os.getpid(),
             "user": os.environ.get("USER")}
    try:
        p = local_log()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        print(f"{command}: could not log the --local run ({e})", file=sys.stderr)
    print(f"{command}: {size}, above the local limit ({limit}): running here because of --local (logged to {local_log()})", file=sys.stderr)
    return True


# ---- submit ----

def _git(*args: str) -> str | None:
    from . import gitcode
    r = gitcode.git(*args)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def _estimate(a) -> tuple[int, float]:
    """(items, busy seconds) of the job as this checkout sees it: every cell, or with --stale what is stale."""
    from .. import runner
    from .cli import estimate
    if not a.stale:
        return estimate(a)
    strategies, _ = runner.select_strategies(a.strategies, parked_too=True)
    variants = [v.strip() for v in (a.variants or "").split(",") if v.strip()] or None
    items = runner.plan(runner.select_cases(a.cases, a.exclude_cases), strategies, variants)
    return len(items), busy_seconds(items) if items else 0.0


def submit(a) -> int:
    from . import gitcode
    ref = a.ref or _git("symbolic-ref", "--quiet", "--short", "HEAD") or _git("rev-parse", "HEAD")
    commit = gitcode.resolve(ref) if ref else None
    if commit is None:
        print(f"submit: no commit {ref!r} in this repository", file=sys.stderr)
        return 1
    if a.check_tree != "none" and commit == gitcode.checkout_head():     # a job runs its commit, never this working tree
        names = None if a.strategies in ("all", "everything") or a.strategies.startswith("roster:") else \
            [n.strip() for n in a.strategies.split(",") if n.strip()]
        bad = gitcode.dirty(names, harness=a.check_tree == "all")
        if bad:
            print(f"submit: refused: uncommitted changes in the code this job uses (a job runs {commit[:10]}, not this working tree):",
                  file=sys.stderr)
            for f in bad[:50]:
                print(f"  {f}", file=sys.stderr)
            print("commit them first (CLAUDE.md rule 12: a private index), or --check-tree strategies to check only the job's own"
                  " strategies (other agents' uncommitted harness edits)", file=sys.stderr)
            return 1
    main = gitcode.main_head()
    if main and commit != main and not gitcode.is_ancestor(main, commit):
        behind = _git("rev-list", "--count", f"{commit}..{main}")
        msg = (f"submit: {ref} ({commit[:10]}) lacks {behind or 'some'} commits of {gitcode.branch()} ({main[:10]}):"
               f" bring it up to date (git merge {gitcode.branch()}) and commit, so its results are comparable")
        if ref != gitcode.branch() and not a.behind_ok:
            print(msg + "; --behind-ok submits it as it is (e.g. an older commit on purpose)", file=sys.stderr)
            return 1
        print(msg.replace("submit:", "submit: note:"), file=sys.stderr)
    try:
        items, secs = _estimate(a)
        what = "stale cells" if a.stale else "items"
        print(f"estimate: {items} {what}, {secs / 60:.1f} CPU-minutes of busy time (sdlab-ladder cost's estimate)"
              + ("; small enough to run here with sdlab-ladder run" if items <= SMALL_ITEMS and secs <= SMALL_SECONDS else ""), file=sys.stderr)
        if a.stale and not items:
            print("estimate: nothing is stale here; the server plans the job at its commit and reuses what it has", file=sys.stderr)
    except SystemExit as e:
        print(f"estimate: not available ({e})", file=sys.stderr)
    if a.estimate_only:
        return 0
    body = {"ref": ref, "strategies": a.strategies, "cases": a.cases, "exclude_cases": a.exclude_cases, "variants": a.variants,
            "priority": a.priority, "by": a.by or os.environ.get("SDLAB_AGENT") or f"{os.environ.get('USER', 'agent')}@{ref}",
            "note": a.note, "check_tree": a.check_tree, "fresh": not a.stale, "timeout": a.timeout}
    code, got = _call(a.server, "POST", "/api/pool/jobs", body)
    if code != 202:
        print(f"submit: refused by the server ({code}): {got.get('error') or got.get('detail')}", file=sys.stderr)
        for f in got.get("files") or []:
            print(f"  {f}", file=sys.stderr)
        return 1
    j = got["job"]
    if j.get("commit") and j["commit"] != commit:
        print(f"submit: note: the server resolved {ref} to {j['commit'][:10]}, not {commit[:10]}", file=sys.stderr)
    print(f"job {j['id']} at {(j.get('commit') or '')[:12]} ({j['ref']}): {j['state']}")
    print(f"follow it: uv run sdlab-ladder job {j['id']} --wait", file=sys.stderr)
    return 0


# ---- job ----

def _results(server: str, job_id: int, full: bool = False) -> list[dict]:
    code, got = _call(server, "GET", f"/api/pool/jobs/{job_id}/results?full={int(full)}", token=False)
    return got.get("results") or [] if code == 200 else []


def _status(r: dict) -> str:
    return r.get("status") or ("error" if r.get("state") == "error" else "-")


def _item_line(r: dict, n: int, total: int) -> str:
    where = f" on {r['machine']}/{r.get('slot')}" if r.get("machine") else (" (reused)" if r.get("state") == "reused" else "")
    secs = f" ({r['seconds']:.2f} s)" if r.get("seconds") is not None else ""
    err = f" {r['error']}" if r.get("error") else ""
    return f"  [{n}/{total}] {r['case']} {r['variant']} {r['strategy']}: {_status(r)}{secs}{where}{err}"


def _took(j: dict) -> float | None:
    def ts(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp() if x else None
    start, end = ts(j.get("started") or j.get("created")), ts(j.get("finished"))
    return None if start is None else (end or time.time()) - start


def summary(j: dict, results: list[dict]) -> str:
    """`sdlab-ladder run`'s last line, for a job: how many, how long, the statuses."""
    counts: dict = {}
    for k in [*ORDER, *(_status(r) for r in results)]:
        counts.setdefault(k, 0)
    for r in results:
        counts[_status(r)] += 1
    took = _took(j)
    reused = sum(r.get("state") == "reused" for r in results)
    return (f"job {j['id']}: {len(results)} done" + (f" in {took:.1f} s" if took is not None else "") + ": "
            + ", ".join(f"{v} {k}" for k, v in counts.items() if v) + (f" ({reused} reused)" if reused else "")
            + ("" if j["state"] == "done" else f" [{j['state']}" + (f": {j['error']}" if j.get("error") else "") + "]"))


def job(a) -> int:
    seen: set = set()
    while True:
        code, got = _call(a.server, "GET", f"/api/pool/jobs/{a.job}", token=False)
        if code != 200:
            print(f"job {a.job}: {got.get('error')}", file=sys.stderr)
            return 1
        j = got["job"]
        final = j["state"] in FINAL
        if not a.wait or final:
            break
        if not a.json and not a.quiet:
            fresh = [r for r in _results(a.server, a.job) if r.get("item_id") not in seen]
            for r in fresh:
                seen.add(r.get("item_id"))
                print(_item_line(r, len(seen), j.get("total") or 0), file=sys.stderr)
            print(_job_line(j), file=sys.stderr)
        time.sleep(a.every)
    results = _results(a.server, a.job, full=a.json)
    if a.json:
        print(json.dumps({"job": j, "results": results}, indent=1))
        return 0 if j["state"] == "done" else (1 if final else 0)
    if a.wait and not a.quiet:
        for r in results:
            if r.get("item_id") not in seen:
                seen.add(r.get("item_id"))
                print(_item_line(r, len(seen), j.get("total") or 0), file=sys.stderr)
    print(_job_line(j))
    if final:
        print(summary(j, results))
    return 0 if j["state"] in ("done", "queued", "running", "planning") else 1


def add_parsers(sub) -> None:
    """`submit` and `job` on sdlab-ladder's parser (cli.py)."""
    s = sub.add_parser("submit", help="submit strategies x cases x variants to the CPU pool at a committed ref (pool/agent.py)")
    s.add_argument("--strategies", default="all")
    s.add_argument("--cases")
    s.add_argument("--exclude-cases")
    s.add_argument("--variants")
    s.add_argument("--stale", action="store_true", help="only cells with no stored result of exactly their hashes (as sync); default: every cell again (as run)")
    s.add_argument("--ref", help="the branch or commit to run (default: this checkout's branch)")
    s.add_argument("--by", help="who submits it (default $SDLAB_AGENT, else user@ref)")
    s.add_argument("--note")
    s.add_argument("--priority", type=int, default=100)
    s.add_argument("--timeout", type=float, default=300, help="seconds per item")
    s.add_argument("--check-tree", default="all", choices=("all", "strategies", "none"),
                   help="refuse while these have uncommitted changes here: the strategies and the harness (all), the strategies only, nothing")
    s.add_argument("--behind-ok", action="store_true", help="submit a branch that lacks the sdlab HEAD anyway")
    s.add_argument("--estimate-only", action="store_true")
    s.add_argument("--server", default="http://127.0.0.1:8020")
    j = sub.add_parser("job", help="a pool job's progress and results (pool/agent.py)")
    j.add_argument("job", type=int)
    j.add_argument("--wait", action="store_true", help="until it ends, each item as it finishes, then run's summary")
    j.add_argument("--json", action="store_true", help="the job and its results (with scores and found flows) as JSON")
    j.add_argument("--every", type=float, default=POLL, help="seconds between polls with --wait")
    j.add_argument("--quiet", action="store_true")
    j.add_argument("--server", default="http://127.0.0.1:8020")
