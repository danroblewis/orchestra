"""Sensor: how many of Orchestra's tickets are in each state right now.

Reads (never writes) the factory's tickets.json and prints one JSON object {stock id: count}.
Every state is reported, zeros included, so a state that empties is measured as empty.

    tickets.py [state dir]

The state dir defaults to $SDLAB_FACTORY_DIR, else ~/.orchestrator/orchestra-automata-db8ce182.
"""

import json
import os
import sys
from pathlib import Path

STATES = ["OPEN", "IN_PROGRESS", "BLOCKED", "READY_FOR_REVIEW", "IN_REVIEW", "REJECTED",
          "APPROVED", "MERGING", "DONE", "CANCELLED"]


def state_dir(argv: list[str]) -> Path:
    if argv:
        return Path(argv[0]).expanduser()
    return Path(os.environ.get("SDLAB_FACTORY_DIR") or Path.home() / ".orchestrator" / "orchestra-automata-db8ce182")


def stock_id(state: str) -> str:
    return state.lower()


def counts(tickets: dict) -> dict[str, int]:
    out = {stock_id(s): 0 for s in STATES}
    for t in tickets.values():
        sid = stock_id(t["state"])
        out[sid] = out.get(sid, 0) + 1
    return out


def main() -> None:
    data = json.loads((state_dir(sys.argv[1:]) / "tickets.json").read_text())
    print(json.dumps(counts(data["tickets"])))


if __name__ == "__main__":
    main()
