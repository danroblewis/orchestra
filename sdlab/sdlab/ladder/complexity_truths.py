"""A disk cache of the true models' complexity on a variant's run (complexity.of_truth), so a server
that starts again does not lay every schedule out over every step again (minutes for the whole
ladder). Keyed by case id, case hash and variant, and by the code that counts (complexity.py and
skill.py): a change to either starts a new cache. The file is cache_root()/complexity-truths.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from .data import cache_root

_HERE = Path(__file__).resolve().parent
_lock = threading.Lock()
_state: dict = {"path": None, "code": None, "values": None}


def _code() -> str:
    h = hashlib.sha256()
    for p in (_HERE / "complexity.py", _HERE.parent / "skill.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _load() -> dict:
    p = cache_root() / "complexity-truths.json"
    if _state["path"] != p:
        code, values = _code(), {}
        try:
            got = json.loads(p.read_text())
            if got.get("code") == code:
                values = got.get("values") or {}
        except (OSError, ValueError):
            pass
        _state.update(path=p, code=code, values=values)
    return _state["values"]


def get(case_id: str, case_hash: str, variant: str) -> dict | None:
    with _lock:
        return _load().get(f"{case_id}|{case_hash}|{variant}")


def put(case_id: str, case_hash: str, variant: str, value: dict) -> None:
    with _lock:
        values = _load()
        values[f"{case_id}|{case_hash}|{variant}"] = value
        p = _state["path"]
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"code": _state["code"], "values": values}))
            tmp.replace(p)
        except OSError:
            pass
