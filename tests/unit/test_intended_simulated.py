"""Simulated and draft series (docs/proposals/intended-model.md §6.3; §10 tests 17, 32): a
placeholder's parts are marked ``simulated`` in the saved version and read only while an entry
(the project's or a plugin's) says so; a draft instrument's series is left out of discovery while
its entry exists and after; points written once the flag is cleared join the same key; the flags
are read on Orchestra's own series only; a verdict never counts a simulated part and a target on
one is never met; a real series of the same key keeps the expected mark."""

import random
import time

from intended_seed import project_at

from orchestra.collect.round import points_of
from orchestra.collect.spec import Collector, from_toml
from orchestra.metrics import Point
from orchestra.metrics import for_project as metrics_for
from orchestra.sd import simulated
from orchestra.sd.intended.facts import judged
from orchestra.sd.intended.keys import ref_key, stock_key
from orchestra.sd.intended.view import dynamics_block
from orchestra.sd.model import Equation, Flow, Model, SeriesRef, Stock
from orchestra.sd.rediscover import rediscover
from orchestra.sd.store import ModelStore
from orchestra.sd.verdict import unpredicted

SIM = '\n[[collect]]\nname = "features.sim"\ncommand = "true"\nsimulated = true\n'


def write_queue(project, labels, now, seed=3):
    rng, lv, inn, out, pts = random.Random(seed), 0, 0, 0, []
    for i in range(700):
        t = now - 3500 + 5 * i
        a = rng.random() < 0.3
        d = lv > 0 and rng.random() < 0.05 * lv
        inn, out, lv = inn + a, out + d, lv + a - d
        pts += [Point("features_level", float(lv), t, {"project": project.key, **labels}),
                Point("features_in_total", float(inn), t, {"project": project.key, **labels}),
                Point("features_out_total", float(out), t, {"project": project.key, **labels})]
    metrics_for(project).write(pts)


def test_the_collector_labels_a_placeholders_and_a_drafts_points():
    cs, errors = from_toml({"collect": [{"name": "sim", "command": "x", "simulated": True},
                                        {"name": "try", "command": "x", "draft": True, "expires": "2026-11-08T00:00:00+00:00"},
                                        {"name": "bad", "command": "x", "expires": 5}]})
    assert [c.name for c in cs] == ["sim", "try"] and "expires goes with draft" in errors[0]
    sim, draft = (points_of(c, "q 1\n", "p", 1.0).points[0].labels for c in cs)
    assert sim["simulated"] == "true" and "draft" not in sim
    assert draft["draft"] == "true" and cs[1].expires == 1794096000.0
    faked = points_of(cs[0], 'q{simulated="no",draft="x"} 1\n', "p", 1.0).points[0].labels
    assert faked["exported_simulated"] == "no" and faked["exported_draft"] == "x"


def test_simulated_parts_are_marked_read_while_named_then_left_out_and_the_mark_survives(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    project.config_file.write_text(project.config_file.read_text() + SIM)
    project.reload_config()
    now = time.time()
    write_queue(project, {"instrument": "features.sim", "simulated": "true"}, now)
    r = rediscover(project, metrics_for(project), now=now)
    st = next(s for s in r.model.stocks if s.series.name == "features_level")
    assert st.evidence["simulated"] and all(f.evidence.get("simulated") for f in r.model.flows)
    store = ModelStore.for_state(project.state_dir)
    saved = store.load()
    assert next(s for s in saved.stocks if s.id == st.id).evidence["simulated"]
    store.intended().apply([{"op": "expect", "part": "stock", "key": "features_level"}], {"author": "owner"}, via="page")
    b = dynamics_block(store.intended(), hold=3)
    assert "simulated" in b["marks"]["stocks"][st.id] and next(e for e in b["expected"])["simulated"]
    # a simulated part is never an unpredicted change; a target on it is never met
    comparison = {"flows": [{"id": f.id, "status": "appeared"} for f in r.model.flows], "stocks": {"appeared": [st.id]}}
    assert unpredicted([], comparison, [], r.model) == []
    assert judged({"op": "above", "value": 0, "over_s": 60}, 5.0, True)["met"] == "unknown"
    # the entry removed: its points stay, the series is left out, the parts leave
    project.config_file.write_text(project.config_file.read_text().replace(SIM, ""))
    project.reload_config()
    r = rediscover(project, metrics_for(project), now=now + 1)
    assert not r.model.stocks and r.model.discovery["left_out"][
        'features_level{instrument="features.sim",simulated="true"}'].startswith("simulated, expired")
    assert metrics_for(project).latest("features_level", {"instrument": "features.sim", "simulated": "true"})
    # a real series of the same name and identity labels takes the mark
    write_queue(project, {"instrument": "features.real"}, now + 2, seed=4)
    r = rediscover(project, metrics_for(project), now=now + 2)
    b = dynamics_block(store.intended(), hold=3)
    e = next(e for e in b["expected"] if e["key"] == "features_level")
    assert e["present"] and not e["simulated"]


DRAFT = '\n[[collect]]\nname = "features.try"\ncommand = "true"\ndraft = true\nexpires = "2026-11-08T00:00:00Z"\n'


def test_32_a_draft_series_is_left_out_while_its_entry_exists_and_after_and_clean_points_join_its_key(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    project.config_file.write_text(project.config_file.read_text() + DRAFT)
    project.reload_config()
    now = time.time()
    then = now - 4000
    labels = {"instrument": "features.try", "draft": "true"}
    write_queue(project, labels, then)
    key = 'features_level{draft="true",instrument="features.try"}'
    r = rediscover(project, metrics_for(project), now=then)
    assert not r.model.stocks and r.model.discovery["left_out"][key].startswith("draft")
    project.config_file.write_text(project.config_file.read_text().replace(DRAFT, ""))        # the entry removed
    project.reload_config()
    r = rediscover(project, metrics_for(project), now=then + 1)
    assert not r.model.stocks and r.model.discovery["left_out"][key].startswith("draft")
    write_queue(project, {"instrument": "features.try"}, now, seed=4)                           # the flag cleared
    r = rediscover(project, metrics_for(project), now=now)
    st = next(s for s in r.model.stocks if s.series.name == "features_level")
    assert stock_key(st) == ref_key(SeriesRef("features_level", labels)) == "features_level"


def test_a_plugins_simulated_collector_is_not_expired(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    plugin = Collector("ramp", "collect", "true", owner="features", simulated=True)
    assert simulated.configured(project, [plugin]) == {"features.ramp"}
    monkeypatch.setattr(simulated, "plugin_collectors", lambda project: [plugin])
    now = time.time()
    write_queue(project, {"instrument": "features.ramp", "simulated": "true"}, now)
    r = rediscover(project, metrics_for(project), now=now)
    st = next(s for s in r.model.stocks if s.series.name == "features_level")
    assert st.evidence["simulated"] and not any(v.startswith("simulated, expired") for v in r.model.discovery["left_out"].values())


def test_the_flags_are_read_on_orchestras_own_series_only():
    own = ("q", {"instrument": "i", "draft": "true"}, [])
    theirs = ("jira:q", {"draft": "true"}, [])
    sim = ("s", {"instrument": "gone", "simulated": "true"}, [])
    kept, left = simulated.select([own, theirs, sim], {'jira:q{draft="true"}': {"source": "jira"}}, lambda: set())
    assert kept == [theirs] and left['q{draft="true",instrument="i"}'].startswith("draft")
    assert left['s{instrument="gone",simulated="true"}'].startswith("simulated, expired")
    asked = []
    simulated.select([own, theirs], {}, lambda: asked.append(1) or set())
    assert not asked                                           # no simulated series: the plugins are not loaded


def test_the_judges_halves_leave_a_draft_series_out(tmp_path, monkeypatch):
    from orchestra.sd import strategies
    from orchestra.sd.judge import false_change

    project = project_at(tmp_path, monkeypatch)
    now = time.time()
    write_queue(project, {"instrument": "features.try", "draft": "true"}, now)
    write_queue(project, {"instrument": "real"}, now, seed=5)
    seen = []
    real = strategies.discover_with

    def spy(dump, **kw):
        seen.append({(n, labels.get("draft")) for n, labels, _ in dump})
        return real(dump, **kw)
    monkeypatch.setattr(strategies, "discover_with", spy)
    false_change(project, metrics_for(project), None, now, {"flows": []})
    assert len(seen) == 2 and all(("features_level", "true") not in names and ("features_level", None) in names for names in seen)


def test_a_flow_reading_a_simulated_input_is_marked():
    eq = Equation("linear", {"c": 0.1, "k": 0.2}, "fitted", inputs=["input:ramp"])
    f = Flow("in", "in", None, "q", SeriesRef("q_in_total", {"instrument": "real"}), equations=[eq],
             evidence={"machines": {"hypotheses": [{"machine": "m", "confidence": 0.5}]}})
    m = Model("system", "s", stocks=[Stock("q", "q", series=SeriesRef("q", {"instrument": "real"}))], flows=[f])
    m.discovery = {"inputs": {"ramp": {"name": "ramp", "labels": {"instrument": "features.sim", "simulated": "true"}}}}
    simulated.mark(m)
    assert f.evidence["simulated"] and f.evidence["machines"]["hypotheses"][0]["simulated"]
    assert not m.stocks[0].evidence.get("simulated")
    assert f.evidence["simulated_from"] == [{"series": 'ramp{instrument="features.sim",simulated="true"}', "as": "input"}]
    back = Model.from_json(m.to_json()).flow("in")
    assert back.current().quality["simulated"] == 1 and back.evidence["simulated_from"] == f.evidence["simulated_from"]


def test_a_simulated_stock_and_the_flows_fitted_on_it_say_which_series():
    real = Flow("in", "in", None, "q", SeriesRef("q_in_total", {"instrument": "real"}),
                equations=[Equation("constant", {"c": 1.0}, "fitted")])
    net = Flow("net", "net", None, "q", None, equations=[Equation("constant", {"c": 1.0}, "fitted")])
    q = Stock("q", "q", series=SeriesRef("q", {"instrument": "features.sim", "simulated": "true"}))
    m = Model("system", "s", stocks=[q], flows=[real, net])
    simulated.mark(m)
    key = 'q{instrument="features.sim",simulated="true"}'
    assert q.evidence["simulated_from"] == [{"series": key, "as": "series"}]
    assert real.evidence["simulated_from"] == net.evidence["simulated_from"] == [{"series": key, "as": "end"}]
    assert "simulated" not in real.current().quality                # fitted on its real counter
    assert net.current().quality["simulated"] == 1                  # fitted on the placeholder's level


def test_a_placeholders_input_is_named_as_the_real_series_that_replaces_it():
    from orchestra.sd.inputs import _name

    assert _name("features_wip", {"project": "p", "instrument": "features.sim", "simulated": "true"}) == "features_wip"
    assert _name("features_wip", {"instrument": "real", "team": "a"}) == _name("features_wip", {"team": "a", "draft": "true"})


def test_a_newly_flagged_instrument_is_read_without_a_restart(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    assert simulated.configured(project, []) == set()
    project.config_file.write_text(project.config_file.read_text() + SIM)          # a plugin's config_edit, as the web server runs
    assert simulated.configured(project, []) == {"features.sim"}


def test_a_declared_stock_measured_only_by_a_placeholder_reads_simulated(tmp_path, monkeypatch):
    from intended_seed import QUOTE, record_points, seed

    project = project_at(tmp_path, monkeypatch)
    seed(project)
    project.intended.apply([{"op": "record_measurement", "part": "stock", "id": "features", "chosen": "d", "options": [
        {"key": "d", "title": "a simulated ramp", "kind": "simulated", "instrument": "features.sim", "simulated": True}]}],
        {"author": "owner", "source": "supervisor", "quote": QUOTE})
    record_points(project, instrument="features.sim", name="features_ramp")
    e = next(x for x in project.intended.diff(metrics=metrics_for(project))["expected"] if x.get("id") == "features")
    assert e["simulated"] is True and e["measured"] is True and e["measure"]["recording"]["simulated"] is True


def test_discovery_given_the_collectors_never_loads_the_plugins(tmp_path, monkeypatch):
    from orchestra import plugins
    from orchestra.sources.catalogue import Reading

    project = project_at(tmp_path, monkeypatch)

    def refuse(*a, **k):
        raise AssertionError("the plugins were loaded again")
    monkeypatch.setattr(plugins, "load", refuse)
    reading = Reading()
    reading.dump = [("q", {"instrument": "features.ramp", "simulated": "true"}, [(0.0, 1.0), (60.0, 2.0)])]
    m = simulated.discovered(project, reading, collectors=[Collector("ramp", "collect", "true", owner="features", simulated=True)],
                             start=0.0, end=60.0, step=60.0)
    assert not any(v.startswith("simulated, expired") for v in (m.discovery.get("left_out") or {}).values())


def test_the_simulated_label_on_another_stores_series_marks_nothing():
    theirs = SeriesRef("jira_q", {"simulated": "true"})
    f = Flow("in", "in", None, "q", SeriesRef("jira_q_in_total", {"simulated": "true"}))
    m = Model("system", "s", stocks=[Stock("q", "q", series=theirs)], flows=[f])
    others = {'jira_q{simulated="true"}': {"source": "jira"}, 'jira_q_in_total{simulated="true"}': {"source": "jira"}}
    simulated.mark(m, others)
    assert not m.stocks[0].evidence.get("simulated") and not f.evidence.get("simulated")
    simulated.mark(m)
    assert m.stocks[0].evidence["simulated"] and f.evidence["simulated"]


def test_a_simulated_part_never_seeds_the_next_eras_prior():
    from orchestra.sd.prior import merge

    sim = Stock("ramp", "ramp", series=SeriesRef("ramp", {"simulated": "true"}), evidence={"simulated": True})
    real = Stock("q", "q", series=SeriesRef("q", {}))
    eq = Equation("constant", {"c": 0.4}, "fitted", quality={"events": 40.0})
    prior = Model("system", "s", stocks=[sim, real], flows=[Flow("into_ramp", "into ramp", None, "ramp", equations=[eq]),
                                                            Flow("into_q", "into q", None, "q", equations=[eq])], era="e0")
    got = merge(Model("system", "s"), prior, age_s=10.0, keep_s=3600.0)
    assert [s.id for s in got.stocks] == ["q"] and [f.id for f in got.flows] == ["into_q"]
    report = got.discovery["prior"]
    assert report["dropped"] == {"stocks": ["ramp"], "flows": ["into_ramp"]}
    assert report["why"] == {"stocks": {"ramp": "simulated"}, "flows": {"into_ramp": "simulated"}}
