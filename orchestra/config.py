"""orchestra.toml, ~/.orchestrator layout, and project resolution. SPEC.md sections 8 and 9."""

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
class TestSpec:
    name: str
    command: str
    select: str | None = None
    timeout: float = 900.0


@dataclass
class Config:
    base_branch: str = "main"
    ticket_prefix: str = "ORC"
    push: bool = False
    provider: str | None = None
    model: str | None = None
    thinking: str | None = None
    workers: int = 1
    reviewers: int = 1
    turn_timeout: float = 900.0
    review_rounds_before_escalation: int = 3
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    build_command: str | None = None
    build_artifact: str | None = None
    build_timeout: float = 600.0
    acceptance_start: str | None = None
    acceptance_ready: str | None = None
    acceptance_ready_timeout: float = 60.0
    acceptance_stop: str | None = None
    batch_size: int = 6
    batch_wait: float = 120.0
    gate_timeout: float = 900.0
    unit: list[TestSpec] = field(default_factory=list)
    acceptance: list[TestSpec] = field(default_factory=list)
    staging_start: str | None = None
    staging_port: int = 8001
    staging_health: str = "/"
    staging_health_timeout: float = 60.0
    staging_stop: str | None = None
    tunnel_name: str | None = None
    tunnel_hostname: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def staging_configured(self) -> bool:
        return bool(self.staging_start)

    @classmethod
    def from_toml(cls, text: str) -> Config:
        raw = tomllib.loads(text)
        p, a, b, acc, g, st = (raw.get(k, {}) for k in ("project", "agents", "build", "acceptance", "gate", "staging"))
        tun = st.get("tunnel", {}) or {}
        gt = parse_duration(g.get("timeout"), 900.0)

        def specs(items: list[dict]) -> list[TestSpec]:
            return [
                TestSpec(
                    name=i["name"], command=i["command"], select=i.get("select"),
                    timeout=parse_duration(i.get("timeout"), gt),
                )
                for i in items
            ]

        return cls(
            base_branch=p.get("base_branch", "main"),
            ticket_prefix=p.get("ticket_prefix", "ORC"),
            push=bool(p.get("push", False)),
            provider=a.get("provider") or None,
            model=a.get("model") or None,
            thinking=a.get("thinking"),
            workers=int(a.get("workers", 1)),
            reviewers=int(a.get("reviewers", 1)),
            turn_timeout=parse_duration(a.get("turn_timeout"), 900.0),
            review_rounds_before_escalation=int(a.get("review_rounds_before_escalation", 3)),
            prompt_overrides=dict(a.get("prompts", {})),
            build_command=b.get("command"),
            build_artifact=b.get("artifact"),
            build_timeout=parse_duration(b.get("timeout"), 600.0),
            acceptance_start=acc.get("start"),
            acceptance_ready=acc.get("ready"),
            acceptance_ready_timeout=parse_duration(acc.get("ready_timeout"), 60.0),
            acceptance_stop=acc.get("stop"),
            batch_size=int(g.get("batch_size", 6)),
            batch_wait=parse_duration(g.get("batch_wait"), 120.0),
            gate_timeout=gt,
            unit=specs(g.get("unit", [])),
            acceptance=specs(g.get("acceptance", [])),
            staging_start=st.get("start"),
            staging_port=int(st.get("port", 8001)),
            staging_health=st.get("health", "/"),
            staging_health_timeout=parse_duration(st.get("health_timeout"), 60.0),
            staging_stop=st.get("stop"),
            tunnel_name=tun.get("name"),
            tunnel_hostname=tun.get("hostname"),
            raw=raw,
        )


STARTER_TOML = """[project]
base_branch = "main"
ticket_prefix = "{prefix}"
push = false

[agents]
provider = "{provider}"   # leave empty to use Pi's default provider
model = "{model}"         # leave empty to use Pi's default model
thinking = "medium"
workers = 3
reviewers = 3
turn_timeout = "900s"
review_rounds_before_escalation = 3

# [build]
# command = "uv build"
# artifact = "dist/*.whl"

# [acceptance]
# start = "uv run --with {{artifact}} myapp serve --port {{port}}"
# ready = "http://127.0.0.1:{{port}}/health"

[gate]
batch_size = 6
batch_wait = "120s"
timeout = "900s"

[[gate.unit]]
name = "unit"
command = "{unit_command}"

# [[gate.acceptance]]
# name = "acceptance"
# command = "uv run pytest tests/acceptance -q --base-url {{url}}"
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
    def tickets_file(self) -> Path:
        return self.state_dir / "tickets.json"

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
    def worktrees_dir(self) -> Path:
        return self.state_dir / "worktrees"

    @property
    def gate_dir(self) -> Path:
        return self.state_dir / "gate"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def staging_dir(self) -> Path:
        return self.state_dir / "staging"

    @property
    def artifacts_dir(self) -> Path:
        return self.state_dir / "artifacts"

    def ensure_dirs(self) -> None:
        for d in (self.state_dir, self.sessions_dir, self.worktrees_dir, self.gate_dir, self.logs_dir,
                  self.staging_dir, self.artifacts_dir):
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


def init_project(repo: Path, *, provider: str | None = None, model: str | None = None,
                 prefix: str | None = None, unit_command: str = "uv run pytest -q") -> Project:
    """Write a starter ``orchestra.toml`` (if missing) and register the project.

    Provider and model may be left empty, in which case Pi's own default model is used."""
    root = find_repo_root(repo)
    toml_path = root / "orchestra.toml"
    if not toml_path.exists():
        pfx = prefix or re.sub(r"[^A-Za-z]", "", root.name.upper())[:4] or "ORC"
        toml_path.write_text(STARTER_TOML.format(prefix=pfx, provider=provider or "", model=model or "",
                                                 unit_command=unit_command))
    project = Project(key=project_key(root), repo_root=root, config=Config.from_toml(toml_path.read_text()))
    _register(project)
    return project
