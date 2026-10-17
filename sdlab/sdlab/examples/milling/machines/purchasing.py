"""Purchasing: raises one purchase order for one cutting bit (no inputs).

    purchasing.py [--supplier NAME]

The flow's equation decides how often (the gap between four bits and what is on hand); each
run is one order line.
"""

import argparse
import json
import random
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--supplier", default="Harvey Carbide")
    args, _ = ap.parse_known_args()
    ctx = json.load(sys.stdin).get("context", {})
    po = {"po": f"PO-{random.randint(100000, 999999)}", "supplier": args.supplier,
          "tool": random.choice(["6mm 3-flute carbide endmill", "10mm 3-flute carbide endmill"]),
          "price_usd": 38.5, "open_lines_before": ctx.get("on_order", {}).get("level", 0)}
    print(json.dumps({"to": "on_order", "item": po}))


if __name__ == "__main__":
    main()
