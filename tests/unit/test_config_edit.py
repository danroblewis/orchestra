"""Changing the configuration through Orchestra (orchestra/config_edit.py): in orchestra.toml or the
private overlay, keeping comments, validated against the merged result, reloaded."""

import os
import stat
import subprocess
import tomllib

import pytest
import tomlkit

from orchestra import plugins
from orchestra import toml_text as tt
from orchestra.config import OVERLAY_ENV, ConfigError, init_project
from orchestra.config_edit import Change

TEXT = """# the team's settings
[metrics]
url = "file"             # the default store

[tasks]
workers = 2              # tickets at once

# programs
[[machines]]
name = "a"
command = "a.sh"

[[machines]]
name = "b"
# b's own note
command = "b.sh"

# ---- the task system ----

[gate]
timeout = "300s"

[[gate.unit]]            # what a branch must pass
name = "unit"
command = "pytest"
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])    # the installed plugins' checks are theirs
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    monkeypatch.delenv("ORCHESTRA_REPO", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "orchestra.toml").write_text(TEXT)
    return init_project(r)


def test_set_in_the_repository_keeps_comments_and_reloads(project):
    c = project.config_edit.set("tasks.workers", 3)
    text = project.config_file.read_text()
    assert c.changed and c.target == "repo" and c.what == "tasks.workers = 3" and c.keys == ["tasks.workers"]
    assert "workers = 3\n" in text and "# the default store" in text and "# ---- the task system ----" in text
    assert text.replace("workers = 3\n", "workers = 2              # tickets at once\n") == TEXT
    assert project.config.raw["tasks"]["workers"] == 3                       # reloaded
    again = project.config_edit.set("tasks.workers", 3)
    assert not again.changed and again.keys == []
    both = project.config_edit.set_many({"tasks.workers": 4, "tasks.reviewers": 2})
    assert both.keys == ["tasks.reviewers", "tasks.workers"] and both.what == "tasks.workers = 4, tasks.reviewers = 2"
    assert project.config_edit.set_many({"tasks.workers": 5, "desk.owner": "person.u1"}, target="overlay").what == (
        "tasks.workers, desk.owner in the private overlay")


def test_set_in_the_overlay_creates_it_privately_and_wins(project):
    c = project.config_edit.set("desk.owner", "person.u0123", target="overlay")
    assert c.before is None and c.file == str(project.overlay_file) and "u0123" not in c.what
    assert stat.S_IMODE(os.stat(project.overlay_file).st_mode) == 0o600
    assert project.config_file.read_text() == TEXT                          # the repository's file is untouched
    assert project.config.raw["desk"] == {"owner": "person.u0123"} and project.config.layers.set >= {"desk"}
    over = project.config_edit.set("tasks.workers", 5, target="overlay")
    assert over.keys == ["tasks.workers"] and project.config.raw["tasks"]["workers"] == 5
    shadowed = project.config_edit.set("tasks.workers", 4)                   # the repository's: the overlay still wins
    assert shadowed.changed and shadowed.keys == [] and "still wins" in shadowed.note
    assert project.config_edit.unset("tasks.workers", target="overlay").keys == ["tasks.workers"]
    assert project.config.raw["tasks"]["workers"] == 4


def test_entries_in_the_repository(project):
    ed = project.config_edit
    assert ed.add_entry("collect", {"name": "disk", "command": "machines/disk.sh"}).what == "added [[collect]] disk"
    assert ed.add_entry("machines", {"name": "a", "command": "a2.sh"}).what == "changed [[machines]] a"
    text = project.config_file.read_text()
    assert '\n\n[[collect]]\nname = "disk"\ncommand = "machines/disk.sh"\n' in text and "# b's own note" in text
    c = ed.remove_entry("machines", "b")
    text = project.config_file.read_text()
    assert c.keys == ["machines[b]"] and "# ---- the task system ----" in text and "b's own note" not in text
    assert "\n\n\n" not in text
    ed.remove_entry("gate.unit", "unit")
    assert tomllib.loads(project.config_file.read_text())["gate"] == {"timeout": "300s"}
    with pytest.raises(ConfigError, match="no \\[\\[machines\\]\\] entry named 'zz'"):
        ed.remove_entry("machines", "zz")


def test_entries_in_the_overlay(project):
    ed = project.config_edit
    c = ed.add_entry("machines", {"name": "a", "restart": "never"}, target="overlay")
    assert c.what == "changed [[machines]] a in the private overlay"
    assert project.config.raw["machines"][0] == {"name": "a", "command": "a.sh", "restart": "never"}   # whole, from the repo's
    ed.remove_entry("machines", "b", target="overlay")
    assert [m["name"] for m in project.config.raw["machines"]] == ["a"]
    assert {"name": "b", "enabled": False} in tomllib.loads(project.overlay_file.read_text())["machines"]
    ed.add_entry("machines", {"name": "b", "command": "b2.sh"}, target="overlay")    # back, replacing the remover
    assert {m["name"]: m["command"] for m in project.config.raw["machines"]} == {"a": "a.sh", "b": "b2.sh"}
    ed.add_entry("machines", {"name": "pager", "command": "pager.sh"}, target="overlay")
    ed.remove_entry("machines", "pager", target="overlay")                   # the overlay's own: dropped
    assert "pager" not in project.overlay_file.read_text()
    assert project.config_file.read_text() == TEXT


def test_a_change_the_readers_refuse_is_not_made(project):
    ed = project.config_edit
    with pytest.raises(ConfigError, match="restart must be one of"):
        ed.add_entry("machines", {"name": "c", "command": "c.sh", "restart": "sometimes"})
    with pytest.raises(ConfigError, match="bad duration"):
        ed.set("discovery.every", "soon", target="overlay")
    with pytest.raises(ConfigError, match="mine says no"):
        ed.set("tasks.workers", -1, check=lambda raw: ["mine says no"] if raw["tasks"]["workers"] < 0 else [])
    with pytest.raises(ConfigError, match="not a table"):
        ed.set("tasks.workers.x", 1)
    assert project.config_file.read_text() == TEXT and not project.overlay_file.exists()


def test_dry_run_apply_and_restore(project):
    ed = project.config_edit
    c = ed.set("tasks.workers", 7, dry_run=True)
    assert project.config_file.read_text() == TEXT
    ed.apply(Change.from_dict(c.to_dict()))
    assert project.config.raw["tasks"]["workers"] == 7
    with pytest.raises(ConfigError, match="changed after"):
        ed.apply(c)
    assert ed.restore(c) and project.config_file.read_text() == TEXT
    assert not ed.restore(c)                                                 # the file no longer holds what it wrote
    o = ed.set("desk.owner", "person.x", target="overlay")
    assert ed.restore(o) and not project.overlay_file.exists()               # an overlay it created is gone again


def test_bad_targets_and_keys(project):
    with pytest.raises(ConfigError, match="target is repo or overlay"):
        project.config_edit.set("tasks.workers", 1, target="elsewhere")
    with pytest.raises(ConfigError, match="bad key"):
        project.config_edit.set("", 1)
    with pytest.raises(ConfigError, match="an entry is a table with a name"):
        project.config_edit.add_entry("machines", {"command": "x"})


def test_text_helpers_keep_layout():
    doc = tomlkit.parse(TEXT)
    assert tt.upsert(doc, ["machines"], {"name": "a", "command": "a2.sh"}) == {"name": "a", "command": "a.sh"}
    assert not tt.set_key(tt.table(doc, ["metrics"], True), "url", "file")    # unchanged: its comment stays
    assert "# the default store" in tomlkit.dumps(doc)
    with pytest.raises(ConfigError, match="not an array of tables"):
        tt.entries(tomlkit.parse('[gate]\nunit = "make test"\n'), ["gate", "unit"])


def test_every_loaded_plugin_s_check_judges_a_change(project, monkeypatch):
    """Plugin.check runs on every change: what it newly says refuses the change, with its name; a
    plugin that does not load, or whose check fails, refuses nothing and is reported."""
    from orchestra import config_edit, plugins
    from orchestra.plugins import Loaded, Plugin

    seen = []

    def tools_check(raw, repo_root):
        seen.append(repo_root)
        s = raw.get("tools")
        return [] if s is None or isinstance(s.get("every"), int) else ["[tools] every must be a number"]

    def broken_check(raw, repo_root):
        raise RuntimeError("oops")

    loads = []

    def load(project, found=None):
        loads.append(1)
        return Loaded([Plugin("tools", check=tools_check), Plugin("shaky", check=broken_check), Plugin("plain")],
                      [{"plugin": "gone", "error": "ImportError: no", "trace": ""}])

    monkeypatch.setattr(config_edit, "_LOADED", {})
    monkeypatch.setattr(plugins, "load", load)
    edit = project.config_edit
    c = edit.set("tools.every", 3)
    assert seen and seen[0] == project.repo_root
    assert any("plugin gone did not load" in w for w in c.warnings)
    assert any("plugin shaky's check failed" in w and "oops" in w for w in c.warnings)
    with pytest.raises(ConfigError, match=r"tools: \[tools\] every must be a number"):
        edit.set("tools.every", "soon")
    assert project.config.raw["tools"]["every"] == 3
    edit.unset("tools")                                            # removing its section: no objection
    assert "tools" not in project.config.raw
    assert len(loads) == 1                                         # loaded once, not per change


def test_a_plugin_check_only_refuses_what_it_newly_says(project):
    from orchestra.config_edit import ConfigEdit

    def check(raw, repo_root):
        return ["[gate] is old"] if "gate" in raw else []

    edit = ConfigEdit(project, plugins=[("tasks", check)])
    assert edit.set("tasks.workers", 5).changed                    # it already said so: not refused
    edit.unset("gate")
    with pytest.raises(ConfigError, match=r"tasks: \[gate\] is old"):
        edit.set("gate.timeout", "1s")


WRITER = """
import sys
from orchestra import plugins
plugins.entry_points = lambda group: []
from orchestra.config import ConfigError, load_project
project = load_project(sys.argv[1])
done = 0
for i in range(15):
    while True:
        try:
            project.config_edit.set(f"{sys.argv[2]}.k{i}", i)
            done += 1
            break
        except ConfigError as e:
            if "changed after" not in str(e):
                raise
            project.reload_config()            # another process wrote first: work it out again
print(done)
"""


def test_two_processes_changing_the_configuration_lose_nothing(project, spawn):
    import sys
    env = {**os.environ}
    procs = [spawn([sys.executable, "-c", WRITER, str(project.repo_root), who], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for who in ("alpha", "beta")]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), outs
    assert [o.strip() for o, _ in outs] == ["15", "15"]
    raw = tomllib.loads(project.config_file.read_text())
    assert raw["alpha"] == {f"k{i}": i for i in range(15)} and raw["beta"] == {f"k{i}": i for i in range(15)}


@pytest.mark.parametrize("array, other", [("machines", "collect"), ("collect", "machines"), ("scrape", "machines"),
                                          ("sources", "collect")])
def test_removing_the_overlay_s_last_entry_of_an_array_drops_the_array(project, array, other):
    ed = project.config_edit
    entry = {"sources": {"name": "x", "kind": "prometheus", "url": "http://localhost:1"},
             "scrape": {"name": "x", "url": "http://localhost:1/metrics"}}.get(array, {"name": "x", "command": "x.sh"})
    keep = {"name": "y", "command": "y.sh"}
    project.overlay_file.parent.mkdir(parents=True, exist_ok=True)
    project.overlay_file.write_text(f"# mine\n[[{other}]]\nname = \"y\"\ncommand = \"y.sh\"\n")
    project.reload_config()
    ed.add_entry(array, entry, target="overlay")
    ed.remove_entry(array, "x", target="overlay")
    text = project.overlay_file.read_text()
    assert array not in tomllib.loads(text) and tomllib.loads(text)[other] == [keep] and "# mine" in text
    ed.add_entry(array, entry, target="overlay")                             # and it can be added again
    assert tomllib.loads(project.overlay_file.read_text())[array] == [entry]


def test_an_empty_array_left_by_an_earlier_removal_is_no_entries():
    doc = tomlkit.parse('machines = []\n[[collect]]\nname = "y"\n')
    assert tt.entries(doc, ["machines"]) is None
    tt.upsert(doc, ["machines"], {"name": "x", "command": "x.sh"})
    assert tomllib.loads(tomlkit.dumps(doc))["machines"] == [{"name": "x", "command": "x.sh"}]
