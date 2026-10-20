"""Which machine runs which part of the ladder (machines.yaml), and this machine's name.

    here()            this machine's name: $SDLAB_MACHINE, else the first line of ~/.sdlab/machine, else the
                      short hostname. Every result records it (store.record); rows stored before 2026-10-19
                      have none and read as here()
    config()          {name: {ssh, cases}} from machines.yaml: the other machines and the cases they run
    cases_of(name)    the --cases spec a machine runs (also usable as `--cases machine:NAME`)
    owner(case_id, case)  the machine whose spec selects that case (None: this one runs it)

The split (docs/LADDER.md, "Two machines and backups"): node2 runs the realistic, physics, particle,
heavy, real-data and canonical cases; this machine (mac) runs everything else with
`--exclude-cases machine:node2`. Results flow node2 -> mac by `sdlab-ladder export` there and
`sdlab-ladder import` here (exchange.py, scripts/sdlab-sync.sh).
"""

from __future__ import annotations

import os
import socket
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).with_name("machines.yaml")


def here() -> str:
    env = os.environ.get("SDLAB_MACHINE")
    if env:
        return env.strip()
    return _named()


@lru_cache(maxsize=1)
def _named() -> str:
    f = Path.home() / ".sdlab" / "machine"
    try:
        name = f.read_text().strip().splitlines()[0].strip()
        if name:
            return name
    except (OSError, IndexError):
        pass
    return socket.gethostname().split(".")[0]


@lru_cache(maxsize=1)
def config() -> dict:
    import yaml
    return dict(yaml.safe_load(FILE.read_text()) or {}) if FILE.exists() else {}


def cases_of(name: str) -> str:
    m = config().get(name)
    if not m or not m.get("cases"):
        raise SystemExit(f"no machine {name!r} in {FILE.name} (have: {', '.join(config()) or 'none'})")
    return str(m["cases"])


def tag_owner() -> dict[str, str]:
    """{tag: machine} for the machines whose spec is a list of tags (what owner() reads fast)."""
    out = {}
    for name, m in config().items():
        for part in str((m or {}).get("cases") or "").split(","):
            part = part.strip()
            if part.startswith("tag:"):
                out[part[4:]] = name
    return out


def owner(tags) -> str | None:
    """The other machine that runs a case with these tags (None: this machine runs it)."""
    if here() in config():
        return None                     # on the other machine itself, everything it sees is its own
    own = tag_owner()
    for t in tags or []:
        if t in own:
            return own[t]
    return None
