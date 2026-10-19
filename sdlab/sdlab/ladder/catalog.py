"""The strategies the ladder runs: every module in sdlab/discovery/strategies, listed afresh each time
(so a strategy added there is picked up by the next sync), with a hash of the code it runs.

A strategy's hash covers its own module (a file, or a package folder), any sibling strategy module
it imports (`from .other import ...`), and the rest of sdlab/discovery (everything outside the
strategies folder, plus strategies/__init__.py): a change to any of them makes its results stale.
Other strategies' modules are left out, so adding a strategy does not re-run the others.

A strategy that cannot be imported (an optional package missing) is listed as unavailable, with
the reason, and skipped. Listing imports nothing: availability is read from the source (the packages
its files import at module level, outside try blocks, looked up with importlib.util.find_spec, and an
`identify` defined or imported in its module), and the listing is cached in memory until a file
under sdlab/discovery changes (its path, size or modification time), so a page can ask often.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

from ..discovery import strategies as _strategies

DISCOVERY = Path(_strategies.__file__).resolve().parents[1]
STRATEGIES = DISCOVERY / "strategies"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
SIBLING = re.compile(r"from\s+\.(\w+)\s+import|from\s+sdlab\.discovery\.strategies\.(\w+)\s+import|from\s+\.\s+import\s+(\w+)")


def names() -> list[str]:
    return [n for n in _strategies.names() if NAME_RE.match(n)]


def _key() -> tuple:
    """Every file under sdlab/discovery with its size and modification time: the cache key."""
    out = []
    for p in sorted(DISCOVERY.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        st = p.stat()
        out.append((p.as_posix(), st.st_size, st.st_mtime_ns))
    return tuple(out)


def _files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
    return [path] if path.exists() else []


def _module_path(name: str) -> Path:
    """The strategy's package folder or file, found without importing it (it may live on another
    path of the strategies package)."""
    if (STRATEGIES / name).is_dir() or (STRATEGIES / f"{name}.py").exists():
        return STRATEGIES / name if (STRATEGIES / name).is_dir() else STRATEGIES / f"{name}.py"
    spec = importlib.util.find_spec(f"{_strategies.__name__}.{name}")
    if spec is None or not spec.origin:
        return STRATEGIES / f"{name}.py"
    origin = Path(spec.origin)
    return origin.parent if spec.submodule_search_locations else origin


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


def code_files(name: str) -> list[Path]:
    """The files a strategy's hash covers: its own (and imported siblings'), then the shared ones."""
    return sorted(set(_own_files(name))) + _shared_files()


def strategy_hash(name: str, contents: dict[Path, bytes] | None = None) -> str:
    """The hash of a strategy's code: as on disk, or as given in contents (path -> bytes), e.g. the
    code a process imported earlier (provenance.py)."""
    h = hashlib.sha256()
    for p in code_files(name):
        rel = p.relative_to(DISCOVERY).as_posix() if DISCOVERY in p.parents else p.name
        h.update(rel.encode() + b"\n" + (contents[p] if contents and p in contents else p.read_bytes()) + b"\n")
    return h.hexdigest()[:16]


def _required(tree: ast.Module) -> set[str]:
    """Top-level packages a module imports at module level, outside try blocks (absolute imports only)."""
    out: set[str] = set()

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.Import):
                out.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                out.add(node.module.split(".")[0])
            elif isinstance(node, ast.If):                      # if TYPE_CHECKING / version checks: both arms count
                visit(node.body)
                visit(node.orelse)
    visit(tree.body)
    return out


def availability(name: str) -> tuple[bool, str | None]:
    """(True, None) if every package its files import is installed and its module has identify();
    else (False, why). Nothing is imported."""
    mod = _module_path(name)
    main = mod / "__init__.py" if mod.is_dir() else mod
    try:
        trees = {p: ast.parse(p.read_text(errors="replace")) for p in _own_files(name)}
    except SyntaxError as e:
        return False, f"import failed: SyntaxError: {e}"
    for tree in trees.values():
        for pkg in sorted(_required(tree)):
            if pkg in ("sdlab", "__future__") or pkg in sys.stdlib_module_names:
                continue
            if importlib.util.find_spec(pkg) is None:
                return False, f"missing package: {pkg}"
    tree = trees.get(main)
    defined = tree is not None and any(
        (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "identify")
        or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "identify" for t in n.targets))
        or (isinstance(n, ast.ImportFrom) and any((a.asname or a.name) == "identify" for a in n.names))
        for n in tree.body)
    return (True, None) if defined else (False, "no identify(stocks, run, opts)")


_cache: dict = {}


def listing(check: bool = True) -> list[dict]:
    """[{name, hash, available, reason}] for every strategy module (cached until a file changes)."""
    key = (_key(), tuple(names()), tuple(map(str, _strategies.__path__)), check)
    if _cache.get("key") != key:
        out = []
        for n in names():
            ok, why = availability(n) if check else (True, None)
            out.append({"name": n, "hash": strategy_hash(n), "available": ok, "reason": why})
        _cache.update(key=key, value=out)
    return [dict(x) for x in _cache["value"]]
