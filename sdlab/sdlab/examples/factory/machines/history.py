"""History: how many of Orchestra's tickets were in each state at the end of every step.

Replays the factory's events.jsonl (read only): `ticket_created` puts a ticket in OPEN, each
`ticket_transition` moves it from `from` to `to`. Time is cut into steps of a fixed number of
minutes, starting at the first event; for every step it prints
{"t": n, "levels": {stock id: count}}, n counting from 1, the levels being the counts after
every event before the step's end. Only levels: which tickets moved where is never printed.

    history.py [minutes per step, default 15] [state dir]

The state dir defaults to $SDLAB_FACTORY_DIR, else ~/.orchestrator/orchestra-automata-db8ce182.
"""

import json
import sys
from datetime import datetime, timedelta

from tickets import STATES, state_dir, stock_id


def events(path):
    for line in path.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue                     # a line being written as we read
        if isinstance(e, dict) and "ts" in e:
            yield e


def history(evs: list[dict], minutes: float):
    """Yield (t, levels) for every step from the first event to the last."""
    if not evs:
        return
    step = timedelta(minutes=minutes)
    t0 = datetime.fromisoformat(evs[0]["ts"])
    state: dict[str, str] = {}
    level = {stock_id(s): 0 for s in STATES}

    def move(ticket, src, dst):
        if src is not None:
            level[stock_id(src)] -= 1
        level[stock_id(dst)] = level.get(stock_id(dst), 0) + 1
        state[ticket] = dst

    t, end = 1, t0 + step
    for e in evs:
        when = datetime.fromisoformat(e["ts"])
        while when >= end:
            yield t, dict(level)
            t, end = t + 1, end + step
        if e.get("type") == "ticket_created" and e["ticket"] not in state:
            move(e["ticket"], None, "OPEN")
        elif e.get("type") == "ticket_transition":
            move(e["ticket"], state.get(e["ticket"]), e["to"])   # unknown ticket: arrives from outside
    yield t, dict(level)


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    evs = list(events(state_dir(sys.argv[2:]) / "events.jsonl"))
    for t, levels in history(evs, minutes):
        print(json.dumps({"t": t, "levels": levels}))


if __name__ == "__main__":
    main()
