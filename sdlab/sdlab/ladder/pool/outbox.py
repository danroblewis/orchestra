"""A worker's outbox ($HOME/outbox): every finished item's post is written here before it is sent and deleted
once the server has answered it, so a result survives a server that is down or a worker that restarts.
Posts are idempotent on the server (the same item is stored once), so sending one twice is harmless.
A post the server refuses for good (400, 404, 409) moves to outbox/refused/ with the answer."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .client import Client, Down

log = logging.getLogger("sdlab.pool.worker")


class Outbox:
    def __init__(self, folder: Path, client: Client):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.lock = threading.Lock()
        self.sent = 0

    def put(self, body: dict) -> Path:
        name = f"{int(body['item_id']):09d}-{str(body.get('lease_id') or 'none')[:12]}.json"
        f = self.dir / name
        tmp = f.with_suffix(".part")
        tmp.write_text(json.dumps(body, default=str))
        os.replace(tmp, f)
        return f

    def pending(self) -> list[Path]:
        return sorted(self.dir.glob("*.json"))

    def send(self, f: Path) -> bool:
        """Post one; True when it is settled (accepted, a duplicate, or refused for good)."""
        with self.lock:
            try:
                body = json.loads(f.read_text())
            except FileNotFoundError:
                return True                                    # sent by the other sender meanwhile
            except ValueError:
                f.rename(f.with_suffix(".broken"))
                return True
            try:
                code, ans = self.client.call("POST", "/api/pool/results", body, timeout=120)
            except Down as e:
                log.warning("outbox: the server is down (%s); %s kept", e, f.name)
                return False
            if code == 200:
                f.unlink(missing_ok=True)
                self.sent += 1
                log.info("posted item %s: %s", body.get("item_id"), json.dumps(ans)[:200])
                return True
            if code == 401:
                log.error("outbox: the server refused the token (401); %s kept", f.name)
                return False
            refused = self.dir / "refused"
            refused.mkdir(exist_ok=True)
            (refused / f.name).write_text(json.dumps({"answer": ans, "code": code, "body": body}, default=str))
            f.unlink(missing_ok=True)
            log.warning("item %s refused (%s): %s", body.get("item_id"), code, json.dumps(ans)[:300])
            return True

    def flush(self) -> int:
        """Send what waits, oldest first, stopping at the first that cannot be sent; returns how many are left."""
        for f in self.pending():
            if not self.send(f):
                break
        return len(self.pending())
