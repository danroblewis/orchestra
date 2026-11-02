"""JSON holds no infinity and no NaN: a non-finite number in something written or sent as JSON
becomes ``null``, and is logged once, by its path, so one bad number never stops a page or a
model version from being read (the strict encoders refuse the whole document for it)."""

from __future__ import annotations

import logging
import math

log = logging.getLogger("orchestra.finite")
_logged: set[str] = set()


def finite(obj, where: str = "$"):
    """``obj`` with every non-finite float replaced by None (lists and dicts copied only where one
    is found). Each replaced field is logged once per process, by its path from ``where``."""
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        if where not in _logged:
            _logged.add(where)
            log.warning("a non-finite number (%s) at %s is sent as null", obj, where)
        return None
    if isinstance(obj, dict):
        out = {k: finite(v, f"{where}.{k}") for k, v in obj.items()}
        return obj if all(out[k] is v for k, v in obj.items()) else out
    if isinstance(obj, list | tuple):
        out = [finite(v, f"{where}[{i}]") for i, v in enumerate(obj)]
        return obj if all(a is b for a, b in zip(out, obj, strict=True)) else out
    return obj
