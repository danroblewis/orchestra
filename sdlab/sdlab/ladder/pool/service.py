"""The pool's background work in the server: plan submitted jobs, expire leases, promote results whose
main-line plan was not known when they came, and keep the standing main-line job fed (only while a
worker is live). Started by the server's lifespan (start()); one thread, every TICK seconds."""

from __future__ import annotations

import logging
import threading
import time

from . import accept, db, gitcode, jobs, leases

TICK = 15
MAINLINE_EVERY = 60
log = logging.getLogger("sdlab.pool")
_stop = threading.Event()
_state: dict = {"head": None, "mainline_at": 0.0, "last": None}


def tick() -> dict:
    out = {"planned": jobs.plan_pending()}
    with db.LOCK, db.connect() as con:
        out["expired"] = leases.expire(con)
    head = gitcode.main_head()
    if head and head != _state["head"]:
        if _state["head"] is not None:
            out["rechecked"] = accept.recheck_on_new_head()
        _state["head"] = head
        _state["mainline_at"] = 0.0
    if time.time() - _state["mainline_at"] >= MAINLINE_EVERY:
        _state["mainline_at"] = time.time()
        out["mainline"] = jobs.refresh_mainline()
    out["promoted"] = accept.promote_pending()
    _state["last"] = out
    return out


def _loop() -> None:
    while not _stop.wait(TICK):
        try:
            tick()
        except Exception:                                    # noqa: BLE001  (logged; the next tick tries again)
            log.exception("pool tick failed")


def start() -> None:
    from . import auth
    auth.token()                                             # made on the first start (0600)
    _stop.clear()
    threading.Thread(target=_loop, daemon=True, name="pool-service").start()


def stop() -> None:
    _stop.set()
