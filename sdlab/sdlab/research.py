"""The research view's data, read only: the discovery research topics (docs/research) and the
bench's saved runs (tests/bench/evaluate.py writes them to $SDLAB_BENCH_CACHE/runs, default
~/.cache/sdlab/bench/runs).

Nothing here takes a path from the client: topics and runs are listed from their folders, and one
is fetched by a name that must be in that listing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .discovery.api import jsonable

DOCS = Path(__file__).resolve().parent.parent / "docs" / "research"
GOAL_SKILL20, GOAL_SKILL100 = 0.9, 0.8           # docs/DISCOVERY-GOAL.md, as tests/bench/evaluate.py
ROW = re.compile(r"^\|\s*\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*\|\s*(?P<status>[^|]*)\|\s*(?P<verdict>[^|]*)\|\s*$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")

router = APIRouter(prefix="/api/research")


def bench_runs() -> Path:
    return Path(os.environ.get("SDLAB_BENCH_CACHE") or Path.home() / ".cache" / "sdlab" / "bench") / "runs"


def topic_files() -> dict[str, Path]:
    """Every research document by its name relative to docs/research ("frols.md", "literature/x.md")."""
    if not DOCS.is_dir():
        return {}
    return {p.relative_to(DOCS).as_posix(): p for p in sorted(DOCS.rglob("*.md"))}


def kind(status: str) -> str:
    s = status.strip().lower()
    return "done" if s.startswith("done") else "running" if s.startswith("running") else "idea" if s.startswith("idea") else "other"


@router.get("/topics")
def topics() -> dict:
    files = topic_files()
    index = (DOCS / "README.md").read_text() if (DOCS / "README.md").exists() else ""
    rows, intro = [], []
    for line in index.splitlines():
        m = ROW.match(line)
        if m:
            f = m["file"].strip()
            rows.append({"title": m["title"].strip(), "file": f if f in files else None, "status": m["status"].strip(),
                         "kind": kind(m["status"]), "verdict": "" if m["verdict"].strip() in ("-", "") else m["verdict"].strip()})
        elif not rows and not line.startswith("|") and not line.startswith("#"):
            intro.append(line)
    listed = {r["file"] for r in rows}
    others = [n for n in files if n not in listed and n != "README.md"]
    return {"intro": "\n".join(intro).strip(), "topics": rows, "documents": others}


@router.get("/topics/{name:path}")
def topic(name: str) -> dict:
    files = topic_files()
    if name not in files:
        raise HTTPException(404, "no such research document")
    return {"name": name, "markdown": files[name].read_text()}


def _clip(v) -> float:
    return max(-1.0, float(v)) if isinstance(v, (int, float)) else -1.0


def _meets(x: dict, key: str) -> bool:
    s = x.get(key) or {}
    return not x.get("error") and isinstance(s.get("20"), (int, float)) and isinstance(s.get("100"), (int, float)) \
        and s["20"] >= GOAL_SKILL20 and s["100"] >= GOAL_SKILL100


def summary(name: str, run: dict) -> dict:
    """A run's headline, as evaluate.py prints it: mean skill@20 and @100 (each clipped at -100%),
    runs meeting the goal, and the same on fresh runs when the run graded them."""
    res = [x for x in run.get("results") or [] if isinstance(x, dict)]
    n = len(res)

    def mean(key, h):
        vals = [(x.get(key) or {}).get(str(h)) for x in res]
        return sum(_clip(v) for v in vals) / n if n and all(isinstance(v, (int, float)) for v in vals) else None

    fresh = n > 0 and all(x.get("fresh") for x in res)
    parts, of = sum(x.get("parts") or 0 for x in res), sum(x.get("of") or 0 for x in res)
    return {"file": name, "baseline": name[len("baseline-"):-len(".json")] if name.startswith("baseline-") else None,
            "at": run.get("at"), "label": run.get("label") or "", "engine": run.get("engine") or "", "branch": run.get("branch") or "",
            "commit": run.get("commit") or "", "n": n, "examples": len({x.get("example") for x in res}),
            "lengths": sorted({str(x.get("length")) for x in res}),
            "skill20": mean("skill", 20), "skill100": mean("skill", 100), "meets": sum(_meets(x, "skill") for x in res),
            "fresh20": mean("fresh", 20) if fresh else None, "fresh100": mean("fresh", 100) if fresh else None,
            "freshMeets": sum(_meets(x, "fresh") for x in res) if fresh else None,
            "parts": parts / of if of else None, "errors": sum(1 for x in res if x.get("error"))}


_cache: dict[str, tuple[tuple, dict]] = {}


def run_files() -> dict[str, Path]:
    d = bench_runs()
    if not d.is_dir():
        return {}
    return {p.name: p for p in sorted(d.glob("*.json")) if NAME.match(p.name) and p.is_file()}


@router.get("/runs")
def runs() -> dict:
    out = []
    for name, p in run_files().items():
        st = p.stat()
        key = (st.st_mtime_ns, st.st_size)
        hit = _cache.get(name)
        if hit is None or hit[0] != key:
            try:
                hit = (key, summary(name, json.loads(p.read_text())))
            except (ValueError, OSError, AttributeError, TypeError):
                hit = (key, {"file": name, "broken": True})
            _cache[name] = hit
        out.append(hit[1])
    out.sort(key=lambda r: (r.get("at") or "", r["file"]))
    return jsonable({"folder": str(bench_runs()), "goal": {"skill20": GOAL_SKILL20, "skill100": GOAL_SKILL100}, "runs": out})


@router.get("/runs/{name}")
def run(name: str) -> dict:
    files = run_files()
    if not NAME.match(name) or name not in files:
        raise HTTPException(404, "no such run")
    try:
        data = json.loads(files[name].read_text())
    except ValueError:
        raise HTTPException(422, "that run's file is not JSON")
    return jsonable({"file": name, "summary": summary(name, data), **data})
