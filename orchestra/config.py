"""orchestra.toml, the ~/.orchestrator layout, and project resolution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("ORCHESTRATOR_HOME") or Path.home() / ".orchestrator")


def project_key(repo_root: Path) -> str:
    real = str(repo_root.resolve())
    digest = hashlib.sha256(real.encode()).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", repo_root.resolve().name) or "repo"
    return f"{name}-{digest}"


def parse_duration(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*", str(value))
    if not m:
        raise ConfigError(f"bad duration {value!r}")
    n, unit = float(m.group(1)), m.group(2) or "s"
    return n * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]


@dataclass
class Config:
    """What an empty Orchestra reads from ``orchestra.toml``. Unknown sections are ignored, so a
    file written for an older Orchestra still loads."""

    harness: str = "pi"          # pi | claude_code | codex: the product the agent driver runs
    provider: str | None = None
    model: str | None = None
    thinking: str | None = None
    turn_timeout: float = 0.0          # hard cap per turn; 0 = none
    silence_timeout: float = 1200.0    # end a turn after this long with nothing from the harness
    session_max_bytes: int = 300_000   # transcript growth since the last compaction that triggers one
    compact_tokens: int = 100_000      # harnesses that compact themselves (Claude Code) are told to do so past this
    events_url: str | None = None      # [events] url: file (default), redis://, amqp://, kafka://
    metrics_url: str | None = None     # [metrics] url: file (default) or http://host:port (VictoriaMetrics)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_toml(cls, text: str) -> Config:
        raw = tomllib.loads(text)
        a = raw.get("agents", {}) or {}
        return cls(
            harness=(a.get("harness") or "pi").replace("-", "_"),
            provider=a.get("provider") or None,
            model=a.get("model") or None,
            thinking=a.get("thinking"),
            turn_timeout=parse_duration(a.get("turn_timeout"), 0.0),
            silence_timeout=parse_duration(a.get("silence_timeout"), 1200.0),
            session_max_bytes=int(a.get("session_max_bytes", 300_000)),
            compact_tokens=int(a.get("compact_tokens", 100_000)),
            events_url=(raw.get("events", {}) or {}).get("url"),
            metrics_url=(raw.get("metrics", {}) or {}).get("url"),
            raw=raw,
        )


STARTER_TOML = """# Orchestra: the event bus, the metrics store and the system dynamics model for this repository.

[events]
url = "file"             # file (default), redis://host:6379/0, amqp://user:pass@host:5672/, kafka://host:9092

[metrics]
url = "file"             # file (default) or http://host:8428 (VictoriaMetrics)

[agents]                 # the agent driver, for machines that are AI agents
harness = "pi"           # pi | claude_code | codex
provider = "{provider}"   # Pi only; leave empty to use Pi's default provider
model = "{model}"         # leave empty for the harness's default
thinking = "medium"
silence_timeout = "20m"  # a turn ends when nothing has come from the agent for this long
"""


@dataclass
class Project:
    key: str
    repo_root: Path
    config: Config

    @property
    def state_dir(self) -> Path:
        return home() / self.key

    @property
    def runtime_file(self) -> Path:
        return self.state_dir / "runtime.json"

    @property
    def events_file(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / ".lock"

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "sessions"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.state_dir, self.sessions_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def reload_config(self) -> None:
        self.config = Config.from_toml((self.repo_root / "orchestra.toml").read_text())


def find_repo_root(start: Path) -> Path:
    """The main repository root containing ``start``.

    Uses git itself, so it works from any subdirectory and from inside a linked
    worktree: a worktree resolves to the repository it belongs to, since that is
    the project Orchestra manages."""
    start = Path(start).resolve()
    probe = start if start.is_dir() else start.parent
    p = subprocess.run(["git", "-C", str(probe), "rev-parse", "--git-common-dir"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise ConfigError(f"{start} is not inside a git repository")
    common = Path(p.stdout.strip())
    if not common.is_absolute():
        common = (probe / common).resolve()
    if common.name == ".git":
        return common.parent.resolve()
    top = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    return Path(top).resolve() if top else common.parent.resolve()


def load_project(repo: Path | str | None = None) -> Project:
    """Resolve the project for ``repo`` (default: ORCHESTRA_REPO, else the cwd).

    ``orchestra.toml`` must exist at the repository root. The state directory under
    ``~/.orchestrator`` is created on demand, so a freshly cloned repository that
    already carries an ``orchestra.toml`` needs no ``orchestra init``."""
    root = find_repo_root(Path(repo or os.environ.get("ORCHESTRA_REPO") or Path.cwd()))
    toml_path = root / "orchestra.toml"
    if not toml_path.exists():
        raise ConfigError(f"no orchestra.toml in {root}; run `orchestra init` there first")
    project = Project(key=project_key(root), repo_root=root, config=Config.from_toml(toml_path.read_text()))
    if not project.state_dir.exists():
        _register(project)
    return project


def _register(project: Project) -> None:
    project.ensure_dirs()
    (project.state_dir / "project.json").write_text(json.dumps(
        {"key": project.key, "repo_root": str(project.repo_root), "backend": "local"}, indent=2))
    index = home() / "projects.json"
    data = json.loads(index.read_text()) if index.exists() else {}
    data[str(project.repo_root)] = project.key
    index.write_text(json.dumps(data, indent=2))


def init_project(repo: Path, *, provider: str | None = None, model: str | None = None) -> Project:
    """Write a starter ``orchestra.toml`` (if missing) and register the project."""
    root = find_repo_root(repo)
    toml_path = root / "orchestra.toml"
    if not toml_path.exists():
        toml_path.write_text(STARTER_TOML.format(provider=provider or "", model=model or ""))
    project = Project(key=project_key(root), repo_root=root, config=Config.from_toml(toml_path.read_text()))
    _register(project)
    return project
