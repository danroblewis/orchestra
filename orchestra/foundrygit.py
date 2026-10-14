"""Read-only git readings for the foundry: commits ahead of main per ticket branch, the
size of each landing, how much of each landing's added lines still survive on main, and
the agent-facing documents in the checkout. Cached by the heads they depend on; nothing
here writes to the repository (AGENTS.md invariant 3)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_CACHE: dict[tuple, dict] = {}
DOC_GLOBS = ("AGENTS.md", "README.md", "CLAUDE.md", ".orchestra/teams/*.md", ".orchestra/roles/*.md", ".orchestra/spaces/*/**/*.md")
MAX_BLAME_BYTES = 200_000


def _git(repo: Path, *args: str, timeout: float = 30) -> str:
    try:
        r = subprocess.run(["git", *args], check=False, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def heads(repo: Path, base: str) -> dict[str, str]:
    """Every branch and its commit, for the cache key and the ahead counts."""
    out = _git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    return dict(line.split(" ", 1) for line in out.splitlines() if " " in line)


def ahead(repo: Path, base: str, branches: dict[str, str]) -> dict[str, int]:
    """Commits on each branch that are not on the base branch."""
    out = {}
    for b in branches:
        if b == base:
            continue
        n = _git(repo, "rev-list", "--count", f"{base}..{b}").strip()
        if n.isdigit():
            out[b] = int(n)
    return out


def landing_size(repo: Path, commit: str) -> dict | None:
    """Lines added and removed by a landing, against its first parent."""
    out = _git(repo, "diff", "--shortstat", f"{commit}^1", commit)
    if not out:
        return None
    ins = re.search(r"(\d+) insertion", out)
    dele = re.search(r"(\d+) deletion", out)
    files = re.search(r"(\d+) files? changed", out)
    return {"added": int(ins.group(1)) if ins else 0, "removed": int(dele.group(1)) if dele else 0, "files": int(files.group(1)) if files else 0}


def survival(repo: Path, base: str, commits: list[str]) -> dict[str, int]:
    """How many lines on the base branch today are attributed, first-parent, to each of the
    given commits: the surviving part of what each landing added."""
    want = {c[:10]: c for c in commits}
    counts: dict[str, int] = {c: 0 for c in commits}
    files = _git(repo, "ls-files", "-z").split("\0")
    for f in files:
        if not f:
            continue
        p = repo / f
        try:
            if not p.is_file() or p.stat().st_size > MAX_BLAME_BYTES:
                continue
        except OSError:
            continue
        out = _git(repo, "blame", "-l", "--first-parent", "-s", base, "--", f, timeout=60)
        for line in out.splitlines():
            sha = line[:40]
            full = want.get(sha[:10])
            if full:
                counts[full] += 1
    return counts


def documents(repo: Path) -> dict:
    """Agent-facing documents in the checkout: count, lines, and decided lessons."""
    seen: set[Path] = set()
    for pat in DOC_GLOBS:
        for p in repo.glob(pat):
            if p.is_file():
                seen.add(p)
    lines = 0
    for p in seen:
        try:
            lines += sum(1 for _ in p.open(errors="replace"))
        except OSError:
            pass
    lessons = [p for p in seen if "lessons" in p.parts and "decided" in p.parts]
    return {"count": len(seen), "lines": lines, "lessons_decided": len(lessons), "files": sorted(str(p.relative_to(repo)) for p in seen)}


def readings(repo: Path, base: str, landings: list[str]) -> dict:
    """All git readings at once, cached by the branch heads and the landings asked for."""
    br = heads(repo, base)
    key = (str(repo), base, tuple(sorted(br.items())), tuple(landings))
    if key in _CACHE:
        return _CACHE[key]
    r = {"heads": br, "ahead": ahead(repo, base, br), "landings": {c: landing_size(repo, c) for c in landings},
         "survival": survival(repo, base, landings) if landings else {}, "documents": documents(repo)}
    _CACHE.clear()
    _CACHE[key] = r
    return r
