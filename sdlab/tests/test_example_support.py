import importlib.util
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import create_app

DESK = Path(__file__).parent.parent / "sdlab" / "examples" / "support" / "machines" / "desk.py"
spec = importlib.util.spec_from_file_location("support_desk", DESK)
desk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desk)

QUEUE = {"billing": "billing", "bug": "engineering", "howto": "answered", "spam": "spam"}
ROUTED = ("billing", "engineering", "answered", "spam")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def items(client, stock, mid="support"):
    return client.get(f"/api/models/{mid}/live/stocks/{stock}").json()["items"]


def triaged(client, mid="support"):
    """Every message that has left the Inbox, with the stock Triage sent it to (resolved ones are
    traced back by the team that worked them)."""
    out = [(s, it) for s in ROUTED for it in items(client, s, mid)]
    out += [("billing" if it["team"] == "billing" else "engineering", it) for it in items(client, "resolved", mid)]
    return out


def test_support_validates_and_rules_route_by_kind(client):
    m = client.get("/api/models/support").json()
    assert next(s for s in m["stocks"] if s["id"] == "answered")["target"]
    triage = next(f for f in m["flows"] if f["id"] == "triage")
    assert triage["machine"] == "ai_triage" and next(x for x in m["machines"] if x["id"] == "ai_triage")["kind"] == "agent"
    triage["machine"] = "rules"
    assert client.put("/api/models/my-support", json=m).json() == {"ok": True}
    for _ in range(30):
        client.post("/api/models/my-support/live/step")
    snap = client.get("/api/models/my-support/live").json()
    assert snap["t"] == 30 and not snap["errors"], snap["errors"]
    done = triaged(client, "my-support")
    assert len(done) >= 3, "too few messages arrived in 30 minutes"
    plain = wrong = 0
    for stock, it in done:
        kind, tricky = desk.which(it["text"])
        assert it.get("triaged_by") == "rules"
        if not tricky:
            plain += 1
            assert stock == QUEUE[kind], (kind, stock, it["text"])
        wrong += stock != QUEUE[kind]
        if stock == "answered":
            assert it["answer"]
    print(f"\nrules triage: {len(done)} messages, {plain} plain, {wrong} misrouted (all tricky)")


def llm_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/v1/models", timeout=3):
            return True
    except OSError:
        return False


def test_ai_agent_triages(client):
    if not llm_up():
        pytest.skip("no language model at http://127.0.0.1:8081/v1")
    began = time.time()
    while time.time() - began < 180:
        client.post("/api/models/support/live/step")
        snap = client.get("/api/models/support/live").json()
        if any("timed out" in e["error"] for e in snap["errors"]):
            pytest.skip("the language model is too busy to answer in time (it is shared with other agents)")
        assert not snap["errors"], snap["errors"]
        if len(triaged(client)) >= 3:
            break
    done = triaged(client)
    assert len(done) >= 3, f"only {len(done)} triaged in {snap['t']} steps"
    right = 0
    print()
    for stock, it in done:
        assert stock in ROUTED
        kind, tricky = desk.which(it["text"])
        right += stock == QUEUE[kind]
        print(f"[{kind}{' tricky' if tricky else ''}] {it['subject']!r} -> {stock}: {it.get('reason')}"
              + (f"\n    answer: {it['answer']}" if it.get("answer") else ""))
    print(f"AI triage: {right}/{len(done)} to the right queue in {snap['t']} steps, {time.time() - began:.0f} s")
