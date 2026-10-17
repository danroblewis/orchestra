"""Laundry programs: one CLI tool, one subcommand per task.

The runner gives each run the items it took on stdin; the tool writes what it makes to
stdout, one {"to": <stock>, "item": {...}} per line. The arguments are its parameters.

    socks.py arrive [--colours black,white,...]   a new sock from outside (no inputs)
    socks.py unload                                one sock from the basket, laid out
    socks.py pair                                  two socks (inputs a and b) into one pair
    socks.py file [--sport-colours white,red]      one pair into the dress or sport drawer
    socks.py lose                                  one sock goes missing
    socks.py wear                                  a pair from a drawer is worn: two socks back in the basket
    socks.py dog                                   the dog takes a loose sock; it is never seen again
"""

import argparse
import json
import random
import sys


def emit(to, item):
    print(json.dumps({"to": to, "item": item}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["arrive", "unload", "pair", "file", "lose", "wear", "dog"])
    ap.add_argument("--colours", default="black,white,grey,navy,red")
    ap.add_argument("--sizes", default="M,L")
    ap.add_argument("--sport-colours", default="white,red")
    args, _ = ap.parse_known_args()
    inputs = json.load(sys.stdin).get("inputs", {})

    if args.task == "arrive":
        emit("basket", {"colour": random.choice(args.colours.split(",")), "size": random.choice(args.sizes.split(","))})

    elif args.task == "unload":
        sock = inputs["item"]
        emit("loose", {"colour": sock["colour"], "size": sock["size"]})

    elif args.task == "pair":
        a, b = inputs["a"], inputs["b"]
        if (a["colour"], a["size"]) != (b["colour"], b["size"]):
            sys.exit(f"these do not match: {a['colour']} {a['size']} and {b['colour']} {b['size']}")
        emit("pairs", {"colour": a["colour"], "size": a["size"], "socks": [a["_id"], b["_id"]]})

    elif args.task == "file":
        pair = inputs["item"]
        drawer = "sport" if pair["colour"] in args.sport_colours.split(",") else "dress"
        emit(drawer, {"colour": pair["colour"], "size": pair["size"]})

    elif args.task == "lose":
        sock = inputs["item"]
        emit("lost", {"colour": sock["colour"], "size": sock["size"]})

    elif args.task == "wear":
        pair = inputs["item"]
        for _ in range(2):
            emit("basket", {"colour": pair["colour"], "size": pair["size"]})

    elif args.task == "dog":
        pass                                    # taken, and nothing comes back


if __name__ == "__main__":
    main()
