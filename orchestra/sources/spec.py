"""``[[sources]]`` and ``[[series]]`` in ``orchestra.toml``: what other stores to read and how.

```toml
[[sources]]
name = "work"
type = "prometheus"
url = "https://tenant.example/data/metrics"
auth = { bearer_env = "WORK_PROM_TOKEN" }   # never the secret itself
prefix = "work"                             # series work:<name>, machines work.<id>
machine = "service"                         # the canonical label that names machines
match = ['{__name__=~"http_.*"}']           # what to infer from (default: everything, capped)
max_series = 200

[sources.labels]                            # canonical = spellings; the first a metric has wins
service = ["service", "svc", "app"]

[sources.transform]
queries = "orchestra/transform/queries.py"  # any executable, run from the repository root

[[series]]                                  # a hand-written definition, still allowed
source = "work"
name = "checkout_errors"
query = 'sum(rate(http_errors_total{svc="checkout"}[5m]))'
kind = "rate"
```

A source that cannot be used is **refused with its reason**, never half-used: a literal secret
(a token, a password, ``user:pass@`` in the URL), a secret file inside the repository (it would be
committed), an auth kind not built yet, a bad prefix. A refused source counts as missing for
discovery, which then saves no model version until it is fixed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..config import parse_duration
from .auth import AuthSpec, auth_problems

NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
TYPES = {"prometheus"}
KINDS = {"level", "counter", "rate"}
SECRET_KEYS = re.compile(r"(?i)^(token|bearer|password|passwd|secret|api_?key|apikey|credentials?)$")
IDENTITY = ["pod", "instance", "container"]      # canonical labels that name one reporting thing, by default


@dataclass
class SourceSpec:
    name: str
    type: str
    url: str
    prefix: str
    auth: AuthSpec
    machine: str | None = None
    match: list[str] = field(default_factory=lambda: ['{__name__=~".+"}'])
    max_series: int = 200
    max_per_family: int = 12
    labels: dict[str, list[str]] = field(default_factory=dict)    # canonical -> spellings
    identity: list[str] = field(default_factory=lambda: list(IDENTITY))
    queries_script: str | None = None
    script_timeout: float = 20.0
    timeout: float = 30.0
    deadline: float = 120.0             # for one discovery's reads from this source, all told
    max_points: int = 11000             # per series per request; longer ranges are read in chunks
    concurrency: int = 4
    infer_every: float = 3600.0
    insecure: bool = False

    def aliases(self) -> dict[str, str]:
        """real -> canonical for a query someone wrote (a script's, a declared series'): every
        spelling the table names, the first canonical naming it winning."""
        out: dict[str, str] = {}
        for canonical, spellings in self.labels.items():
            for s in spellings:
                out.setdefault(s, canonical)
        return out

    def where(self) -> str:
        """The server without path or credentials: what logs and pages may show."""
        u = urlsplit(self.url)
        return f"{u.scheme}://{u.hostname}{f':{u.port}' if u.port else ''}"


@dataclass
class DeclaredSeries:
    source: str
    name: str
    query: str
    kind: str = "level"
    unit: str | None = None


@dataclass
class Specs:
    sources: list[SourceSpec] = field(default_factory=list)
    declared: list[DeclaredSeries] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)        # source name (or [[series]] n) -> why


def _secret_keys(d: Any, path: str = "") -> list[str]:
    """Keys anywhere in a table that name a secret and hold a literal value."""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if SECRET_KEYS.match(str(k)) and isinstance(v, str):
                out.append(f"{path}{k}")
            out += _secret_keys(v, f"{path}{k}.")
    return out


def _source(raw: dict, repo_root: Path) -> SourceSpec:
    name = str(raw.get("name") or "")
    if not NAME.match(name):
        raise ValueError(f"name {name!r}: use lower-case letters, digits and _")
    if (typ := raw.get("type", "prometheus")) not in TYPES:
        raise ValueError(f"type {typ!r}: only {', '.join(sorted(TYPES))} is built")
    url = str(raw.get("url") or "")
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"url {url!r}: give http(s)://host[:port][/path]")
    if u.username or u.password:
        raise ValueError("the url carries user:pass@: a literal secret in orchestra.toml is refused; "
                         "use auth = { basic = { user = ..., password_env = ... } }")
    if keys := _secret_keys({k: v for k, v in raw.items() if k != "auth"}):
        raise ValueError(f"{', '.join(keys)}: a literal secret in orchestra.toml is refused; "
                         "name an environment variable or a file outside the repository in auth")
    auth = AuthSpec.parse(raw.get("auth") or {})
    if problems := auth_problems(auth, repo_root):
        raise ValueError("; ".join(problems))
    prefix = str(raw.get("prefix") or name)
    if not NAME.match(prefix) or prefix.startswith("orchestra"):
        raise ValueError(f"prefix {prefix!r}: lower-case letters, digits and _, and not orchestra (Orchestra's own)")
    labels = raw.get("labels") or {}
    if not isinstance(labels, dict) or not all(isinstance(v, list) for v in labels.values()):
        raise ValueError("[sources.labels]: canonical = [spellings]")
    transform = raw.get("transform") or {}
    match = raw.get("match") or ['{__name__=~".+"}']
    return SourceSpec(
        name=name, type=typ, url=url.rstrip("/"), prefix=prefix, auth=auth, machine=raw.get("machine"),
        match=[match] if isinstance(match, str) else list(match),
        max_series=int(raw.get("max_series", 200)), max_per_family=int(raw.get("max_per_family", 12)),
        labels={str(k): [str(x) for x in v] for k, v in labels.items()},
        identity=list(raw.get("identity") or IDENTITY),
        queries_script=transform.get("queries"), script_timeout=parse_duration(transform.get("timeout"), 20.0),
        timeout=parse_duration(raw.get("timeout"), 30.0), deadline=parse_duration(raw.get("deadline"), 120.0),
        max_points=int(raw.get("max_points", 11000)), concurrency=max(1, int(raw.get("concurrency", 4))),
        infer_every=parse_duration(raw.get("infer_every"), 3600.0), insecure=bool(raw.get("insecure", False)))


def load(raw: dict, repo_root: Path) -> Specs:
    """The sources and declared series ``orchestra.toml`` names; the refused ones with why."""
    out = Specs()
    for i, r in enumerate(raw.get("sources") or []):
        label = str((r or {}).get("name") or f"sources[{i}]")
        try:
            s = _source(r or {}, Path(repo_root))
        except ValueError as e:
            out.refused[label] = str(e)
            continue
        if any(x.name == s.name for x in out.sources):
            out.refused[label] = "the name is used by another source"
            continue
        out.sources.append(s)
    for i, r in enumerate(raw.get("series") or []):
        r = r or {}
        src, name, query, kind = r.get("source"), str(r.get("name") or ""), r.get("query"), r.get("kind", "level")
        if not any(s.name == src for s in out.sources):
            out.refused[f"series[{i}]"] = f"source {src!r} is not a usable source"
        elif not NAME.match(name) or not query or kind not in KINDS:
            out.refused[f"series[{i}]"] = f"needs a name (lower-case letters, digits, _), a query and a kind in {sorted(KINDS)}"
        else:
            out.declared.append(DeclaredSeries(src, name, str(query), kind, r.get("unit")))
    return out


def for_project(project) -> Specs:
    raw = getattr(project.config, "raw", None) or {}
    return load(raw, project.repo_root) if raw.get("sources") or raw.get("series") else Specs()
