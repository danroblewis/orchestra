"""Demo 10 (before/after attribution) and its refit: with the structure fixed, refitting the numbers recovers a known
change, and on noise-free data the measured effect is the true effect. Skips without the stored 310 result."""

import numpy as np
import pytest

from sdlab.demos import attribution as A
from sdlab.demos import demos as D


def _have_310():
    try:
        D._base(A.SCEN)
        return True
    except Exception:                                                  # noqa: BLE001  (no stored passing result here)
        return False


def test_refit_recovers_a_known_rate_on_a_toy_chain():
    # q fed by a measured input, drained at 0.3 into r, r drained at 0.1; start the refit from wrong numbers
    t = list(range(1, 301))
    u = [10 + 5 * np.sin(i / 20) for i in t]
    q, r = [50.0], [20.0]
    for i in range(1, len(t)):
        q.append(q[-1] + u[i] - 0.3 * q[-1])
        r.append(r[-1] + 0.3 * q[-2] - 0.1 * r[-1])
    flows = [{"from": None, "to": "q", "input": "u", "rate": {"form": "proportional", "stock": "u", "k": 1.0}},
             {"from": "q", "to": "r", "rate": {"form": "proportional", "stock": "q", "k": 0.25}},
             {"from": "r", "to": None, "rate": {"form": "proportional", "stock": "r", "k": 0.2}}]
    fit = A.refit(flows, ["q", "r"], t, {"q": q, "r": r}, {"u": u}, (1, len(t)), boot=50)
    got = {n["ends"]: n for n in fit["nums"]}
    assert abs(got["q → r"]["value"] - 0.3) < 1e-6 and abs(got["r → outside"]["value"] - 0.1) < 1e-6
    assert all(n["lo"] <= n["value"] <= n["hi"] for n in fit["nums"])
    assert flows[1]["rate"]["k"] == 0.25                                # a copy: the input is untouched


@pytest.mark.skipif(not _have_310(), reason="no stored passing result for the 310 scenario in this store")
def test_noise_free_attribution_finds_the_moved_number_and_the_true_effect():
    r = A.attribution("slower-retries")
    moved = [x for x in r["numbers"] if x["moved"]]
    assert [x["ends"] for x in moved] == ["retries → queue"]
    assert abs(moved[0]["after"]["value"] - 0.3) < 0.005 and abs(moved[0]["before"]["value"] - 0.6) < 0.005
    for s in ("errors_total", "queue", "retries"):
        m = r["outcomes"][s]["summary"]
        assert abs(m["estimate"] - m["truth"]) <= 0.01 * abs(m["truth"]) + 0.5, (s, m)


@pytest.mark.skipif(not _have_310(), reason="no stored passing result for the 310 scenario in this store")
def test_routes():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    assert "slower-retries" in c.get("/api/demos/attribution/projects").json()["projects"]
    r = c.get("/api/demos/attribution/run", params={"project": "fewer-errors"})
    assert r.status_code == 200 and r.json()["project"]["flow"] == "errors"
    assert c.get("/api/demos/attribution/run", params={"project": "nope"}).status_code == 404
    assert any(s.endswith("demos-attribution.js") for s in c.get("/api/demos/manifest").json()["scripts"])
