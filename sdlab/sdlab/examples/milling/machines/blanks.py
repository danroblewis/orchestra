"""Blanks arrive from the saw shop: one aluminium blank per run (no inputs).

    blanks.py [--alloys 6061,7075]
"""

import argparse
import json
import random
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alloys", default="6061,7075")
    args, _ = ap.parse_known_args()
    json.load(sys.stdin)
    blank = {"alloy": random.choice(args.alloys.split(",")),
             "size_mm": random.choice(["60x40x20", "80x50x25", "100x60x30"]),
             "heat_lot": f"H{random.randint(1000, 9999)}"}
    print(json.dumps({"to": "blanks", "item": blank}))


if __name__ == "__main__":
    main()
