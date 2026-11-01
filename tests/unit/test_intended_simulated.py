"""Simulated and draft series (docs/proposals/intended-model.md §6.3; §10 test 17): a placeholder's
parts are marked ``simulated`` in the saved version and read only while its entry says so; a
draft instrument's series is never read by discovery; a verdict never counts a simulated part and
a target on one is never met; a real series of the same key keeps the expected mark."""

import random
import time

from intended_seed import project_at

from orchestra.collect.round import points_of
from orchestra.collect.spec import from_toml
from orchestra.metrics import Point
from orchestra.metrics import for_project as metrics_for
from orchestra.sd.intended.facts import judged
from orchestra.sd.intended.view import dynamics_block
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
    assert draft["draft"] == "true" and cs[1].expired(cs[1].expires) and not cs[1].expired(cs[1].expires - 1)
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
    store.intended().apply([{"op": "expect", "part": "stock", "key": "features_level"}], {"author": "owner", "via": "page"},
                           via="page")
    b = dynamics_block(store.intended())
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
    b = dynamics_block(store.intended())
    e = next(e for e in b["expected"] if e["key"] == "features_level")
    assert e["present"] and not e["simulated"]


def test_a_draft_instruments_series_is_never_read(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    now = time.time()
    write_queue(project, {"instrument": "features.try", "draft": "true"}, now)
    r = rediscover(project, metrics_for(project), now=now)
    assert not r.model.stocks
    assert r.model.discovery["left_out"]['features_level{draft="true",instrument="features.try"}'].startswith("a draft")
