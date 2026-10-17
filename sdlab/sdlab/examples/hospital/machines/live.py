"""Sensor: the hospital's dashboard, live. Each tick of a run is one hour of the same seeded
simulation the history comes from, so "Start" plays the 60 days hour by hour and "Import history"
loads them all at once. Prints {"levels": {...}, "flows": {...}} for the hour the run is at (the
`t` on stdin), with "era" when the number of staffed ED beds changes. The recording ends at hour
1440: empty every stock to play it again.

    live.py [seed]
"""

import json
import os
import sys
import tempfile

import sim
from history import wanted


def recording(seed: int) -> dict:
    """The simulation's measured levels and counts, cached on disk: rerunning all 60 days for
    every hour the run reads would make the live run slow."""
    stamp = int(os.stat(sim.__file__).st_mtime)
    path = os.path.join(tempfile.gettempdir(), f"sdlab-hospital-{seed}-{stamp}.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    res = sim.run(seed)
    rec = {"levels": res.levels, "flows": res.flows, "eras": res.eras}
    tmp = f"{path}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(rec, f)
    os.replace(tmp, path)
    return rec


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    t = int((json.loads(stdin) if stdin.strip() else {}).get("t") or 1)
    if t > sim.STEPS:
        sys.exit(f"the recording ends at hour {sim.STEPS}: empty every stock to play it again")
    rec, (stocks, flows) = recording(seed), wanted(stdin)
    row = {"levels": {s: rec["levels"][s][t - 1] for s in stocks}, "flows": {f: rec["flows"][f][t - 1] for f in flows}}
    era = next((e["label"] for e in rec["eras"] if e["t"] == t and t > 1), None)
    if era:
        row["era"] = era
    print(json.dumps(row))


if __name__ == "__main__":
    main()
