"""Discovery reads through one catalogue over the own store and the remote sources: remote series
are prefixed, carry their provenance and declared kind, a remote counter's first sample is a
baseline, a missing source is recorded and never saved as a version, and querying a remote store
yields the model copying the same points into the own store does."""

from __future__ import annotations

import json
import math
import time

from fake_prometheus import Busy, FakePrometheus
from helpers import project, source_toml, world

from orchestra.metrics import Point, for_project
from orchestra.sd.rediscover import aligned, rediscover
from orchestra.sd.series import Declared, sample
from orchestra.sd.store import ModelStore
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.cache import cached, save
from orchestra.web.dynamics import model_view


def now_grid(step: float = 60.0) -> float:
    return math.floor(time.time() / step) * step


def test_a_remote_counters_first_sample_is_a_baseline():
    pts = [(0.0, 5000.0), (60.0, 5003.0), (120.0, 5007.0)]
    own, remote = (sample([("jobs_total", {}, pts)], 0.0, 60.0, 2, kinds)[0] for kinds in
                   (None, {"jobs_total": Declared("counter", baseline=True)}))
    assert own.counter and remote.counter
    assert remote.deltas == [3.0, 4.0]
    early = sample([("jobs_total", {}, pts[1:])], 0.0, 60.0, 2, {"jobs_total": Declared("counter", baseline=True)})[0]
    assert early.deltas == [0.0, 4.0]                 # before its first sample it stood where that sample says
    level = sample([("slots_total", {}, [(0.0, 3.0), (60.0, 1.0), (120.0, 4.0)])], 0.0, 60.0, 2, {"slots_total": Declared("level")})[0]
    assert not level.counter and level.deltas == [-2.0, 3.0]


def test_rediscovery_reads_the_remote_and_records_where_each_series_came_from(tmp_path, monkeypatch):
    dump, _ = world(now_grid(), 240, regions={"us-east": 1.0, "eu-west": 0.5}, deploy_every=30)
    fake = FakePrometheus(dump, token="s3cret-rig-token")
    (tmp_path / "tok").write_text("s3cret-rig-token\n")
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, auth=f'auth = {{ bearer_file = "{tmp_path / "tok"}" }}', window="240m"))
        r = rediscover(p, for_project(p))
    finally:
        fake.close()
    m = r.model
    assert r.version == 1 and m.discovery["sources"]["rig"]["ok"] and "not_saved" not in m.discovery
    pods = [s for s in m.stocks if s.series and s.series.name.endswith("_pods")]
    assert {s.series.labels["service"] for s in pods} == {"checkout", "search", "authz"}
    for s in pods:
        assert s.unit == "pods" and s.series.source == "rig" and s.series.name.startswith("rig:")
        assert s.series.labels["machine"] == f"rig.{s.series.labels['service']}"
        # read every 60 s (the source's step, a floor), the pods' count is as fine as its changes
        assert s.series.query.startswith("count by (") and "counted from" in s.series.origin[0] and s.series.resolution_s >= 60.0
    flows = [f for f in m.flows if f.dst in {s.id for s in pods} or f.src in {s.id for s in pods}]
    assert flows and all(f.current().sources == ["rig"] for f in flows)
    # the remote store's machine label is its own dimension of the data, kept; it makes no machine
    # and associates none with a flow (AGENTS.md rule 7): the rig has no events on this bus
    assert m.machines == [] and all(f.evidence["machines"]["hypotheses"] == [] for f in flows)
    stored = (p.state_dir / "model" / "discovered.json").read_text() + (p.state_dir / "sources" / "rig.json").read_text()
    assert "s3cret-rig-token" not in stored and "s3cret-rig-token" not in json.dumps(model_view(p))


def test_a_missing_source_is_recorded_and_saves_no_version(tmp_path, monkeypatch):
    dump, _ = world(now_grid(), 240, regions={"us-east": 1.0}, deploy_every=30)
    fake = FakePrometheus(dump)
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, window="240m"))
        first = rediscover(p, for_project(p))
        assert first.version == 1
        fake.fail_status = 503                         # the store is down: inference falls back to its cache, the reads fail
        down = rediscover(p, for_project(p))
    finally:
        fake.close()
    assert down.version is None and "rig" in down.model.discovery["not_saved"]
    st = down.model.discovery["sources"]["rig"]
    assert not st["ok"] and "503" in st["error"]
    store = ModelStore.for_state(p.state_dir)
    assert store.current_version() == 1 and store.load().stocks == first.model.stocks
    assert store.latest_discovery()[1].discovery["sources"]["rig"]["ok"] is False


def test_a_refused_source_is_missing_too(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch, source_toml("http://127.0.0.1:9", auth='auth = { token = "literal" }'))
    p_store = for_project(p)
    t = time.time()
    p_store.write([Point("queue_depth", float(k % 3), t - 600 + 10 * k, {"machine": "w", "project": p.key}) for k in range(60)])
    r = rediscover(p, p_store)
    assert r.version is None and "refused in orchestra.toml" in r.model.discovery["not_saved"]


def test_gaps_in_what_a_source_returned_are_recorded(tmp_path, monkeypatch):
    end = now_grid()
    pts = [(end - 7200 + 60 * k, float(k % 4)) for k in range(121) if not 40 <= k < 70]     # half an hour with nothing
    fake = FakePrometheus([("queue_depth", {"svc": "a"}, pts)])
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url) + '\n[[series]]\nsource = "rig"\nname = "depth"\nquery = "last_over_time(queue_depth[61s])"\n')
        start, stop = aligned(end - 7200, end, 60.0)
        reading = Catalogue(p, for_project(p)).read(start, stop, 60.0)
    finally:
        fake.close()
    st = reading.status["rig"]
    assert st["ok"] and any(a <= end - 7200 + 41 * 60 and b >= end - 7200 + 69 * 60 for a, b in st["gaps"]), st["gaps"]
    assert reading.provenance['rig:depth{svc="a"}']["origin"] == ["declared in orchestra.toml"]


def _queue(end: float, machine: str) -> list:
    """A queue a consumer fills and drains, written every 30 s: a level and its two counters."""
    level, ins, outs, n_in, n_out = [], [], [], 0, 0
    for k in range(241):
        t = end - 7200 + 30 * k
        n_in += (k * 7) % 3
        n_out += (k * 5) % 2 if n_in > n_out else 0
        level.append((t, float(n_in - n_out)))
        ins.append((t, float(n_in)))
        outs.append((t, float(n_out)))
    lab = {"machine": machine}
    return [("queue_depth", lab, level), ("jobs_in_total", lab, ins), ("jobs_out_total", lab, outs)]


def test_querying_equals_copying(tmp_path, monkeypatch):
    end = now_grid(30.0)
    own_dir, remote_dir = tmp_path / "own", tmp_path / "remote"
    own_dir.mkdir()
    remote_dir.mkdir()
    p = project(own_dir, monkeypatch, "[discovery]\nwindow = \"120m\"\nstep = \"30s\"\nstrategy = \"conservation\"\n")
    store = for_project(p)
    store.write([Point(n, v, t, {**lab, "project": p.key}) for n, lab, pts in _queue(end, "consumer") for t, v in pts])
    copied = rediscover(p, store).model
    fake = FakePrometheus(_queue(end, "consumer"))
    try:
        declared = "".join(f'\n[[series]]\nsource = "rig"\nname = "{n}"\nquery = "{n}"\nkind = "{k}"\n'
                           for n, k in (("queue_depth", "level"), ("jobs_in_total", "counter"), ("jobs_out_total", "counter")))
        q = project(remote_dir, monkeypatch, source_toml(fake.url, window="120m", step="30s", extra='match = [\'{__name__="none"}\']') + declared)
        queried = rediscover(q, for_project(q)).model
    finally:
        fake.close()
    assert len(copied.stocks) == len(queried.stocks) == 1 and len(copied.flows) == len(queried.flows) == 2
    assert queried.stocks[0].series.source == "rig" and copied.stocks[0].series.source == "own"
    norm = lambda m: sorted((f.id.replace("rig:", "").replace("rig.", ""), f.current().form, tuple(round(v, 5) for v in f.current().params.values()))
                            for f in m.flows)
    assert norm(copied) == norm(queried)


def test_a_store_that_holds_nothing_after_a_sleep_keeps_the_definitions_and_saves_no_version(tmp_path, monkeypatch):
    dump, _ = world(now_grid(), 240, regions={"us-east": 1.0}, deploy_every=30)
    fake = FakePrometheus(dump)
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, window="240m"))
        first = rediscover(p, for_project(p))
        assert first.version == 1 and any(s.series and s.series.source == "rig" for s in first.model.stocks)
        good = cached(p.state_dir, "rig")
        good.at -= 7200                                # the laptop slept past infer_every
        save(p.state_dir, good)
        fake.dump = []                                 # and the store holds nothing in the window
        empty = rediscover(p, for_project(p))
        assert empty.version is None and "returned no series" in empty.model.discovery["not_saved"]
        st = empty.model.discovery["sources"]["rig"]
        assert not st["ok"] and st["gaps"] and st["definitions"] == len(good.kept) and "kept 0 definitions" in st["inference_error"]
        assert ModelStore.for_state(p.state_dir).load().stocks == first.model.stocks
        kept = cached(p.state_dir, "rig")
        assert len(kept.kept) == len(good.kept) and kept.at == good.at          # not renewed: the next discovery tries again
        fake.dump = dump
        back = rediscover(p, for_project(p))
    finally:
        fake.close()
    assert back.model.discovery["sources"]["rig"]["ok"] and "not_saved" not in back.model.discovery
    assert {s.id for s in back.model.stocks} == {s.id for s in first.model.stocks}
    assert cached(p.state_dir, "rig").at > good.at


def test_a_round_that_fails_midway_is_not_cached_and_the_old_definitions_stand(tmp_path, monkeypatch):
    end = now_grid()
    dump, _ = world(end, 240, regions={"us-east": 1.0}, deploy_every=30)
    fake = FakePrometheus(dump)
    answer = fake.answer

    def probe_fails(endpoint, form):                  # every probe stays busy (at the series' resolution; the schema reads coarser)
        if endpoint == "query_range" and float((form.get("step") or ["0"])[0]) < 200:
            raise Busy("injected probe failure")
        return answer(endpoint, form)

    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, window="240m"))
        cat = Catalogue(p, for_project(p))
        good = cat.inference("rig", end - 7200, end)
        before = (p.state_dir / "sources" / "rig.json").read_text()
        fake.fail_next = 1                            # the schema listing fails
        listing = cat.inference("rig", end - 7200, end, refresh=True)
        fake.answer = probe_fails
        probing = cat.inference("rig", end - 7200, end, refresh=True)
    finally:
        fake.close()
    assert "inference failed" in listing.error and "injected failure" in listing.error
    assert "inference failed" in probing.error and "probes could not be made" in probing.error and "HTTP 503" in probing.error
    for again in (listing, probing):
        assert [d.id for d in again.kept] == [d.id for d in good.kept]
    assert (p.state_dir / "sources" / "rig.json").read_text() == before


def test_a_source_answering_in_another_shape_is_only_that_source_missing(tmp_path, monkeypatch):
    end = now_grid(30.0)
    dump, _ = world(now_grid(), 120, regions={"us-east": 1.0})
    fake = FakePrometheus(dump)
    answer = fake.answer
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, window="120m", step="30s"))
        store = for_project(p)
        store.write([Point(n, v, t, {**lab, "project": p.key}) for n, lab, pts in _queue(end, "consumer") for t, v in pts])
        fake.answer = lambda endpoint, form: None                   # {"status": "success", "data": null}
        fresh = rediscover(p, store)
        fake.answer = answer
        Catalogue(p, store).inference("rig", end - 7200, end, refresh=True)   # a good round cached (at once: not waiting out the failure)
        fake.answer = lambda endpoint, form: {"resultType": "matrix", "result": None} if endpoint != "series" else answer(endpoint, form)
        cached_defs = rediscover(p, store)
    finally:
        fake.close()
    for r in (fresh, cached_defs):
        st = r.model.discovery["sources"]["rig"]
        assert not st["ok"] and "not a Prometheus answer" in st["error"] and "rig" in r.model.discovery["not_saved"]
        assert [s.series.name for s in r.model.stocks] == ["queue_depth"]


def test_a_source_past_its_deadline_is_cut_short_and_missing(tmp_path, monkeypatch):
    end = now_grid()
    dump, _ = world(end, 120, regions={"us-east": 1.0}, deploy_every=30)
    fake = FakePrometheus(dump)
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, extra='deadline = "2s"\ntimeout = "3s"\nmax_points = 5'))
        cat = Catalogue(p, for_project(p))
        cat.inference("rig", end - 7200, end)                 # cached while the store is fast
        fake.latency = 1.5                                     # every request now takes 1.5 s, and a read takes many
        began = time.monotonic()
        reading = cat.read(end - 7200, end, 60.0)
        took = time.monotonic() - began
    finally:
        fake.close()
    assert took < 2 + 3 + 1, took
    why = reading.missing["rig"]
    assert "reads were not done within the deadline of 2 s" in why and "failed" not in why, why


def test_a_source_whose_machine_label_is_machine_prefixes_it_once():
    from orchestra.sources.fetch import read as read_definition
    from orchestra.sources.views import Definition

    class Store:
        def query_range(self, query, start, end, step, until=None):
            return [({"__name__": "q", "machine": "app", "source": "app"}, [(start, 1.0)])]

    d = Definition(id="q", source="owner", name="q", family="q", view="sum_by", kind="level", query="q", resolution_s=60.0)
    for machine in ("machine", "source", None):
        (_, labels, _, _), = read_definition(Store(), d, "owner", machine, 0.0, 60.0, 60.0)
        assert labels == {"machine": "owner.app", "source": "owner.app"}, machine
