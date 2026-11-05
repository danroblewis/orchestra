"""``orchestra run --web``: the host and the web server from one command, the web server stopped with
the host (the owner, 2026-11-04)."""

import subprocess
import sys
from typing import ClassVar

from orchestra import cli


class FakePopen:
    made: ClassVar[list] = []

    def __init__(self, argv):
        self.argv, self.stopped = argv, False
        FakePopen.made.append(self)

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.stopped = True


def test_run_web_starts_the_web_server_and_stops_it_with_the_host(monkeypatch, tmp_path):
    args = type("A", (), {"web": True, "once": False, "port": 8123, "host": "127.0.0.1"})()
    from orchestra import host
    monkeypatch.setattr(cli, "_project", lambda a: type("P", (), {"repo_root": tmp_path})())
    monkeypatch.setattr(cli, "_cannot_bind", lambda h, p: None)
    monkeypatch.setattr(host, "Host", lambda p: type("H", (), {"run": lambda self, once=False: None})())
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    FakePopen.made = []
    assert cli.cmd_run(args) == 0
    (web,) = FakePopen.made
    assert web.argv[:3] == [sys.executable, "-m", "orchestra"] and "web" in web.argv and "8123" in web.argv
    assert web.stopped


def test_run_without_web_starts_no_server(monkeypatch, tmp_path):
    args = type("A", (), {"web": False, "once": False, "port": 8000, "host": "127.0.0.1"})()
    from orchestra import host
    monkeypatch.setattr(cli, "_project", lambda a: type("P", (), {"repo_root": tmp_path})())
    monkeypatch.setattr(host, "Host", lambda p: type("H", (), {"run": lambda self, once=False: None})())
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    FakePopen.made = []
    assert cli.cmd_run(args) == 0 and FakePopen.made == []


def test_run_web_refuses_a_port_in_use(monkeypatch, tmp_path, capsys):
    args = type("A", (), {"web": True, "once": False, "port": 8000, "host": "127.0.0.1"})()
    monkeypatch.setattr(cli, "_project", lambda a: type("P", (), {"repo_root": tmp_path})())
    monkeypatch.setattr(cli, "_cannot_bind", lambda h, p: "port 8000 is in use")
    assert cli.cmd_run(args) == 1 and "--port 8010" in capsys.readouterr().err
