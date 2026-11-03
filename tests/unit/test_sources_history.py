"""A new source reads its history, and every query carries the source's match (bootstrap run 4: a
Prometheus holding a week of the team's queues, of which discovery read none, and whose queries
named no namespace, so another team's series were summed into the project's).

The store is in process: the transport's request is answered from points held in memory by
Orchestra's PromQL subset (``orchestra.metrics.promql``), and every request's form is kept."""

from __future__ import annotations

import re
import subprocess

import pytest

from orchestra.config import load_project
from orchestra.metrics import promql
from orchestra.metrics.file import FileMetrics
from orchestra.sd.rediscover import held_window, rediscover
from orchestra.sources import held
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.plan import read_form
from orchestra.sources.regroup import BASES, expr
from orchestra.sources.scope import scope_of, scoped
from orchestra.sources.transport import Transport

DAY = 86400.0
NOW = 1_800_000_000.0
RAW = re.compile(r"^(?P<sel>.*)\[(?P<n>\d+)s\]\s*$", re.DOTALL)


class Store:
    """Points in memory, answered as Prometheus answers (``data`` only), every form kept."""

    def __init__(self, dump):
        self.dump, self.forms = dump, []

    def answer(self, path: str, form: dict):
        f = {k: (v if isinstance(v, list) else [str(v)]) for k, v in (form or {}).items()}
        one = lambda k, d=None: (f.get(k) or [d])[0]
        self.forms.append((path, f))
        if path.endswith("/query_range"):
            res = promql.query_range(self.dump, one("query"), float(one("start")), float(one("end")), float(one("step")))
            return {"resultType": "matrix", "result": [{"metric": lab, "values": [[t, repr(v)] for t, v in pts]} for lab, pts in res]}
        if path.endswith("/query"):
            m, at = RAW.match(one("query")), float(one("time", NOW))
            d = int(m["n"])
            got = promql.select(self.dump, m["sel"], at - d, at)
            return {"resultType": "matrix", "result": [{"metric": lab, "values": [[t, repr(v)] for t, v in pts if t > at - d]} for lab, pts in got]}
        if path.endswith(("/series", "/values")):
            start, end = float(one("start", 0)), float(one("end", NOW))
            seen = {}
            for m in f.get("match[]") or ['{__name__=~".+"}']:
                for lab, _ in promql.select(self.dump, m, start, end):
                    seen.setdefault(tuple(sorted(lab.items())), lab)
            out = sorted(seen.values(), key=lambda x: sorted(x.items()))
            return sorted({lab["__name__"] for lab in out}) if path.endswith("/values") else out
        if path.endswith("/metadata"):
            return {}
        return {}


@pytest.fixture
def store(monkeypatch):
    holder = {}

    def call(self, path, form=None, *, post=True, until=None):
        if self.budget is not None:
            self.budget.spend(path)
        self.requests += 1
        return holder["store"].answer(path, form)
    monkeypatch.setattr(Transport, "_call", call)
    return holder


def week(days: float, *, step: float = 300.0, namespaces=("hackriff", "other")):
    """A queue in each namespace, a point every ``step`` for ``days`` before NOW; its arrivals counted."""
    dump = []
    for ns in namespaces:
        n = int(days * DAY / step)
        lab = {"namespace": ns, "queue": "analyze", "service": "worker"}
        depth = [(NOW - (n - i) * step, float(10 + (i % 7) + (5 if ns == "other" else 0))) for i in range(n + 1)]
        arrived = [(NOW - (n - i) * step, float(3 * i)) for i in range(n + 1)]
        dump += [("queue_depth", lab, depth), ("jobs_arrived_total", lab, arrived)]
    return dump


def project(tmp_path, monkeypatch, extra: str = "", *, match: str = '["{namespace=\\"hackriff\\"}"]'):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "orchestra.toml").write_text(f"""
[discovery]
window = "60m"
step = "30s"
strategy = "conservation"

[[sources]]
name = "prom"
url = "http://127.0.0.1:9"
prefix = "prom"
machine = "service"
match = {match}
infer = false
{extra}

[[series]]
source = "prom"
name = "queue_depth"
query = 'sum by (queue) (queue_depth)'
kind = "level"
""")
    return load_project(repo)


# --- a new source reads its history


def test_a_new_sources_first_read_reaches_back_a_week_in_pages_and_discovery_reads_it(tmp_path, monkeypatch, store):
    store["store"] = Store(week(10))
    p = project(tmp_path, monkeypatch)
    r = rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW)
    rec = held.read(p.state_dir, "prom")
    assert rec["complete"] and rec["pages"] == 7 and rec["through"] == NOW - 7 * DAY, "seven pages of a day: the history bound"
    assert NOW - rec["oldest"] == pytest.approx(7 * DAY, abs=600)
    pages = [f for path, f in store["store"].forms[:7] if path.endswith("query_range")]
    assert [round(NOW - float(f["end"][0])) for f in pages] == [round(i * DAY) for i in range(7)], "newest first"
    d = r.model.discovery
    assert d["window_s"] == 7 * DAY and d["step_s"] == 30.0 * 168, "the grid keeps its number of steps"
    assert d["start"] <= NOW - 7 * DAY + d["step_s"] and d["history"]["sources_s"]["prom"] == pytest.approx(7 * DAY, abs=600)
    before = len(store["store"].forms)
    rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW + 60)
    assert not any(float((f.get("start") or [NOW])[0]) < NOW - DAY and float((f.get("end") or [0])[0]) <= NOW - 6 * DAY
                   for _, f in store["store"].forms[before:]), "no first read again: the record stands"


def test_a_store_holding_less_is_read_as_far_as_it_holds_and_no_further(tmp_path, monkeypatch, store):
    store["store"] = Store(week(1.5))
    p = project(tmp_path, monkeypatch)
    r = rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW)
    rec = held.read(p.state_dir, "prom")
    assert rec["complete"] and rec["pages"] == 2 and NOW - rec["oldest"] == pytest.approx(1.5 * DAY, abs=600)
    assert r.model.discovery["window_s"] == 36 * 3600.0


def test_history_bounds_the_first_read_and_the_window(tmp_path, monkeypatch, store):
    store["store"] = Store(week(10))
    p = project(tmp_path, monkeypatch, 'history = "1d"')
    r = rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW)
    assert held.read(p.state_dir, "prom")["pages"] == 1 and r.model.discovery["window_s"] == DAY
    assert min(float(f["start"][0]) for path, f in store["store"].forms if "start" in f) >= NOW - DAY - 3600


def test_a_first_read_stopped_by_its_budget_is_taken_up_by_the_next_discovery(tmp_path, monkeypatch, store):
    store["store"] = Store(week(10))
    p = project(tmp_path, monkeypatch, "max_requests = 3")
    cat = Catalogue(p, None)
    cat.held(NOW, NOW - 3600.0, NOW)
    rec = held.read(p.state_dir, "prom")
    assert not rec["complete"] and rec["pages"] == 3 and rec["through"] == NOW - 3 * DAY
    assert held.span(rec, cat.spec("prom"), NOW) == pytest.approx(3 * DAY, abs=600), "what was read is used meanwhile"
    Catalogue(p, None).held(NOW, NOW - 3600.0, NOW)
    Catalogue(p, None).held(NOW, NOW - 3600.0, NOW)
    rec = held.read(p.state_dir, "prom")
    assert rec["complete"] and rec["pages"] == 7 and NOW - rec["oldest"] == pytest.approx(7 * DAY, abs=600)


def test_a_budget_too_small_for_any_page_stops_trying_after_three_rounds(tmp_path, monkeypatch):
    p = project(tmp_path, monkeypatch)
    spec = Catalogue(p, None).spec("prom")
    rec = {}
    for _ in range(held.STALLS):
        assert held.due(rec, spec)
        rec = held.first_read(spec, rec, NOW, lambda a, b, step: (None, True))
    assert not held.due(rec, spec) and rec["stalls"] == held.STALLS and "oldest" not in rec
    assert held.span(rec, spec, NOW) == 0.0, "nothing known: the configured window"


def test_a_changed_match_reads_the_history_again(tmp_path, monkeypatch, store):
    store["store"] = Store(week(2))
    p = project(tmp_path, monkeypatch)
    Catalogue(p, None).held(NOW, NOW - 3600.0, NOW)
    first = held.read(p.state_dir, "prom")
    p2 = project(tmp_path, monkeypatch, match='["{namespace=\\"hackriff\\",queue=\\"analyze\\"}"]')
    assert held.due(first, Catalogue(p2, None).spec("prom")), "another match: another first read"
    n = len(store["store"].forms)
    Catalogue(p2, None).held(NOW, NOW - 3600.0, NOW)
    assert len(store["store"].forms) > n and held.read(p2.state_dir, "prom")["key"] != first["key"]


def test_the_web_servers_catalogue_never_makes_a_first_read(tmp_path, monkeypatch, store):
    store["store"] = Store(week(2))
    p = project(tmp_path, monkeypatch)
    assert Catalogue(p, None, infer=False).held(NOW, NOW - 3600.0, NOW) == {"prom": 0.0} and store["store"].forms == []


def test_the_window_is_the_longer_of_its_default_and_the_history_within_the_era():
    assert held_window(3600.0, 30.0, 0.0, None, NOW) == (3600.0, 30.0)
    assert held_window(3600.0, 30.0, 1800.0, None, NOW) == (3600.0, 30.0), "a source holding less: the default"
    assert held_window(3600.0, 30.0, 7 * DAY, None, NOW) == (7 * DAY, 30.0 * 168)
    assert held_window(3600.0, 30.0, 30 * DAY, None, NOW) == (7 * DAY, 30.0 * 168), "never past MAX_WINDOW"
    assert held_window(3600.0, 30.0, 7 * DAY, NOW - 3 * 3600, NOW) == (3 * 3600.0, 90.0), "no longer than the era"
    assert held_window(3600.0, 30.0, 7 * DAY, NOW - 600, NOW) == (3600.0, 30.0), "a young era: the default, clipped as before"


def test_an_explicit_window_is_read_as_asked(tmp_path, monkeypatch, store):
    store["store"] = Store(week(3))
    p = project(tmp_path, monkeypatch)
    r = rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW, window_s=3600.0, step_s=30.0)
    assert r.model.discovery["window_s"] == 3600.0 and "history" not in r.model.discovery


# --- every query carries the source's match


def test_the_scope_is_what_every_match_selector_carries():
    assert scope_of(['{namespace="hackriff"}']) == ['namespace="hackriff"']
    assert scope_of(['{__name__=~"http_.*",env="prod"}', 'queue_depth{env="prod", team="a"}']) == ['env="prod"']
    assert scope_of(['{__name__=~".+"}']) == [] and scope_of(['{a="1"}', '{b="2"}']) == []
    assert scope_of(['{cluster=~"eu-.*", namespace!="kube-system"}']) == ['cluster=~"eu-.*"', 'namespace!="kube-system"']


def test_scoped_adds_the_matchers_to_every_selector_and_nothing_else():
    sc = ['namespace="hackriff"']
    q = ('label_replace(sum by (status) (increase(http_requests_total[120s])), "orchestra_part", "0", "", "") or '
         'label_replace(sum by (service, job) (last_over_time(queue_depth{queue="a,b}"}[151s])), "orchestra_part", "1", "", "")')
    assert scoped(q, sc) == (
        'label_replace(sum by (status) (increase(http_requests_total{namespace="hackriff"}[120s])), "orchestra_part", "0", "", "") or '
        'label_replace(sum by (service, job) (last_over_time(queue_depth{queue="a,b}",namespace="hackriff"}[151s])), "orchestra_part", "1", "", "")')
    assert scoped('{__name__=~"a|b"}', sc) == '{__name__=~"a|b",namespace="hackriff"}'
    assert scoped('x{namespace=~"hackriff|ops"}', sc) == 'x{namespace=~"hackriff|ops"}', "a label it constrains keeps its own"
    assert scoped("sum(rate(x[5m] offset 1h)) without (pod) > bool 1e-3", sc) == \
        'sum(rate(x{namespace="hackriff"}[5m] offset 1h)) without (pod) > bool 1e-3'
    assert scoped("a unless on (pod) group_left (svc) b", sc) == 'a{namespace="hackriff"} unless on (pod) group_left (svc) b{namespace="hackriff"}'
    assert scoped(scoped("x", sc), sc) == scoped("x", sc), "idempotent"


def test_every_planned_query_and_every_request_carries_the_match(tmp_path, monkeypatch, store):
    """Inferred over a store shared with another namespace: each definition's query, the read
    planned from it, and every request sent name the namespace, and the level read is the
    project's own (run 4: 0 of 160 queries did, and ``sum`` mixed the other team's in)."""
    store["store"] = Store(week(0.2, step=30.0))
    p = project(tmp_path, monkeypatch)
    toml = (p.repo_root / "orchestra.toml").read_text().replace("infer = false\n", "")
    (p.repo_root / "orchestra.toml").write_text(toml)
    p = load_project(p.repo_root)
    cat = Catalogue(p, None)
    inf = cat.inference("prom", NOW - 3600, NOW)
    gen = [d for d in inf.kept if not d.id.startswith("declared.")]
    assert gen and all('namespace="hackriff"' in d.query for d in inf.kept), [d.query for d in inf.kept]
    for d in gen:
        if (f := read_form(d, 30.0)) is not None:
            inner, agg, _ = f
            for b in BASES[agg]:
                assert 'namespace="hackriff"' in expr(b, d.by_real, inner)
    sent = [(path, f) for path, f in store["store"].forms if "query" in f or "match[]" in f]
    assert sent and all(all('namespace="hackriff"' in q for q in f.get("match[]", []) + f.get("query", [])) for _, f in sent)
    reading = cat.read(NOW - 3600, NOW, 30.0)
    depth = [pts for name, lab, pts in reading.dump if name == "prom:queue_depth"]
    assert depth and max(v for pts in depth for _, v in pts) <= 16, "the other namespace's queue (15 to 21) is not summed in"


# --- the first read covers levels and counters, and an era of the project's own keeps it (bootstrap run 5)


def _inferred(tmp_path, monkeypatch):
    """The project with its source inferred (no declared series): levels and counters as found."""
    p = project(tmp_path, monkeypatch)
    toml = (p.repo_root / "orchestra.toml").read_text().replace("infer = false\n", "")
    (p.repo_root / "orchestra.toml").write_text(toml[:toml.index("[[series]]")])
    return load_project(p.repo_root)


def test_the_first_read_reaches_back_for_levels_as_well_as_counters(tmp_path, monkeypatch, store):
    store["store"] = Store(week(10, step=60.0))
    p = _inferred(tmp_path, monkeypatch)
    cat = Catalogue(p, None)
    n = len(store["store"].forms)
    cat.held(NOW, NOW - 3600, NOW)
    # a level is read on a grid (query_range), a counter from its raw samples (an instant query of sel[range], ending at "time")
    pages = [f["query"][0] for path, f in store["store"].forms[n:] if (path.endswith("query_range") and float(f["start"][0]) < NOW - DAY)
             or (path.endswith("/query") and "time" in f and float(f["time"][0]) < NOW - DAY)]
    assert pages, "pages before the last day were read"
    assert any("queue_depth" in q for q in pages) and any("jobs_arrived_total" in q for q in pages), pages


def _bus(tmp_path, *evs):
    from orchestra.events import Events
    events = Events(tmp_path / "events.jsonl")
    for ev in evs:
        events.bus.append(ev)
    return events


def _at(t: float) -> str:
    from datetime import UTC, datetime
    return datetime.fromtimestamp(t, UTC).isoformat()


def test_an_era_the_projects_configuration_began_keeps_the_sources_history_and_cuts_the_own_series(tmp_path, monkeypatch, store):
    """Run 5: an era begun by a ``config.changed`` 30 minutes before (a machine's spec changed) cut
    a source's week of history to the era. The source's series keep the week; the own store's are
    read from the era's start only."""
    from orchestra.events import envelope
    from orchestra.metrics import Point

    store["store"] = Store(week(10, step=300.0))
    p = _inferred(tmp_path, monkeypatch)
    own = FileMetrics(tmp_path / "m.jsonl")
    own.write([Point("own_queue", float(i % 5), NOW - 2 * DAY + 60 * i, {"project": p.key, "machine": "w"}) for i in range(2 * 1440)])
    era_at = NOW - 1800
    events = _bus(tmp_path, envelope("config.changed", "supervisor", subject="machine:worker", time=_at(era_at), id="c1"))
    seen = []
    read = Catalogue.read

    def spy(self, start, end, step, **kw):
        r = read(self, start, end, step, **kw)
        seen.append((start, kw.get("own_from"), [pts for name, _, pts in r.dump if name == "own_queue"]))
        return r
    monkeypatch.setattr(Catalogue, "read", spy)
    m = rediscover(p, own, now=NOW, events=events).model
    d = m.discovery
    assert m.era == "e1" and d["era_start"] == era_at
    assert d["window_s"] == 7 * DAY and d["start"] <= NOW - 7 * DAY + d["step_s"], "the source's week is kept"
    assert d["sources_kept"]["own_from"] == era_at and "machine:worker" in d["sources_kept"]["why"]
    _, own_from, pts = seen[0]
    assert own_from == era_at and pts and min(t for t, _ in pts[0]) >= era_at, "the own series from the era's start"


def test_an_era_another_system_changed_in_cuts_the_sources_history_too(tmp_path, monkeypatch, store):
    """A ``system.changed`` (a deploy) may change what the source measures: every series from it."""
    from orchestra.events import envelope

    store["store"] = Store(week(10, step=300.0))
    p = _inferred(tmp_path, monkeypatch)
    era_at = NOW - 3 * 3600
    events = _bus(tmp_path, envelope("system.changed", "deployer", subject="machine:api", time=_at(era_at), id="d1"))
    d = rediscover(p, FileMetrics(tmp_path / "m.jsonl"), now=NOW, events=events).model.discovery
    assert d["window_s"] == 3 * 3600.0 and d["start"] >= era_at and "sources_kept" not in d
