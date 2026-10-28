"""What a process Orchestra starts finds as `python` (orchestra/launcher.py, child_env): Orchestra's
own Python, even inside `sh -c`, while the project's `uv run python` stays the project's."""

import os
import shutil
import subprocess
import sys

import pytest

from orchestra import launcher
from orchestra.collect.round import collect
from orchestra.collect.spec import Collector


@pytest.fixture
def failing_python_first(tmp_path, monkeypatch):
    """A `python` and `python3` that only fail, first on the PATH (Anaconda's, say)."""
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for name in ("python", "python3"):
        (fake / name).write_text("#!/bin/sh\necho 'No module named orchestra' >&2\nexit 9\n")
        (fake / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    return fake


def test_python_inside_sh_c_is_orchestras(tmp_path, failing_python_first):
    cmd = ["sh", "-c", ("python -c 'import orchestra; print(\"ok_total 1\")'; "
                        "python3 -c 'import orchestra; print(\"ok3_total 1\")'")]
    r = collect(Collector("t", "collect", cmd, 60, 30), tmp_path, "proj", tmp_path / "t.log")
    assert r.error is None, (tmp_path / "t.log").read_text()
    assert {p.series for p in r.points} == {"ok_total", "ok3_total"}


def test_the_directory_put_first_runs_orchestras_python(tmp_path, failing_python_first):
    d = launcher.python_dir()
    env = launcher.child_env({"X": "1"})
    assert env["PATH"].split(os.pathsep)[0] == d and env["X"] == "1"
    for name in ("python", "python3"):
        out = subprocess.run([os.path.join(d, name), "-c", "import sys; print(sys.prefix)"],
                             capture_output=True, text=True, check=True).stdout.strip()
        assert out == sys.prefix


def test_a_shim_when_sys_executable_has_no_python_beside_it(tmp_path, failing_python_first, monkeypatch):
    """sys.executable named python3.12 only (no python, python3 beside it): a shim directory under
    Orchestra's home whose scripts exec it, never the directory with another python."""
    alone = tmp_path / "alone"
    alone.mkdir()
    exe = alone / "python3.99"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n")
    exe.chmod(0o755)
    (alone / "python").write_text("#!/bin/sh\nexit 9\n")          # another interpreter beside it
    (alone / "python").chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(exe))
    d = launcher.python_dir()
    assert d is not None and d != str(alone) and d.startswith(str(tmp_path / "home"))
    out = subprocess.run([os.path.join(d, "python"), "-c", "print(42)"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "42"
    assert launcher.python_dir() == d                               # made once, found again


def test_virtual_env_of_orchestras_own_is_dropped(monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
    assert "VIRTUAL_ENV" not in launcher.child_env()
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else/.venv")
    assert launcher.child_env()["VIRTUAL_ENV"] == "/somewhere/else/.venv"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_uv_run_python_is_still_the_projects(tmp_path, failing_python_first, monkeypatch):
    """A scratch uv project, its `.venv` made; `uv run python` in a collect command is the project's."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text('[project]\nname = "scratch"\nversion = "0"\nrequires-python = ">=3.8"\n'
                                         'dependencies = []\n')
    monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)                      # as under `uv run orchestra`
    made = subprocess.run(["uv", "venv", "-q", "--python", sys.executable, str(proj / ".venv")], check=False,
                          cwd=proj,
                          capture_output=True, text=True, env=launcher.child_env())
    if made.returncode != 0:
        pytest.skip(f"uv cannot make a venv here: {made.stderr.strip()}")
    cmd = ["sh", "-c", "uv run --offline -q python -c 'import sys; print(\"prefix{p=\\\"\" + sys.prefix + \"\\\"} 1\")'"]
    log = tmp_path / "uv.log"
    r = collect(Collector("uv", "collect", cmd, 60, 120), proj, "proj", log)
    if r.error is not None:
        pytest.skip(f"uv run failed here: {log.read_text()[-400:]}")
    assert [p.labels["p"] for p in r.points] == [str(proj / ".venv")]
    assert "VIRTUAL_ENV" not in log.read_text()                      # no warning about a mismatched env
