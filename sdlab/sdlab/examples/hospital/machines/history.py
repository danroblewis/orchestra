"""History: what the hospital's dashboard showed at the end of every hour of the 60 days.

Runs the seeded simulation (sim.py) and prints one line per hour,
{"t": n, "levels": {stock: patients}, "flows": {flow: patients this hour}}, with "era" on the
hour the number of staffed ED beds changed. Only what is measured is printed: the stocks and
flows of the model on stdin that the dashboard has (all of them when stdin is empty). The places
patients go that nobody measures never appear, even if the model names them.

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
    flows = [f["id"] for f in m.get("flows") or [] if f.get("id") in sim.MEASURED_FLOWS]
    if not m.get("stocks"):
        stocks, flows = list(sim.MEASURED_STOCKS), list(sim.MEASURED_FLOWS)
    return stocks, flows


def lines(res: sim.Result, stocks: list[str], flows: list[str]):
    eras = {e["t"]: e["label"] for e in res.eras if e["t"] > 1}
    for i in range(len(res.levels[sim.MEASURED_STOCKS[0]])):
        row = {"t": i + 1, "levels": {s: res.levels[s][i] for s in stocks}, "flows": {f: res.flows[f][i] for f in flows}}
        if i + 1 in eras:
            row["era"] = eras[i + 1]
        yield row


def main() -> None:
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    for row in lines(sim.run(seed), *wanted(stdin)):
        print(json.dumps(row))


if __name__ == "__main__":
    main()
