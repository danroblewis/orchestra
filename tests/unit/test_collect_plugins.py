"""A plugin's collectors (``Plugin.collectors``): run like the project's own, named for the
plugin, and replaced by a project entry of the same name."""

import http.server
import os
import subprocess
import threading
import time

import pytest

from orchestra.collect.runner import Collecting
from orchestra.collect.spec import Collector
from orchestra.config import init_project
from orchestra.metrics import for_project

PROVENANCE = "instrument"  # the label a collected point names its instrument by


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return init_project(r)


@pytest.fixture
def servers():
    made = []

    def make(body: bytes) -> str:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return f"http://127.0.0.1:{srv.server_address[1]}/metrics"
    yield make
    for srv in made:
        srv.shutdown()
        srv.server_close()


_n = iter(range(1, 10_000))


def declare(project, text):
    path = project.repo_root / "orchestra.toml"
    path.write_text('[metrics]\nurl = "file"\n' + text)
    t = time.time() + next(_n)
    os.utime(path, (t, t))


def run_once(c: Collecting):
    c.tick(1000.0)
    assert c.idle(10)
    c.stop()


def by(project, name):
    return sorted(labels.get(PROVENANCE) for n, labels in for_project(project).series(name) if n == name)


def test_a_plugins_collector_runs_named_for_it_and_a_project_entry_of_that_name_wins(project, servers):
    theirs, ours = servers(b"messages_total 1\n"), servers(b"messages_total 2\n")
    declare(project, "")
    lines = []
    plugin = [Collector.scrape("slack", theirs, every_s=5, timeout_s=30, owner="bridges")]
    c = Collecting(project, lines.append, plugin_collectors=lambda: plugin)
    run_once(c)
    assert list(c.wanted) == ["bridges.slack"] and c.wanted["bridges.slack"].timeout_s == 5
    assert by(project, "messages_total") == ["bridges.slack"]

    c = Collecting(project, lines.append, plugin_collectors=lambda: plugin)
    declare(project, f'\n[[scrape]]\nname = "bridges.slack"\nurl = "{ours}"\n')
    run_once(c)
    assert c.wanted["bridges.slack"].target == ours and c.wanted["bridges.slack"].owner == "project"
    assert for_project(project).latest("messages_total", {PROVENANCE: "bridges.slack"})[1] == 2.0
    assert any("replaced by the project's entry" in ln for ln in lines)


def test_a_plugin_collector_that_cannot_run_is_left_out_with_the_reason(project):
    declare(project, "")
    lines = []
    plugin = [Collector.scrape("bad", "ftp://x", owner="bridges"), Collector.collect("ok", "true", every_s=60, owner="bridges")]
    c = Collecting(project, lines.append, plugin_collectors=lambda: plugin)
    c.tick(1000.0)
    c.stop()
    assert list(c.wanted) == ["bridges.ok"]
    assert any("plugin bridges: bridges.bad: url must start with" in ln for ln in lines)


class EntryPoint:
    def __init__(self, name, fn):
        self.name, self.fn = name, fn

    def load(self):
        return self.fn


def test_orchestra_run_scrapes_for_a_plugin_and_reports_a_second_plugin_of_its_name(project, servers):
    from orchestra.host import Host
    from orchestra.plugins import Plugin
    url = servers(b"messages_total 7\n")
    declare(project, "")
    found = [EntryPoint("bridges", lambda p: Plugin("bridges", collectors=[Collector.scrape("slack", url, every_s=1)])),
             EntryPoint("impostor", lambda p: Plugin("bridges", collectors=[Collector.scrape("other", url, every_s=1)]))]
    host = Host(project, interval=0.1, found=lambda: found, launch_every=0.05)
    t = threading.Thread(target=host.run)
    t.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline and not by(project, "messages_total"):
            time.sleep(0.1)
        assert by(project, "messages_total") == ["bridges.slack"]
    finally:
        host.stop()
        t.join(timeout=20)
    assert not t.is_alive()
    log = (project.logs_dir / "orchestra-host.log").read_text()
    assert "bridges.slack" in log and "bridges.other" not in log
    assert "plugin impostor failed to load: its name 'bridges' is taken" in log
