"""The commands removed on 2026-10-27 (whatif, predict, eras, observability), and `sd fit`, are
gone: the owner does not use command lines; machines use the APIs (SPEC §3.1, §4.5) and people the
web UI. The docs describe what is, not what was removed."""

from pathlib import Path

import pytest

from orchestra.cli import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("command", ["whatif", "predict", "eras", "observability", "fit"])
def test_the_command_is_gone(command, capsys):
    with pytest.raises(SystemExit) as e:
        main(["sd", command])
    assert e.value.code == 2 and f"invalid choice: '{command}'" in capsys.readouterr().err


def test_the_modules_behind_them_are_gone():
    sd = ROOT / "orchestra" / "sd"
    assert not (sd / "whatif.py").exists() and not (sd / "whatif_report.py").exists() and not (sd / "fit.py").exists()
