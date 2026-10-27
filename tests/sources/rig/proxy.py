"""The rig's front door: a small HTTP proxy that demands a credential before passing a request on
to the rig's VictoriaMetrics, as a hosted store (Chronosphere, Grafana Cloud) does.

    python tests/sources/rig/proxy.py --listen 127.0.0.1:8432 --to http://127.0.0.1:8431 \\
        --token-file ~/.orchestra-sources-rig/token [--mode bearer|header]

``bearer`` wants ``Authorization: Bearer <token>``; ``header`` wants ``API-Token: <token>``.
Anything else gets 401. The credential is never logged; ``--down`` answers 503 to everything (an
outage, for the acceptance check that a missing source saves no version)."""

from __future__ import annotations

import argparse
import hmac
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOP = {"connection", "keep-alive", "transfer-encoding", "host", "content-length", "authorization", "api-token"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="127.0.0.1:8432")
    ap.add_argument("--to", default="http://127.0.0.1:8431")
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--mode", choices=["bearer", "header"], default="bearer")
    ap.add_argument("--down", action="store_true", help="answer 503 to everything")
    args = ap.parse_args(argv)
    token = Path(args.token_file).expanduser().read_text().strip()
    host, port = args.listen.rsplit(":", 1)

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {a[1] if len(a) > 1 else ''}\n")

        def _ok(self) -> bool:
            got = self.headers.get("Authorization", "") if args.mode == "bearer" else self.headers.get("API-Token", "")
            want = f"Bearer {token}" if args.mode == "bearer" else token
            return hmac.compare_digest(got.encode(), want.encode())

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _go(self) -> None:
            if args.down:
                return self._send(503, b'{"status":"error","error":"the rig proxy is down (--down)"}')
            if not self._ok():
                return self._send(401, b'{"status":"error","error":"unauthorized"}')
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            req = urllib.request.Request(args.to + self.path, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
            except OSError as e:
                self._send(502, f'{{"status":"error","error":"upstream: {e}"}}'.encode())

        do_GET = do_POST = _go

    ThreadingHTTPServer((host, int(port)), H).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
