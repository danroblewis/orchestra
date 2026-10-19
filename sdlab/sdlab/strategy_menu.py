"""The editor's strategy picker: every discovery strategy with what the ladder says of it.

For each strategy: its one-line idea and full explanation (explanations.yaml), its status (active,
parked, work in progress, retire-candidate), whether it can run here, its version (the catalog's
strategy hash, and the last commit that touched its files, or "uncommitted" when they have local
changes), and its leaderboard numbers: pass rate over the cells it has run, and coverage (cells run
of all cells). Ordered best first; the best available one is the page's default.

The ladder's summary takes seconds to compute from cold, so this is worked out in a background
thread (at the server's start and on use, then again every REFRESH seconds). The last menu is kept
in $SDLAB_HOME/strategy-menu.json, so after a restart the page gets it at once (marked `cached`)
while a fresh one is worked out; with no copy at all, the page gets the names alone.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .discovery.strategies import names as discovery_names

REFRESH = 300.0
STRATEGIES = Path(__file__).parent / "discovery" / "strategies"
RAN = ("pass", "equivalent", "fail", "error", "timeout")

_state: dict = {"value": None, "at": 0.0, "busy": False}
_lock = threading.Lock()


def _saved() -> Path:
    return Path(os.environ.get("SDLAB_HOME", Path.home() / ".sdlab")) / "strategy-menu.json"


def menu() -> dict:
    """{ready, best, default, strategies: [...]}, never waiting for the ladder."""
    with _lock:
        if _state["value"] is None and not _state.get("tried_disk"):
            _state["tried_disk"] = True
            try:
                _state["value"] = {**json.loads(_saved().read_text()), "cached": True}
            except (OSError, ValueError):
                pass
        value, at, busy = _state["value"], _state["at"], _state["busy"]
        if not busy and (value is None or time.time() - at > REFRESH):
            _state["busy"] = True
            threading.Thread(target=_refresh, name="strategy-menu", daemon=True).start()
    if value is not None:
        return value
    return {"ready": False, "best": None, "default": "matrix",
            "strategies": [{"name": n, "available": True} for n in discovery_names()]}


def _refresh() -> None:
    try:
        value = compute()
        with _lock:
            _state.update(value=value, at=time.time())
        try:
            p = _saved()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(value))
            tmp.replace(p)
        except OSError:
            pass
    except Exception:  # noqa: BLE001 - the page keeps the names-only menu
        pass
    finally:
        with _lock:
            _state["busy"] = False


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=STRATEGIES, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _paths(name: str) -> list[str]:
    return [str(p) for p in (STRATEGIES / name, STRATEGIES / f"{name}.py") if p.exists()]


def version(name: str) -> dict:
    paths = _paths(name)
    if not paths:
        return {}
    last = _git("log", "-1", "--format=%h %cs", "--", *paths).split()
    dirty = bool(_git("status", "--porcelain", "--", *paths))
    return {"commit": last[0] if last else None, "date": last[1] if len(last) > 1 else None, "uncommitted": dirty}


def compute() -> dict:
    from .ladder import api as ladder
    from .ladder import explain
    from .ladder.runner import parked

    sm = ladder.summary()
    totals, park, about = sm["totals"], parked(), explain.strategies()
    have = set(discovery_names())
    rows = []
    for s in sm["strategies"]:
        n = s["name"]
        if n not in have:
            continue
        t = totals.get(n) or {}
        ran, total = sum(t.get(k, 0) for k in RAN), t.get("total", 0)
        a = about.get(n) or {}
        status = "parked" if n in park else a.get("status") or "active"
        rows.append({"name": n, "available": bool(s["available"]), "reason": s.get("reason"), "hash": s["hash"], **version(n),
                     "status": status, "parked": park.get(n), "idea": a.get("idea"), "how": a.get("how"), "note": a.get("note"),
                     "pass": t.get("pass", 0), "ran": ran, "total": total,
                     "pass_rate": (t.get("pass", 0) / ran) if ran else None, "coverage": (ran / total) if total else None})
    rows.sort(key=lambda r: (not r["available"], -(r["pass_rate"] or -1), -(r["coverage"] or 0), r["name"]))
    ok = [r for r in rows if r["available"] and r["pass_rate"] is not None]
    # the best: highest pass rate over the cells run, among strategies that have run most of the ladder
    wide = [r for r in ok if (r["coverage"] or 0) >= 0.5] or ok
    best = max(wide, key=lambda r: (r["pass_rate"], r["coverage"]))["name"] if wide else None
    return {"ready": True, "best": best, "default": best or "matrix", "strategies": rows, "at": time.time()}
