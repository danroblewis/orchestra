"""History: what the water board's telemetry showed at the end of every hour of the 90 days.

Runs the seeded simulation (sim.py) and prints one line per hour,
{"t": n, "levels": {stock: ML}, "flows"?: {flow: ML this hour}}, with "era" on the hour the
weather or the dams' operation changed. Only what the model on stdin asks for is printed: its
stocks that the telemetry has (all of them when stdin is empty), and, as flows, only the
simulator's per-hour amounts whose ids the model's flows use (see sim.COUNTERS). The example
model has no flows, so it gets levels only. The rivers between the dams never appear.

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
    counters = set(sim.COUNTERS)
    stocks = [s["id"] for s in m.get("stocks") or [] if s.get("id") in sim.MEASURED_STOCKS]
    flows = [f["id"] for f in m.get("flows") or [] if f.get("id") in counters]
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
    out = sys.stdout
    for row in lines(sim.run(seed), *wanted(stdin)):
        out.write(json.dumps(row, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
