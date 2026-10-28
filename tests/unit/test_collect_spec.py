"""``[[collect]]`` entries as ``orchestra.toml`` gives them (orchestra/collect/spec.py)."""

import sys
import tomllib

from orchestra.collect.round import collect
from orchestra.collect.spec import from_toml


def parsed(text: str):
    return from_toml(tomllib.loads(text))


def test_a_command_may_be_a_list_of_words_run_as_they_are(tmp_path):
    found, errors = parsed('[[collect]]\nname = "x"\ncommand = ["sh", "-c", "echo \\"x_items 4\\""]\n')
    assert errors == []
    [c] = found
    assert c.argv() == ["sh", "-c", 'echo "x_items 4"']          # no shell splitting of the words
    assert c.shown == "sh -c 'echo \"x_items 4\"'"
    hash(c)                                                      # still a frozen, hashable collector
    r = collect(c, tmp_path, "proj", tmp_path / "x.log")
    assert r.error is None and [(p.series, p.value) for p in r.points] == [("x_items", 4.0)]


def test_a_string_command_is_split_like_a_shell_would():
    [c], errors = parsed('[[collect]]\nname = "x"\ncommand = "tools/x.sh --gate \'a b\'"\n')
    assert errors == [] and c.argv() == ["tools/x.sh", "--gate", "a b"] and c.shown == "tools/x.sh --gate 'a b'"


def test_python_is_the_python_orchestra_runs_in():
    found, _ = parsed('[[collect]]\nname = "a"\ncommand = "python3 tools/x.py"\n'
                      '[[collect]]\nname = "b"\ncommand = ["python", "-m", "orchestra.instruments.test_reports"]\n'
                      '[[collect]]\nname = "c"\ncommand = "python3.11 tools/x.py"\n')
    assert [c.argv() for c in found] == [[sys.executable, "tools/x.py"],
                                         [sys.executable, "-m", "orchestra.instruments.test_reports"],
                                         ["python3.11", "tools/x.py"]]        # only python and python3
    assert found[0].shown == "python3 tools/x.py"                          # shown as written


def test_a_bad_command_says_what_it_must_be():
    found, errors = parsed('[[collect]]\nname = "a"\ncommand = []\n'
                           '[[collect]]\nname = "b"\ncommand = ["sh", 3]\n'
                           '[[collect]]\nname = "c"\ncommand = 3\n'
                           '[[collect]]\nname = "d"\n'
                           '[[scrape]]\nname = "e"\nurl = ["http://x"]\n')
    assert found == []
    assert errors == ["[[collect]] entry 1: a: empty command; left out",
                      "[[collect]] entry 2: b: command must be a string or a list of strings, not ['sh', 3]; left out",
                      "[[collect]] entry 3: c: command must be a string or a list of strings, not 3; left out",
                      "[[collect]] entry 4: d: needs a command; left out",
                      "[[scrape]] entry 1: e: url must be a string, not ['http://x']; left out"]
