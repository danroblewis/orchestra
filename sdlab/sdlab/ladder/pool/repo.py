"""A worker's code: one bare object store per worker ($HOME/repo.git), fed only by the server's bundles (the
Mac's repository; never GitHub), and checkouts that share its objects (`git clone --shared`): one per slot
($HOME/slot-<n>) and the supervisor's own ($HOME/self). Each commit fetched is kept as refs/pool/c/<sha>,
so its objects stay. A checkout's venv is synced (`uv sync --all-extras`) when its uv.lock or
pyproject.toml differ from the last sync's."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .client import Client

PROJECT = os.environ.get("SDLAB_POOL_PROJECT") or "sdlab"      # the project (pyproject.toml) inside the repository
SHA_LEN = 40


class CodeError(Exception):
    """A commit that cannot be had or checked out (not the server being down: that is client.Down)."""


def _git(*args: str, cwd: Path | None = None, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def uv_path() -> str:
    for p in (shutil.which("uv"), str(Path.home() / ".local" / "bin" / "uv"), str(Path.home() / ".cargo" / "bin" / "uv")):
        if p and Path(p).exists():
            return p
    raise CodeError("uv not found (PATH, ~/.local/bin, ~/.cargo/bin)")


class Repo:
    def __init__(self, home: Path, client: Client):
        self.home = Path(home)
        self.git_dir = self.home / "repo.git"
        self.client = client
        self.lock = threading.Lock()
        self.sync_locks: dict[str, threading.Lock] = {}
        if not (self.git_dir / "HEAD").exists():
            self.git_dir.parent.mkdir(parents=True, exist_ok=True)
            r = _git("init", "-q", "--bare", str(self.git_dir))
            if r.returncode != 0:
                raise CodeError(r.stderr)

    def g(self, *args: str, timeout: float = 600) -> subprocess.CompletedProcess:
        return _git("--git-dir", str(self.git_dir), *args, timeout=timeout)

    def has(self, sha: str) -> bool:
        return self.g("cat-file", "-t", sha).stdout.strip() == "commit"

    def tips(self, n: int = 20) -> list[str]:
        r = self.g("for-each-ref", "--sort=-committerdate", f"--count={n}", "--format=%(objectname)", "refs/pool/c/")
        return [x for x in r.stdout.split() if len(x) == SHA_LEN]

    def ensure(self, sha: str) -> None:
        """Have the commit (a bundle from the server, without what the newest commits here already hold)."""
        if len(sha) != SHA_LEN or not all(c in "0123456789abcdef" for c in sha):
            raise CodeError(f"not a commit id: {sha!r}")
        with self.lock:
            if self.has(sha):
                return
            data = self.client.bundle(sha, self.tips())
            with tempfile.TemporaryDirectory(dir=self.home) as d:
                f = Path(d) / "c.bundle"
                f.write_bytes(data)
                r = self.g("fetch", "-q", "--no-tags", str(f), f"refs/pool/want:refs/pool/c/{sha}")
                if r.returncode != 0:
                    raise CodeError(f"fetching the bundle of {sha[:12]} failed: {r.stderr.strip()[-400:]}")
            if not self.has(sha):
                raise CodeError(f"the bundle did not hold {sha[:12]}")

    def tree(self, sha: str, path: str) -> str | None:
        """The git object a path names at a commit (None: it does not exist there)."""
        r = self.g("rev-parse", "--verify", "--quiet", f"{sha}:{path}")
        return r.stdout.strip() if r.returncode == 0 else None

    def checkout(self, dest: Path, sha: str) -> None:
        """Make dest a clean checkout of the commit (ignored files, the venv among them, stay)."""
        dest = Path(dest)
        if not (dest / ".git").exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = _git("clone", "-q", "--shared", "--no-checkout", str(self.git_dir), str(dest))
            if r.returncode != 0:
                raise CodeError(f"cloning {dest} failed: {r.stderr.strip()[-400:]}")
        r = _git("checkout", "-q", "-f", "--detach", sha, cwd=dest)
        if r.returncode != 0:
            raise CodeError(f"checking out {sha[:12]} in {dest} failed: {r.stderr.strip()[-400:]}")
        _git("clean", "-fdq", cwd=dest)

    def head(self, dest: Path) -> str | None:
        r = _git("rev-parse", "HEAD", cwd=dest)
        return r.stdout.strip() if r.returncode == 0 else None

    def python(self, dest: Path) -> Path:
        """The checkout's venv python, synced first when the lock or pyproject changed since its last sync."""
        project = Path(dest) / PROJECT
        stamp_src = b"".join((project / n).read_bytes() if (project / n).exists() else b"-" for n in ("uv.lock", "pyproject.toml"))
        stamp = hashlib.sha256(stamp_src).hexdigest()
        py = project / ".venv" / "bin" / "python"
        mark = project / ".venv" / ".pool-synced"
        with self.sync_locks.setdefault(str(project), threading.Lock()):
            if py.exists() and mark.exists() and mark.read_text().strip() == stamp:
                return py
            env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
            r = subprocess.run([uv_path(), "sync", "-q", "--all-extras", "--directory", str(project)], env=env,
                               capture_output=True, text=True, timeout=3600)
            if r.returncode != 0 or not py.exists():
                raise CodeError(f"uv sync in {project} failed: {r.stderr.strip()[-600:]}")
            mark.write_text(stamp + "\n")
            return py
