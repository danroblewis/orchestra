"""Demo 11 (canary guard): an identical noise-free canary is a go, a noise-free regression is a stop on the right
number, and the routes answer. Skips without the stored 310 result."""

import pytest

from sdlab.demos import canary as C
from sdlab.demos import demos as D


def _have_310():
    try:
        D._base(C.SCEN)
        return True
    except Exception:                                                  # noqa: BLE001  (no stored passing result here)
        return False


pytestmark = pytest.mark.skipif(not _have_310(), reason="no stored passing result for the 310 scenario in this store")


def test_noise_free_same_canary_goes_and_worse_canary_stops_on_the_changed_number():
    same = C.compare("errors", 0.0, 1, 300, False)
    assert same["verdict"] == "right go"
    worse = C.compare("errors", 0.05, 1, 300, False)
    assert worse["verdict"] == "right stop" and worse["right_number"]
    hit = next(r for r in worse["rows"] if r["is_changed_flow"])
    assert abs(hit["relative"] - 0.05) < 0.005


def test_counted_canary_on_its_own_seed():
    c = C.compare("slower", 0.30, 1, 300, True)
    assert c["seeds"]["baseline"] != c["seeds"]["canary"]
    assert c["stop"] and c["right_number"]                             # a 30% slower canary is plain even on 300 counted steps


def test_routes():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    assert "errors" in c.get("/api/demos/canary/options").json()["regressions"]
    r = c.get("/api/demos/canary/run", params={"regression": "timeouts", "size": 0.3, "seed": 2, "steps": 300, "counts": False})
    assert r.status_code == 200 and r.json()["stop"]
    assert c.get("/api/demos/canary/run", params={"regression": "errors", "size": 0.07}).status_code == 400
    assert c.get("/api/demos/canary/run", params={"regression": "nope", "size": 0.05}).status_code == 404
