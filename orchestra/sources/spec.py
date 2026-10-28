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

[[series]]                                  # a counter read from raw samples, reset-safe, summed by
source = "work"                             # labels, and marked as counted traffic (traffic.py)
name = "orders_published_total"
select = '{__name__="broker_published_total"}'
by = ["topic"]
kind = "counter"
traffic = { direction = "out", channel = "{topic}" }
```

A source may name a ``preset`` (``preset.py``): a file of series definitions for one exporter, and
defaults for the source table; ``infer = false`` reads only the declared series, and
``[sources.producers]`` (channel = machine) names the producer of a channel whose counts name none.
``settle`` ends every read from the source that long before now, so its series end together: a
store that hides the newest samples from range queries but not from raw reads (VictoriaMetrics'
``-search.latencyOffset``, 30 s by default) would otherwise give a counter read from raw samples
steps its levels never saw.

A source that cannot be used is **refused with its reason**, never half-used: a literal secret
(a token, a password, ``user:pass@`` in the URL), a query string in the URL (the API path is
appended to it), a secret file inside the repository (it would be committed), an auth kind not
built yet, a bad prefix or one another source uses. A refused source counts as missing for
discovery, which then saves no model version until it is fixed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..config import parse_duration
from . import preset as presets
from . import traffic as counted
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
    deadline: float = 120.0             # for one discovery's reads from this source; a fresh inference's probes get as long again
    max_points: int = 11000             # per series per request; longer ranges are read in chunks
    concurrency: int = 4
    infer_every: float = 3600.0
    insecure: bool = False
    infer: bool = True                  # False: read only the declared series (a preset's), never the schema
    settle: float = 0.0                 # every read from this source ends this long before now: the store's own delay
    producers: dict[str, str] = field(default_factory=dict)      # channel -> the machine producing into it (declared)
    preset: str | None = None

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
    query: str                          # PromQL; for a select, the selector whose raw samples are read
    kind: str = "level"
    unit: str | None = None
    by: list[str] | None = None         # a select's counters are summed by these labels (as the store spells them)
    traffic: dict | None = None         # counted traffic (traffic.py)
    preset: str | None = None           # the preset it came from


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
    if u.query or u.fragment or url.rstrip().endswith(("?", "#")):
        raise ValueError("the url has a query string or fragment: the API path is appended to it; put credentials in auth")
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
    producers = raw.get("producers") or {}
    if not isinstance(producers, dict) or not all(isinstance(v, str) and v for v in producers.values()):
        raise ValueError("[sources.producers]: channel = \"machine\"")
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
        infer_every=parse_duration(raw.get("infer_every"), 3600.0), insecure=bool(raw.get("insecure", False)),
        infer=bool(raw.get("infer", True)), settle=parse_duration(raw.get("settle"), 0.0), producers={str(k): v for k, v in producers.items()}, preset=raw.get("preset"))


def _series(r: dict) -> DeclaredSeries:
    """One ``[[series]]`` definition, checked; raises ``ValueError`` with what it needs."""
    name, kind, query, select = str(r.get("name") or ""), r.get("kind", "level"), r.get("query"), r.get("select")
    if not NAME.match(name) or kind not in KINDS or bool(query) == bool(select):
        raise ValueError(f"needs a name (lower-case letters, digits, _), a query or a select (one of them) and a kind in {sorted(KINDS)}")
    if select and kind != "counter":
        raise ValueError("a select reads a counter's raw samples: kind = \"counter\"")
    by = r.get("by")
    if by is not None and (not select or not isinstance(by, list) or not all(isinstance(x, str) for x in by)):
        raise ValueError("by = [labels] goes with a select")
    traffic = counted.parse(r["traffic"], kind) if r.get("traffic") is not None else None
    return DeclaredSeries(r.get("source"), name, str(query or select), kind, r.get("unit"),
                          list(by or []) if select else None, traffic, r.get("preset"))


def load(raw: dict, repo_root: Path) -> Specs:
    """The sources and declared series ``orchestra.toml`` names; the refused ones with why."""
    out = Specs()
    series = [(f"series[{i}]", r or {}) for i, r in enumerate(raw.get("series") or [])]
    for i, r in enumerate(raw.get("sources") or []):
        label = str((r or {}).get("name") or f"sources[{i}]")
        try:
            r, from_preset = presets.apply(r or {}, Path(repo_root))
            s = _source(r, Path(repo_root))
        except ValueError as e:
            out.refused[label] = str(e)
            continue
        if any(x.name == s.name for x in out.sources):
            out.refused[label] = "the name is used by another source"
            continue
        if other := next((x.name for x in out.sources if x.prefix == s.prefix), None):
            out.refused[label] = f"the prefix {s.prefix} is used by source {other}"
            continue
        out.sources.append(s)
        series += [(f"{s.name} preset series[{j}]", x) for j, x in enumerate(from_preset)]
    for label, r in series:
        if not any(s.name == r.get("source") for s in out.sources):
            out.refused[label] = f"source {r.get('source')!r} is not a usable source"
            continue
        try:
            out.declared.append(_series(r))
        except ValueError as e:
            out.refused[label] = str(e)
    return out


def for_project(project) -> Specs:
    raw = getattr(project.config, "raw", None) or {}
    return load(raw, project.repo_root) if raw.get("sources") or raw.get("series") else Specs()
