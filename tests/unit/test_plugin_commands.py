"""Plugin commands: `orchestra <plugin> [args...]` from the entry point group orchestra.commands
(orchestra/commands.py, orchestra/cli.py)."""

import argparse
import sys
import types

import pytest

from orchestra import cli, commands


class EntryPoint:
    def __init__(self, name, fn, value=None):
        self.name, self.fn, self.value = name, fn, value or f"fake.{name}:main"

    def load(self):
        if isinstance(self.fn, Exception):
            raise self.fn
        return self.fn


@pytest.fixture
def installed(monkeypatch):
    for k in (commands.PROG_ENV, "ORCHESTRA_REPO"):     # run() sets them: set and unset here so each is restored
        monkeypatch.setenv(k, "")
        monkeypatch.delenv(k)

    def use(*eps):
        monkeypatch.setattr(commands, "entry_points", lambda group: list(eps) if group == commands.GROUP else [])
    return use


def test_a_plugin_command_gets_the_rest_of_argv_and_its_prog(installed, capsys):
    seen = {}

    def main(argv):
        seen["argv"] = argv
        seen["env"] = commands.os.environ[commands.PROG_ENV]
        p = argparse.ArgumentParser()
        p.add_argument("action")
        p.add_argument("--to")
        a = p.parse_args(argv)
        print(p.format_usage().strip(), a.action, a.to)
        return 3
    installed(EntryPoint("tasks", main))
    before = sys.argv
    assert cli.main(["tasks", "add", "--to", "y"]) == 3
    assert seen == {"argv": ["add", "--to", "y"], "env": "orchestra tasks"}
    assert capsys.readouterr().out.startswith("usage: orchestra tasks [-h]")
    assert sys.argv is before


def test_none_is_success_and_repo_before_the_name_is_passed_on(installed):
    got = {}
    installed(EntryPoint("desk", lambda argv: got.update(argv=argv, repo=commands.os.environ.get("ORCHESTRA_REPO"))))
    assert cli.main(["--repo", "/r", "desk", "--help"]) == 0
    assert got == {"argv": ["--help"], "repo": "/r"}
    assert cli.main(["--repo=/s", "desk"]) == 0 and got == {"argv": [], "repo": "/s"}


def test_help_lists_plugin_commands_with_one_line_each(installed, capsys, monkeypatch):
    mod = types.ModuleType("fake_agents")
    mod.__doc__ = "The AI agents: hosts and harnesses.\n\nMore here."
    monkeypatch.setitem(sys.modules, "fake_agents", mod)

    def agents(argv):
        return 0
    agents.__module__ = "fake_agents"

    def desk(argv):
        return 0
    desk.help = "the owner's desk"
    installed(EntryPoint("agents", agents), EntryPoint("desk", desk), EntryPoint("outbox", ImportError("no module named outbox")))
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "(plugin) The AI agents: hosts and harnesses." in out and "More here" not in out
    assert "(plugin) the owner's desk" in out
    assert "(broken: ImportError: no module named outbox)" in out
    assert "init" in out and "sources" in out


def test_a_broken_command_fails_alone_with_a_clear_error(installed, capsys, tmp_path, monkeypatch):
    installed(EntryPoint("outbox", ImportError("no module named outbox"), "orchestra_outbox.cli:main"),
              EntryPoint("bridges", 42, "orchestra_bridges:VERSION"))
    assert cli.main(["outbox", "send"]) == 1
    err = capsys.readouterr().err
    assert "plugin command 'outbox' (orchestra_outbox.cli:main) failed to load: ImportError: no module named outbox" in err
    assert cli.main(["bridges"]) == 1
    assert "not a callable" in capsys.readouterr().err
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    with pytest.raises(SystemExit):     # Orchestra's own commands still parse
        cli.main(["sd", "--help"])
    assert "discover" in capsys.readouterr().out


def test_a_name_colliding_with_a_builtin_is_refused_with_a_warning(installed, capsys):
    called = []
    installed(EntryPoint("events", lambda argv: called.append(argv), "evil:main"),
              EntryPoint("tasks", lambda argv: called.append(("first", argv)), "a:main"),
              EntryPoint("tasks", lambda argv: called.append(("second", argv)), "b:main"))
    with pytest.raises(SystemExit):
        cli.main(["events", "--help"])
    out = capsys.readouterr()
    assert called == [] and "--to" in out.out
    assert "plugin command 'events' (evil:main) is refused" in out.err
    assert "plugin command 'tasks' (b:main) is left out: the name is taken by a:main" in out.err
    assert cli.main(["tasks", "x"]) == 0 and called == [("first", ["x"])]


def test_the_builtin_names_are_the_parsers_subcommands():
    p = cli.build_parser()
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == commands.BUILTIN
