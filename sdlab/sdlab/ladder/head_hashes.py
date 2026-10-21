"""What "current" means on the ladder's pages: the hashes of the `sdlab` branch's HEAD commit, not of the
working tree. Results are run at committed code (the pool runs a job's commit), and many agents keep
uncommitted edits to strategies and the harness in the shared checkout, so hashing the files on disk
marked every newly posted result stale. The summary (summary_build.py) takes a cell's case, strategy and
score hash from the main line's plan (pool/planner.py, cached per commit) and falls back to the working
tree only for a cell HEAD's plan does not have (an uncommitted new case or strategy).

    current()           {"head", "cells": {(case, variant): (case hash, score hash)}, "strategies": {name: hash}} or None
    hashes(case, variant, strategy)  (case hash, strategy hash, score hash) of HEAD, or None (not in HEAD's plan / unknown)
    version()           the commit current() describes (a summary is rebuilt when it changes)

When HEAD moves, its plan is made in the background (jobs.mainline_plan) and the last known plan is
served meanwhile, from memory or, after a restart, the newest main-line plan on disk. Only the server
turns this on (enable()); the command line keeps the working tree's hashes, and so do tests that start the
server (SDLAB_HEAD_HASHES=0, tests/conftest.py: they must not read the live pool's plans).
"""

from __future__ import annotations

import json
import os
import threading

ENABLED = False
_last: dict = {"head": None, "cells": None, "strategies": None}
_lock = threading.Lock()


def enable() -> None:
    global ENABLED
    ENABLED = os.environ.get("SDLAB_HEAD_HASHES", "1") != "0"


def _index(head: str, p: dict) -> None:
    _last.update(head=head, cells={(cid, v["name"]): (c["hash"], v["score_hash"]) for cid, c in p["cases"].items() for v in c["variants"]},
                 strategies=dict(p["strategies"]))


def _newest_on_disk() -> tuple[str, dict] | None:
    from .pool import gitcode, jobs, planner
    suffix = planner._key("x", jobs.MAINLINE_SPEC)[1:] + ".json"           # "-<spec hash>.json"
    files = sorted((gitcode.home() / "plans").glob("*" + suffix), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        try:
            return f.name[: -len(suffix)], json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return None


def current() -> dict | None:
    if not ENABLED:
        return None
    from .pool import jobs
    with _lock:
        try:
            got = jobs.mainline_plan(wait=False)                            # HEAD's, when known; else planned in the background
        except Exception:                                                   # noqa: BLE001  (git or the plan file: keep the last)
            got = None
        if got is not None and got[0] != _last["head"]:
            _index(*got)
        elif got is None and _last["head"] is None:
            old = _newest_on_disk()
            if old is not None:
                _index(*old)
        return dict(_last) if _last["head"] else None


def hashes(cur: dict | None, case: str, variant: str, strategy: str) -> tuple[str, str, str] | None:
    if cur is None:
        return None
    c, sh = cur["cells"].get((case, variant)), cur["strategies"].get(strategy)
    if c is None or sh is None:
        return None
    return c[0], sh, c[1]


def version() -> str | None:
    cur = current()
    return cur["head"] if cur else None
