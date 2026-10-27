"""One conformance suite for every metrics store. The file store always runs; VictoriaMetrics
runs when ORCHESTRA_TEST_VM_URL is set (e.g. http://127.0.0.1:8428; see tests/bus/README.md for
the demo servers). Each test uses its own project label and deletes its series afterwards."""

from __future__ import annotations

import os
import uuid

import pytest

from orchestra.metrics import Point, open_metrics

BACKENDS = {"file": "file", "victoriametrics": os.environ.get("ORCHESTRA_TEST_VM_URL")}


@pytest.fixture(params=list(BACKENDS))
def store(request, tmp_path):
    url = BACKENDS[request.param]
    if not url:
        pytest.skip(f"set the URL for the {request.param} store to run it")
    s = open_metrics(url, file_path=tmp_path / "metrics.jsonl")
    project = f"test-{uuid.uuid4().hex[:10]}"
    s.project = project
    yield s
    s.delete("", {"project": project})
    s.close()


def P(store, series, value, ts, **labels):
    return Point(series, value, ts, {"project": store.project, **labels})


def test_write_and_read_raw(store):
    store.write([P(store, "orchestra_stock", v, 1000 + 10 * i, stock="OPEN") for i, v in enumerate([3, 4, 2, 5])])
    assert store.raw("orchestra_stock", {"project": store.project, "stock": "OPEN"}) == [(1000, 3), (1010, 4), (1020, 2), (1030, 5)]


def test_backfill_out_of_order(store):
    store.write([P(store, "orchestra_stock", 5, 2000, stock="DONE")])
    store.write([P(store, "orchestra_stock", 1, 1000, stock="DONE")])
    assert store.raw("orchestra_stock", {"project": store.project, "stock": "DONE"}) == [(1000, 1), (2000, 5)]


def test_range_carries_the_last_value_forward(store):
    store.write([P(store, "orchestra_stock", 3, 1000, stock="OPEN"), P(store, "orchestra_stock", 7, 1025, stock="OPEN")])
    got = store.range("orchestra_stock", {"project": store.project, "stock": "OPEN"}, 990, 1040, 10)
    assert got == [(1000, 3), (1010, 3), (1020, 3), (1030, 7), (1040, 7)], "steps before the first point are left out"


def test_latest_and_labels_keep_series_apart(store):
    store.write([P(store, "orchestra_stock", 1, 1000, stock="OPEN"), P(store, "orchestra_stock", 9, 1000, stock="DONE"),
                 P(store, "orchestra_stock", 2, 1100, stock="OPEN")])
    assert store.latest("orchestra_stock", {"project": store.project, "stock": "OPEN"}) == (1100, 2)
    assert store.latest("orchestra_stock", {"project": store.project, "stock": "DONE"}) == (1000, 9)
    names = [(n, l["stock"]) for n, l in store.series() if l.get("project") == store.project]
    assert names == [("orchestra_stock", "DONE"), ("orchestra_stock", "OPEN")]


def test_series_lists_every_name_a_machine_writes_and_filters_by_labels(store):
    store.write([P(store, "disk_free_bytes", 5e9, 1000, machine="telemetry"), P(store, "orchestra_stock", 1, 1000, stock="OPEN")])
    assert [n for n, _ in store.series("", {"project": store.project})] == ["disk_free_bytes", "orchestra_stock"]
    assert store.series("", {"project": store.project, "machine": "telemetry"}) == [
        ("disk_free_bytes", {"project": store.project, "machine": "telemetry"})]
    assert [n for n, _, _ in store.dump("", {"project": store.project})] == ["disk_free_bytes", "orchestra_stock"]


def test_delete_by_prefix_and_label(store):
    store.write([P(store, "orchestra_stock", 1, 1000, stock="OPEN"), P(store, "orchestra_flow_total", 4, 1000, flow="a>b")])
    store.delete("orchestra_flow", {"project": store.project})
    assert store.raw("orchestra_flow_total", {"project": store.project, "flow": "a>b"}) == []
    assert store.raw("orchestra_stock", {"project": store.project, "stock": "OPEN"}) == [(1000, 1)]


def test_dump_returns_every_matching_series_in_one_pass(store):
    store.write([P(store, "orchestra_stock", 1, 1000, stock="OPEN"), P(store, "orchestra_stock", 2, 1010, stock="OPEN"),
                 P(store, "orchestra_flow_total", 4, 1000, flow="a>b")])
    got = store.dump("orchestra_", {"project": store.project})
    assert [(n, l.get("stock") or l.get("flow"), pts) for n, l, pts in got] == [
        ("orchestra_flow_total", "a>b", [(1000, 4)]), ("orchestra_stock", "OPEN", [(1000, 1), (1010, 2)])]
