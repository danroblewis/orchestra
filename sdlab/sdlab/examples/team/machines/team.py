"""The Team: finishes one work item from the backlog.

    team.py work     one item (input item) from the backlog into done work

The runner decides how many items the Team finishes in a week: its capacity is one week of
work per staff member, so this program only does one item.
"""

import json
import sys


def main():
    if sys.argv[1:2] != ["work"]:
        sys.exit(f"team.py does not know {sys.argv[1:2]}")
    run = json.load(sys.stdin)
    item = run["inputs"]["item"]
    print(json.dumps({"to": "done", "item": {"title": item.get("title", item["_id"]), "kind": item.get("kind"), "arrived": item.get("_t")}}))


if __name__ == "__main__":
    main()
