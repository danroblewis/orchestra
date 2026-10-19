"""When each ladder case file was added: its first commit (date, hash, subject), from git, cached.

    dates()          {file id: {at, commit, subject, path}} for every committed case file; a file not
                     committed yet is {at: None, commit: None, seen: its mtime, path}
    refresh()        run git once and rewrite the cache (python -m sdlab.ladder.case_dates does this)
    warm()           at server start: load the cache, and refresh it in a thread if HEAD moved

The cache is a JSON file beside the result store (cache_root()/case-dates.json), keyed by the
repository's HEAD commit. A request never runs git: HEAD is read from the .git files (a cheap file
read, at most every CHECK_EVERY seconds), and when it has moved one background thread runs the single
`git log` over sdlab/ladder/cases/ again. Renames keep the date the file was first added under its
old name (git log -M).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import cases as casemod
from .data import cache_root

CASES = casemod.CASES
CHECK_EVERY = 30.0              # seconds between looks at HEAD

_state: dict = {"head": None, "entries": None, "checked": 0.0}
_lock = threading.Lock()
_busy = threading.Lock()


def cache_path() -> Path:
    return cache_root() / "case-dates.json"


def repo_root(start: Path | None = None) -> Path | None:
    """The git work tree holding the cases (the folder with .git), or None."""
    start = (start or CASES).resolve()
    for p in [start, *start.parents]:
        if (p / ".git").exists():
            return p
    return None


def head(root: Path | None = None) -> str | None:
    """The commit HEAD names, read from the .git files (no git process); None if it cannot be read."""
    root = root or repo_root()
    if root is None:
        return None
    git = root / ".git"
    try:
        if git.is_file():                                         # a worktree: "gitdir: <path>"
            git = Path(git.read_text().split(":", 1)[1].strip())
        h = (git / "HEAD").read_text().strip()
        if not h.startswith("ref:"):
            return h
        ref = h.split(":", 1)[1].strip()
        common = Path((git / "commondir").read_text().strip()) if (git / "commondir").exists() else None
        for base in [git] + ([git / common] if common else []):
            if (base / ref).exists():
                return (base / ref).read_text().strip()
            packed = base / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


def parse_log(text: str) -> dict[str, dict]:
    """`git log --reverse -M --name-status --format=@@%H|%aI|%s` output -> {path: {at, commit, subject}}
    for the commit that first added each path (a renamed path keeps its old name's first commit)."""
    first: dict[str, dict] = {}
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("@@"):
            h, at, subject = (line[2:].split("|", 2) + ["", ""])[:3]
            cur = {"commit": h, "at": utc(at), "subject": subject}
            continue
        if not line.strip() or cur is None:
            continue
        parts = line.split("\t")
        kind = parts[0]
        if kind == "A" and len(parts) >= 2:
            first.setdefault(parts[1], cur)
        elif kind.startswith("R") and len(parts) >= 3:
            first.setdefault(parts[2], first.get(parts[1], cur))
        elif kind.startswith("C") and len(parts) >= 3:
            first.setdefault(parts[2], cur)
        elif kind == "M" and len(parts) >= 2:
            first.setdefault(parts[1], cur)                       # added before the log's reach (shallow clone): earliest seen
    return first


def utc(iso: str) -> str:
    """An ISO time with any offset, as UTC (2026-10-19T07:41:57Z), so times sort as text."""
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return iso


def _git_log(root: Path) -> str:
    rel = CASES.resolve().relative_to(root).as_posix()
    return subprocess.run(["git", "-C", str(root), "log", "--reverse", "-M", "--name-status", "--format=@@%H|%aI|%s", "--", rel + "/"],
                          capture_output=True, text=True, timeout=60, check=True).stdout


def _files() -> dict[str, Path]:
    return {**casemod.case_files(), **casemod.realistic_files(), **casemod.real_files(), **casemod.physics_files(), **casemod.particles_files()}


def _entries(first: dict[str, dict], root: Path | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    by_stem: dict[tuple, dict] = {}                               # a case rewritten in the other format (.json -> .yaml) keeps its first date
    for path, f in first.items():
        d, _, name = path.rpartition("/")
        key = (d, name.rsplit(".", 1)[0])
        if key not in by_stem or (f["at"] or "") < (by_stem[key]["at"] or ""):
            by_stem[key] = f
    for cid, p in _files().items():
        rel = p.resolve().relative_to(root).as_posix() if root else p.name
        d, _, name = rel.rpartition("/")
        f = by_stem.get((d, name.rsplit(".", 1)[0])) or first.get(rel)
        if f:
            out[cid] = {**f, "path": rel}
        else:
            try:
                seen = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                seen = None
            out[cid] = {"at": None, "commit": None, "subject": None, "seen": seen, "path": rel}
    return out


def refresh() -> dict[str, dict]:
    """Run git once, rebuild every entry and write the cache. Returns the entries."""
    root = repo_root()
    h = head(root)
    try:
        first = parse_log(_git_log(root)) if root else {}
    except (OSError, subprocess.SubprocessError):
        first = {}
    entries = _entries(first, root)
    with _lock:
        _state.update(head=h, entries=entries, checked=time.time(), files=_file_key())
    try:
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"head": h, "files": _file_key(), "first": first}))
        os.replace(tmp, cache_path())
    except OSError:
        pass
    return entries


def _file_key() -> list[str]:
    return sorted(_files())


def _load_cache() -> bool:
    """Fill the state from the cache file if it was written at the current HEAD (no git)."""
    try:
        d = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return False
    root = repo_root()
    if d.get("head") != head(root):
        return False
    with _lock:
        _state.update(head=d["head"], entries=_entries(d.get("first") or {}, root), checked=time.time(), files=_file_key())
    return True


def _refresh_bg() -> None:
    if not _busy.acquire(blocking=False):
        return

    def run():
        try:
            refresh()
        finally:
            _busy.release()
    threading.Thread(target=run, daemon=True, name="case-dates").start()


def warm() -> None:
    """At server start: the cache if it is current, else a refresh in the background."""
    if not _load_cache():
        _refresh_bg()


def dates() -> dict[str, dict]:
    """The entries (see the module docstring). Never runs git in the caller's thread unless nothing at
    all is known yet (the very first call with no cache file)."""
    now = time.time()
    if _state["entries"] is None:
        if not _load_cache():
            with _busy:
                if _state["entries"] is None:
                    refresh()
        return _state["entries"]
    if now - _state["checked"] >= CHECK_EVERY:
        _state["checked"] = now
        if head() != _state["head"]:
            _refresh_bg()
        elif _state.get("files") != _file_key():                  # a case file added or removed, not committed
            with _lock:
                _state.update(entries=_entries(_first_from_entries(_state["entries"]), repo_root()), files=_file_key())
    return _state["entries"]


def _first_from_entries(entries: dict[str, dict]) -> dict[str, dict]:
    return {e["path"]: {k: e[k] for k in ("commit", "at", "subject")} for e in entries.values() if e.get("commit")}


def added_at(entry: dict | None) -> str | None:
    """When a case counts as added: its first commit, or (not committed yet) when its file was last written."""
    if not entry:
        return None
    return entry.get("at") or entry.get("seen")


if __name__ == "__main__":
    e = refresh()
    print(f"{len(e)} case files, {sum(1 for x in e.values() if x['commit'])} committed; cache at {cache_path()}")
