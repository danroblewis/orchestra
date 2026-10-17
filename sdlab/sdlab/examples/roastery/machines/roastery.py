"""Roastery programs: one CLI tool, one subcommand per step.

The runner gives each run the items it took on stdin; the tool writes what it makes to
stdout, one {"to": <stock>, "item": {...}} per line.

    roastery.py deliver [--origins a,b,...]   a sack of green beans arrives (no inputs)
    roastery.py roast [--profiles light,...]   one sack of green beans into one roasted batch
    roastery.py cool                           a hot batch rests on the cooling tray
    roastery.py package [--size-g 250]         a cooled batch is weighed, bagged and sealed
    roastery.py order                          a customer orders a bag (no inputs)
    roastery.py ship                           a bag goes out against an open order
"""

import argparse
import json
import random
import sys

CUSTOMERS = ["Ada", "Bo", "Chen", "Dee", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun"]


def emit(to, item):
    print(json.dumps({"to": to, "item": item}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["deliver", "roast", "cool", "package", "order", "ship"])
    ap.add_argument("--origins", default="ethiopia,colombia,brazil,kenya,guatemala")
    ap.add_argument("--profiles", default="light,medium,dark")
    ap.add_argument("--size-g", type=int, default=250)
    args, _ = ap.parse_known_args()
    payload = json.load(sys.stdin)
    inputs = payload.get("inputs", {})
    item = inputs.get("item") or {}

    if args.task == "deliver":
        emit("green", {"origin": random.choice(args.origins.split(","))})

    elif args.task == "roast":
        if "origin" not in item:
            sys.exit("roast needs a sack of green beans")
        emit("roasted", {"origin": item["origin"], "profile": random.choice(args.profiles.split(",")), "temp_c": 220})

    elif args.task == "cool":
        emit("cooled", {"origin": item.get("origin"), "profile": item.get("profile"), "temp_c": 25})

    elif args.task == "package":
        if item.get("temp_c", 25) > 40:
            sys.exit("too hot to seal")
        emit("bags", {"origin": item.get("origin"), "profile": item.get("profile"), "grams": args.size_g})

    elif args.task == "order":
        emit("orders", {"customer": random.choice(CUSTOMERS)})

    elif args.task == "ship":
        # the open order this bag answers is used up by the flow itself (its "uses")
        emit("shipped", {"origin": item.get("origin"), "profile": item.get("profile"), "grams": item.get("grams")})


if __name__ == "__main__":
    main()
