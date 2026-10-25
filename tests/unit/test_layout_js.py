"""The Node tests (tests/layout: the Dynamics layout; tests/loops: feedback loops), run here so the suite covers them.

They need Node and elkjs (``npm ci`` in tests/layout); without them they are skipped, with how to
get them."""

import shutil
import subprocess
from pathlib import Path

import pytest

LAYOUT = Path(__file__).resolve().parent.parent / "layout"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
@pytest.mark.skipif(not (LAYOUT / "node_modules" / "elkjs").exists(), reason="needs elkjs: npm ci in tests/layout")
def test_the_dynamics_layout():
    r = subprocess.run(["node", "--test", "layout.test.mjs"], cwd=LAYOUT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_feedback_loops():
    loops = LAYOUT.parent / "loops"
    r = subprocess.run(["node", "--test", "loops.test.mjs"], cwd=loops, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
