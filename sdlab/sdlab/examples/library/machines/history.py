"""History: what the library's circulation dashboard showed at the end of every day of the year.

Runs the seeded simulation (sim.py) and prints one line per day,
{"t": n, "levels": {stock: count}, "flows"?: {flow: count that day}}, with "era" on the day the
library changed how it works (the loan period, the renovation). Only what the model on stdin asks
for is printed: its stocks that the dashboard has (all of them when stdin is empty), and, as flows,
only the day's counts whose ids the model's flows use (`borrow`, `return`, `reshelve`, `reserve`,
...; see sim.FLOWS). The example model has no flows, so it gets levels only. Books in the
interlibrary van are never printed: nobody counts them.

    history.py [seed] [steps]       steps: the run's length (default sim.STEPS; see sim.py for long runs)
"""

import json
import sys

import sim

COUNTERS = sim.COUNTERS


def wanted(stdin: str) -> tuple[list[str], list[str]]:
    try:
        m = json.loads(stdin) if stdin.strip() else {}
    except ValueError:
        m = {}
    stocks = [s["id"] for s in m.get("stocks") or [] if s.get("id") in sim.MEASURED_STOCKS]
    flows = [f["id"] for f in m.get("flows") or [] if f.get("id") in COUNTERS]
    if not m.get("stocks"):
        stocks = list(sim.MEASURED_STOCKS)
    return stocks, flows


def lines(res: sim.Result, stocks: list[str], flows: list[str]):
    eras = {e["t"]: e["label"] for e in res.eras if e["t"] > 1}
    for i in range(len(res.levels[sim.MEASURED_STOCKS[0]])):
        row = {"t": i + 1, "levels": {s: res.levels[s][i] for s in stocks}}
        if flows:
            row["flows"] = {f: res.flows[f][i] for f in flows}
        if i + 1 in eras:
            row["era"] = eras[i + 1]
        yield row


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    steps = int(sys.argv[2]) if len(sys.argv) > 2 else sim.STEPS
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    for row in lines(sim.run(seed, steps), *wanted(stdin)):
        print(json.dumps(row, separators=(",", ":")))


if __name__ == "__main__":
    main()
