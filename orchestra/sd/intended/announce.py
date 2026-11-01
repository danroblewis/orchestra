"""The host's announcement of each accepted call (§5): ``orchestra.intent.changed`` as
``orchestra-host``, one event per element the call touches, in the order the call first touched
them: ``subject`` ``<part>:<id>``, ``data`` ``{version, via, ops: [{op, part, id, change}]}`` with
``ops`` that element's changes only. So one call can give several events, and a listener on one
element hears every call that touched it, with the existing filter syntax,
``orchestra.intent.changed:subject=machine:feature_count_improver``. It follows the journal by
``seq`` from ``announced.json``, written once a whole call is announced, so a call the web server
wrote is announced once the host is up. Delivery is at least once per element: a publish that
fails partway through a call leaves the call unannounced, and the next pass sends the elements
already sent again, so a listener de-duplicates by ``version`` and the change ids in ``ops``."""

from __future__ import annotations

import json

CHANGED = "orchestra.intent.changed"


def _last(intended) -> int:
    try:
        return int(json.loads((intended.dir / "announced.json").read_text(encoding="utf-8")).get("seq", 0))
    except (OSError, ValueError, TypeError):
        return 0


def per_element(changes: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """A call's changes grouped by the element they touch, in the order first touched."""
    out: dict[tuple[str, str], list[dict]] = {}
    for c in changes:
        out.setdefault((c["part"], c["id"]), []).append(c)
    return out


def announce(intended, publish) -> list[int]:
    """Announce every call not announced yet; returns their seqs."""
    if not intended.dir.exists():
        return []
    done = []
    with intended.models.locked("intended-announce"):
        last = _last(intended)
        for e in intended.journal(after=last):
            via = (e.get("provenance") or {}).get("via")
            for (part, eid), ops in per_element(e.get("changes") or []).items():
                publish(CHANGED, {"version": e["seq"], "via": via, "ops": ops}, subject=f"{part}:{eid}")
            done.append(e["seq"])
            p = intended.dir / "announced.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"seq": e["seq"]}) + "\n", encoding="utf-8")
            tmp.replace(p)
    return done
