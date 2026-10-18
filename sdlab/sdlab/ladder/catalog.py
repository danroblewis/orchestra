"""The strategies the ladder runs: every module in sdlab/discovery/strategies, listed afresh each time
(so a strategy added there is picked up by the next sync), with a hash of the code it runs.

A strategy's hash covers its own module (a file, or a package folder), any sibling strategy module
it imports (`from .other import ...`), and the rest of sdlab/discovery (everything outside the
strategies folder, plus strategies/__init__.py): a change to any of them makes its results stale.
Other strategies' modules are left out, so adding a strategy does not re-run the others.

A strategy that cannot be imported (an optional package missing) is listed as unavailable, with
the reason, and skipped.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path

from ..discovery import strategies as _strategies

DISCOVERY = Path(_strategies.__file__).resolve().parents[1]
STRATEGIES = DISCOVERY / "strategies"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SIBLING = re.compile(r"from\s+\.(\w+)\s+import|from\s+sdlab\.discovery\.strategies\.(\w+)\s+import|from\s+\.\s+import\s+(\w+)")


def names() -> list[str]:
    return [n for n in _strategies.names() if NAME_RE.match(n)]


def _files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
    return [path] if path.exists() else []


def _module_path(name: str) -> Path:
    return STRATEGIES / name if (STRATEGIES / name).is_dir() else STRATEGIES / f"{name}.py"


def _own_files(name: str, seen: set | None = None) -> list[Path]:
    seen = set() if seen is None else seen
    if name in seen:
        return []
    seen.add(name)
    files = _files(_module_path(name))
    for p in list(files):
        for m in SIBLING.finditer(p.read_text(errors="replace")):
            other = next(g for g in m.groups() if g)
            if other in names() and other != name:
                files += _own_files(other, seen)
    return files


def _shared_files() -> list[Path]:
    return sorted(p for p in DISCOVERY.rglob("*.py") if "__pycache__" not in p.parts
                  and (STRATEGIES not in p.parents or p == STRATEGIES / "__init__.py"))


def strategy_hash(name: str) -> str:
    h = hashlib.sha256()
    for p in sorted(set(_own_files(name))) + _shared_files():
        h.update(p.relative_to(DISCOVERY).as_posix().encode() + b"\n" + p.read_bytes() + b"\n")
    return h.hexdigest()[:16]


def availability(name: str) -> tuple[bool, str | None]:
    """(True, None) if the strategy imports and has identify(); else (False, why)."""
    try:
        mod = importlib.import_module(f"{_strategies.__name__}.{name}")
    except ModuleNotFoundError as e:
        return False, f"missing package: {e.name}"
    except Exception as e:                                    # noqa: BLE001
        return False, f"import failed: {type(e).__name__}: {e}"
    if not callable(getattr(mod, "identify", None)):
        return False, "no identify(stocks, run, opts)"
    return True, None


def listing(check: bool = True) -> list[dict]:
    """[{name, hash, available, reason}] for every strategy module."""
    out = []
    for n in names():
        ok, why = availability(n) if check else (True, None)
        out.append({"name": n, "hash": strategy_hash(n), "available": ok, "reason": why})
    return out
