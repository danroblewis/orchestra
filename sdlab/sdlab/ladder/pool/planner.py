"""The items' hashes, worked out by the job's own commit: a checkout of the server's own
($SDLAB_POOL_HOME/planner, a clone of the Mac's repository) is moved to the commit, and that commit's
code (`runner.select_strategies`, `runner.select_cases`, `runner.plan(force=True)`) says which strategies,
cases and variants a spec means and what each hashes to. The working tree never enters a hash.

    plan(commit, spec) -> {"strategies": {name: hash}, "skipped": {name: why}, "parked": [...], "retired": [...],
                           "cases": {case: {"hash", "tags", "timeout", "variants": [{name, noise, length, steps, score_hash}]}}}

spec: {strategies, cases, exclude_cases, timeout}; cases "*" is every case, the heavy ones included (the
main line's plan). Plans are cached per (commit, spec) in $SDLAB_POOL_HOME/plans/. The planner runs with a
private ladder cache (an empty store): it reads no result. Tests replace RUN with a function of their own.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

from . import gitcode

LOCK = threading.Lock()

SNIPPET = r'''
import json, os, sys
from sdlab.ladder import runner
from sdlab.ladder import cases as casemod
spec = json.loads(os.environ["SDLAB_POOL_SPEC"])
try:
    strategies, skipped = runner.select_strategies(spec.get("strategies") or "all")
except SystemExit as e:
    print(json.dumps({"error": str(e)})); sys.exit(0)
try:
    if spec.get("cases") == "*":
        ids = casemod.case_ids()
    else:
        try:
            ids = runner.select_cases(spec.get("cases"), spec.get("exclude_cases"))
        except TypeError:                                  # a commit from before --exclude-cases
            ids = runner.select_cases(spec.get("cases"))
except SystemExit as e:
    print(json.dumps({"error": str(e)})); sys.exit(0)
probe = strategies[:1]
if not probe:
    from sdlab.ladder import catalog
    probe = [s for s in catalog.listing() if s["available"]][:1]
cases = {}
timeout = float(spec.get("timeout") or 300)
for it in runner.plan(ids, probe, None, force=True) if probe else []:
    c = cases.get(it["case"])
    if c is None:
        cc = casemod.load(it["case"])
        c = cases[it["case"]] = {"hash": it["case_hash"], "tags": list(cc.get("tags") or []),
                                 "timeout": runner.case_timeout(it["case"], timeout), "variants": [],
                                 "_v": {v["name"]: v for v in cc["variants"]}}
    v = c["_v"][it["variant"]]
    c["variants"].append({"name": it["variant"], "noise": v.get("noise"), "length": v.get("length"),
                          "steps": v.get("steps") or 0, "score_hash": it["score_hash"]})
for c in cases.values():
    c.pop("_v", None)
out = {"strategies": {s["name"]: s["hash"] for s in strategies}, "skipped": {s["name"]: s.get("reason") for s in skipped},
       "parked": sorted(runner.parked()), "retired": sorted(runner.retired()) if hasattr(runner, "retired") else [],
       "cases": cases}
with open(os.environ["SDLAB_POOL_OUT"], "w") as f:
    json.dump(out, f)
print(json.dumps({"ok": True}))
'''


class PlanError(Exception):
    pass


def _key(commit: str, spec: dict) -> str:
    want = {k: spec.get(k) for k in ("strategies", "cases", "exclude_cases", "timeout")}
    return f"{commit}-{hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:12]}"


def _checkout(commit: str) -> Path:
    co = gitcode.home() / "planner"
    if not (co / ".git").exists():
        co.parent.mkdir(parents=True, exist_ok=True)
        r = gitcode.git("clone", "-q", "--no-checkout", str(gitcode.root()), str(co), timeout=600)
        if r.returncode != 0:
            raise PlanError("cloning the planner's checkout failed: " + r.stderr.decode()[-400:])
    if gitcode.git("cat-file", "-t", commit, cwd=co).stdout.strip() != b"commit":
        r = gitcode.git("fetch", "-q", "--no-tags", "origin", commit, cwd=co, timeout=600)
        if r.returncode != 0:
            raise PlanError("fetching the commit failed: " + r.stderr.decode()[-400:])
    r = gitcode.git("checkout", "-q", "-f", "--detach", commit, cwd=co)
    if r.returncode != 0:
        raise PlanError("checking out the commit failed: " + r.stderr.decode()[-400:])
    gitcode.git("clean", "-fdq", cwd=co)                     # ignored files (the venv) stay
    return co / Path(gitcode.pkg_rel()).parent                # the project (pyproject.toml) holding the package


SHARED = ("data", "draws", "real", "physics", "particles")   # the ladder cache's parts named by hash: shared with the main cache


def _cache() -> Path:
    """The planner's ladder cache: a store of its own (it reads no result and must never migrate the live
    store with another commit's schema), with the simulated data, draws, twins and references of the main cache linked
    in (keyed by case hash; without them a cold plan simulates every realistic case first)."""
    from ..data import cache_root
    cache = gitcode.home() / "planner-cache"
    cache.mkdir(parents=True, exist_ok=True)
    main = cache_root()
    for part in SHARED:
        link, target = cache / part, main / part
        if target.is_dir() and not link.exists() and not link.is_symlink():
            link.symlink_to(target, target_is_directory=True)
    return cache


def _run_checkout(commit: str, spec: dict) -> dict:
    project = _checkout(commit)
    out = gitcode.home() / "plans" / (_key(commit, spec) + ".tmp")
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = _cache()
    env = {**os.environ, "SDLAB_POOL_SPEC": json.dumps(spec), "SDLAB_POOL_OUT": str(out), "SDLAB_LADDER_CACHE": str(cache),
           "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMBA_NUM_THREADS": "1"}
    env.pop("VIRTUAL_ENV", None)
    r = subprocess.run(["nice", "-n", "10", "uv", "run", "-q", "--all-extras", "--directory", str(project), "python", "-c", SNIPPET],
                       cwd=project, env=env, capture_output=True, text=True, timeout=1800)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    try:
        said = json.loads(last)
    except ValueError:
        said = {}
    if said.get("error"):
        raise PlanError(said["error"])
    if r.returncode != 0 or not said.get("ok"):
        raise PlanError(f"the planner failed at {commit[:12]}: " + (r.stderr.strip()[-600:] or last[-600:]))
    data = json.loads(out.read_text())
    out.unlink(missing_ok=True)
    return data


RUN = _run_checkout


def plan(commit: str, spec: dict) -> dict:
    """The commit's plan of a spec (cached on disk per commit and spec)."""
    f = gitcode.home() / "plans" / (_key(commit, spec) + ".json")
    if f.exists():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    with LOCK:
        if f.exists():
            return json.loads(f.read_text())
        data = RUN(commit, spec)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_text(json.dumps(data))
        tmp.replace(f)
        return data


def cells(p: dict, variants: list[str] | None = None, strategies: list[str] | None = None):
    """(case, variant entry, strategy, strategy hash, case entry) of a plan, filtered like runner.plan's variants."""
    names = strategies if strategies is not None else list(p["strategies"])
    for cid, c in p["cases"].items():
        for v in c["variants"]:
            if variants and v["name"] not in variants and v.get("noise") not in variants and v.get("length") not in variants:
                continue
            for s in names:
                if s in p["strategies"]:
                    yield cid, v, s, p["strategies"][s], c
