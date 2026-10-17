"""What happens around the team: work arriving, hiring, training, people leaving.

    world.py arrive     a new work item from outside (no inputs)
    world.py hire       a new recruit, with a name, starts training (no inputs)
    world.py onboard    a recruit (input item) finishes training and joins the staff
    world.py leave      a staff member (input item) leaves

Same contract as every program: the run on stdin, one {"to": <stock>, "item": {...}} per line out.
"""

import argparse
import json
import random
import sys

FIRST = ["Ada", "Ben", "Chen", "Dara", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea", "Mo", "Nia", "Omar", "Pia", "Raj", "Sol", "Tess", "Uma"]
LAST = ["Abe", "Brook", "Cruz", "Dahl", "Eze", "Ford", "Gil", "Hart", "Ito", "Kerr", "Lund", "Moss", "Novak", "Okoro", "Park", "Quinn", "Reyes", "Silva"]
KINDS = ["bug", "feature", "chore", "support"]


def emit(to, item):
    print(json.dumps({"to": to, "item": item}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["arrive", "hire", "onboard", "leave"])
    args, _ = ap.parse_known_args()
    run = json.load(sys.stdin)
    inputs = run.get("inputs", {})

    if args.task == "arrive":
        kind = random.choice(KINDS)
        emit("backlog", {"title": f"{kind} #{random.randint(100, 999)}", "kind": kind})

    elif args.task == "hire":
        emit("training", {"name": f"{random.choice(FIRST)} {random.choice(LAST)}", "role": "engineer"})

    elif args.task == "onboard":
        person = inputs["item"]
        emit("staff", {"name": person["name"], "role": person.get("role", "engineer"), "hired": person.get("_t")})

    elif args.task == "leave":
        person = inputs["item"]
        emit("left", {"name": person["name"], "role": person.get("role", "engineer")})


if __name__ == "__main__":
    main()
