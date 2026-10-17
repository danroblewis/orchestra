import copy

import pytest
from fastapi.testclient import TestClient

from sdlab.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def test_the_bakery_is_an_example(client):
    listing = client.get("/api/models").json()
    assert {"id": "bakery", "name": "Bakery"} in [{k: m[k] for k in ("id", "name")} for m in listing["examples"]]
    assert listing["models"] == []
    m = client.get("/api/models/bakery").json()
    assert [s["id"] for s in m["stocks"]] == ["flour", "dough", "shelf", "sold", "stale"]


def test_examples_are_read_only_and_a_copy_is_what_is_edited(client):
    m = client.get("/api/models/bakery").json()
    assert m["example"] is True
    m["machines"].append({"id": "oven", "name": "Oven", "kind": "code", "color": "#c2410c", "capacity": 1})
    next(f for f in m["flows"] if f["id"] == "bake")["machine"] = "oven"
    assert client.put("/api/models/bakery", json=m).status_code == 409
    copy_ = client.post("/api/models/bakery/copy", json={"name": "My bakery"}).json()
    assert copy_ == {"id": "my-bakery", "name": "My bakery"}
    assert client.put(f"/api/models/{copy_['id']}", json=m).json() == {"ok": True}
    again = client.get("/api/models/my-bakery").json()
    assert next(f for f in again["flows"] if f["id"] == "bake")["machine"] == "oven"
    assert again["example"] is False
    assert not any(f["machine"] == "oven" for f in client.get("/api/models/bakery").json()["flows"])   # still as shipped
    assert [x["id"] for x in client.get("/api/models").json()["models"]] == ["my-bakery"]


def test_a_copy_takes_the_run_and_hidden_flows_with_it(client):
    for _ in range(4):
        client.post("/api/models/surprises/live/step")
    c = client.post("/api/models/surprises/copy", json={}).json()
    assert c["name"].endswith("(copy)")
    assert client.get(f"/api/models/{c['id']}/live").json()["t"] == 4
    shipped = client.get("/api/models/surprises?reveal=1").json()
    assert [f["id"] for f in client.get(f"/api/models/{c['id']}?reveal=1").json()["flows"]] == [f["id"] for f in shipped["flows"]]


def test_delete_download_and_upload(client):
    c = client.post("/api/models/socks/copy", json={"name": "Socks to delete"}).json()
    client.post(f"/api/models/{c['id']}/live/step")
    file = client.get(f"/api/models/{c['id']}/download")
    assert "attachment" in file.headers["content-disposition"] and file.json()["name"] == "Socks to delete"
    assert client.delete(f"/api/models/{c['id']}").json() == {"ok": True}
    assert client.get(f"/api/models/{c['id']}").status_code == 404
    assert client.delete("/api/models/socks").status_code == 409             # examples stay
    up = client.post("/api/models", json=file.json()).json()                  # back from disk, under a free id
    assert up["id"] == "socks-to-delete" and client.get("/api/models/socks-to-delete").json()["name"] == "Socks to delete"
    assert client.get("/api/models/socks-to-delete/live").json()["t"] == 0    # its old run went with the delete
    bad = {**file.json(), "flows": [{"id": "x", "name": "x", "from": "nowhere", "to": None, "rate": {"form": "constant", "value": 1}}]}
    assert client.post("/api/models", json=bad).status_code == 422


def test_old_copies_of_examples_are_adopted(tmp_path, monkeypatch):
    """Before examples were read-only they were copied into the models folder and edited there."""
    import json
    from fastapi.testclient import TestClient
    from sdlab.server import EXAMPLES
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "bakery.json").write_text((EXAMPLES / "bakery.json").read_text())     # untouched
    edited = json.loads((EXAMPLES / "socks.json").read_text())
    edited["description"] = "mine"
    (tmp_path / "models" / "socks.json").write_text(json.dumps(edited))
    (tmp_path / "runs" / "socks").mkdir(parents=True)
    (tmp_path / "runs" / "socks" / "log.jsonl").write_text("")
    c = TestClient(create_app())
    assert [m["id"] for m in c.get("/api/models").json()["models"]] == ["socks-edited"]
    assert c.get("/api/models/socks-edited").json()["description"] == "mine"
    assert (tmp_path / "runs" / "socks-edited" / "log.jsonl").exists() and not (tmp_path / "runs" / "socks").exists()
    assert not (tmp_path / "models" / "bakery.json").exists() and not (tmp_path / "models" / "socks.json").exists()


def test_broken_models_are_refused(client):
    m = client.get("/api/models/bakery").json()
    bad = copy.deepcopy(m)
    bad["flows"][0]["machine"] = "nobody"
    r = client.put("/api/models/my-bakery", json=bad)
    assert r.status_code == 422 and "does not exist" in r.text
    bad = copy.deepcopy(m)
    bad["flows"][1]["to"] = "nowhere"
    assert client.put("/api/models/my-bakery", json=bad).status_code == 422


def test_ids_are_checked(client):
    assert client.get("/api/models/..%2Fx").status_code in (400, 404)


def test_socks_runs_live(client):
    m = client.get("/api/models/socks").json()
    assert m["flows"][2]["take"][1]["where"] == {"colour": "a.colour", "size": "a.size"}
    for _ in range(12):
        client.post("/api/models/socks/live/step")
    snap = client.get("/api/models/socks/live").json()
    assert snap["t"] == 12 and not snap["errors"], snap["errors"]
    lv = {k: v[-1] for k, v in snap["series"]["levels"].items()}
    assert lv["basket"] > 0                                   # one worker cannot keep up
    assert lv["pairs"] + lv["dress"] + lv["sport"] > 0          # but some pairs were made
    pairs = client.get("/api/models/socks/live/stocks/dress").json()["items"] + client.get("/api/models/socks/live/stocks/sport").json()["items"]
    assert all(set(p) >= {"colour", "size", "_id"} for p in pairs)


def test_pairs_always_match(client):
    for _ in range(15):
        client.post("/api/models/socks/live/step")
    snap = client.get("/api/models/socks/live").json()
    assert not snap["errors"]                                  # socks.py exits non-zero on a mismatched pair


def test_live_run_survives_a_restart(client, tmp_path, monkeypatch):
    for _ in range(5):
        client.post("/api/models/socks/live/step")
    before = client.get("/api/models/socks/live").json()
    again = TestClient(create_app())                          # a fresh server replays the log
    after = again.get("/api/models/socks/live").json()
    assert after["t"] == 5 and after["series"]["levels"]["loose"] == before["series"]["levels"]["loose"]
    assert again.post("/api/models/socks/live/reset").json()["t"] == 0


def test_programs_are_named_not_given_as_commands(client):
    m = client.get("/api/models/socks").json()
    m["machines"][0]["program"] = "../../etc/passwd"
    assert client.put("/api/models/my-socks", json=m).status_code == 422
    assert "socks/socks" in client.get("/api/programs").json()["programs"]


def test_each_firing_keeps_what_the_program_saw_and_said(client):
    for _ in range(3):
        client.post("/api/models/socks/live/step")
    recent = client.get("/api/models/socks/live").json()["recent"]
    unload = next(r for r in recent if r["flow"] == "unload")
    f = client.get(f"/api/models/socks/live/firings/{unload['n']}").json()
    assert f["argv"] == ["unload"] and f["program"] == "socks/socks" and f["ok"]
    assert '"inputs"' in f["stdin"] and '"to": "loose"' in f["stdout"]


def test_a_change_to_the_system_starts_an_era_and_an_equation_change_does_not(client):
    client.post("/api/models/socks/copy", json={"name": "My socks"})          # an example is edited as a copy
    for _ in range(3):
        client.post("/api/models/my-socks/live/step")
    m = client.get("/api/models/my-socks").json()
    next(f for f in m["flows"] if f["id"] == "pair")["rate"] = {"form": "constant", "value": 1}   # a belief
    client.put("/api/models/my-socks", json=m)
    client.post("/api/models/my-socks/live/step")
    m["machines"].append({"id": "pairer", "name": "Pairer", "kind": "code", "color": "#123456", "capacity": 1, "program": "socks/socks"})
    next(f for f in m["flows"] if f["id"] == "pair")["machine"] = "pairer"                        # the system
    client.put("/api/models/my-socks", json=m)
    for _ in range(2):
        client.post("/api/models/my-socks/live/step")
    eras = client.get("/api/models/my-socks/live").json()["eras"]
    assert [e["start"] for e in eras] == [1, 5]
    assert "new machine Pairer" in eras[1]["label"] and "Pair now run by Pairer" in eras[1]["label"]
    assert len(eras[0]["equations"]) == 2                    # the equation change stayed inside era 1
    assert TestClient(create_app()).get("/api/models/my-socks/live").json()["eras"][1]["start"] == 5   # and survives a restart


def test_hidden_flows_run_but_never_reach_the_page(client):
    m = client.get("/api/models/surprises").json()
    assert {f["id"] for f in m["flows"]} == {"arrive", "unload", "pair", "file", "lose"}
    full = client.get("/api/models/surprises?reveal=1").json()
    assert {"wear", "dog"} <= {f["id"] for f in full["flows"]}
    client.post("/api/models/surprises/copy", json={"name": "Renamed"})
    m["name"] = "Renamed"                                     # saving the page's model keeps them
    client.put("/api/models/renamed", json=m)
    assert {"wear", "dog"} <= {f["id"] for f in client.get("/api/models/renamed?reveal=1").json()["flows"]}
    for _ in range(40):
        client.post("/api/models/renamed/live/step")
    snap = client.get("/api/models/renamed/live").json()
    assert "wear" not in snap["series"]["rates"] and "dog" not in snap["series"]["rates"]
    assert all(r["flow"] not in ("wear", "dog") for r in snap["recent"])
    assert all("wear" not in m and "dog" not in m for m in snap["series"]["moved"])
    assert any("unload" in m for m in snap["series"]["moved"])      # measured flows are accounted per stock
