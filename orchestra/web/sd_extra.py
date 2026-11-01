"""What the web server answers when ``orchestra[sd]`` is not installed (``sd.extra``): a request
whose handler needs the extra gets a 503 naming it, instead of failing."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..sd.extra import message, missing


def unavailable(what: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message(what), "needs": "orchestra[sd]"}, status_code=503)


def install(app: FastAPI) -> None:
    """Answer any request whose handler imports a missing module of the extra with a 503."""

    @app.exception_handler(ImportError)
    async def import_failed(request: Request, e: ImportError):
        if not missing(e):
            raise e
        return unavailable(request.url.path)
