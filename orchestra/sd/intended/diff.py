"""The structural comparison of the declared layer ``dN`` with a discovered version ``vM`` against a
base ``vK`` (§3.2, §5), computed on keys (``keys.py``), never with ``sd.compare``:

- the **expected set**: each declared stock, effect and flow and each discovered part marked
  expected, present or absent in ``vM`` (a declared flow with a ``null`` end, or two flows between
  its ends, lists the matches as ``candidates`` and chooses none);
- **new** (a key in ``vM`` not in ``vK``) and **removed** (in ``vK``, not in ``vM``), leaving out
  the parts ``sd.prior`` carries into the era;
- each key's **suggestion status** (``history.py``).

The structural diff of a pair is cached as ``diff/d{N}-v{M}-v{K}-{era}.json``: its inputs never
change, so a file never changes (``live`` for the latest discovery: newest only, rewritten when
the discovery is newer). Bus and metrics facts are never cached (``facts.py``)."""

from __future__ import annotations

import json
from pathlib import Path

from . import history
from .keys import Keys, ref_key


def _end_key(end, layer: dict, keys: Keys) -> tuple[bool, str | None]:
    """A declared flow's end as a stock key: (resolved, key); None is outside."""
    if end is None:
        return True, None
    for group in ("stocks", "effects"):
        if end in layer[group]:
            fa = layer[group][end].get("found_as")
            return (fa is not None), fa
    if end in keys.stock_of_id:
        return True, keys.stock_of_id[end]
    return True, end


def flow_matches(el: dict, layer: dict, keys: Keys) -> tuple[str | None, list[str]]:
    """A declared flow's match in a model: (the one flow key it is, or None; the candidates)."""
    ok_a, a = _end_key(el.get("from"), layer, keys)
    ok_b, b = _end_key(el.get("to"), layer, keys)
    if not (ok_a and ok_b) or keys.model is None:
        return None, []
    found = [k for k in keys.flows if keys.ends(k) == (a, b)]
    if a is None or b is None or len(found) != 1:
        return None, sorted(found)
    return found[0], []


def input_keys(model) -> set[str]:
    """The series an equation reads as measured inputs: an effect may be found only as one."""
    out = set()
    for ref in ((model.discovery or {}).get("inputs") or {}).values() if model else []:
        if isinstance(ref, dict) and ref.get("name"):
            from ..model import SeriesRef
            out.add(ref_key(SeriesRef(ref["name"], ref.get("labels") or {})))
    return out


def structural(layer: dict, shown: Keys, base: Keys | None, statuses: dict) -> dict:
    expected = []
    inputs = input_keys(shown.model)
    for part, group in (("stock", "stocks"), ("effect", "effects")):
        for el in layer[group].values():
            fa = el.get("found_as")
            present = fa is not None and (fa in shown.stocks or (part == "effect" and fa in inputs))
            expected.append({"part": part, "id": el["id"], "key": fa, "present": present})
    for el in layer["flows"].values():
        key, cands = flow_matches(el, layer, shown)
        expected.append({"part": "flow", "id": el["id"], "key": key, "present": key is not None, "flow_candidates": cands})
    for key, mk in layer["marks"]["expected"].items():
        expected.append({"part": mk["part"], "id": None, "key": key, "present": key in shown.of(mk["part"]), "mark": True})
    out = {"expected": expected, "new": {"stock": [], "flow": []}, "removed": {"stock": [], "flow": []},
           "status": statuses}
    if base is not None:
        for part in ("stock", "flow"):
            out["new"][part] = sorted(shown.own(part) - base.own(part) - set(base.of(part)))
            out["removed"][part] = sorted(base.own(part) - set(shown.of(part)))
    return out


def cache_name(d: int, v, since, era) -> str:
    return f"d{d}-v{v}-v{since if since is not None else 'off'}-{era or 'none'}.json"


def cached(intended, d: int, v, since, era, shown: Keys, base: Keys | None, layer: dict, hold: int, models,
           stamp: float | None = None) -> dict:
    """The structural diff of a pair, from the cache or computed and written there. ``v`` is a
    saved version's number or ``"live"`` (with ``stamp``, the discovery's time)."""
    folder = Path(intended.dir) / "diff"
    p = folder / cache_name(d, v, since, era)
    try:
        got = json.loads(p.read_text(encoding="utf-8"))
        if v != "live" or got.get("stamp") == stamp:
            return got["diff"]
    except (OSError, ValueError, KeyError):
        pass
    upto = None if v == "live" else v
    statuses = history.statuses(models, upto, shown if v == "live" else None, hold)
    out = structural(layer, shown, base, statuses)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if v == "live":
            for old in folder.glob("d*-vlive-*.json"):
                old.unlink(missing_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"stamp": stamp, "diff": out}) + "\n", encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass                                         # a cache that cannot be written is computed again
    return out
