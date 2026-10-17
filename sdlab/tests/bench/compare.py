"""Paired tests between two saved bench runs: is the change from A to B more than noise?

    uv run python tests/bench/compare.py v2.1 2026-10-17T10-23-11-135Z-try-x.json
    uv run python tests/bench/compare.py v2.1 latest

A and B are a baseline name (saved with evaluate.py --save NAME), a run's file name in the runs
folder, a path, or "latest" (the newest saved run). Runs are paired by example and length; for
skill@20 and @100 (and on fresh runs, when both have them) it prints how many got better and worse,
the mean change, and the sign test's and Wilcoxon signed-rank test's two-sided p-values
(sdlab/bench_stats.py), then the runs that changed by more than 2 points.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluate import RUNS

from sdlab.bench_stats import describe, paired, pairs


def find(name: str) -> Path:
    if name == "latest":
        saved = sorted(p for p in RUNS.glob("*.json") if not p.name.startswith("baseline-"))
        if not saved:
            raise SystemExit(f"no saved runs in {RUNS}")
        return saved[-1]
    for p in (RUNS / f"baseline-{name}.json", RUNS / name, Path(name)):
        if p.is_file():
            return p
    raise SystemExit(f"no run {name!r} (a baseline name, a file in {RUNS}, a path, or latest)")


def report(a: dict, b: dict) -> list[str]:
    lines = []
    for key in ("skill", "fresh"):
        for h in (20, 100):
            t = paired(a["results"], b["results"], key, h)
            if t["n"]:
                lines.append(describe(t))
    moved = [(e, n, q - p) for e, n, p, q in pairs(a["results"], b["results"], "skill", 20) if abs(q - p) > 0.02]
    if moved:
        lines.append("Changed by more than 2 points at skill@20: " + ", ".join(f"{e} ({n}) {'+' if d > 0 else ''}{100 * d:.1f}" for e, n, d in moved))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", help="the run before")
    ap.add_argument("b", help="the run after")
    x = ap.parse_args()
    fa, fb = find(x.a), find(x.b)
    a, b = json.loads(fa.read_text()), json.loads(fb.read_text())
    print(f"{fa.name} ({a.get('label') or a.get('at')}) -> {fb.name} ({b.get('label') or b.get('at')})")
    print("\n".join(report(a, b)))


if __name__ == "__main__":
    main()
