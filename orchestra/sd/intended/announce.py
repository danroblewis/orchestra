"""The host's announcement of each accepted call (§5): ``orchestra.intent.changed`` as
``orchestra-host``, ``subject`` ``<part>:<id>`` (the call's first change), ``data`` ``{version, via,
ops: [{op, part, id, change}]}``. It follows the journal by ``seq`` from ``announced.json``, so a
call the web server wrote is announced once the host is up, and each call once. A listener filters
with the existing syntax, ``orchestra.intent.changed:subject=machine:feature_count_improver``."""

from __future__ import annotations

import json

CHANGED = "orchestra.intent.changed"


def _last(intended) -> int:
    try:
        return int(json.loads((intended.dir / "announced.json").read_text(encoding="utf-8")).get("seq", 0))
    except (OSError, ValueError, TypeError):
        return 0


def announce(intended, publish) -> list[int]:
    """Announce every call not announced yet; returns their seqs."""
    if not intended.dir.exists():
        return []
    done = []
    with intended.models.locked("intended-announce"):
        last = _last(intended)
        for e in intended.journal(after=last):
            ch = e.get("changes") or []
            first = ch[0] if ch else {"part": "layer", "id": str(e["seq"])}
            publish(CHANGED, {"version": e["seq"], "via": (e.get("provenance") or {}).get("via"), "ops": ch},
                    subject=f"{first['part']}:{first['id']}")
            done.append(e["seq"])
            p = intended.dir / "announced.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"seq": e["seq"]}) + "\n", encoding="utf-8")
            tmp.replace(p)
    return done
