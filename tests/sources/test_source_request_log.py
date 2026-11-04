"""Every request Orchestra sends to a source is logged in ``<state>/sources/<name>.requests.jsonl``
(``reqlog.py``): its endpoint, what it asked, the window, the answer's size, how long, who asked,
and the error if any; never a token. The log keeps its last 10,000 lines."""

from __future__ import annotations

import json
import math
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project, source_toml

from orchestra.sources import SourceError, reqlog
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.report import check
from orchestra.sources.spec import for_project

NOW = math.floor(time.time() / 60) * 60
TOKEN = "s3cret-log-token"


def dump():
    return [("queue_depth", {"queue": q}, [(NOW - 3600 + 60 * i, float(i % 5)) for i in range(61)]) for q in ("a", "b")]


def test_a_read_through_the_store_appends_a_line_with_its_fields(tmp_path, monkeypatch):
    fake = FakePrometheus(dump(), token=TOKEN)
    (tmp_path / "tok").write_text(TOKEN + "\n")
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, auth=f'auth = {{ bearer_file = "{tmp_path / "tok"}" }}'))
        spec = for_project(p).sources[0]
        src = PrometheusSource(spec, log_dir=p.state_dir, by="host")
        got = src.query_range("sum by (queue) (queue_depth)", NOW - 1800, NOW, 60)
        fake.fail_status = 500
        with pytest.raises(SourceError):
            src.instant("queue_depth", NOW)
    finally:
        fake.close()
    ok, bad = reqlog.last(p.state_dir, "rig", 10)
    assert ok["endpoint"] == "/api/v1/query_range" and ok["by"] == "host" and ok["query"].startswith("sum by (queue) (queue_depth")
    assert ok["window"] == [NOW - 1800, NOW] and ok["step"] == 60 and ok["series"] == len(got) == 2
    assert ok["points"] == sum(len(pts) for _, pts in got) and ok["ms"] >= 0 and "error" not in ok and ok["t"] > NOW - 600
    assert bad["endpoint"] == "/api/v1/query" and "500" in bad["error"] and bad["series"] is None and bad["window"] == [NOW]
    assert TOKEN not in reqlog.path(p.state_dir, "rig").read_text()
    assert reqlog.today(p.state_dir, "rig")["sent"] == 2


def test_every_reader_logs_and_check_prints_the_last_five(tmp_path, monkeypatch):
    fake = FakePrometheus(dump())
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url))
        cat = Catalogue(p, None, by="cli")
        cat.inference("rig", NOW - 3600, NOW, refresh=True)
        lines = check(cat)
    finally:
        fake.close()
    logged = [json.loads(x) for x in reqlog.path(p.state_dir, "rig").read_text().splitlines()]
    assert {x["by"] for x in logged} == {"infer", "cli"} and len(logged) == fake.requests
    i = next(n for n, x in enumerate(lines) if "requests today (UTC)" in x)
    assert f"{fake.requests} sent of the cap" in lines[i] and len(lines[i + 1:]) == 5
    assert all(" cli " in x for x in lines[i + 1:])


def test_the_log_keeps_its_last_ten_thousand_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(reqlog, "_COUNTS", {})
    for i in range(reqlog.KEEP + reqlog.SLACK + 1):
        reqlog.append(tmp_path, "s", {"endpoint": "/api/v1/query", "i": i})
    lines = reqlog.path(tmp_path, "s").read_text().splitlines()
    assert len(lines) == reqlog.KEEP
    assert json.loads(lines[0])["i"] == reqlog.SLACK + 1 and json.loads(lines[-1])["i"] == reqlog.KEEP + reqlog.SLACK
    reqlog.append(tmp_path, "s", {"i": "next"})
    assert len(reqlog.path(tmp_path, "s").read_text().splitlines()) == reqlog.KEEP + 1     # cut back only past the slack
