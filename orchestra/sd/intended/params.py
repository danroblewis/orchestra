"""The version parameters, parsed in one place (§3.2, §6.1): the comparison's ``since`` (the base)
and ``v`` (the shown version), and the routes' plain numbers (``version``, ``d``, ``after``). Not
given (or empty) is the default; ``since`` also takes ``off`` or ``none`` (no marks); anything
else is a number: a non-integer is refused (400), and for ``since`` and ``v`` an integer no saved
version has is not found (404)."""

from __future__ import annotations

from .checks import IntentError

OFF = "off"
OFFS = ("off", "none")


def integer(value, name: str) -> int | None:
    """``value`` as a version's (or a seq's) number; None when not given."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit())):
        raise IntentError(f"{name} is a version's number, not {value!r}", status=400)
    return int(value)


def saved_version(value, nums: list[int], name: str) -> int | None:
    """``value`` as a saved version's number; None when not given."""
    n = integer(value, name)
    if n is None:
        return None
    if n not in nums:
        raise IntentError(f"there is no version v{n}", status=404)
    return n


def since_of(value, nums: list[int]) -> int | str | None:
    """``since``: None for the default, ``OFF`` for no marks, or a saved version's number."""
    if value is False or (isinstance(value, str) and value.strip().lower() in OFFS):
        return OFF
    return saved_version(value, nums, "since")
