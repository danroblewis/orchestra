"""The repository the pool's code comes from (the Mac's, never GitHub): resolving refs, the agents'
checkout's uncommitted files, and git bundles for workers, made from a bare mirror the server owns
($SDLAB_POOL_HOME/mirror.git, default ~/.sdlab/pool/mirror.git) so the repository's own refs are never
written. A bundle needs a ref, and git refuses to bundle a bare commit id: the mirror holds the wanted
commit as refs/pool/want."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
PKG = Path(__file__).resolve().parents[2]            # .../sdlab/sdlab: the package
_MIRROR_LOCK = threading.Lock()


def home() -> Path:
    return Path(os.environ.get("SDLAB_POOL_HOME") or Path.home() / ".sdlab" / "pool")


def branch() -> str:
    """The branch the main line follows."""
    return os.environ.get("SDLAB_POOL_BRANCH") or "sdlab"


def git(*args: str, cwd: Path | None = None, input: bytes | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd or root(), input=input, capture_output=True, timeout=timeout)


@lru_cache(maxsize=1)
def _root(where: str) -> Path:
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=where, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"not a git repository: {where}")
    return Path(r.stdout.strip())


def root() -> Path:
    return _root(os.environ.get("SDLAB_POOL_REPO") or str(PKG))


def resolve(ref: str) -> str | None:
    """The commit a branch, tag or commit names (None: unknown)."""
    if not ref or ref.startswith("-") or len(ref) > 200:
        return None
    r = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return r.stdout.decode().strip() if r.returncode == 0 else None


def main_head() -> str | None:
    return resolve(branch())


def checkout_head() -> str | None:
    return resolve("HEAD")


def pkg_rel() -> str:
    """The package's path inside the repository (sdlab/sdlab in the orchestra repository)."""
    return PKG.relative_to(root()).as_posix()


def harness_paths() -> list[str]:
    """What every job's results also depend on: the shared discovery code, the ladder, the engine."""
    p = pkg_rel()
    return [f"{p}/discovery", f"{p}/ladder", f"{p}/sdtruth.py", f"{p}/sdtruth_expr.py", f"{p}/skill.py", f"{p}/runner.py"]


def strategy_paths(names: list[str] | None) -> list[str]:
    """Each named strategy's own package or module (None: every strategy)."""
    p = f"{pkg_rel()}/discovery/strategies"
    if names is None:
        return [p]
    out = []
    for n in names:
        if (PKG / "discovery" / "strategies" / n).is_dir():
            out.append(f"{p}/{n}")
        else:
            out.append(f"{p}/{n}.py")
    return out


def _status(paths: list[str]) -> list[tuple[str, str]]:
    r = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    if r.returncode != 0:
        return []
    out, parts = [], r.stdout.decode(errors="replace").split("\0")
    i = 0
    while i < len(parts):
        e = parts[i]
        if len(e) > 3:
            code, path = e[:2], e[3:]
            out.append((code, path))
            if code[0] in "RC":                             # a rename's second path follows
                i += 1
        i += 1
    return out


def dirty(strategies: list[str] | None, harness: bool) -> list[str]:
    """Uncommitted files of the code a job uses: the strategies' own packages (modified or untracked) and,
    with harness, the shared discovery code and the harness (tracked files only: a new untracked module
    nothing in the commit imports is not used)."""
    strat_root = f"{pkg_rel()}/discovery/strategies/"
    own = strategy_paths(strategies)
    got = [path for code, path in _status(own) if "__pycache__" not in path]
    if harness:
        for code, path in _status(harness_paths()):
            if code == "??" or "__pycache__" in path:
                continue
            if path.startswith(strat_root):                  # another strategy's package: not this job's code
                continue
            got.append(path)
    return sorted(set(got))


def is_ancestor(a: str, b: str) -> bool:
    return git("merge-base", "--is-ancestor", a, b).returncode == 0


def bundle(want: str, haves: list[str]) -> bytes:
    """A bundle holding want as refs/pool/want, less what the haves hold (a full one when they are unknown)."""
    if not SHA.match(want) or not all(SHA.match(h) for h in haves):
        raise ValueError("commits are 40 hex digits")
    if git("cat-file", "-t", want).stdout.strip() != b"commit":
        raise LookupError(f"no commit {want}")
    with _MIRROR_LOCK:
        m = home() / "mirror.git"
        if not (m / "HEAD").exists():
            m.parent.mkdir(parents=True, exist_ok=True)
            r = git("init", "-q", "--bare", str(m))
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode())
        known = [h for h in haves if git("cat-file", "-t", h).stdout.strip() == b"commit"]
        r = git("fetch", "-q", "--no-tags", str(root()), want, *known, cwd=m, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("mirror fetch failed: " + r.stderr.decode()[-500:])
        git("update-ref", "refs/pool/want", want, cwd=m)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.bundle"
            excl = [f"^{h}" for h in known if h != want]
            r = git("bundle", "create", "-q", str(out), "refs/pool/want", *excl, cwd=m, timeout=300)
            if r.returncode != 0:                            # e.g. a have that already holds want: send it whole
                r = git("bundle", "create", "-q", str(out), "refs/pool/want", cwd=m, timeout=300)
                if r.returncode != 0:
                    raise RuntimeError("bundle failed: " + r.stderr.decode()[-500:])
            return out.read_bytes()
