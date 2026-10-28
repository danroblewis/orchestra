"""The private overlay (orchestra/overlay.py): a file outside the repository merged over orchestra.toml."""

import os
import subprocess
import sys
import threading
import time
import tomllib

import pytest
from fastapi.testclient import TestClient

from orchestra import runtime
from orchestra.config import OVERLAY_ENV, ConfigError, init_project, load_project
from orchestra.launcher import Process
from orchestra.overlay import describe, merge

PY = sys.executable
SLEEPER = "import time\nwhile True: time.sleep(0.1)"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    monkeypatch.delenv("ORCHESTRA_REPO", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "orchestra.toml").write_text('[metrics]\nurl = "file"\n')
    return init_project(r)


_bump = iter(range(1, 10_000))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    t = time.time() + next(_bump)
    os.utime(path, (t, t))                      # a new mtime, however fast the test rewrites it


def until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


# ---- the merge rules

REPO = tomllib.loads("""
[events]
url = "file"
listen = "127.0.0.1:0"

[slack]
team = "eng"
channels = ["#general"]

[[machines]]
name = "a"
command = "run a"

[[machines]]
name = "b"
command = "run b"

[[collect]]
name = "disk"
command = "./disk.sh"
""")


def test_tables_merge_key_by_key_and_the_overlay_wins():
    raw, layers = merge(REPO, tomllib.loads('[events]\nlisten = "off"\n[slack]\nchannels = ["#mine"]\nme = "U1"\n'))
    assert raw["events"] == {"url": "file", "listen": "off"}
    assert raw["slack"] == {"team": "eng", "channels": ["#mine"], "me": "U1"}     # an array of values is replaced
    assert layers.set == {"events.listen", "slack.channels", "slack.me"}
    assert REPO["events"]["listen"] == "127.0.0.1:0"                              # the repository's is untouched


def test_arrays_of_tables_merge_by_name_append_replace_and_disable():
    raw, layers = merge(REPO, tomllib.loads("""
[[machines]]
name = "b"
command = "my b"

[[machines]]
name = "c"
command = "run c"

[[machines]]
name = "a"
enabled = false

[[machines]]
name = "nowhere"
enabled = false

[[scrape]]
name = "app"
url = "http://127.0.0.1:9100/metrics"
"""))
    assert raw["machines"] == [{"name": "b", "command": "my b"}, {"name": "c", "command": "run c"}]
    assert raw["collect"] == REPO["collect"]                                     # untouched
    assert raw["scrape"] == [{"name": "app", "url": "http://127.0.0.1:9100/metrics"}]
    assert layers.removed == ["machines[a]"]                                     # nothing named "nowhere" to remove
    assert layers.set == {"machines[b]", "machines[c]", "scrape[app]"}


def test_nested_arrays_of_tables_in_a_plugin_section_merge_the_same_way():
    repo = tomllib.loads('[tasks]\nbase = "main"\n[[tasks.roles]]\nname = "worker"\nn = 1\n')
    raw, _ = merge(repo, tomllib.loads('[[tasks.roles]]\nname = "worker"\nn = 3\n[[tasks.roles]]\nname = "drafter"\n'))
    assert raw["tasks"] == {"base": "main", "roles": [{"name": "worker", "n": 3}, {"name": "drafter"}]}


def test_describe_says_where_each_key_came_from_and_hides_secrets():
    raw, layers = merge(REPO, tomllib.loads("""
[overlay]
secret = ["slack.me", "machines[c].command"]

[slack]
me = "U1"

[[machines]]
name = "c"
command = "page-me --to U1"
restart = "never"
"""))
    assert "overlay" not in raw                                                  # the overlay's own table is not merged
    rows = {r["key"]: r for r in describe(raw, layers)}
    assert rows["events.url"] == {"key": "events.url", "from": "repo", "value": "file"}
    assert rows["slack.team"]["from"] == "repo"
    assert rows["slack.me"] == {"key": "slack.me", "from": "overlay", "secret": True}
    assert rows["machines[a]"] == {"key": "machines[a]", "from": "repo", "value": {"name": "a", "command": "run a"}}
    assert rows["machines[c]"] == {"key": "machines[c]", "from": "overlay", "value": {"name": "c", "restart": "never"},
                                   "secret_fields": ["command"]}
    assert all(r["from"] == "repo" and "secret" not in r for r in describe(REPO, None))


def test_a_bad_overlay_table_is_refused():
    with pytest.raises(ValueError):
        merge(REPO, {"overlay": {"secret": "slack"}})


# ---- the project

def test_without_an_overlay_the_configuration_is_orchestra_toml_alone(project):
    assert not project.overlay_file.exists()
    assert project.overlay_file == project.state_dir / "orchestra.local.toml"
    assert project.config.layers is None
    assert project.config.raw == tomllib.loads((project.repo_root / "orchestra.toml").read_text())
    assert load_project(project.repo_root).config.raw == project.config.raw


def test_the_overlay_in_the_state_directory_is_merged_on_load(project):
    write(project.overlay_file, '[metrics]\nurl = "http://127.0.0.1:8428"\n[desk]\nme = "U1"\n')
    p = load_project(project.repo_root)
    assert p.config.metrics_url == "http://127.0.0.1:8428" and p.config.raw["desk"] == {"me": "U1"}
    assert p.config.layers.path == str(project.overlay_file)


def test_the_overlay_can_be_named_by_the_environment_and_a_missing_one_is_an_error(project, tmp_path, monkeypatch):
    elsewhere = tmp_path / "private" / "work.toml"
    monkeypatch.setenv(OVERLAY_ENV, str(elsewhere))
    with pytest.raises(ConfigError, match="does not exist"):
        load_project(project.repo_root)
    write(elsewhere, '[desk]\nme = "U1"\n')
    write(project.state_dir / "orchestra.local.toml", '[desk]\nme = "ignored"\n')     # the environment's wins
    assert load_project(project.repo_root).config.raw["desk"] == {"me": "U1"}


def test_an_overlay_that_does_not_parse_is_a_config_error(project):
    write(project.overlay_file, "[desk\n")
    with pytest.raises(ConfigError, match="orchestra.local.toml"):
        project.read_config()


def test_the_stamp_changes_when_the_overlay_appears_changes_or_goes(project):
    s0 = project.config_stamp()
    write(project.overlay_file, "[desk]\n")
    s1 = project.config_stamp()
    write(project.overlay_file, '[desk]\nme = "U1"\n')
    s2 = project.config_stamp()
    project.overlay_file.unlink()
    assert len({s0, s1, s2}) == 3 and project.config_stamp() == s0


def test_api_project_shows_where_each_key_came_from(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    write(project.overlay_file, '[overlay]\nsecret = ["desk.token_name"]\n[desk]\nme = "U1"\ntoken_name = "WORK_SLACK"\n'
                                '[metrics]\nurl = "file"\n')
    body = TestClient(create_app(project), headers=bearer(project)).get("/api/project").json()
    assert body["key"] == project.key
    files = {f["role"]: f for f in body["config"]["files"]}
    assert files["overlay"]["exists"] and files["overlay"]["named_by"] == "state directory"
    rows = {r["key"]: r for r in body["config"]["keys"]}
    assert rows["metrics.url"] == {"key": "metrics.url", "from": "overlay", "value": "file"}
    assert rows["desk.me"] == {"key": "desk.me", "from": "overlay", "value": "U1"}
    assert rows["desk.token_name"] == {"key": "desk.token_name", "from": "overlay", "secret": True}
    assert "WORK_SLACK" not in str(body)


def test_api_project_without_an_overlay(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    body = TestClient(create_app(project), headers=bearer(project)).get("/api/project").json()
    assert not {f["role"]: f for f in body["config"]["files"]}["overlay"]["exists"]
    assert all(r["from"] == "repo" for r in body["config"]["keys"]) and body["config"]["removed"] == []


# ---- the host follows the overlay

def test_a_plugin_section_only_in_the_overlay_reaches_the_plugin_and_follows_its_changes(project):
    """The plugin reads project.config.raw, as every plugin does; it never knows there is an overlay."""
    from orchestra.host import Host
    from orchestra.plugins import Plugin

    seen = []

    def make(project):
        seen.append(project.config.raw.get("tools"))
        return Plugin("tools", processes=[Process("helper", [PY, "-c", SLEEPER])] if "tools" in project.config.raw else [])

    class EntryPoint:
        name = "tools"

        def load(self):
            return make

    def procs():
        return {n: r["state"] for n, r in (runtime.read(project).get("processes") or {}).items()}

    host = Host(project, interval=0.1, found=lambda: [EntryPoint()], launch_every=0.05)
    t = threading.Thread(target=host.run)
    t.start()
    try:
        until(lambda: "launcher" in runtime.read(project))
        time.sleep(0.3)
        assert procs() == {}
        write(project.overlay_file, '[tools]\nchannel = "#me"\n')                  # only in the overlay: the plugin sees it
        until(lambda: procs() == {"tools.helper": "running"})
        assert {"channel": "#me"} in seen
        assert "tools" not in tomllib.loads((project.repo_root / "orchestra.toml").read_text())
        pid = runtime.read(project)["processes"]["tools.helper"]["pid"]
        project.overlay_file.unlink()                                               # the overlay gone: its process stops
        until(lambda: procs() == {})
        assert not runtime.alive(pid)
    finally:
        host.stop()
        t.join(timeout=20)


def test_the_launcher_follows_machines_the_overlay_adds_and_removes(project):
    from orchestra.launcher import Launcher

    write(project.repo_root / "orchestra.toml",
          f'[[machines]]\nname = "team"\ncommand = {_toml_list([PY, "-c", SLEEPER])}\n')
    la = Launcher(project, lambda t, d: None, lambda m: None, backoff=0.05, grace=2.0)

    def running():
        la.tick()
        return {n for n, r in la.runs.items() if r.state == "running"}

    try:
        until(lambda: running() == {"team"})
        write(project.overlay_file, f'[[machines]]\nname = "mine"\ncommand = {_toml_list([PY, "-c", SLEEPER])}\n'
                                    '[[machines]]\nname = "team"\nenabled = false\n')
        until(lambda: running() == {"mine"} and "team" not in la.runs)
    finally:
        la.stop_all()


def _toml_list(items):
    import json
    return "[" + ", ".join(json.dumps(i) for i in items) + "]"
