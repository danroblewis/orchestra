"""`orchestra events copy` copies the whole log forward in bounded pages, in order, and says so
when the target does not hold what the source does; `metrics backfill` is gone (the host replays
the log into the counters at every start)."""

import subprocess

import pytest

from orchestra import cli, plugins
from orchestra.bus.file import FileBus
from orchestra.cli import main
from orchestra.config import init_project
from orchestra.events import Events


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_copy_reads_every_event_in_order_a_small_page_at_a_time(project, monkeypatch, capsys):
    monkeypatch.setattr(cli, "COPY_PAGE", 3)
    pub = Events.for_project(project, source="m")
    for i in range(20):
        pub.publish("x.counted", {"i": i})
    pages = []
    real = Events.page
    monkeypatch.setattr(Events, "page", lambda self, since, limit: pages.append(limit) or real(self, since, limit))
    assert main(["--repo", str(project.repo_root), "events", "copy", "--to", "file"]) == 0
    got = FileBus(project.events_file.with_name("events.copy.jsonl")).read(0, 1000)[0]
    assert [e["data"]["i"] for e in got] == list(range(20))
    assert len(pages) == 7 and set(pages) == {3}
    assert "copied 20 events" in capsys.readouterr().out


def test_a_copy_that_does_not_match_the_source_exits_1(project, capsys):
    pub = Events.for_project(project, source="m")
    pub.publish("x.counted", {"i": 0})
    with project.events_file.open("a") as f:
        f.write("{torn\n")
    assert main(["--repo", str(project.repo_root), "events", "copy", "--to", "file"]) == 1
    assert "the source holds 2" in capsys.readouterr().out


def test_metrics_backfill_is_gone(capsys):
    with pytest.raises(SystemExit) as e:
        main(["metrics", "backfill"])
    assert e.value.code == 2 and "invalid choice: 'backfill'" in capsys.readouterr().err
