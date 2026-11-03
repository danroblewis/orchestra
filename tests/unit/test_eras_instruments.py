"""An instrument's process is not a machine that behaves: its ``machine:`` change begins no era
(bootstrap run 5: a GitHub poller, a ``[[machines]]`` entry with a ``[[collect]]`` twin, was
removed as ``machine:github_plugins_poller`` and began the run's one era, which cut a week of the
source's history to 58 minutes)."""

from types import SimpleNamespace

from orchestra.events import Events, envelope
from orchestra.sd import eras
from orchestra.sd.store import ModelStore

T0 = 1_800_000_000.0


def at(t: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat()


def bus(tmp_path, *evs):
    events = Events(tmp_path / "events.jsonl")
    for ev in evs:
        events.bus.append(ev)
    return events


def cc(subject, t, id_):
    return envelope("config.changed", "supervisor", subject=subject, time=at(T0 + t), id=id_)


def test_run_5s_poller_removed_as_a_machine_begins_no_era_and_a_machine_that_acts_still_does(tmp_path):
    """Run 5's bus as it was (17:14 to 17:18): seven pollers added as collectors, two removed as
    machines; then a machine that acts is changed."""
    store = ModelStore.for_state(tmp_path)
    events = bus(tmp_path, *[cc(f"collector:{n}", i * 30, f"a{i}") for i, n in enumerate(
        ["jira_poller", "github_poller", "slack_poller", "github_plugins_poller", "github_ops_poller", "jira_epics_poller", "jira_uff_poller"])],
        cc("machine:github_plugins_poller", 240, "r1"), cc("machine:github_ops_poller", 243, "r2"))
    all_, new = eras.sync(store, events, ["config.changed"], min_s=1800.0)
    assert all_ == [] and new == [], "a collector's removal is a measurement change, whatever its subject says"
    events.bus.append(cc("machine:reviewer", 300, "m1"))
    all_, _ = eras.sync(store, events, ["config.changed"], min_s=1800.0)
    assert [e.cause for e in all_] == ["m1"], "a machine that acts begins one"


def test_the_configurations_instruments_are_known_before_the_bus_names_them(tmp_path):
    """No ``collector:`` event was ever read (the bus was replaced): the configuration's
    ``[[collect]]``, ``[[scrape]]`` and ``[[sources]]`` names are instruments' all the same."""
    raw = {"collect": [{"name": "jira_poller", "command": "p measure"}], "scrape": [{"name": "node", "url": "http://x"}],
           "sources": [{"name": "prom", "url": "http://y"}], "machines": [{"name": "jira_poller"}, {"name": "worker"}]}
    project = SimpleNamespace(config=SimpleNamespace(raw=raw))
    assert eras.instrument_names(project) == {"jira_poller", "node", "prom"}
    store = ModelStore.for_state(tmp_path)
    events = bus(tmp_path, cc("machine:jira_poller", 0, "j"), cc("machine:node,jira_poller", 10, "n"))
    assert eras.sync(store, events, ["config.changed"], instruments=lambda: eras.instrument_names(project))[0] == []
    events.bus.append(cc("machine:worker,jira_poller", 20, "w"))
    all_, _ = eras.sync(store, events, ["config.changed"], instruments=lambda: eras.instrument_names(project))
    assert [e.cause for e in all_] == ["w"], "a change that names a machine that acts, too, begins one"


def test_an_instrument_removed_from_the_configuration_is_still_known_as_one(tmp_path):
    """Its entries are gone once its removal is read: the record keeps what the bus and the
    configuration named, across a reread of the bus when the filters change."""
    store = ModelStore.for_state(tmp_path)
    events = bus(tmp_path, cc("collector:old_poller", 0, "a"))
    eras.sync(store, events, ["config.changed"])
    assert "old_poller" in store.read_record("eras")["instruments"]
    events.bus.append(cc("machine:old_poller", 60, "r"))
    assert eras.sync(store, events, ["config.changed", "deploy.*"])[0] == [], "the bus read again, the names kept"


def test_begins_judges_an_instruments_machine_subject_as_a_measurement():
    ev = {"type": "config.changed", "source": "supervisor", "subject": "machine:github_poller", "id": "c"}
    assert eras.begins(ev, ["config.changed"])
    assert not eras.begins(ev, ["config.changed"], instruments={"github_poller"})
    assert not eras.begins(ev, ["config.changed"], {"c"}, {"github_poller"}), "predicted or not: a measurement"
    assert not eras.begins({**ev, "type": "system.changed"}, [], instruments={"github_poller"}), "whatever the type"
    assert eras.begins({**ev, "subject": "definition:github_poller"}, ["config.changed"], instruments={"github_poller"}), \
        "only a machine: subject is an instrument's process"
