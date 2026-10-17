"""Browser check: arranging the canvas must not change what discovery found.

    <python with playwright> tests/bench/ui_arrange_keeps_discovery.py [example]

Starts a scratch SD Lab server (its own SDLAB_HOME, port 8021), opens the example (default sd-saas)
in the Run view, turns on "keep discovering", plays the run at full speed, pauses, notes the
discovered flows, clicks Arrange, and checks the discovered flows afterwards are the same (Arrange
saves a copy of an example, which must not change the data discovery reads). Needs Playwright and
Google Chrome; not part of the regular tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 8021


def found(page) -> list[str]:
    """The discovered flows the panel lists (their headings)."""
    return sorted(page.eval_on_selector_all("#inspector .found-list li b", "bs => bs.map(b => b.textContent)"))


def main() -> int:
    example = sys.argv[1] if len(sys.argv) > 1 else "sd-saas"
    home = tempfile.mkdtemp(prefix="sdlab-ui-")
    server = subprocess.Popen(["uv", "run", "--directory", str(ROOT), "sdlab", "--port", str(PORT)],
                              env={**os.environ, "SDLAB_HOME": home}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/models", timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME)
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{PORT}/?model={example}#run")
            page.wait_for_timeout(2000)
            page.select_option("#speed", "0")
            page.eval_on_selector('[data-live="start"]', "b => b.click()")
            page.wait_for_timeout(1500)
            page.click("[data-autodisc]")
            page.wait_for_timeout(25000)                        # several rediscoveries as data arrives
            page.eval_on_selector('[data-live="stop"]', "b => b.click()")
            page.wait_for_timeout(4000)                         # the last rediscovery settles
            before, steps = found(page), page.inner_text("#run-panel").split("\n")[0]
            page.click("#arrange")
            page.wait_for_timeout(5000)
            after = found(page)
            url = page.url
            browser.close()
        print(json.dumps({"example": example, "run": steps, "before": before, "after": after, "url": url, "page errors": errors}, indent=1))
        ok = bool(before) and before == after and not errors
        print("OK: arranging kept the discovered model" if ok else "FAIL: the discovered model changed (or nothing was found)")
        return 0 if ok else 1
    finally:
        server.terminate()


if __name__ == "__main__":
    sys.exit(main())
