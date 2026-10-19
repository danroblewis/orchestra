"""Strategy isolation: no strategy imports another strategy (sdlab/CLAUDE.md, invariant 11).

A composite or derivative strategy contains its own copy of what it builds on, so the original
can be changed freely without changing (or breaking) anything built from it. Found by parsing
each strategy's code: imports of another strategy's module, and `load("name")` calls (how a
strategy is called by name).
"""

from __future__ import annotations

import ast
from pathlib import Path

STRATEGIES = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"


def names() -> set[str]:
    out = set()
    for p in STRATEGIES.iterdir():
        if p.name.startswith(("_", ".")) or p.name == "__pycache__":
            continue
        if p.is_dir() and (p / "__init__.py").exists():
            out.add(p.name)
        elif p.suffix == ".py":
            out.add(p.stem)
    return out


def _files(name: str) -> list[Path]:
    d = STRATEGIES / name
    return sorted(d.rglob("*.py")) if d.is_dir() else [STRATEGIES / f"{name}.py"]


def _module_of(path: Path) -> list[str]:
    rel = path.relative_to(STRATEGIES.parents[2]).with_suffix("")
    parts = list(rel.parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def uses(name: str, every: set[str]) -> set[str]:
    """The other strategies `name` reaches: by import, or by load("other")."""
    found = set()
    for f in _files(name):
        if "__pycache__" in f.parts:
            continue
        mod = _module_of(f)
        pkg = mod if f.name == "__init__.py" else mod[:-1]
        for node in ast.walk(ast.parse(f.read_text(), str(f))):
            targets = []
            if isinstance(node, ast.ImportFrom):
                base = pkg[: len(pkg) - (node.level - 1)] if node.level else (node.module or "").split(".")
                full = base + ((node.module or "").split(".") if node.level and node.module else [])
                targets.append(full)
                targets += [full + [a.name] for a in node.names]
            elif isinstance(node, ast.Import):
                targets += [a.name.split(".") for a in node.names]
            elif isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "load":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    targets.append(["sdlab", "discovery", "strategies", node.args[0].value])
            for t in targets:
                if t[:3] == ["sdlab", "discovery", "strategies"] and len(t) > 3 and t[3] in every and t[3] != name:
                    found.add(t[3])
    return found


def violations() -> dict[str, set[str]]:
    every = names()
    return {n: u for n in sorted(every) if (u := uses(n, every))}


if __name__ == "__main__":
    for n, u in violations().items():
        print(f"{n} -> {sorted(u)}")
