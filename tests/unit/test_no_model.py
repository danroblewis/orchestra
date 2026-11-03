"""With no model, the page, the CLI and the model reads give one paragraph (sd.no_model): the series
looked at, those left out grouped by reason, and the events per counter against the minimum."""

import subprocess

import pytest

from orchestra.config import init_project
from orchestra.sd.model import Model
from orchestra.sd.no_model import NoModel, kind_of, reason, said, text
from orchestra.sd.reads import ModelReads, ReadError
from orchestra.sd.store import ModelStore

NEW = "too new to measure: its first point is after the window's last step, so the next discovery considers it"
D = {"sampled": 6, "series": 4, "step": 5.0, "start": 100.0, "end": 3700.0,
     "left_out": {"a": NEW, "b": NEW, "c": "no counters balance it", "d": "no counters balance it",
                  "e": "a level that changed in only 2 steps: fewer than 5, too few", "f": "a level that changed in only 3 steps: fewer than 5"},
     "counter_events": {"counters": 2, "most": 3.0, "needed": 5}}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    (tmp_path / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path / "repo", check=True)
    return init_project(tmp_path / "repo")


def test_the_paragraph_says_what_was_looked_at_left_out_and_the_events_per_counter():
    r = reason(D, host=False)
    assert r["looked_at"] == 6 and r["considered"] == 4 and r["left_out"] == 6
    assert r["by_reason"] == {"too new": 2, "no counters balance it": 2, "a level that changed in only n steps": 2}
    t = text(r)
    assert t.startswith("There is no model yet: the last discovery found no stocks among the 6 series it looked at (nothing balances yet).")
    assert "It left out 6 of them: 2 too new to measure; 2 that no counters balance; 2 levels that changed too few times." in t
    assert "Too few events: at most 3 per counter, 5 needed" in t
    assert t.endswith("No orchestra run is running, so discovery will not run again until it starts.")
    enough = text(reason({**D, "counter_events": {"counters": 2, "most": 40.0, "needed": 5}}, host=True))
    assert "Events per counter: up to 40 (5 needed for a balance)." in enough and enough.endswith("It looks again every few minutes.")
    assert "No counter moved" in text(reason({**D, "counter_events": {"counters": 0, "most": 0.0, "needed": 5}}))


def test_like_reasons_count_together():
    assert kind_of("the same as x_total (counts the same events)") == "the same as another series"
    assert kind_of("Orchestra's own: not a measure") == "Orchestra's own"
    assert kind_of("live in only 3 of 40 steps while every counter was: too few") == "live in only n of n steps while every counter was"
    assert kind_of("a counter of only 1 event") == kind_of("a counter of only 3 events") == "a counter of only n events"


LIVE = {"sampled": 70, "series": 2, "counter_events": {"counters": 3, "most": 2.0, "needed": 5},
        "left_out": {**{f"l{i}": f"live in only {i % 7 + 1} of 40 steps while every counter was: too few to balance" for i in range(21)},
                     **{f"g{i}": "its instrument says it is an aggregate (places that overlap): never a stock" for i in range(16)},
                     **{f"q{i}": "a counter that did not move in the window" for i in range(12)},
                     **{f"o{i}": "Orchestra's own (the host's and the Core page's plumbing), not a measure of the system" for i in range(10)},
                     **{f"r{i}": f"a counter of only {i % 3 + 1} event{'s' if i % 3 else ''}: fewer than 5, too few to carry a balance" for i in range(6)},
                     "a1": "its instrument says it is an age (how long the oldest has waited): never a stock",
                     "a2": "its instrument says it is an age (how long the oldest has waited): never a stock",
                     "x": "the same as y_total (counts the same events)"}}


def test_each_group_is_said_plainly_with_its_count_first_and_no_bare_n():
    t = text(reason(LIVE, host=True))
    assert ("It left out 68 of them: 21 live in only some of the steps that their counters were live in; 16 that their instrument "
            "says are aggregates; 12 counters that did not move in the window; 10 of Orchestra's own; 6 counters with too few "
            "events; 2 that their instrument says are ages; 1 the same as another series.") in t
    assert t.endswith("Too few events: at most 2 per counter, 5 needed. It looks again every few minutes.")
    assert " n " not in t and "(" not in t.split("It left out")[1].split(".")[0]


def test_every_reason_discovery_gives_is_said_without_a_bare_n():
    reasons = ["named orchestra_*: the orchestra_ prefix is Orchestra's own", "no longer written: nothing in the last 5 min",
               "not written in the window: its last point is 9 min before the end", NEW,
               "a level that did not change in the window", "a level that changed only 1 time, between two values (0, 3)",
               "a flag (it only ever takes 0 and 1, and no counters balance it exactly), not a quantity that accumulates",
               "a statistic of what it measures (a maximum, a mean): a summary", "written for only 4 min of the 60 min the window",
               "no counters balance it (best R² 0.31 with a_total)", "no counters of its own balance it (best R² 0.20); the others",
               "only an accumulator of other stocks' flows (R² 0.99 with counters of its own)", "a counter no stock's balance needed",
               "with a_total and b_total in the balance of q, the same as c_total, which counts their sum itself",
               "the same items as q: its capacity of 3", "the start of p, the capacity of q: it moves items within",
               "a count of reporters split by outcome, balanced by its own turnover"]
    for why in reasons:
        for k in (1, 3):
            got = said(kind_of(why), k)
            assert got.startswith(f"{k} ") and "left out as" not in got and " n " not in f"{got} ", got
    assert said(kind_of("something new at 3 of 7 steps"), 2) == "2 left out as something new at some of some steps"


def test_no_discovery_says_so():
    e = NoModel(None)
    assert e.text.startswith("There is no model yet: no discovery has run yet.") and "orchestra run" in e.text
    assert e.reason == {"discovered": False, "host_running": None, "headline": "There is no model yet: no discovery has run yet."}


def test_the_read_raises_no_model_with_text_and_reason(project):
    ModelStore.for_state(project.state_dir).write_discovery(Model("m", "nothing yet", discovery=D))
    with pytest.raises(NoModel) as e:
        ModelReads(project).model()
    assert isinstance(e.value, ReadError) and e.value.status == 404       # callers catching ReadError still do
    assert "Too few events: at most 3 per counter, 5 needed" in e.value.text and str(e.value) == e.value.text
    assert e.value.reason["counter_events"] == D["counter_events"]
    assert e.value.answer() == {"ok": False, "error": "no model", "text": e.value.text, "reason": e.value.reason}


def test_the_endpoint_answers_404_and_the_web_api_200_with_no_model_text_and_reason(project):
    from fastapi.testclient import TestClient

    from orchestra.endpoint.api import handle
    from orchestra.web import auth
    from orchestra.web.app import create_app

    ModelStore.for_state(project.state_dir).write_discovery(Model("m", "nothing yet", discovery=D))
    status, out = handle(project, "GET", "/model", "", b"")
    assert status == 404 and out["error"] == "no model" and "at most 3 per counter" in out["text"]
    assert set(out) == {"ok", "error", "text", "reason"}
    c = TestClient(create_app(project), headers={"Authorization": f"Bearer {auth.token(project)}"})
    r = c.get("/api/dynamics/model")
    got = r.json()
    assert r.status_code == 200 and got["error"] == "no model" and got["model"] is None     # the page's state, not a missing resource
    assert got["text"] == out["text"] and got["reason"]["by_reason"] == out["reason"]["by_reason"]   # the same paragraph
    assert got["reason"]["headline"] == got["text"].split(" It left out")[0]
    assert "rediscover now" in got["hint"] and got["discovery"]["looked_at"] == 6


def test_the_discovery_records_the_events_per_counter():
    from orchestra.sd.discover import discover

    pts = [(1000.0 + 10 * i, float(i % 3)) for i in range(60)]
    dump = [("disk_free_bytes", {"machine": "telemetry"}, pts),
            ("jobs_done_total", {"machine": "telemetry"}, [(t, float(i // 20)) for i, (t, _) in enumerate(pts)])]
    m = discover(dump, start=1000.0, end=1590.0, step=10.0)
    assert m.discovery["counter_events"] == {"counters": 1, "most": 2.0, "needed": 5}
    assert "at most 2 per counter, 5 needed" in NoModel(m.discovery).text


def test_the_notice_says_how_long_until_a_counter_has_counted_enough_at_the_current_rate():
    from orchestra.sd.no_model import minutes_to_enough, reason, text
    assert minutes_to_enough(1, 5, 600) == 40                # 1 event in 10 min: 4 more take 40 min
    assert minutes_to_enough(0, 5, 600) is None and minutes_to_enough(5, 5, 600) is None and minutes_to_enough(2, 5, None) is None
    d = {"left_out": {"moves_total": "a counter of only 1 event: fewer than 5"}, "series": 1, "start": 1000.0, "end": 1600.0,
         "counter_events": {"counters": 1, "most": 1, "needed": 5}}
    assert "Too few events: at most 1 per counter, 5 needed; about 40 more minutes at the current rate." in text(reason(d, True))
