"""The people relayed from one system as one group on the Machines page (web/people.py; SPEC §10,
"Many people"): ``/api/machines?people=grouped`` gives one row per system's people in place of
theirs, every line that named one of them naming the group, summed; ``expand`` keeps a group's
people one by one; ``/api/machines/people`` lists a group's people. The default answer is every
machine, as before. Display only: each person is still a machine (AGENTS.md rule 2)."""

import json
import time
from datetime import datetime

from fastapi.testclient import TestClient
from intended_seed import project_at
from people_seed import T0, people_events

from orchestra.events import Events
from orchestra.web.machines import machines_view
from orchestra.web.people import GROUP_MIN, grouped, members


def view(evs):
    out = machines_view(evs, now=T0 + 7 * len(evs) + 60)
    for m in out["machines"]:
        m.setdefault("intent", None)
        m.setdefault("hidden", None)
    return out


def ids_in(out):
    """Every machine id the answer names, outside the machine rows' own fields."""
    text = json.dumps({k: v for k, v in out.items() if k not in ("machines", "people_groups")})
    return text


def test_a_systems_people_are_one_row_and_every_line_that_named_them_names_the_group():
    out = view(people_events(600))
    full = json.dumps(out)
    between = sum(h["count"] for h in out["handoffs"] if h["from"].startswith("person.jira.") and h["to"].startswith("person.jira."))
    grouped(out)
    rows = {m["id"]: m for m in out["machines"]}
    assert set(rows) == {"orchestra-host", "triage", "notifier", "builder", "person.alice", "people/jira"}
    g = rows["people/jira"]
    assert g["name"] == "Jira people (600)" and g["kind"] == "person" and g["package"] == "bridges"
    p = g["people_group"]
    assert p["system"] == "jira" and p["size"] == 600 and len(p["ids"]) == 600 and p["expanded"] is False
    assert {x["type"]: x["count"] for x in g["publishes"]} == {"jira.issue.updated": 1200, "jira.comment.added": 600}
    # the people hand each issue to triage: one line, summed; the notifier's acting next after them too
    hs = {(h["from"], h["via"], h["to"]): h["count"] for h in out["handoffs"]}
    assert hs[("people/jira", "jira.issue.updated", "triage")] == 600
    assert "person.jira." not in ids_in(out), "no line names one of the grouped people"
    assert p["within"] == between > 0, "the hand-offs between two of its people: counted, drawn by no line"
    assert out["people_groups"] == [g]
    assert len(json.dumps(out)) < len(full) / 15


def test_expanded_a_groups_people_are_rows_of_their_own_marked_with_it():
    out = view(people_events(60))
    grouped(out, {"people/jira"})
    people = [m for m in out["machines"] if m["id"].startswith("person.jira.")]
    assert len(people) == 60 and all(m["in_people"] == "people/jira" for m in people)
    assert not any(m["id"] == "people/jira" for m in out["machines"])
    [g] = out["people_groups"]
    assert g["people_group"]["expanded"] is True and g["people_group"]["size"] == 60
    assert any(h["from"].startswith("person.jira.") for h in out["handoffs"])


def test_a_mapped_person_a_few_people_a_hidden_or_declared_one_and_each_team_are_kept_apart():
    teams = {i: "sre" for i in range(GROUP_MIN)} | {i: "web" for i in range(GROUP_MIN, GROUP_MIN + 2)}
    out = view(people_events(40, slack=GROUP_MIN - 1, teams=teams))
    for m in out["machines"]:
        if m["id"] == "person.jira.u0030":
            m["hidden"] = {"provenance": {"via": "page"}}
        if m["id"] == "person.jira.u0031":
            m["intent"] = {"state": "declared"}
    grouped(out)
    rows = {m["id"]: m for m in out["machines"]}
    assert rows["people/jira/sre"]["people_group"]["size"] == GROUP_MIN and rows["people/jira/sre"]["name"] == f"Jira people · sre ({GROUP_MIN})"
    assert rows["people/jira"]["people_group"]["size"] == 40 - GROUP_MIN - 2 - 2
    # too few to group: the web team and the Slack people stay one by one; so do the hidden, the declared and the mapped
    assert "person.jira.u0008" in rows and "person.jira.u0009" in rows and sum(1 for i in rows if i.startswith("person.slack.")) == GROUP_MIN - 1
    assert {"person.jira.u0030", "person.jira.u0031", "person.alice"} <= set(rows)


def test_a_group_whose_people_only_announced_themselves_folds_as_one_machine():
    evs = [e for e in people_events(GROUP_MIN) if e["type"] == "orchestra.machine.started" or not e["source"].startswith("person.jira.")]
    out = machines_view(evs, now=T0 + 7 * len(evs) + 3600)
    grouped(out)
    g = next(m for m in out["machines"] if m["id"] == "people/jira")
    assert g["announced_only"] is True and g["people_group"]["announced_only"] == GROUP_MIN


def test_a_groups_people_listed_busiest_first():
    out = view(people_events(30))
    got = members(out["machines"], "people/jira")
    assert got["size"] == 30 and got["title"] == "Jira people"
    assert [r["events"] for r in got["members"]] == sorted((r["events"] for r in got["members"]), reverse=True)
    assert {"id", "name", "active", "last_seen", "events", "announced_only"} <= set(got["members"][0])
    assert members(out["machines"], "people/slack") is None


def test_the_api_grouped_and_its_members_with_600_people(tmp_path, monkeypatch):
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    project = project_at(tmp_path, monkeypatch)
    bus = Events(project.events_file, source="x")
    evs = people_events(600, step=1.0)
    shift = time.time() - 60 - (T0 + len(evs))
    for e in evs:
        t = datetime.fromisoformat(e["time"]).timestamp() + shift
        bus.publish(e["type"], e["data"], source=e["source"], time=t, **({"subject": e["subject"]} if "subject" in e else {}))
    with TestClient(create_app(project), headers=bearer(project)) as c:
        deadline, full = time.time() + 30, None
        while time.time() < deadline:
            full = c.get("/api/machines")
            if full.json().get("ok") and len(full.json()["machines"]) >= 604:
                break
            time.sleep(0.2)
        assert sum(1 for m in full.json()["machines"] if m["id"].startswith("person.jira.")) == 600, "the default: every machine"
        t = time.perf_counter()
        g = c.get("/api/machines", params={"people": "grouped"})
        took = time.perf_counter() - t
        d = g.json()
        assert d["ok"] and [m["id"] for m in d["machines"] if m.get("people_group")] == ["people/jira"]
        # was 749 KB and 291 ms by default with 600 people (2026-11-04)
        assert len(g.content) < 60_000 and len(full.content) > 600_000 and took < 0.25, (len(g.content), took)
        bridges = next(x for p in d["subsystems"]["partitions"] if p["label"] == "package" for x in p["groups"] if x["value"] == "bridges")
        assert sorted(bridges["machines"]) == ["people/jira", "person.alice"], "the boxes take the group as a machine"
        e = c.get("/api/machines", params={"people": "grouped", "expand": "people/jira"}).json()
        assert sum(1 for m in e["machines"] if m.get("in_people") == "people/jira") == 600
        m = c.get("/api/machines/people", params={"group": "people/jira"}).json()
        assert m["ok"] and m["size"] == 600 and len(m["members"]) == 600
        assert c.get("/api/machines/people", params={"group": "people/nowhere"}).json()["ok"] is False
