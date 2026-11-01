"""How long tentative things persist (§3.3), from the saved versions' keys.

1. A key inference adds becomes a **suggestion** the first time it is in a saved version (a key in
   the first saved version, present ever since, is where the model began: no suggestion).
2. A suggestion present in ``announce_hold`` consecutive saved versions is **settled**: no ring,
   no answer needed; it stays settled only while present.
3. One that leaves before settling **came and went** (with how many versions it was in), and is a
   suggestion again if its key comes back.

The model has stabilised when no suggestion is unsettled. Nothing here expires by time."""

from __future__ import annotations

from .keys import Keys

_cache: dict[tuple, tuple[set[str], set[str]]] = {}


def version_keys(models, n: int) -> tuple[set[str], set[str]] | None:
    """A saved version's own stock and flow keys (cached: a saved version never changes)."""
    ck = (str(models.dir), n)
    if ck in _cache:
        return _cache[ck]
    m = models.load(n)
    if m is None:
        return None
    k = Keys(m)
    _cache[ck] = (k.own_stocks, k.own_flows)
    if len(_cache) > 4096:
        _cache.pop(next(iter(_cache)))
    return _cache[ck]


def presence(models, upto: int | None, shown: Keys | None,
             saved: list[int] | None = None) -> tuple[list[int], list[set[str]], list[set[str]]]:
    """The saved versions up to ``upto`` and the shown model (when it is not one of them): their
    numbers (0 for the live one) and their stock and flow keys, oldest first. ``saved``: the
    saved versions' numbers, when the caller has read them already."""
    saved = [v["version"] for v in models.versions()] if saved is None else saved
    nums = [n for n in saved if upto is None or n <= upto]
    out_n, out_s, out_f = [], [], []
    for n in nums:
        got = version_keys(models, n)
        if got is not None:
            out_n.append(n)
            out_s.append(got[0])
            out_f.append(got[1])
    if shown is not None and (not out_n or (shown.own_stocks, shown.own_flows) != (out_s[-1], out_f[-1])):
        out_n.append(0)
        out_s.append(shown.own_stocks)
        out_f.append(shown.own_flows)
    return out_n, out_s, out_f


def status(nums: list[int], sets: list[set[str]], key: str, hold: int) -> dict | None:
    """One key's status at the last entry: ``settled``, ``suggestion`` or ``came_and_went``, with
    the version its run began (``since``) and how many versions it was in; None for a key that is
    no suggestion (where the model began, or never seen)."""
    flags = [key in s for s in sets]
    if not any(flags):
        return None
    if all(flags):
        return None                                      # where the model began, present ever since
    last = len(flags) - 1
    end = last if flags[last] else max(i for i, f in enumerate(flags) if f)
    start = end
    while start > 0 and flags[start - 1]:
        start -= 1
    run = end - start + 1
    began = nums[start] or None
    if flags[last]:
        if start == 0:
            return None
        return {"status": "settled" if run >= hold else "suggestion", "since": began, "run": run, "versions": sum(flags)}
    if start == 0 or run >= hold:
        return None                                      # a part the model began with, or one that settled, then left
    return {"status": "came_and_went", "since": began, "run": run, "versions": sum(flags), "last": nums[end] or None}


def statuses(models, upto: int | None, shown: Keys | None, hold: int,
             saved: list[int] | None = None) -> dict[str, dict[str, dict]]:
    """Every key's status, per part: ``{"stock": {key: {...}}, "flow": {...}}``."""
    nums, s_sets, f_sets = presence(models, upto, shown, saved)
    out: dict[str, dict[str, dict]] = {"stock": {}, "flow": {}}
    for part, sets in (("stock", s_sets), ("flow", f_sets)):
        for key in set().union(*sets) if sets else set():
            if (st := status(nums, sets, key, hold)) is not None:
                out[part][key] = st
    return out
