"""Who the owner's requests reach: the pages name the machines that announced they listen for
``orchestra.intent.requested`` (sd/intended/requests.py ``askers``, static/intended-core.js), never
a machine by assumption, and the Dynamics answer carries them as ``model.intended.askers``."""

import time

from intended_seed import project_at, record_points, seed
from test_intended_api_shapes import client, machines

from orchestra.events import Events
from orchestra.sd.intended.requests import REQUESTED, askers


def test_only_a_machine_that_listens_for_requests_is_an_asker():
    ms = [{"id": "operator", "subscribes": [REQUESTED]}, {"id": "all", "subscribes": ["orchestra.*"]},
          {"id": "intents", "subscribes": ["orchestra.intent.*"]}, {"id": "baker", "subscribes": ["order.placed"]},
          {"id": "quiet"}, {"id": "other", "subscribes": ["orchestra.prediction.*"]}]
    assert askers(ms) == ["all", "intents", "operator"]
    assert askers([]) == []
    # declared by a plugin, never heard: nothing on the bus listens, so nobody is named
    assert askers([{"id": "supervisor", "subscribes": [REQUESTED], "unseen": True}]) == []


def test_the_dynamics_answer_names_who_listens_for_requests(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    record_points(project)
    Events.for_project(project).publish("orchestra.machine.started", {"mode": "continuous", "listens_for": [REQUESTED]},
                                        source="operator")
    c = client(project)
    machines(c)
    deadline = time.time() + 15
    while time.time() < deadline:
        it = c.get("/api/dynamics/model").json()["model"]["intended"]
        if "operator" in it.get("askers", []):
            break
        time.sleep(0.2)
    assert it["askers"] == ["operator"], it.get("askers")
