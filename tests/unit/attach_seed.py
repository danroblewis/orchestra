"""A project for the attachment tests (docs/proposals/instruments-on-machines.md §6): a
``[[collect]]`` named ``pg``, a ``[[scrape]]`` named ``ci``, and a source ``work`` (never read
here) whose ``[sources.labels]`` makes ``svc`` a spelling of ``service`` and whose declared
``select`` sums ``broker_published_total`` by ``topic``; a declared external machine
``postgres``; and points written as an instrument writes them."""

from __future__ import annotations

import time

from intended_seed import project_at

from orchestra.config import load_project
from orchestra.metrics import Point
from orchestra.metrics import for_project as metrics_for

TOML = """
[[collect]]
name = "pg"
command = "true"
every = "10s"

[[scrape]]
name = "ci"
url = "http://127.0.0.1:1/metrics"

[[sources]]
name = "work"
type = "prometheus"
url = "http://127.0.0.1:1"
match = ['{namespace="shop"}']
auth = { bearer_env = "ORCHESTRA_TEST_NO_TOKEN" }
prefix = "work"
infer = false

[sources.labels]
service = ["service", "svc"]

[[series]]
source = "work"
name = "orders_published_total"
select = '{__name__="broker_published_total"}'
by = ["topic"]
kind = "counter"
"""
SUPERVISOR = {"author": "supervisor", "source": "supervisor", "reason": "the owner said they have a Postgres cluster"}
OWNER = {"author": "owner", "source": "supervisor", "quote": "yes, those are its series"}


def project_with_instruments(tmp_path, monkeypatch, extra: str = "", *, sources: bool = True):
    p = project_at(tmp_path, monkeypatch)
    toml = TOML if sources else TOML[:TOML.index("[[sources]]")]
    p.config_file.write_text(p.config_file.read_text() + toml + extra)
    return load_project(p.repo_root)


def declare_postgres(project, **attach) -> str:
    """``postgres`` declared (proposed, then confirmed) with one attachment, confirmed; its id."""
    intended = project.intended
    intended.apply([{"op": "propose_machine", "id": "postgres", "kind": "programmatic", "managed": "external",
                     "engagement": {"mode": "continuous"}}], SUPERVISOR)
    got = intended.apply([{"op": "propose_attachment", "machine": "postgres", **({"instrument": "pg"} | attach)}], SUPERVISOR)
    aid = got["changes"][0]["id"]
    intended.apply([{"op": "confirm", "part": "machine", "id": "postgres"}, {"op": "confirm", "part": "attachment", "id": aid}], OWNER)
    return aid


def write(project, name: str, labels: dict, times, value: float = 1.0, instrument: str = "pg") -> None:
    metrics_for(project).write([Point(name, value, t, {"project": project.key, "instrument": instrument, **labels}) for t in times])


def every(seconds: float, n: int, ago: float = 0.0) -> list[float]:
    """``n`` times ``seconds`` apart, the last ``ago`` seconds before now."""
    now = time.time() - ago
    return [now - (n - 1 - i) * seconds for i in range(n)]
