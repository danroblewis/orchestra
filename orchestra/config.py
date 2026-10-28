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

from .overlay import Layers, OverlayError, merge

CONFIG_FILE = "orchestra.toml"
OVERLAY_FILE = "orchestra.local.toml"      # the private overlay's name in the state directory
OVERLAY_ENV = "ORCHESTRA_CONFIG_OVERLAY"   # or a path named here

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

    events_url: str | None = None      # [events] url: file (default), redis://, amqp://, kafka://
    events_listen: Any = None          # [events] listen: where the host serves the events endpoint ("127.0.0.1:0" unless given; "off")
    web_auth: Any = None               # [web] auth: "on" (default) or "off" (only on a loopback bind; orchestra/web/auth.py)
    metrics_url: str | None = None     # [metrics] url: file (default) or http://host:port (VictoriaMetrics)
    discovery_strategy: str | None = None   # [discovery] strategy: conservation, or an SD Lab strategy (default: kalman_lna when installed)
    discovery_window: float = 3600.0        # [discovery] window: how far back each discovery looks
    discovery_step: float = 30.0            # [discovery] step: the grid it samples on
    discovery_every: float = 300.0          # [discovery] every: how often the host rediscovers
    discovery_options: dict[str, Any] = field(default_factory=dict)   # [discovery.options]: passed to the strategy
    eras_from: list[str] = field(default_factory=lambda: ["config.changed"])   # [discovery] eras_from: events that begin an era, besides system.changed (sd.eras)
    prior_for: float | None = None          # [discovery] prior_for: how long a new era carries what it has not found of its prior (default: the window)
    announce_hold: int = 3                  # [discovery] announce_hold: discoveries a structure change must hold before orchestra.model.changed
    announce_gap: float = 1800.0            # [discovery] announce_gap: the least time between two orchestra.model.changed
    diverge_after: float = 900.0            # [discovery] diverge_after: how long a stock is out of its band before orchestra.model.diverged
    raw: dict[str, Any] = field(default_factory=dict)   # the whole configuration, the overlay merged in
    layers: Layers | None = None       # what the private overlay did (orchestra/overlay.py); None: no overlay

    @classmethod
    def from_toml(cls, text: str) -> Config:
        """The configuration in one file's text (no overlay)."""
        return cls.from_raw(tomllib.loads(text))

    @classmethod
    def from_raw(cls, raw: dict[str, Any], layers: Layers | None = None) -> Config:
        from .sd.eras import DEFAULT_FROM, FilterError, check

        disc = raw.get("discovery", {}) or {}
        try:
            eras_from = check(disc.get("eras_from", DEFAULT_FROM))
        except FilterError as e:
            raise ConfigError(f"[discovery] {e}") from None
        hold = disc.get("announce_hold", 3)
        if not isinstance(hold, int) or isinstance(hold, bool) or hold < 1:
            raise ConfigError(f"[discovery] announce_hold must be a whole number of discoveries, at least 1, not {hold!r}")
        return cls(
            events_url=(raw.get("events", {}) or {}).get("url"),
            events_listen=(raw.get("events", {}) or {}).get("listen"),
            web_auth=(raw.get("web", {}) or {}).get("auth"),
            metrics_url=(raw.get("metrics", {}) or {}).get("url"),
            discovery_strategy=(raw.get("discovery", {}) or {}).get("strategy"),
            discovery_window=parse_duration((raw.get("discovery", {}) or {}).get("window"), 3600.0),
            discovery_step=parse_duration((raw.get("discovery", {}) or {}).get("step"), 30.0),
            discovery_every=parse_duration((raw.get("discovery", {}) or {}).get("every"), 300.0),
            discovery_options=dict((raw.get("discovery", {}) or {}).get("options") or {}),
            eras_from=eras_from,
            prior_for=parse_duration(disc["prior_for"], 0.0) if disc.get("prior_for") is not None else None,
            announce_hold=hold,
            announce_gap=parse_duration(disc.get("announce_gap"), 1800.0),
            diverge_after=parse_duration(disc.get("diverge_after"), 900.0),
            raw=raw,
            layers=layers,
        )


STARTER_TOML = """# Orchestra: the event bus, the metrics store and the system dynamics model for this repository.

[events]
url = "file"             # file (default), redis://host:6379/0, amqp://user:pass@host:5672/, kafka://host:9092
# listen = "127.0.0.1:0"  # where `orchestra run` serves events over HTTP (port 0: one the system picks; "off": none)

[metrics]
url = "file"             # file (default) or http://host:8428 (VictoriaMetrics)

[web]
# auth = "on"            # `orchestra web` asks for the project's token (`orchestra web token`); "off" only on a loopback bind

[discovery]              # how the model is discovered from the metrics
# strategy = "kalman_lna" # conservation (Orchestra's own), or an SD Lab strategy (needs orchestra[sd])
window = "60m"           # how far back each discovery looks
step = "30s"             # the grid it samples on
every = "5m"             # how often the host rediscovers
# eras_from = ["config.changed"]  # events that begin an era (besides system.changed): type[:source=…,subject=…]
# prior_for = "60m"      # how long a new era carries what it has not yet found of the era before (default: window)
# announce_hold = 3      # discoveries a structure change must hold before orchestra.model.changed
# announce_gap = "30m"   # the least time between two orchestra.model.changed
# diverge_after = "15m"  # how long a stock is outside its predicted band before orchestra.model.diverged
# [discovery.options]    # passed to the strategy as they are

# The programs `orchestra run` keeps running (docs/machines.md in Orchestra's repository). A command
# runs in the repository root with the PATH `orchestra run` was started with, so `python` is the
# interpreter Orchestra is installed in when `orchestra run` starts from that environment; use
# `uv run python ...` only if this project's pyproject.toml depends on Orchestra. Try a program
# once first (`python machines/telemetry.py --once`); one that exits 0 is started again after a
# pause, so a one-reading sampler runs about once a minute.
# [[machines]]
# name = "telemetry"
# command = "python machines/telemetry.py"
# restart = "always"     # always, on-failure or never

# Measurements in the Prometheus text format (`disk_free_bytes 1.2e11`, one per line), written to
# the metrics store with machine = <name> (docs/machines.md). A script run on an interval:
# [[collect]]
# name = "disk"
# command = "machines/disk.sh"   # executable, named with a slash; not run by a shell
# every = "60s"
# timeout = "20s"
# A URL that serves them, read on an interval:
# [[scrape]]
# name = "app"
# url = "http://127.0.0.1:9100/metrics"
# every = "30s"

# Another time-series store (Prometheus, VictoriaMetrics, Mimir, Chronosphere), read where its data
# lives: what to read is inferred from its schema (`orchestra sources infer` shows it). The
# credential comes from an environment variable or a file outside the repository, never this file.
# [[sources]]
# name = "work"
# url = "https://tenant.example/data/metrics"
# auth = { bearer_env = "WORK_TOKEN" }
# machine = "service"                    # the label that names machines
# [sources.labels]                       # the label spellings that mean the same thing
# service = ["service", "app", "k8s_app"]
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
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.state_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def config_file(self) -> Path:
        return self.repo_root / CONFIG_FILE

    @property
    def overlay_file(self) -> Path:
        """Where the private overlay is read from: ``ORCHESTRA_CONFIG_OVERLAY`` (relative to the
        repository root unless absolute), else ``orchestra.local.toml`` in the state directory. It
        need not exist (``read_config``)."""
        named = os.environ.get(OVERLAY_ENV)
        if named:
            p = Path(named).expanduser()
            return p if p.is_absolute() else self.repo_root / p
        return self.state_dir / OVERLAY_FILE

    def config_stamp(self) -> tuple:
        """Changes whenever either file changes, appears or goes: what readers that follow the
        configuration compare to know when to read it again."""
        out = []
        for p in (self.config_file, self.overlay_file):
            try:
                st = p.stat()
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def read_config(self) -> Config:
        """``orchestra.toml`` with the private overlay merged over it, read now. Raises if either
        does not parse, or if ``ORCHESTRA_CONFIG_OVERLAY`` names a file that is not there (a
        mistyped path must not silently drop the private configuration)."""
        raw = tomllib.loads(self.config_file.read_text(encoding="utf-8"))
        path = self.overlay_file
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if os.environ.get(OVERLAY_ENV):
                raise ConfigError(f"{OVERLAY_ENV} names {path}, which does not exist") from None
            return Config.from_raw(raw)
        try:
            merged, layers = merge(raw, tomllib.loads(text), str(path))
        except (tomllib.TOMLDecodeError, OverlayError) as e:
            raise ConfigError(f"{path}: {e}") from e
        return Config.from_raw(merged, layers)

    def reload_config(self) -> None:
        self.config = self.read_config()

    @property
    def config_edit(self):
        """How the configuration is changed, in ``orchestra.toml`` or the private overlay
        (``orchestra.config_edit.ConfigEdit``): the only way, for Orchestra and every plugin."""
        from .config_edit import ConfigEdit
        return ConfigEdit(self)


def find_repo_root(start: Path) -> Path:
    """The main repository root containing ``start``.

    Uses git itself, so it works from any subdirectory and from inside a linked
    worktree: a worktree resolves to the repository it belongs to, since that is
    the project Orchestra manages."""
    start = Path(start).resolve()
    probe = start if start.is_dir() else start.parent
    p = subprocess.run(["git", "-C", str(probe), "rev-parse", "--git-common-dir"],
                       capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise ConfigError(f"{start} is not inside a git repository")
    common = Path(p.stdout.strip())
    if not common.is_absolute():
        common = (probe / common).resolve()
    if common.name == ".git":
        return common.parent.resolve()
    top = subprocess.run(["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True, check=False).stdout.strip()
    return Path(top).resolve() if top else common.parent.resolve()


def load_project(repo: Path | str | None = None) -> Project:
    """Resolve the project for ``repo`` (default: ORCHESTRA_REPO, else the cwd).

    ``orchestra.toml`` must exist at the repository root; the private overlay, if there is one,
    is merged over it (``Project.read_config``). The state directory under
    ``~/.orchestrator`` is created on demand, so a freshly cloned repository that
    already carries an ``orchestra.toml`` needs no ``orchestra init``."""
    root = find_repo_root(Path(repo or os.environ.get("ORCHESTRA_REPO") or Path.cwd()))
    toml_path = root / CONFIG_FILE
    if not toml_path.exists():
        raise ConfigError(f"no orchestra.toml in {root}; run `orchestra init` there first")
    project = Project(key=project_key(root), repo_root=root, config=Config())
    project.reload_config()
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


def init_project(repo: Path) -> Project:
    """Write a starter ``orchestra.toml`` (if missing) and register the project."""
    root = find_repo_root(repo)
    toml_path = root / "orchestra.toml"
    if not toml_path.exists():
        toml_path.write_text(STARTER_TOML)
    project = Project(key=project_key(root), repo_root=root, config=Config())
    project.reload_config()
    _register(project)
    return project
