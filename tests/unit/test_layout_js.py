"""The Node tests (tests/layout: the Dynamics layout; tests/loops: feedback loops; tests/names: what stocks and flows are called; tests/cards: the rows of a machine's card, its details panel, and who the owner's requests reach; tests/machine_graph: the Machines page's event map; tests/left_out: what a discovery left out; tests/charts: the line charts; tests/evidence: what the Dynamics tables say of the evidence; tests/panel_order: the Dashboard's panel order), run here so the suite covers them.

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
    r = subprocess.run(["node", "--test", "layout.test.mjs"], cwd=LAYOUT, capture_output=True, text=True, timeout=300, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_feedback_loops():
    loops = LAYOUT.parent / "loops"
    r = subprocess.run(["node", "--test", "loops.test.mjs"], cwd=loops, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_names_of_stocks_and_flows():
    names = LAYOUT.parent / "names"
    r = subprocess.run(["node", "--test", "names.test.mjs"], cwd=names, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_rows_of_a_machines_card():
    cards = LAYOUT.parent / "cards"
    r = subprocess.run(["node", "--test", "cards.test.mjs"], cwd=cards, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_a_machines_panel_closed_and_reopened_is_drawn_again():
    cards = LAYOUT.parent / "cards"
    r = subprocess.run(["node", "--test", "intended-panel.test.mjs"], cwd=cards, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_machines_event_map():
    graph = LAYOUT.parent / "machine_graph"
    r = subprocess.run(["node", "--test", "machine_graph.test.mjs"], cwd=graph, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_what_a_discovery_left_out_adds_up():
    here = LAYOUT.parent / "left_out"
    r = subprocess.run(["node", "--test", "left_out.test.mjs"], cwd=here, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_line_charts():
    charts = LAYOUT.parent / "charts"
    r = subprocess.run(["node", "--test", "charts.test.mjs"], cwd=charts, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_what_the_dynamics_tables_say_of_the_evidence():
    here = LAYOUT.parent / "evidence"
    r = subprocess.run(["node", "--test", "evidence.test.mjs"], cwd=here, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_who_the_owners_requests_reach():
    cards = LAYOUT.parent / "cards"
    r = subprocess.run(["node", "--test", "intended-core.test.mjs"], cwd=cards, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_dashboards_panel_order():
    here = LAYOUT.parent / "panel_order"
    r = subprocess.run(["node", "--test", "panel_order.test.mjs"], cwd=here, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_dynamics_pages_tags_say_who_said_what():
    cards = LAYOUT.parent / "cards"
    r = subprocess.run(["node", "--test", "intended-tags.test.mjs"], cwd=cards, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_the_eras_bar_with_no_era_and_the_panel_wrapper():
    here = LAYOUT.parent / "eras"
    r = subprocess.run(["node", "--test", "eras.test.mjs"], cwd=here, capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
