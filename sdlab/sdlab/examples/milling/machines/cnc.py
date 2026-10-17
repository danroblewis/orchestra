"""The CNC mill: one blank in, one part out.

    cnc.py mill [--spindle-rpm 12000]

The runner has already used up this part's share of the bits (the flow's `uses`); the bits
on hand are in the context. With few bits the operator runs gentler feeds, so the cycle is
longer and the finish rougher.
"""

import argparse
import json
import random
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["mill"])
    ap.add_argument("--spindle-rpm", type=int, default=12000)
    args, _ = ap.parse_known_args()
    payload = json.load(sys.stdin)
    blank = payload["inputs"]["blank"]
    bits = payload.get("context", {}).get("bits", {})
    on_hand = bits.get("level", 0)
    sample = bits.get("sample") or [{}]
    feed = min(1.0, max(0.25, on_hand / 5))           # the same curve as the flow's effect, roughly
    part = {"part_no": f"BRKT-{blank['size_mm'].split('x')[0]}", "alloy": blank["alloy"], "heat_lot": blank["heat_lot"],
            "bit": sample[-1].get("serial", "worn"), "rpm": int(args.spindle_rpm * feed),
            "cycle_s": round(12 / feed + random.uniform(-1, 1), 1), "ra_um": round(random.uniform(0.6, 1.0) * (2 - feed), 2)}
    print(json.dumps({"to": "parts", "item": part}))


if __name__ == "__main__":
    main()
