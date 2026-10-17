"""The supplier delivers the oldest open order line: one purchase order in, one bit on the shelf."""

import json
import random
import sys


def main():
    po = json.load(sys.stdin)["inputs"]["po"]
    bit = {"serial": f"EM{random.randint(10000, 99999)}", "tool": po["tool"], "coating": "AlTiN",
           "po": po["po"], "supplier": po["supplier"]}
    print(json.dumps({"to": "bits", "item": bit}))


if __name__ == "__main__":
    main()
