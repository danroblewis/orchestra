"""The rig's generator: the world (``world.py``) written into the rig's VictoriaMetrics, six hours
backfilled through its import API and then live, one minute at a time, with the ground truth
beside it.

    python tests/sources/rig/generator.py --vm http://127.0.0.1:8431 --dir ~/.orchestra-sources-rig

Writes ``<dir>/ground_truth.jsonl`` (one line per minute: pods, requests per second and p95 per
service and region, and which are down) after ``<dir>/rule.json`` (the spellings, the scaling
rule, the outage). After a pause (the laptop slept) it writes every minute it missed, as a store
that kept collecting would hold them. One region is down for an hour of the backfill (by default
``eu-west``, from its second hour to its third)."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from world import RULE, SPELLINGS, World


def write(vm: str, samples: list[tuple[str, dict, float, float]]) -> None:
    groups: dict[tuple, dict] = {}
    for name, labels, t, v in samples:
        g = groups.setdefault((name, tuple(sorted(labels.items()))), {"metric": {"__name__": name, **labels}, "values": [], "timestamps": []})
        g["values"].append(v)
        g["timestamps"].append(int(t * 1000))
    body = "".join(json.dumps(g) + "\n" for g in groups.values()).encode()
    for path, data in (("/api/v1/import", body), ("/internal/force_flush", None)):
        with urllib.request.urlopen(urllib.request.Request(vm + path, data=data, method="POST" if data else "GET"), timeout=60):
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm", default="http://127.0.0.1:8431")
    ap.add_argument("--dir", default=str(Path.home() / ".orchestra-sources-rig"))
    ap.add_argument("--hours", type=float, default=6.0, help="backfill this much before now")
    ap.add_argument("--down", default="eu-west:1:2", help="REGION:FROM:TO, hours into the backfill a region is down; '' for none")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--once", action="store_true", help="backfill, then stop")
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    start = time.time() - args.hours * 3600
    down = None
    if args.down:
        region, a, b = args.down.split(":")
        down = (region, start + float(a) * 3600, start + float(b) * 3600)
    world = World(start, seed=args.seed, down=down)
    (out / "rule.json").write_text(json.dumps({"spellings": SPELLINGS, "scaling": RULE, "down": down, "start": world.t}, indent=1))
    truth = (out / "ground_truth.jsonl").open("w")
    batch: list = []
    while world.t + 60 <= time.time():
        samples, t = world.minute()
        batch += samples
        truth.write(json.dumps(t) + "\n")
        if len(batch) > 20000:
            write(args.vm, batch)
            batch = []
    write(args.vm, batch)
    truth.flush()
    print(f"backfilled to {time.strftime('%H:%M', time.localtime(world.t))}", file=sys.stderr, flush=True)
    while not args.once:
        time.sleep(max(1.0, world.t + 62 - time.time()))
        batch = []
        while world.t + 60 <= time.time():         # every minute since the last, after a pause too
            samples, t = world.minute()
            batch += samples
            truth.write(json.dumps(t) + "\n")
        try:
            write(args.vm, batch)
        except OSError as e:
            print(f"write failed: {e}", file=sys.stderr, flush=True)
        truth.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
