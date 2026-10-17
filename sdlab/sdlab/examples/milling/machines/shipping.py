"""Shipping: one finished part is boxed and leaves on the next truck."""

import json
import random
import sys


def main():
    part = json.load(sys.stdin)["inputs"]["item"]
    print(json.dumps({"to": "shipped", "item": {"part_no": part.get("part_no"), "alloy": part.get("alloy"),
                                                "carrier": random.choice(["UPS", "FedEx", "local"]),
                                                "box": f"B{random.randint(10000, 99999)}"}}))


if __name__ == "__main__":
    main()
