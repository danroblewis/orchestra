import pytest
from fastapi.testclient import TestClient
from sdlab.server import create_app, validate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def test_the_team_model_loads(client):
    m = client.get("/api/models/team").json()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == ["backlog", "done", "training", "staff", "left"]
    team = next(x for x in m["machines"] if x["id"] == "team")
    assert team["capacity_stock"] == "staff"
    assert client.put("/api/models/team", json=m).json() == {"ok": True}


def test_the_team_runs_live_and_its_capacity_follows_staff(client):
    for _ in range(60):
        client.post("/api/models/team/live/step")
    snap = client.get("/api/models/team/live").json()
    assert snap["t"] == 60 and not snap["errors"], snap["errors"]
    s = snap["series"]
    staff, done, work = s["levels"]["staff"], s["levels"]["done"], s["rates"]["work"]
    assert max(staff) >= 8, staff                 # hiring grew the team from nobody
    assert done[-1] > 300, done[-1]

    # Each week the team finishes at most one item per person (staff at the start of the week),
    # and while there is a backlog it is busy: so finished work tracks the staff it had.
    before = [0] + staff[:-1]
    assert all(n == 0 for k, n in enumerate(work) if before[k] == 0)   # no staff, no capacity
    for k, n in enumerate(work):
        assert n <= before[k] + 1, (k, n, before[k])  # +1: a firing may run past the end of a week
    early = [w for k, w in enumerate(work) if 1 <= before[k] <= 3]
    late = [w for k, w in enumerate(work) if before[k] >= 8 and s["levels"]["backlog"][k] >= 10]
    assert early and late
    assert sum(late) / len(late) > 2 * sum(early) / len(early), (early, late)

    # staff are people: every one has a name
    people = client.get("/api/models/team/live/stocks/staff").json()
    assert people["count"] == staff[-1] and all(p["name"] for p in people["items"])
