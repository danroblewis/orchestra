"""History: what the town's public-health dashboard showed at the end of every day of the season.

Runs the seeded simulation (sim.py) and prints one line per day,
{"t": n, "levels": {stock: people}, "flows"?: {flow: people that day}}, with "era" on the day
something changed (school holidays, the vaccination campaign). Only what the model on stdin asks
for is printed: its stocks that the dashboard has (all of them when stdin is empty), and, as
flows, only the recorded daily counters whose ids the model's flows use (see sim.COUNTERS). The
example model has no flows, so it gets levels only.

    history.py [seed]
"""

import json
import sys

import sim


def wanted(stdin: str) -> tuple[list[str], list[str]]:
    try:
        m = json.loads(stdin) if stdin.strip() else {}
    except ValueError:
        m = {}
    stocks = [s["id"] for s in m.get("stocks") or [] if s.get("id") in sim.MEASURED_STOCKS]
    flows = [f["id"] for f in m.get("flows") or [] if f.get("id") in sim.COUNTERS]
    if not m.get("stocks"):
        stocks = list(sim.MEASURED_STOCKS)
    return stocks, flows


def lines(res: sim.Result, stocks: list[str], flows: list[str]):
    eras = {e["t"]: e["label"] for e in res.eras if e["t"] > 1}
    for i in range(sim.STEPS):
        row = {"t": i + 1, "levels": {s: res.levels[s][i] for s in stocks}}
        if flows:
            row["flows"] = {f: res.counters[f][i] for f in flows}
        if i + 1 in eras:
            row["era"] = eras[i + 1]
        yield row


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    for row in lines(sim.run(seed), *wanted(stdin)):
        print(json.dumps(row, separators=(",", ":")))


if __name__ == "__main__":
    main()
