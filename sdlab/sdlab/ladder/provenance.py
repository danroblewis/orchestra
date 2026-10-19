"""Which code a result was made with: the strategy hash of the code this process actually imported,
and where that code is in git, so every stored number can be traced back to its code.

A worker imports a strategy (and the shared discovery code) once and keeps it in memory, so the
hash recorded with a result is computed from what was imported, not from the files on disk when
the run was planned: the shared files are read when this module is imported (with the ladder's
runner, before any strategy), a strategy's own files just before it is first imported. A file
edited during a long run therefore cannot put newer code under an older hash, or the reverse.

    loaded(name) -> {strategy_hash, code_commit, code_dirty}

code_commit is the repository's HEAD then. code_dirty is None when the imported code is that
commit's; otherwise it is the hash of a patch (the imported files against HEAD), saved as
$SDLAB_LADDER_CACHE/code/<code_dirty>.patch, so `git checkout <commit> && git apply <patch>`
gives back the exact code.
"""

from __future__ import annotations

import difflib
import hashlib
import subprocess
from pathlib import Path

from . import catalog

_SHARED: dict[Path, bytes] = {p: p.read_bytes() for p in catalog._shared_files()}
_DONE: dict[str, dict] = {}


def _git(*args: str, input: bytes | None = None) -> bytes | None:
    try:
        r = subprocess.run(["git", *args], cwd=catalog.DISCOVERY, input=input, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _head_blobs(root: Path, paths: list[Path]) -> tuple[str | None, dict[Path, bytes | None]]:
    """HEAD's commit and each file's content in it (None: not in HEAD)."""
    head = _git("rev-parse", "HEAD")
    if head is None:
        return None, {}
    commit = head.decode().strip()
    inside = [p for p in paths if root in p.resolve().parents]
    rels = [p.resolve().relative_to(root).as_posix() for p in inside]
    out = _git("cat-file", "--batch", input="".join(f"{commit}:{r}\n" for r in rels).encode()) or b""
    blobs: dict[Path, bytes | None] = {p: None for p in paths}        # a file outside the repository is all patch
    pos = 0
    for p in inside:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        if len(header) == 3 and header[1] == b"blob":
            size = int(header[2])
            blobs[p] = out[nl + 1: nl + 1 + size]
            pos = nl + 1 + size + 1
        else:
            blobs[p] = None
            pos = nl + 1
    return commit, blobs


def _patch(root: Path, contents: dict[Path, bytes], blobs: dict[Path, bytes | None]) -> str:
    parts = []
    for p, now in contents.items():
        was = blobs.get(p)
        if was == now:
            continue
        rel = p.resolve().relative_to(root).as_posix() if root in p.resolve().parents else p.resolve().as_posix()
        a = (was or b"").decode(errors="replace").splitlines(keepends=True)
        b = now.decode(errors="replace").splitlines(keepends=True)
        parts.append(f"diff --git a/{rel} b/{rel}\n" + ("new file mode 100644\n" if was is None else "")
                     + "".join(difflib.unified_diff(a, b, "/dev/null" if was is None else f"a/{rel}", f"b/{rel}")))
    return "".join(parts)


def loaded(name: str) -> dict:
    """The strategy's code as this process runs it (computed before it is first imported here)."""
    if name in _DONE:
        return _DONE[name]
    own = {p: p.read_bytes() for p in catalog.code_files(name) if p not in _SHARED}
    contents = {**own, **{p: _SHARED.get(p, b"") for p in catalog.code_files(name) if p not in own}}
    out = {"strategy_hash": catalog.strategy_hash(name, contents), "code_commit": None, "code_dirty": None}
    top = _git("rev-parse", "--show-toplevel")
    if top is not None:
        root = Path(top.decode().strip()).resolve()
        commit, blobs = _head_blobs(root, list(contents))
        out["code_commit"] = commit
        patch = _patch(root, contents, blobs) if commit else ""
        if patch:
            digest = hashlib.sha256(patch.encode()).hexdigest()[:16]
            from .data import cache_root
            f = cache_root() / "code" / f"{digest}.patch"
            if not f.exists():
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(patch)
            out["code_dirty"] = digest
    _DONE[name] = out
    return out


def stale_in_memory(names: list[str]) -> bool:
    """Has this process imported one of these strategies from code that has changed since?"""
    return any(n in _DONE and _DONE[n]["strategy_hash"] != catalog.strategy_hash(n) for n in set(names))
