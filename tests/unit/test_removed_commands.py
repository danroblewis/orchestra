"""The commands experiments replaced (2026-10-27) are gone, and the docs say so: the owner does not
use command lines; machines use the APIs (SPEC §3.1, §4.5) and people the web UI."""

from pathlib import Path

import pytest

from orchestra.cli import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("command", ["whatif", "predict", "eras", "observability"])
def test_the_command_is_gone(command, capsys):
    with pytest.raises(SystemExit) as e:
        main(["sd", command])
    assert e.value.code == 2 and f"invalid choice: '{command}'" in capsys.readouterr().err


def test_the_modules_behind_them_are_gone():
    sd = ROOT / "orchestra" / "sd"
    assert not (sd / "whatif.py").exists() and not (sd / "whatif_report.py").exists()


@pytest.mark.parametrize("doc", ["SPEC.md", "USING_ORCHESTRA.md", "ARCHITECTURE.md"])
def test_the_docs_say_they_were_removed(doc):
    text = " ".join((ROOT / doc).read_text(encoding="utf-8").split())
    assert "were removed on 2026-10-27" in text or "was removed on 2026-10-27" in text
    for command in ("sd whatif", "sd predict", "sd eras", "sd observability"):
        assert command in text, f"{doc} says {command} is gone"
