"""Frozen discovery code stays unchanged (see tests/frozen.py and sdlab/CLAUDE.md invariant 11)."""

from frozen import current, recorded


def test_frozen_code_is_unchanged():
    now, was = current(), recorded()
    changed = sorted(p for p in was if p in now and now[p] != was[p])
    gone = sorted(p for p in was if p not in now)
    added = sorted(p for p in now if p not in was)
    assert not (changed or gone or added), (
        "Frozen discovery code changed. Strategies are isolated: copy the code into a new, separately "
        "named strategy and change the copy instead (sdlab/CLAUDE.md, invariant 11).\n"
        f"changed: {changed}\nremoved: {gone}\nadded to a frozen package: {added}")
