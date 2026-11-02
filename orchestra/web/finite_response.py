"""The app's JSON response: a non-finite number is sent as ``null`` (``orchestra.finite``, logged
once by its path) instead of failing the whole answer with a 500, so a page never goes blank for
one bad number. A model version saved before the store refused them may still hold one."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from ..finite import finite


class FiniteJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(finite(content))
