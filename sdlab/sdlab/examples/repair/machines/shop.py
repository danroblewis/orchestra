"""Repair shop programs: one CLI tool, one subcommand per task.

    shop.py arrive [--mean 4] [--burst-p 0.05] [--burst 20] [--cycle 0] [--swing 0]
        broken devices walk in (no inputs): a few most hours, now and then a crowd; with a
        cycle, the walk-ins rise and fall over that many hours (busy and quiet days)
    shop.py fix          a technician repairs one device from Intake into Ready for pickup
    shop.py collect      a customer picks up one ready device; it leaves the shop
    shop.py send [--min 12] [--max 18]
        (hidden) a device the shop cannot fix goes to the outside vendor; it leaves the
        model and is written to the vendor's queue with the hour it is due back
    shop.py back
        (hidden) the vendor's van: runs once an hour, moves the vendor's clock on one hour,
        and returns every device whose time is up to Ready for pickup

The vendor's queue is real state outside the model, kept in a small JSON file in the run's
directory ($SDLAB_HOME/runs/repair/vendor.json). Nothing in the model measures it: that is
the hidden stock. Resetting the live run starts a new run log, and the vendor's queue starts
empty with it (the file remembers which log it belongs to).
"""

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

FAULTS = ["screen", "battery", "port", "water", "board", "speaker"]
KINDS = ["phone", "tablet", "laptop"]


def emit(to, item):
    print(json.dumps({"to": to, "item": item}))


def run_dir() -> Path:
    home = Path(os.environ.get("SDLAB_HOME") or Path.home() / ".sdlab")
    return home / "runs" / "repair"


def state_path() -> Path:
    return run_dir() / "vendor.json"


def run_marker() -> list:
    """Which run log this is: a reset deletes the log and the next tick starts a new file."""
    try:
        s = (run_dir() / "log.jsonl").stat()
    except OSError:
        return []
    return [s.st_ino, getattr(s, "st_birthtime", None)]


def load() -> dict:
    fresh = {"clock": 0, "queue": [], "run": run_marker()}
    try:
        st = json.loads(state_path().read_text())
    except (OSError, ValueError):
        return fresh
    return st if st.get("run") == fresh["run"] else fresh


def save(st: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(p)


def poisson(mean: float) -> int:
    # Knuth's method; means here are small
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["arrive", "fix", "collect", "send", "back"])
    ap.add_argument("--mean", type=float, default=4.0)
    ap.add_argument("--burst-p", type=float, default=0.05)
    ap.add_argument("--burst", type=float, default=20.0)
    ap.add_argument("--cycle", type=float, default=0.0)
    ap.add_argument("--swing", type=float, default=0.0)
    ap.add_argument("--min", type=int, default=12)
    ap.add_argument("--max", type=int, default=18)
    args, _ = ap.parse_known_args()
    inputs = json.load(sys.stdin).get("inputs", {})

    if args.task == "arrive":
        # a quiet hour is Poisson around the mean; now and then a crowd comes in at once
        # (the mean includes the crowds, so the long-run rate stays `mean`)
        mean = args.mean
        if args.cycle > 0:                      # the hour comes from the vendor's clock (see `back`)
            mean *= 1 + args.swing * math.sin(2 * math.pi * load()["clock"] / args.cycle)
        quiet = max(0.0, mean - args.burst_p * args.burst)
        n = poisson(quiet) + (poisson(args.burst) if random.random() < args.burst_p else 0)
        for _ in range(n):
            emit("intake", {"kind": random.choice(KINDS), "fault": random.choice(FAULTS)})

    elif args.task == "fix":
        d = inputs["item"]
        emit("ready", {"kind": d["kind"], "fault": d["fault"], "fixed_by": "shop"})

    elif args.task == "collect":
        pass                                    # the customer takes it home

    elif args.task == "send":
        d = inputs["item"]
        st = load()
        due = st["clock"] + random.randint(args.min, args.max)
        st["queue"].append({"due": due, "kind": d["kind"], "fault": d["fault"]})
        save(st)

    elif args.task == "back":
        st = load()
        st["clock"] += 1
        keep = []
        for d in st["queue"]:
            if d["due"] <= st["clock"]:
                emit("ready", {"kind": d["kind"], "fault": d["fault"], "fixed_by": "vendor"})
            else:
                keep.append(d)
        st["queue"] = keep
        save(st)


if __name__ == "__main__":
    main()
