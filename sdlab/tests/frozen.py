"""Frozen discovery code: the shared discovery library and every strategy another strategy builds on.

Strategies are a collection of isolated options, not a shared codebase (sdlab/CLAUDE.md,
invariant 11). Code that other strategies import must not change, or a fix for one strategy
becomes a regression in others. To change frozen behaviour, copy the code into a new, separately
named strategy (e.g. `effect_hats_v2`) and change the copy.

`python tests/frozen.py --write` records the manifest; only the user may approve adding to or
re-recording it (a strategy becomes frozen when another strategy starts importing it).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery"
MANIFEST = Path(__file__).with_name("frozen.sha256")

# strategies other strategies import (2026-10-19); a strategy joins when something builds on it
FROZEN_STRATEGIES = [
    "censored", "combined", "combined_lean", "combined_misfit", "common_cause", "earned_pieces",
    "effect_hats", "floors", "gap_prior", "gated", "held_out", "hidden_transit", "impulses",
    "inflow_attribution", "lna", "lna_levels", "lna_loops", "lna_products", "lna_pulses",
    "lna_stack", "mass_balance", "matrix", "periodic_inflows", "symbolic",
]


def files() -> list[Path]:
    out = sorted(p for p in ROOT.glob("*.py"))                       # the shared discovery library
    for s in FROZEN_STRATEGIES:
        d = ROOT / "strategies" / s
        out += sorted(d.rglob("*.py")) if d.is_dir() else [ROOT / "strategies" / f"{s}.py"]
    return [p for p in out if "__pycache__" not in p.parts]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def current() -> dict[str, str]:
    base = ROOT.parents[1]
    return {str(p.relative_to(base)): digest(p) for p in files()}


def recorded() -> dict[str, str]:
    out = {}
    for line in MANIFEST.read_text().splitlines():
        if line.strip():
            h, path = line.split(None, 1)
            out[path] = h
    return out


if __name__ == "__main__" and "--write" in sys.argv:
    MANIFEST.write_text("".join(f"{h}  {p}\n" for p, h in sorted(current().items())))
    print(f"recorded {len(current())} frozen files in {MANIFEST}")
