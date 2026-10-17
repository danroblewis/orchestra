"""Sensor: the hospital's dashboard, live. Each tick of a run is one hour of the same seeded
simulation the history comes from, so "Start" plays the 60 days hour by hour and "Import history"
loads them all at once. Prints {"levels": {...}, "flows": {...}} for the hour the run is at (the
`t` on stdin), with "era" when the number of staffed ED beds changes. The recording ends at hour
1440: empty every stock to play it again.

    live.py [seed]
"""

import json
import sys

import sim
from history import wanted


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    t = int((json.loads(stdin) if stdin.strip() else {}).get("t") or 1)
    if t > sim.STEPS:
        sys.exit(f"the recording ends at hour {sim.STEPS}: empty every stock to play it again")
    res, (stocks, flows) = sim.run(seed), wanted(stdin)
    row = {"levels": {s: res.levels[s][t - 1] for s in stocks}, "flows": {f: res.flows[f][t - 1] for f in flows}}
    era = next((e["label"] for e in res.eras if e["t"] == t and t > 1), None)
    if era:
        row["era"] = era
    print(json.dumps(row))


if __name__ == "__main__":
    main()
