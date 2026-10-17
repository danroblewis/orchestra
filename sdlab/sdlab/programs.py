"""Running machine programs: through a forking helper (see forkhelper.py) when the system can
fork, else as a fresh ``python <path>`` each time. Either way the program sees the same thing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path


class Programs:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.helper: subprocess.Popen | None = None
        self.broken = not hasattr(os, "fork") or os.environ.get("SDLAB_NO_FORK") == "1"

    def run(self, path: Path, argv: list[str], stdin: str, timeout: float) -> subprocess.CompletedProcess:
        """Like subprocess.run([python, path, *argv], input=stdin, cwd=path.parent): raises
        subprocess.TimeoutExpired when the program runs too long."""
        path = Path(path).resolve()
        cmd = [sys.executable, str(path), *argv]
        if not self.broken:
            with self.lock:
                res = self._ask({"path": str(path), "argv": argv, "stdin": stdin, "cwd": str(path.parent), "timeout": timeout})
            if res is not None:
                if res.get("timeout"):
                    raise subprocess.TimeoutExpired(cmd, timeout, res.get("stdout"), res.get("stderr"))
                return subprocess.CompletedProcess(cmd, res["code"], res["stdout"], res["stderr"])
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, cwd=path.parent)

    def _ask(self, req: dict) -> dict | None:
        try:
            if self.helper is None or self.helper.poll() is not None:
                self.helper = subprocess.Popen([sys.executable, "-m", "sdlab.forkhelper"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                               cwd=Path(__file__).resolve().parent.parent)
            self.helper.stdin.write(json.dumps(req).encode() + b"\n")
            self.helper.stdin.flush()
            line = self.helper.stdout.readline()
            res = json.loads(line) if line else {"error": "the helper stopped"}
        except (OSError, ValueError) as e:
            res = {"error": repr(e)}
        if "error" in res:                                     # give up on the helper; run programs the slow way
            self.broken = True
            self.close()
            return None
        return res

    def close(self) -> None:
        h, self.helper = self.helper, None
        if h and h.poll() is None:
            h.kill()
            h.wait()
