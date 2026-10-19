"""Every strategy has a plain-language explanation (sdlab/ladder/explanations.yaml), so a new one cannot
go unexplained on the ladder pages; parked strategies say so; the API serves both."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sdlab.ladder import catalog, explain, runner

FIELDS = ("idea", "how", "helps_with", "builds_on", "status")
STATUSES = {"active", "parked", "work in progress", "retire-candidate", "retired"}


def test_every_strategy_has_an_entry():
    names = [s["name"] for s in catalog.listing(check=False)]
    entries = explain.strategies()
    missing = [n for n in names if n not in entries]
    assert not missing, f"add these to sdlab/ladder/explanations.yaml: {missing}"
    assert not set(entries) - set(names), "explanations for strategies that no longer exist"
    for n in names:
        e = entries[n]
        for f in FIELDS:
            assert isinstance(e.get(f), str) and e[f].strip(), f"{n}: {f} missing"
        assert e["status"] in STATUSES, f"{n}: status {e['status']!r}"


def test_parked_strategies_say_parked():
    entries = explain.strategies()
    gone = runner.retired()
    for n in runner.parked():
        assert entries[n]["status"] == ("retired" if n in gone else "parked"), n
    for n in gone:
        assert entries[n]["status"] == "retired", n


def test_glossary_terms():
    g = explain.glossary()
    for key in ("stock", "flow", "move", "link", "co_flow", "effect", "hidden_stock", "pieces", "era", "injection", "floor",
                "equivalent", "recall", "precision", "skill20", "skill100", "fresh_run", "occam", "complexity",
                "noise_none", "noise_counts", "short_long",
                "lna", "bic", "likelihood", "kalman", "common_cause", "identifiable", "cramer_rao"):
        assert g[key]["term"] and g[key]["text"] and g[key]["group"], key


def test_api_serves_them():
    from sdlab.server import create_app
    client = TestClient(create_app())
    strategies = client.get("/api/ladder/strategies").json()
    assert all(s["about"] and s["about"]["idea"] for s in strategies)
    assert client.get("/api/ladder/glossary").json()["equivalent"]["text"]
    assert client.get("/ladder/glossary").status_code == 200
