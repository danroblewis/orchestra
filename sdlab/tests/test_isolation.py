"""No strategy imports another strategy; a composite or derivative carries its own copy
(sdlab/CLAUDE.md invariant 11; tests/isolation.py)."""

from isolation import violations

# Strategies that still import others: none since queue item 0c (2026-10-19). This list may only
# shrink, so it stays empty. A new entry is a failure: copy the code you build on instead of importing it.
KNOWN: dict[str, set[str]] = {}


def test_no_new_cross_strategy_imports():
    new = {n: u - KNOWN.get(n, set()) for n, u in violations().items()}
    new = {n: u for n, u in new.items() if u}
    assert not new, ("A strategy imports another strategy. Copy the code you build on into your own "
                     f"package instead (sdlab/CLAUDE.md invariant 11): {new}")
