"""Project resolution and ``~/.orchestra`` state management.

Orchestration state lives *outside* the target repo so it can later map to GitHub
Issues / Jira tickets without polluting the codebase. For a target repo at
``<repo-root>`` with slug ``<slug>``::

    ~/.orchestra/<slug>/
      config.json              # base_branch, model, labels, prompt template paths, ...
      state/                   # task / milestone / build / session-log repositories
      sessions/                # per-agent JSONL logs

The *repo itself* only "configures" Orchestra: it provides conventions (read from
``AGENTS.md`` or a ``[tool.orchestra]`` table) and labels that decide which tickets
Orchestra manages. Orchestra never writes to the repo here -- that happens inside
per-ticket git worktrees.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    tomllib = None


def _load_toml(text: str) -> dict:
    """Parse a small TOML document (pyproject.toml). 3.11+ uses tomllib; the
    3.10 fallback only needs to read a flat ``[tool.orchestra]`` table."""
    if tomllib is not None:
        return tomllib.loads(text)
    # Minimal fallback: pull the [tool.orchestra] table as key="value" pairs.
    result: dict = {}
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section == "tool.orchestra" and "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = _coerce_toml_value(value.strip())
    return result


def _coerce_toml_value(value: str):
    """Coerce a TOML scalar string into a Python value (fallback path only)."""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_coerce_toml_value(v.strip()) for v in inner.split(",") if v.strip()]
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if value in ("true", "false"):
        return value == "true"
    try:
        return int(value)
    except ValueError:
        return value

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def home_dir() -> Path:
    """Root of Orchestra's own state: ``~/.orchestra`` (override with env)."""
    override = os.environ.get("ORCHESTRA_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".orchestra"


# --------------------------------------------------------------------------- #
# Repo detection
# --------------------------------------------------------------------------- #


def list_projects() -> list[Project]:
    """Every Orchestra project registered under ``~/.orchestra``.

    A project's config stores its ``repo_root``; callers match a CWD repo against
    it so ``orchestra tickets`` from a repo dir finds the project even if the slug
    was set with a different name at init time.
    """
    root = home_dir()
    if not root.exists():
        return []
    projects: list[Project] = []
    for config_path in sorted(root.glob("*/config.json")):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        projects.append(
            Project(
                slug=config_path.parent.name,
                repo_root=Path(config.get("repo_root", "")),
                state_root=config_path.parent,
                config=config,
            )
        )
    return projects


def resolve_from_cwd(repo_root: Path) -> Project:
    """Find the project whose registered repo_root matches ``repo_root``.

    Falls back to name-based matching, then to CWD-derived slug. Raises
    :class:`ProjectError` when nothing matches.
    """
    repo_root = repo_root.resolve()
    for project in list_projects():
        stored = project.config.get("repo_root")
        if stored and Path(stored).resolve() == repo_root:
            return project
    # Fall back to matching by slug == repo dir name.
    slug = repo_root.name
    for project in list_projects():
        if project.slug == slug:
            return project
    raise ProjectError(
        f"No Orchestra project registered for repo at {repo_root}. "
        "Run `orchestra init` from the repo root first."
    )


def find_repo_root(start: Path | None = None) -> Path:
    """Return the git working-tree root containing ``start`` (default: cwd).

    Raises :class:`RepoError` when ``start`` is not inside a git repository.
    """
    start = (start or Path.cwd()).resolve()
    cur: Path | None = start
    while True:
        if (cur / ".git").exists():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    raise RepoError(f"{start} is not inside a git repository")


def get_repo_slug(repo_root: Path) -> str:
    """Slug for a repo: the directory name, else the ``remote origin`` name.

    Examples: ``/code/my-project`` -> ``my-project``; a clone named
    ``foo/bar.git`` -> ``bar``.
    """
    gitdir = repo_root / ".git"
    remote: str | None = None
    if gitdir.is_dir():
        remote = _git_config(gitdir, "remote.origin.url")
    elif gitdir.is_file():  # submodule-style .git file
        remote = _git_config(gitdir, "remote.origin.url")

    if remote:
        name = remote.rsplit("/", 1)[-1]
        for suffix in (".git", ".git/"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        if name:
            return name

    return repo_root.name


def _git_config(gitdir: Path, key: str) -> str | None:
    """Read a git config value from a (file or dir) ``.git`` location."""
    try:
        out = subprocess.run(
            ["git", "-C", str(gitdir.parent), "config", "--get", key],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    return out.stdout.strip() or None


class RepoError(Exception):
    """Raised when a directory is not inside a git repository."""


# --------------------------------------------------------------------------- #
# Default config
# --------------------------------------------------------------------------- #


def default_config(
    repo_root: Path,
    *,
    base_branch: str = "main",
    model: str | None = None,
    thinking_level: str = "medium",
    max_concurrent_workers: int = 4,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Config seed for a freshly-initialized project."""
    return {
        "repo_root": str(repo_root),
        "base_branch": base_branch,
        "model": model,
        "thinking_level": thinking_level,
        "max_concurrent_workers": max_concurrent_workers,
        "labels": labels or ["orchestra-managed"],
        "prompt_templates": {
            # Paths here are relative to the repo root when they start with "./".
            "worker": None,
            "reviewer": None,
        },
    }


# --------------------------------------------------------------------------- #
# Project object
# --------------------------------------------------------------------------- #


class Project:
    """Everything Orchestra needs to operate on one target repo."""

    def __init__(
        self,
        slug: str,
        repo_root: Path,
        state_root: Path,
        config: dict[str, Any],
    ):
        self.slug = slug
        self.repo_root = repo_root
        self.state_root = state_root
        self.config = config

    # -- derived paths ----------------------------------------------------- #

    @property
    def config_path(self) -> Path:
        return self.state_root / "config.json"

    @property
    def state_dir(self) -> Path:
        return self.state_root / "state"

    @property
    def sessions_dir(self) -> Path:
        return self.state_root / "sessions"

    @property
    def base_branch(self) -> str:
        return self.config.get("base_branch", "main")

    @property
    def max_concurrent_workers(self) -> int:
        return int(self.config.get("max_concurrent_workers", 4))

    @property
    def labels(self) -> list[str]:
        return list(self.config.get("labels", ["orchestra-managed"]))

    @property
    def store_dir(self) -> Path:
        """Directory holding the JSON repository files (tasks, builds, ...)."""
        return self.state_dir

    # -- helpers ----------------------------------------------------------- #

    def session_path(self, name: str) -> Path:
        """Absolute path to a named agent's JSONL session log."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        return self.sessions_dir / f"{name}.jsonl"

    def to_state_env(self) -> dict[str, str]:
        """Env mapping so the backend repos resolve to this project's state dir."""
        return {
            "ORCHESTRA_DATA_DIR": str(self.state_dir),
            "ORCHESTRA_HOME": str(self.state_root.parent),
        }

    # -- persistence ------------------------------------------------------- #

    def save_config(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        os.replace(tmp, self.config_path)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Project(slug={self.slug!r}, repo_root={self.repo_root})"


def load_project(slug: str, repo_root: Path) -> Project:
    """Load a project's config, or raise :class:`ProjectError` if missing."""
    state_root = home_dir() / slug
    config_path = state_root / "config.json"
    if not config_path.exists():
        raise ProjectError(
            f"No Orchestra project named {slug!r} at {state_root}. "
            "Run `orchestra init` from the repo root first."
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # If the caller didn't pass a repo_root, prefer the one persisted in config
    # so ``--project`` works even when invoked from an unrelated directory.
    if repo_root is None:
        repo_root = config.get("repo_root")
    return Project(slug=slug, repo_root=repo_root, state_root=state_root, config=config)


class ProjectError(Exception):
    """Raised when a requested Orchestra project does not exist."""


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #


def init_project(
    repo_root: str | Path,
    *,
    slug: str | None = None,
    base_branch: str = "main",
    model: str | None = None,
    labels: list[str] | None = None,
) -> Project:
    """Create ``~/.orchestra/<slug>/config.json`` for a repo root.

    If ``slug`` is omitted it is derived from the repo name. Raises
    :class:`ProjectError` if a project with that slug already exists.
    """
    repo_root = Path(repo_root)
    repo_root = repo_root.resolve()
    slug = slug or get_repo_slug(repo_root)
    state_root = home_dir() / slug
    if (state_root / "config.json").exists():
        raise ProjectError(
            f"A Orchestra project named {slug!r} already exists at {state_root}."
        )
    config = default_config(
        repo_root, base_branch=base_branch, model=model, labels=labels
    )
    project = Project(slug, repo_root, state_root, config)
    project.save_config()
    return project


def read_repo_config(repo_root: Path) -> dict[str, Any]:
    """Read project-provided Orchestra config from the repo.

    Looks for a ``[tool.orchestra]`` table in ``pyproject.toml`` and/or a top-level
    ``orchestra.json``. Values merge over Orchestra defaults; this is how the *repo*
    configures Orchestra.
    """
    data: dict[str, Any] = {}

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        try:
            loaded = _load_toml(pyproject.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        tool = loaded.get("tool", {}) if isinstance(loaded, dict) else {}
        if isinstance(tool, dict) and isinstance(tool.get("orchestra"), dict):
            data.update(tool["orchestra"])

    manifest = repo_root / "orchestra.json"
    if manifest.exists():
        try:
            repo_cfg = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            repo_cfg = {}
        if isinstance(repo_cfg, dict):
            data.update(repo_cfg)

    return data
