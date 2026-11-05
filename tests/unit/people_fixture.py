"""Writes the Machines page's answers for a bus of 600 relayed people and a few programs
(people_seed.py), for the page tests (tests/screenshots/machines-people.test.mjs): the full answer,
the grouped one, the grouped one with the Jira people expanded, and the Jira people's list, as
web/people.py makes them. Run as ``uv run python tests/unit/people_fixture.py <dir> [n]``."""

from __future__ import annotations

import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from people_seed import T0, people_events

from orchestra.events import utc_time
from orchestra.web.machines import machines_view
from orchestra.web.people import grouped, members


def answers(n: int = 600) -> dict[str, dict]:
    evs = people_events(n, step=1.0)
    shift = time.time() - 120 - (T0 + len(evs))
    for e in evs:
        e["time"] = utc_time(datetime.fromisoformat(e["time"]).timestamp() + shift)
    full = {"ok": True, **machines_view(evs), "era": None, "current_era": None, "eras": [], "channels": [], "counted": [],
            "intended_edges": [], "subsystems": {"default": None, "partitions": []}, "model_parts": None}
    for m in full["machines"]:
        m.update({"intent": None, "hidden": None, "comparison": None, "measured": None})
    out = {"full": full}
    out["grouped"] = copy.deepcopy(full)
    grouped(out["grouped"])
    out["expanded"] = copy.deepcopy(full)
    grouped(out["expanded"], {"people/jira"})
    out["members"] = {"ok": True, **members(full["machines"], "people/jira")}
    return out


if __name__ == "__main__":
    where = Path(sys.argv[1])
    for name, body in answers(int(sys.argv[2]) if len(sys.argv) > 2 else 600).items():
        (where / f"{name}.json").write_text(json.dumps(body), encoding="utf-8")
