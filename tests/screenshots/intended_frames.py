"""The Dynamics page's frames D1–D3 (docs/proposals/intended-model.md §7) rendered from the real
page and the real API, on stores seeded as task C1's tests seed them (``tests/unit/intended_seed.py``):

- **D1** (and D1-closed): the captured model as the only version, the owner's Features stock
  declared with the Supervisor's measurement options, the chosen instrument recording three points;
- **D2**: v1 with a flow files → commits, v2 without it and with a new stock, acceptance tests
  passing, fed from DONE; the same declared layer;
- **D3** (and D3-closed): D2 after the owner pressed *expect* on the new stock in the Changes panel,
  with the changes switched off and the stock's drawer open;
- **D-extras**, with no approved frame: a simulated stock, an expected stock nothing measures, a
  declared flow to it and a predicted one out of it.

    uv run python tests/screenshots/intended_frames.py [out_dir]

seeds the stores in a temporary directory, serves each with ``orchestra web``'s app on a free
loopback port (auth off), runs ``render_intended.cjs`` (headless Chrome for Testing, as the
mockups' ``tools/render.cjs``) and prints what it found on each page as JSON. The screenshots go to
``tests/screenshots/intended/`` by default; compare them with ``mockups/out/D*.png``."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "intended"
RENDER = HERE / "render_intended.cjs"
SCRIPT = """#!/bin/sh
# Passing acceptance tests on main, as Prometheus text:
#   acceptance_tests_passing N
set -eu
tmp=$(mktemp -d)
git worktree add --quiet --detach "$tmp/main" main
cd "$tmp/main"
pytest -q tests/acceptance --junitxml="$tmp/junit.xml" >/dev/null || true
echo "acceptance_tests_passing $(grep -o 'tests="[0-9]*"' "$tmp/junit.xml" | head -1 | tr -dc 0-9)"
"""
COLLECT = """
[[collect]]
name = "features.acceptance"
command = "machines/features_acceptance.sh"
every = "15m"
timeout = "5m"
"""


def _seed_helpers():
    """C1's seed helper, loaded by file (no path hacks, AGENTS.md rule 10)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("intended_seed", ROOT / "tests" / "unit" / "intended_seed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def project(root: Path):
    """A git repository with an Orchestra project in it: auth off (served on loopback only) and the
    chosen option's instrument, as the Supervisor would have written it."""
    from orchestra.config import init_project

    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    p = init_project(repo)
    toml = repo / "orchestra.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('# auth = "on"', 'auth = "off"', 1) + COLLECT, encoding="utf-8")
    (repo / "machines").mkdir()
    (repo / "machines" / "features_acceptance.sh").write_text(SCRIPT, encoding="utf-8")
    p.reload_config()
    return p


def history(p, stocks) -> None:
    """The captured hour of each stock's level (mockups/fixtures/api/dynamics_history.json), moved to
    now and written to the project's metrics store, so the boxes draw their sparklines."""
    from orchestra.metrics import Point
    from orchestra.metrics import for_project as metrics_for

    h = json.loads((ROOT / "mockups/fixtures/api/dynamics_history.json").read_text(encoding="utf-8"))
    shift = time.time() - h["at"]
    pts = [Point(s.series.name, float(v), t + shift, dict(s.series.labels))   # the captured labels, its project included: what the model reads
           for s in stocks if s.series for t, v in h["stocks"].get(s.id, [])]
    metrics_for(p).write(pts)


def seed_d1(root: Path):
    seed = _seed_helpers()
    p = project(root)
    from orchestra.sd.store import ModelStore

    store = ModelStore.for_state(p.state_dir)
    m = seed.captured_model()
    store.save(m, note="discovered")
    store.write_discovery(m)
    seed.seed(p, discovered=False)
    history(p, m.stocks)
    seed.record_points(p)
    return p


def seed_d2(root: Path):
    seed = _seed_helpers()
    p = project(root)
    from orchestra.sd.store import ModelStore

    store = ModelStore.for_state(p.state_dir)
    store.save(seed.v1_model(), note="discovered")
    store.save(seed.v2_model(), note="discovered: the structure changed")
    seed.seed(p, discovered=False)
    history(p, seed.captured_model().stocks)
    seed.record_points(p, values=(41, 43, 46))
    return p


def seed_extras(root: Path):
    """The states no approved frame shows (intended-model.md §7, "No frame yet"): a simulated stock
    (a placeholder series, ``simulated="true"``), an expected stock nothing measures, a declared flow
    from DONE to it, and a machine's draft expected effect predicting a flow out of it."""
    seed = _seed_helpers()
    p = project(root)
    from orchestra.sd.model import SeriesRef, Stock
    from orchestra.sd.store import ModelStore

    store = ModelStore.for_state(p.state_dir)
    m = seed.captured_model()
    m.stocks.append(Stock("features_placeholder", "features placeholder", evidence={"simulated": True},
                          series=SeriesRef("features_placeholder", {"instrument": "features.sim", "simulated": "true"})))
    store.save(m, note="discovered")
    store.write_discovery(m)
    intended = store.intended()
    intended.apply([{"op": "declare_stock", "id": "features", "name": "Features", "near": 'tasks_tickets{state="DONE"}'},
                    {"op": "declare_flow", "id": "delivered", "from": 'tasks_tickets{state="DONE"}', "to": "features", "name": "features delivered"}],
                   {"author": "owner", "source": "supervisor", "quote": seed.QUOTE})
    intended.apply([{"op": "propose_machine", "id": "feature_count_improver", "title": "Feature Count Improver", "kind": "universal",
                     "managed": "orchestra", "engagement": {"mode": "continuous"}, "receives": ["task.reported"], "emits": ["work.requested"]},
                    {"op": "set_expected_effect", "machine": "feature_count_improver", "horizon_s": 604800,
                     "edits": [{"stock": "features", "rises": True}, {"from": "features", "to": None, "appears": True}]}],
                   {"author": "supervisor", "source": "supervisor"})
    history(p, m.stocks)
    return p


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(p):
    """``orchestra web``'s app for ``p`` on a free loopback port, in a thread; (server, url)."""
    import uvicorn

    from orchestra.web.app import create_app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(p, "127.0.0.1"), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    return server, f"http://127.0.0.1:{port}"


def render(out: Path = OUT, work: Path | None = None, frames: list[str] | None = None) -> dict:
    """Seed, serve and render; what the render script found on each frame."""
    with tempfile.TemporaryDirectory(prefix="orchestra-frames-") as tmp:
        work = Path(work or tmp)
        os.environ["ORCHESTRATOR_HOME"] = str(work / "home")
        os.environ.pop("ORCHESTRA_METRICS_URL", None)
        servers = [serve(seed_d1(work / "d1")), serve(seed_d2(work / "d2")), serve(seed_extras(work / "extras"))]
        try:
            out.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "D1_URL": servers[0][1], "D2_URL": servers[1][1], "EXTRAS_URL": servers[2][1], "OUT": str(out)}
            r = subprocess.run(["node", str(RENDER), *(frames or [])], check=False, env=env, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError(f"render failed ({r.returncode}): {r.stderr[-4000:]}{r.stdout[-2000:]}")
            return json.loads(r.stdout.strip().splitlines()[-1])
        finally:
            for s, _ in servers:
                s.should_exit = True
            time.sleep(0.5)


if __name__ == "__main__":
    print(json.dumps(render(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT), indent=1))
