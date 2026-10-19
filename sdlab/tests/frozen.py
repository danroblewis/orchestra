"""The shared discovery library (`sdlab/discovery/*.py`, outside `strategies/`) is pinned.

Strategies use it, so a change to it would change many strategies at once (shared regressions).
It is a shared library that may change only rarely and only with the user's approval; then
re-record with `python tests/frozen.py --write`. A strategy that needs different behaviour copies
the module into its own package. Strategies themselves are not pinned: they are improved freely,
and derivatives carry copies of them (tests/test_isolation.py).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "sdlab" / "discovery"
MANIFEST = Path(__file__).with_name("frozen.sha256")

FROZEN_STRATEGIES: list[str] = []          # strategies are never frozen: derivatives copy them (CLAUDE.md invariant 11)


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
