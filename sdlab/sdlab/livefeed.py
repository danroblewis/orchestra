"""The examples' live feeds: a run reads one step of a recorded simulation per tick.

An example's `live.py` is a sensor program: the runner gives it the model's stocks and flows and the
step it is measuring (`t`) on stdin, and it prints {"levels": {...}, "flows"?: {...}, "era"?: ...}
for that step. The recording is the example simulator's `measured(seed, steps)` over its long
length (`LONG_STEPS`, or SDLAB_LIVE_STEPS), cached on disk keyed by the simulator's source, so a
run can go on for years of simulated time and the simulation is not rerun for every step it reads.
Past the end of the recording it fails, and the runner stops the run; a simulator marked UNBOUNDED
(a system dynamics model: a longer run begins with the shorter one) never runs out.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def recording(sim, machines: Path, seed: int, steps: int) -> dict:
    # everything that decides the data: the example's programs, and (for a ground-truth example) its
    # truth model and the engine that steps it
    h = hashlib.sha256()
    sources = sorted(machines.glob("*.py")) + [p for p in (machines.parent / "truth.model.json", Path(__file__).with_name("sdtruth.py")) if p.exists() and (machines.parent / "truth.model.json").exists()]
    for p in sources:
        h.update(p.name.encode() + p.read_bytes())
    path = Path(tempfile.gettempdir()) / f"sdlab-live-{machines.parent.name}-{seed}-{steps}-{h.hexdigest()[:12]}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    rec = sim.measured(seed=seed, steps=steps)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec, separators=(",", ":")))
    tmp.replace(path)
    return rec


def play(sim, live_file: str) -> None:
    """The body of an example's live.py: `play(sim, __file__)`."""
    machines = Path(live_file).resolve().parent
    try:
        unit = json.loads((machines.parent.parent / f"{machines.parent.name}.json").read_text()).get("time_unit") or "step"
    except (OSError, ValueError):
        unit = "step"
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else sim.SEED
    # SDLAB_LIVE_STEPS: a number, or "default" for the simulator's default length (the tests use that)
    want = os.environ.get("SDLAB_LIVE_STEPS") or ""
    steps = sim.STEPS if want == "default" else int(want) if want.isdigit() else getattr(sim, "LONG_STEPS", sim.STEPS)
    stdin = "" if sys.stdin.isatty() else sys.stdin.read()
    job = json.loads(stdin) if stdin.strip() else {}
    t = int(job.get("t") or 1)
    # a simulator whose longer runs begin with its shorter ones (UNBOUNDED) never runs out: the
    # recording doubles whenever a run goes past it
    if getattr(sim, "UNBOUNDED", False):
        while t > steps:
            steps *= 2
    if t > steps:
        sys.exit(f"the recording ends at {unit} {steps}: empty every stock to play it again")
    rec = recording(sim, machines, seed, steps)
    asked = [s["id"] for s in job.get("stocks") or []] or list(rec["levels"])
    row = {"levels": {s: rec["levels"][s][t - 1] for s in asked if s in rec["levels"]}}
    counters = rec.get("counters") or {}
    flows = [f["id"] for f in job.get("flows") or [] if f.get("id") in counters]
    if flows:
        row["flows"] = {f: counters[f][t - 1] for f in flows}
    era = next((e["label"] for e in rec.get("eras") or [] if e.get("start") == t and t > 1), None)
    if era:
        row["era"] = era
    print(json.dumps(row))
