"""The pool's endpoints (docs/pool.md, "Endpoints"). T: needs the token (auth.py).

    POST   /api/pool/jobs                      T  submit a job
    GET    /api/pool/jobs?limit=&active=          the newest jobs, with their item counts
    GET    /api/pool/jobs/{id}                    one job
    GET    /api/pool/jobs/{id}/results?full=      its results
    DELETE /api/pool/jobs/{id}                 T  cancel it
    POST   /api/pool/claim                     T  items for a worker
    POST   /api/pool/heartbeat                 T  register a worker, renew its leases
    POST   /api/pool/release                   T  a stopping worker gives its leases back
    POST   /api/pool/results                   T  one finished item
    GET    /api/pool/status                       workers, queue by job, main line, throughput
    GET    /api/pool/workers                      the worker registry
    GET    /api/pool/code/head                 T  the main line's branch and commit
    GET    /api/pool/code/bundle?want=&have=   T  a git bundle of a commit
    GET    /api/pool/debug/threads             T  every thread's Python stack and the locks' state (served on the
                                                  event loop, so it answers while the thread pool is stuck)
"""

from __future__ import annotations

import json
import time

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse, Response

from . import accept, auth, db, gitcode, jobs, leases, status

router = APIRouter(prefix="/api/pool")
TOKEN = [Depends(auth.require)]


def _refused(e: jobs.Refused) -> JSONResponse:
    return JSONResponse(e.detail, status_code=e.code)


# the endpoints are plain functions (FastAPI runs them in its thread pool): they read SQLite and git, which
# must not block the event loop the ladder's pages are served from
BODY = Body(None)


@router.post("/jobs", dependencies=TOKEN)
def submit(body: dict[str, Any] | None = BODY):
    try:
        return JSONResponse({"job": jobs.submit(body or {})}, status_code=202)
    except jobs.Refused as e:
        return _refused(e)


@router.get("/jobs")
def list_jobs(limit: int = 50, active: bool = False):
    return {"jobs": jobs.jobs(min(max(limit, 1), 500), active)}


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    try:
        return {"job": jobs.job(job_id)}
    except jobs.Refused as e:
        return _refused(e)


@router.get("/jobs/{job_id}/results")
def job_results(job_id: int, full: bool = False):
    try:
        return {"job": job_id, "results": jobs.results(job_id, full)}
    except jobs.Refused as e:
        return _refused(e)


@router.delete("/jobs/{job_id}", dependencies=TOKEN)
def cancel_job(job_id: int):
    try:
        return {"job": jobs.cancel(job_id)}
    except jobs.Refused as e:
        return _refused(e)


@router.post("/claim", dependencies=TOKEN)
def claim(body: dict[str, Any] | None = BODY):
    try:
        return leases.claim(body or {})
    except jobs.Refused as e:
        return _refused(e)


@router.post("/heartbeat", dependencies=TOKEN)
def heartbeat(body: dict[str, Any] | None = BODY):
    try:
        return leases.heartbeat(body or {})
    except jobs.Refused as e:
        return _refused(e)


@router.post("/release", dependencies=TOKEN)
def release(body: dict[str, Any] | None = BODY):
    try:
        return leases.release(body or {})
    except jobs.Refused as e:
        return _refused(e)


@router.post("/results", dependencies=TOKEN)
def post_result(body: dict[str, Any] | None = BODY):
    try:
        code, answer = accept.post(body or {})
        return JSONResponse(answer, status_code=code)
    except jobs.Refused as e:
        return _refused(e)


@router.get("/status")
def pool_status():
    return status.status()


@router.get("/workers")
def workers():
    now = time.time()
    with db.connect(readonly=True) as con:
        return {"workers": [{"name": r["name"], "machine": r["machine"], "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                             "live": now - r["seen"] < jobs.LIVE, **json.loads(r["info"] or "{}")}
                            for r in con.execute("SELECT * FROM pool_workers ORDER BY name")]}


@router.get("/code/head", dependencies=TOKEN)
def code_head():
    return {"branch": gitcode.branch(), "commit": gitcode.main_head()}


@router.get("/code/bundle", dependencies=TOKEN)
def code_bundle(want: str, have: str = ""):
    haves = [h for h in have.split(",") if h][:20]
    try:
        data = gitcode.bundle(want, haves)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{want[:12]}.bundle"', "Cache-Control": "no-store"})


@router.get("/debug/threads")
async def debug_threads(request: Request):
    """Every thread's Python stack (an async endpoint: it runs on the event loop, not in the thread pool that a
    hang fills, and takes no lock). For diagnosing a stuck server; the pool's token is checked inline."""
    import sys
    import threading
    import traceback
    given = request.headers.get(auth.HEADER) or (request.headers.get("Authorization") or "")[7:].strip() or None
    if not auth.ok(given):
        return JSONResponse({"error": f"the pool's token is required ({auth.HEADER} header)"}, status_code=401)
    names = {t.ident: t.name for t in threading.enumerate()}
    frames = sys._current_frames()
    out = [{"thread": names.get(ident, str(ident)), "ident": ident, "stack": traceback.format_stack(f)} for ident, f in frames.items()]
    return {"threads": len(out), "db_lock": repr(db.LOCK), "stacks": out}
