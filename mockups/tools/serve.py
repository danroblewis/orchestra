"""Serve the mockups the way `orchestra web` serves the pages, with nothing behind them.

    python mockups/tools/serve.py [port]      # from the repository root; default 8187

/dynamics and /machines are the pages as the demo's server sent them (fixtures/served/), with the
mockup's scripts added: fixtures/bundle.js and shim.js first in <head>, additions.css and
additions.js last. /static/ is Orchestra's own static directory in this checkout (the real page
code), /plugins/ the plugins' files as captured, /mockups/ this folder. Every API answer comes
from the fixtures, inside the page (shim.js).
"""

import http.server
import sys
from pathlib import Path

MOCK = Path(__file__).resolve().parent.parent
ROOT = MOCK.parent
STATIC = ROOT / "orchestra" / "web" / "static"
PAGES = {"/dynamics": "dynamics.html", "/machines": "machines.html"}
HEAD = '<script src="/mockups/fixtures/bundle.js"></script><script src="/mockups/shim.js"></script>'
TAIL = '<link rel="stylesheet" href="/mockups/additions.css"><script src="/mockups/additions.js"></script>'
TYPES = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml"}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in PAGES:
            html = (MOCK / "fixtures" / "served" / PAGES[path]).read_text(encoding="utf-8")
            html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + HEAD, 1).replace("</body>", TAIL + "</body>", 1)
            return self.send(html.encode(), ".html")
        for prefix, base in (("/static/", STATIC), ("/plugins/", MOCK / "fixtures" / "plugins"), ("/mockups/", MOCK)):
            if path.startswith(prefix):
                f = (base / path[len(prefix):]).resolve()
                if f.is_file() and base.resolve() in f.parents:
                    return self.send(f.read_bytes(), f.suffix)
        self.send_error(404)

    def send(self, data, suffix):
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(suffix, "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8187
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
