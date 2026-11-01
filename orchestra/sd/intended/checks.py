"""What the declared layer accepts: ids, a machine's envelope, provenance, and the fields that are
derived on read and so never stored (docs/proposals/intended-model.md §2, §4, §5).

The core checks a machine's **envelope** only; its ``spec`` is the plugin's, stored exactly as
sent and never read here (P4 owns its schema)."""

from __future__ import annotations

import math
import re
import time

MACHINE_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,80}$")
KINDS = ("universal", "programmatic")
MANAGED = ("orchestra", "external")
MODES = ("ad hoc", "continuous", "scheduled")
MISSED = ("skip", "run once")
ENVELOPE = ("id", "title", "description", "tags", "kind", "managed", "engagement", "receives", "emits", "reads", "spec")
LISTS = ("tags", "receives", "emits", "reads")
ENGAGEMENT = ("mode", "at", "tz", "missed")
SCHEDULED_ONLY = ("at", "tz", "missed")
# what the comparison derives on read (§5): an op carrying one is refused
DERIVED = frozenset({"present", "heard", "recording", "points", "points_series", "measured", "met", "instances",
                     "candidates", "alias_candidates", "unexpected", "verdict", "verdicts"})
AUTHOR_VIA = ("plugin", "page", "host")
PROVENANCE = ("author", "via", "source", "at", "turn", "message", "quote", "reason", "request", "control", "page", "from")
TARGET_OPS = ("below", "above", "within")
PARTS = ("stock", "effect", "flow", "machine", "attachment", "event")
MAX_TEXT = 4000


class IntentError(ValueError):
    """An op refused: ``index`` is its place in the call."""

    def __init__(self, message: str, index: int | None = None, status: int = 422):
        super().__init__(message)
        self.index = index
        self.status = status


def text(v, name: str, *, required: bool = False, limit: int = MAX_TEXT) -> str | None:
    if v is None and not required:
        return None
    if not isinstance(v, str) or (required and not v.strip()) or len(v) > limit:
        raise IntentError(f"{name} must be {'a non-empty' if required else 'a'} string of at most {limit} characters, not {v!r}")
    return v


def strings(v, name: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise IntentError(f"{name} must be a list of non-empty strings, not {v!r}")
    return list(v)


def number(v, name: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise IntentError(f"{name} must be a number, not {v!r}")
    return float(v)


def slug(v, name: str = "id") -> str:
    if not isinstance(v, str) or not SLUG.match(v):
        raise IntentError(f"{name} must be a slug (lower-case letters, digits, _ . -), not {v!r}")
    return v


def make_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:80] or "element"


def no_derived(op: dict, keys=None) -> None:
    """Refuse a derived field among an op's own keys (never inside an opaque ``spec``)."""
    bad = sorted(set(keys if keys is not None else op) & DERIVED)
    if bad:
        raise IntentError(f"{', '.join(bad)} {'is' if len(bad) == 1 else 'are'} derived on read, never declared")


def only(op: dict, allowed: tuple | set, what: str) -> None:
    extra = sorted(set(op) - set(allowed) - {"op", "guessed"})
    no_derived(op)
    if extra:
        raise IntentError(f"{what}: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")


def engagement(e) -> dict:
    if not isinstance(e, dict):
        raise IntentError(f"engagement is an object {{mode, at, tz, missed}}, not {e!r}")
    no_derived(e)
    if extra := sorted(set(e) - set(ENGAGEMENT)):
        raise IntentError(f"engagement: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}")
    if e.get("mode") not in MODES:
        raise IntentError(f"engagement mode must be one of {', '.join(MODES)}, not {e.get('mode')!r}")
    if e["mode"] != "scheduled" and (given := [k for k in SCHEDULED_ONLY if k in e]):
        raise IntentError(f"engagement {', '.join(given)} only when the mode is scheduled")
    if "missed" in e and e["missed"] not in MISSED:
        raise IntentError(f"engagement missed must be one of {', '.join(MISSED)}, not {e['missed']!r}")
    for k in ("at", "tz"):
        text(e.get(k), f"engagement {k}", limit=64)
    return dict(e)


def envelope_field(k: str, v):
    """One envelope field, checked; ``spec`` is returned as sent."""
    if k == "id":
        if not isinstance(v, str) or not MACHINE_ID.match(v):
            raise IntentError(f"a machine's id is the source it publishes under, matching {MACHINE_ID.pattern}, not {v!r}")
        return v
    if k in ("title", "description"):
        return text(v, k)
    if k in LISTS:
        return strings(v, k)
    if k == "kind":
        if v not in KINDS:
            raise IntentError(f"kind must be one of {', '.join(KINDS)}, not {v!r}")
        return v
    if k == "managed":
        if v not in MANAGED:
            raise IntentError(f"managed must be one of {', '.join(MANAGED)}, not {v!r}")
        return v
    if k == "engagement":
        return engagement(v)
    if k == "spec":
        if not isinstance(v, dict):
            raise IntentError(f"spec is an object, stored as sent, not {v!r}")
        return v
    raise IntentError(f"unknown envelope field {k} (the rest of a machine is its spec)")


def envelope(fields: dict) -> dict:
    no_derived(fields)
    return {k: envelope_field(k, v) for k, v in fields.items()}


def target(t: dict) -> dict:
    if t.get("op") not in TARGET_OPS:
        raise IntentError(f"a target's op is one of {', '.join(TARGET_OPS)}, not {t.get('op')!r}")
    out = {"op": t["op"], "value": number(t.get("value"), "value"), "over_s": number(t.get("over_s"), "over_s")}
    if out["over_s"] <= 0:
        raise IntentError("over_s must be above 0")
    if t["op"] == "within":
        out["hi"] = number(t.get("hi"), "hi")
        if out["hi"] < out["value"]:
            raise IntentError("within needs hi at least value")
    elif "hi" in t:
        raise IntentError("hi goes with within")
    return out


def provenance(p: dict | None, via: str = "plugin") -> dict:
    """A call's provenance, checked, with ``via`` and ``at`` filled in."""
    p = dict(p or {})
    if extra := sorted(set(p) - set(PROVENANCE)):
        raise IntentError(f"provenance: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}", status=400)
    author = p.get("author") or p.get("source")
    if not isinstance(author, str) or not author.strip():
        raise IntentError("provenance needs an author: owner, inference, or the plugin's source", status=400)
    p["author"] = author
    p.setdefault("via", via)
    if p["via"] not in AUTHOR_VIA:
        raise IntentError(f"via is one of {', '.join(AUTHOR_VIA)}, not {p['via']!r}", status=400)
    for k in ("source", "turn", "message", "quote", "reason", "request", "control", "page", "from"):
        if k in p:
            text(p[k], k)
    if p["author"] == "owner" and p["via"] == "plugin" and not p.get("quote"):
        raise IntentError("a plugin's author: owner is backed by the owner's words: give the quote", status=400)
    p["at"] = time.time() if p.get("at") is None else number(p["at"], "at")
    return {k: v for k, v in p.items() if v is not None}
