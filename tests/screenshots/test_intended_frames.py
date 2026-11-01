"""The Dynamics page renders each intended-model frame (docs/proposals/intended-model.md §7, §10 test
32) from C1's API on a seeded store, not from fixture JSON: the screenshots land in
``tests/screenshots/intended/`` to compare by eye with ``mockups/out/D*.png``, and each frame's DOM is
checked here. Needs node, puppeteer-core and Chrome for Testing (as ``mockups/tools/render.cjs``);
skips without them. Not in the default test paths: ``uv run python -m pytest tests/screenshots``."""

import importlib.util
import shutil
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _tools() -> bool:
    home = Path.home()
    return bool(shutil.which("node")) and any((home / ".npm/_npx").glob("*/node_modules/puppeteer-core")) \
        and (home / ".cache/puppeteer/chrome").is_dir()


pytestmark = pytest.mark.skipif(not _tools(), reason="needs node, puppeteer-core and Chrome for Testing")


@pytest.fixture(scope="module")
def frames():
    spec = importlib.util.spec_from_file_location("intended_frames", HERE / "intended_frames.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render()


def test_every_frame_renders_without_errors(frames):
    for f in ("D1", "D1-closed", "D2", "D3", "D3-closed", "D-extras"):
        assert frames[f]["errors"] == [], (f, frames[f]["errors"])
        assert (HERE / "intended" / f"{f}.png").stat().st_size > 10_000


def test_d1_the_ghost_and_how_to_measure_it(frames):
    d = frames["D1"]
    assert d["ghost"]["tags"][0].startswith("expected · declared by you")
    assert "im-ghost" in d["ghost"]["cls"]
    assert d["switch"] is None                         # one version: nothing to compare with
    dr = d["drawer"]
    assert dr["head"].startswith("Features stock") and "no series yet" in dr["head"]
    assert [(o["key"], o["on"]) for o in dr["options"]] == [("a", True), ("d", False)]
    assert "script collector" in dr["options"][0]["text"] and "cost: a CI run" in dr["options"][0]["text"]
    assert dr["readOnly"]
    assert "recording since" in dr["recording"] and "features.acceptance" in dr["recording"] and "3 points" in dr["recording"]
    assert dr["spark"]
    assert "features_acceptance.sh" in dr["script"] and "[[collect]]" in dr["peek"] and 'name = "features.acceptance"' in dr["peek"]


def test_d1_closed_the_expected_group(frames):
    d = frames["D1-closed"]
    assert d["drawer"] is None
    assert len(d["expectedGroup"]) == 1 and d["expectedGroup"][0].startswith("Features")
    assert d["nstocks"] == "7 found · 1 expected"
    assert d["groups"][0].startswith("Expected 1") and d["groups"][1].startswith("Found by discovery 7")
    # one version, nothing to compare with: no "new" or "removed" keys in the legend
    assert d["legend"] == ["expected, present", "expected, missing (ghost)"]


def test_d2_changes_since_the_previous_version(frames):
    d = frames["D2"]
    assert d["switch"] == {"on": True, "text": "changes since v1"}
    assert d["acc"]["ring"] and d["acc"]["tags"] == ["new in v2"]
    assert d["newEdge"] and d["removedEdge"] and "gone in v2" in d["removedLabel"]
    # Features was never in a version: its tag says who declared it, never "not in v2" (mockups/README.md)
    assert d["ghost"]["tags"][0].startswith("expected · declared by you")
    assert d["legend"][2:] == ["new in this version", "removed since last version"]
    assert any(t.startswith("may be: acceptance tests passing") for t in d["ghost"]["tags"])
    rows = d["changes"]["rows"]
    assert d["changes"]["head"] == "Changes since v1" and d["changes"]["count"] == "4"
    assert [r["sign"] for r in rows] == ["+", "+", "-", "o"]
    assert all(r["controls"] == ["expect", "ignore"] for r in rows if r["sign"] == "+")
    assert "Against version 1" in d["changes"]["foot"]
    assert d["tableMarks"]["stocks"] == 1 and d["tableMarks"]["flows"] == 1 and len(d["tableMarks"]["gone"]) == 1


def test_d3_the_expected_switch_and_the_pin(frames):
    assert frames["expectClicked"] == ["expected", "new"]
    d = frames["D3"]
    assert d["switch"]["on"] is False and d["changes"] is None
    assert d["drawer"]["expect"]["on"] and "confirmed by you" in d["drawer"]["expect"]["text"]
    assert 'from "changes since v1"' in d["drawer"]["expect"]["text"]
    c = frames["D3-closed"]
    assert c["acc"]["pin"] and not c["acc"]["ring"]
    rows = [r.lstrip("⌖") for r in c["expectedGroup"]]
    assert rows[0].startswith("Features declared by you") and rows[1] == "acceptance tests passing"
    assert c["nstocks"] == "8 found · 2 expected"


def test_the_states_with_no_frame(frames):
    d = frames["D-extras"]
    assert "not measured" in d["ghost"]["tags"] and d["ghost"]["sub"] == "not measured"
    assert d["declaredFlow"].startswith("features delivered")
    assert "predicted" in d["predictedFlow"]
    assert d["simulated"] == {"hatch": True, "tags": ["simulated"]}
    assert "simulated" in d["legend"]
