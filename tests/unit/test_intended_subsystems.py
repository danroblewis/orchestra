"""A declared subsystem in the intended model (docs/proposals/subsystems.md §5, B15; the owner,
2026-11-02: "sub 4. yes it can gather"): a name for a label's value, or a gathering of parts no
label groups, declared with its provenance and the same checks as the other elements, matched by
key, a member no longer in the model a ghost; served beside the derived partitions, declared first,
on both pages' APIs. No page control declares one, and discovery never reads it."""

import pytest
from fastapi.testclient import TestClient
from intended_seed import project_at, seed, v2_model

from orchestra.sd.intended import IntentError
from orchestra.sd.intended.keys import Keys
from orchestra.sd.intended.subsystems import with_declared
from orchestra.sd.model import Flow, Machine, Model, SeriesRef, Stock
from orchestra.sd.subsystems import subsystems

OWNER = {"author": "owner", "source": "supervisor", "quote": "call the hotfix workflow the hotfix line"}
SUPERVISOR = {"author": "supervisor", "source": "supervisor", "reason": "these move together"}


def model():
    pile = lambda sid, wf: Stock(sid, sid, series=SeriesRef("pile_items", {"instrument": "piles", "workflow": wf}))
    hyp = lambda *ms: {"machines": {"hypotheses": [{"machine": m} for m in ms]}}
    return Model("m", "m", stocks=[pile("h1", "hotfix"), pile("h2", "hotfix"), pile("d1", "delivery"), pile("d2", "delivery"),
                                   Stock("disk", "disk", series=SeriesRef("disk_free_bytes", {}))],
                 flows=[Flow("h", "x", "h1", "h2", evidence=hyp("writer")), Flow("d", "x", "d1", "d2", evidence=hyp("reviewer")),
                        Flow("hd", "x", "h2", "disk")],
                 machines=[Machine("writer", "writer", "machine"), Machine("reviewer", "reviewer", "machine")])


def store(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    seed(project, discovered=False, declared=False)
    return project, project.intended


def test_a_name_for_a_labels_value_is_declared_with_its_provenance_and_titles_its_group(tmp_path, monkeypatch):
    _, s = store(tmp_path, monkeypatch)
    out = s.apply([{"op": "declare_subsystem", "name": "the hotfix line", "label": "workflow", "value": "hotfix"}], OWNER)
    assert out["changes"] == [{"op": "declare_subsystem", "part": "subsystem", "id": "the_hotfix_line", "change": f"c{out['version']}.0"}]
    el = s.read()["layer"]["subsystems"]["the_hotfix_line"]
    assert el["state"] == "declared" and el["provenance"]["author"] == "owner" and el["provenance"]["via"] == "plugin"
    subs = with_declared(subsystems(model()), s.read()["layer"], model())
    assert subs["default"] == "workflow"
    g = {x["value"]: x for x in subs["partitions"][0]["groups"]}
    assert g["hotfix"]["name"] == "the hotfix line" and g["hotfix"]["declared"] == "the_hotfix_line"
    assert g["hotfix"]["value"] == "hotfix" and "name" not in g["delivery"]       # the raw value kept beside the name


def test_the_checks(tmp_path, monkeypatch):
    _, s = store(tmp_path, monkeypatch)
    bad = [({"op": "declare_subsystem", "name": "x"}, "one of the two"),
           ({"op": "declare_subsystem", "name": "x", "label": "workflow", "value": "a", "members": {"stocks": ["k"]}}, "one of the two"),
           ({"op": "declare_subsystem", "name": "x", "label": "machine", "value": "floor"}, "never a subsystem"),
           ({"op": "declare_subsystem", "name": "x", "label": "instrument", "value": "piles"}, "never a subsystem"),
           ({"op": "declare_subsystem", "name": "x", "members": {}}, "at least one member"),
           ({"op": "declare_subsystem", "name": "x", "members": {"series": ["k"]}}, "unknown field"),
           ({"op": "declare_subsystem", "name": "x", "members": {"stocks": "k"}}, "list of non-empty strings"),
           ({"op": "declare_subsystem", "name": "x", "label": "workflow", "value": "a", "colour": "red"}, "unknown field"),
           ({"op": "declare_subsystem", "name": "x", "label": "workflow", "value": "a", "present": True}, "derived on read"),
           ({"op": "declare_subsystem", "id": "Not A Slug", "name": "x", "label": "workflow", "value": "a"}, "slug")]
    for op, why in bad:
        with pytest.raises(IntentError, match=why):
            s.apply([op], OWNER)
    s.apply([{"op": "declare_subsystem", "id": "line", "name": "line", "members": {"stocks": ["a{}"], "machines": ["writer"]}},
             {"op": "declare_subsystem", "id": "hot", "name": "hot", "label": "workflow", "value": "hotfix"}], OWNER)
    # a part in one subsystem at a time; a label's value named by one
    with pytest.raises(IntentError, match="one subsystem at a time"):
        s.apply([{"op": "declare_subsystem", "id": "other", "name": "other", "members": {"machines": ["writer"]}}], OWNER)
    with pytest.raises(IntentError, match="already named by subsystem hot"):
        s.apply([{"op": "declare_subsystem", "id": "again", "name": "again", "label": "workflow", "value": "hotfix"}], OWNER)
    # no page control declares one (rule 9's closed list)
    with pytest.raises(IntentError, match="anything else is a plugin's"):
        s.apply([{"op": "declare_subsystem", "name": "p", "label": "workflow", "value": "delivery"}], {"author": "owner"}, via="page")


def test_a_proposal_waits_for_the_owner_and_what_is_the_owners_is_the_owners(tmp_path, monkeypatch):
    _, s = store(tmp_path, monkeypatch)
    s.apply([{"op": "declare_subsystem", "id": "pair", "name": "the pair", "members": {"machines": ["writer", "reviewer"]}}], SUPERVISOR)
    layer = s.read()["layer"]
    assert layer["subsystems"]["pair"]["state"] == "proposed"
    assert "declared" not in with_declared(subsystems(model()), layer, model())        # a proposal draws no box
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([{"op": "confirm", "part": "subsystem", "id": "pair"}], SUPERVISOR)
    s.apply([{"op": "confirm", "part": "subsystem", "id": "pair"}], OWNER)
    layer = s.read()["layer"]
    assert layer["subsystems"]["pair"]["state"] == "declared" and layer["subsystems"]["pair"]["confirmed"]["by"] == "owner"
    # now the owner's: neither replaced nor retracted by another author
    with pytest.raises(IntentError, match="ask the owner"):
        s.apply([{"op": "declare_subsystem", "id": "pair", "name": "renamed", "members": {"machines": ["writer"]}}], SUPERVISOR)
    with pytest.raises(IntentError, match="ask the owner"):
        s.apply([{"op": "retract", "part": "subsystem", "id": "pair"}], SUPERVISOR)
    v = s.apply([{"op": "retract", "part": "subsystem", "id": "pair"}], OWNER)["version"]
    assert s.read()["layer"]["subsystems"] == {} and "pair" in s.read(v - 1)["layer"]["subsystems"]   # a dN like the others


def test_a_gathering_matches_by_key_and_a_member_gone_is_a_ghost(tmp_path, monkeypatch):
    _, s = store(tmp_path, monkeypatch)
    m = model()
    keys = Keys(m)
    k = {sid: keys.stock_of_id[sid] for sid in ("h1", "d1", "disk")}
    s.apply([{"op": "declare_subsystem", "id": "intake", "name": "intake", "note": "where work arrives",
              "members": {"stocks": [k["h1"], k["d1"], 'gone_items{workflow="x"}'], "machines": ["writer", "nobody"]}},
             {"op": "declare_subsystem", "id": "storage", "name": "storage", "members": {"stocks": [k["disk"]]}}], OWNER)
    subs = with_declared(subsystems(m), s.read()["layer"], m)
    assert subs["default"] == "declared" and [p["label"] for p in subs["partitions"]] == ["declared", "workflow"]
    p = subs["partitions"][0]
    g = {x["value"]: x for x in p["groups"]}
    assert g["intake"]["stocks"] == ["h1", "d1"] and g["intake"]["name"] == "intake" and g["intake"]["note"] == "where work arrives"
    assert g["intake"]["ghosts"] == {"stocks": ['gone_items{workflow="x"}'], "flows": []}
    # gathered by id (the one not in the model included); reviewer by its hypothesis, whose one assigned end is in intake
    assert g["intake"]["machines"] == ["writer", "reviewer", "nobody"]
    assert g["storage"]["stocks"] == ["disk"] and p["unassigned"]["stocks"] == ["h2", "d2"]
    # flows it does not name are placed by their ends; a machine it does not name by its hypotheses
    assert p["unassigned"]["flows"] == ["h", "d", "hd"] and p["unassigned"]["machines"] == [] and p["crossing"] == []
    # the discovered model is untouched (rule 7): no part gains or loses anything
    assert [s_.id for s_ in m.stocks] == ["h1", "h2", "d1", "d2", "disk"] and all(not s_.evidence for s_ in m.stocks)


def client(project):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    return TestClient(create_app(project), headers=bearer(project))


def test_both_apis_serve_the_declared_first(tmp_path, monkeypatch):
    import time
    project = project_at(tmp_path, monkeypatch)
    seed(project)
    m = v2_model()
    keys = Keys(m)
    sid = m.stocks[0].id
    project.intended.apply([{"op": "declare_subsystem", "id": "core", "name": "the core", "members": {"stocks": [keys.stock_of_id[sid]],
                                                                                                    "machines": ["merge_gate"]}}], OWNER)
    c = client(project)
    got = c.get("/api/dynamics/model").json()["model"]["subsystems"]
    assert got["default"] == "declared" and got["partitions"][0]["source"] == "declared"
    assert got["partitions"][0]["groups"][0]["stocks"] == [sid] and got["partitions"][0]["groups"][0]["name"] == "the core"
    assert got["declared"][0]["id"] == "core"
    deadline = time.time() + 15
    while time.time() < deadline and not (ms := c.get("/api/machines").json()).get("ok"):
        time.sleep(0.2)
    subs = ms["subsystems"]
    assert subs["default"] == "declared" and subs["partitions"][0]["label"] == "declared"
    g = subs["partitions"][0]["groups"][0]
    assert set(g) >= {"value", "machines", "events", "name", "declared", "provenance"}
    assert g["ghosts"]["machines"] == ["merge_gate"]               # gathered, never on the bus: a ghost in its box
    assert set(subs["partitions"][0]) >= {"label", "source", "groups", "unassigned", "between", "crossing", "spanning", "joined", "crossed"}
