"""The measured Orchestra factory: its sensor and history programs read the real factory's state.

Without the factory's data on this machine the data tests skip; the model itself is always checked."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from sdlab.server import validate

EXAMPLES = Path(__file__).resolve().parent.parent / "sdlab" / "examples"
MACHINES = EXAMPLES / "factory" / "machines"
STATE_DIR = Path(os.environ.get("SDLAB_FACTORY_DIR") or Path.home() / ".orchestrator" / "orchestra-automata-db8ce182")


def model() -> dict:
    return json.loads((EXAMPLES / "factory.json").read_text())


def run(name: str, *args: str) -> str:
    p = subprocess.run([sys.executable, str(MACHINES / f"{name}.py"), *args], capture_output=True, text=True, timeout=120, cwd=MACHINES)
    assert p.returncode == 0, p.stderr
    return p.stdout


def ticket_counts() -> Counter:
    tickets = json.loads((STATE_DIR / "tickets.json").read_text())["tickets"]
    return Counter(t["state"].lower() for t in tickets.values())


@pytest.fixture
def factory_data():
    if not (STATE_DIR / "events.jsonl").exists() or not (STATE_DIR / "tickets.json").exists():
        pytest.skip(f"no Orchestra factory data in {STATE_DIR}")


def test_the_model_is_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert m["flows"] == [] and m["machines"] == []
    assert m["sensors"] == [{"program": "factory/tickets", "args": []}]
    assert m["history"]["program"] == "factory/history"
    assert {s["unit"] for s in m["stocks"]} == {"tickets"}
    xs = [s["x"] for s in m["stocks"]]
    assert xs == sorted(xs), "stocks are laid out left to right in pipeline order"


def test_the_sensor_counts_the_tickets(factory_data):
    for _ in range(3):                      # the factory is live: retry if it moved while we read
        before = ticket_counts()
        levels = json.loads(run("tickets"))
        if ticket_counts() == before:
            break
    stocks = {s["id"] for s in model()["stocks"]}
    assert set(levels) == stocks
    assert {k: v for k, v in levels.items() if v} == dict(before)


def test_the_history_ends_where_the_tickets_are(factory_data):
    for _ in range(3):
        before = ticket_counts()
        lines = run("history", *model()["history"]["args"]).splitlines()
        if ticket_counts() == before:
            break
    stocks = {s["id"] for s in model()["stocks"]}
    rows = [json.loads(line) for line in lines]
    assert len(rows) > 100
    assert [r["t"] for r in rows] == list(range(1, len(rows) + 1))
    total = None
    for r in rows:
        assert set(r) == {"t", "levels"} and set(r["levels"]) == stocks
        assert all(isinstance(v, int) and v >= 0 for v in r["levels"].values())
        n = sum(r["levels"].values())
        assert total is None or n >= total, "tickets are never destroyed"
        total = n
    assert {k: v for k, v in rows[-1]["levels"].items() if v} == dict(before)
