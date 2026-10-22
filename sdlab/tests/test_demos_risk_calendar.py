"""Demo 5, risk calendar (docs/demos/risk-calendar.md): 30 days of known events through a stored found model and the
true model of 311; the flagged days, found beside true."""

import numpy as np
import pytest

from sdlab.demos import capacity as C
from sdlab.demos import risk_calendar as R


def _have():
    try:
        C.found("milp")
        C.setup()
        return True
    except Exception:                                                  # noqa: BLE001
        return False


needs = pytest.mark.skipif(not _have(), reason="no stored passing result of milp on 311 none-long in this store")


@needs
def test_events_shape_the_traffic_and_injections():
    base = np.asarray(C.base_traffic(R.STEPS))
    traffic, inj, ev = R.events(15, 0.4, 0.1, 22, 12, 4, False)
    D = C.STEPS_PER_DAY
    assert np.allclose(traffic[:15 * D], base[:15 * D])
    assert np.allclose(traffic[15 * D:16 * D], 1.4 * base[15 * D:16 * D])
    assert np.allclose(traffic[16 * D:], 1.1 * base[16 * D:])
    t0 = 22 * D + 12 * 12 + 1
    assert {(j["t"], j["stock"], j["amount"]) for j in inj} == {(t0, "nodes", -1), (t0, "ready", -3), (t0, "pending", 3), (t0 + 48, "nodes", 1)}
    assert [e["kind"] for e in ev] == ["launch", "maintenance"]
    _, inj2, ev2 = R.events(-1, 0.4, 0.1, -1, 12, 4, True)
    assert [e["day"] for e in ev2] == [0, 2, 4, 7, 9, 11, 14, 16, 18, 21, 23, 25, 28]   # Mon, Wed, Fri over 30 days
    assert len(inj2) == 4 * 13                           # each: node out, 3 pods back to pending, node back


@needs
def test_three_nodes_found_flags_the_same_days_as_the_truth():
    c = R.calendar("milp", "queue")
    assert c["flagged"] == {"both": [15, 22], "found_only": [], "truth_only": []}
    p = R.calendar("milp", "pending")
    assert p["flagged"]["both"] == [22] and not p["flagged"]["found_only"] and not p["flagged"]["truth_only"]


@needs
def test_five_nodes_found_misses_the_launch_beyond_its_data():
    c = R.calendar("milp", "queue", nodes=5)
    assert 15 in c["flagged"]["truth_only"]                       # no autoscaler maximum in the found model
    assert all("desired" in d["beyond"] for d in c["days"] if d["weekday"] not in ("Sat", "Sun"))


@needs
def test_route():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    assert "/static/demos-risk-calendar.js" in c.get("/api/demos/manifest").json()["scripts"]
    r = c.get("/api/demos/risk-calendar/days?stock=retries&launch_day=3&maint_day=-1")
    assert r.status_code == 200 and len(r.json()["days"]) == 30
    assert c.get("/api/demos/risk-calendar/days?stock=nope").status_code == 404
