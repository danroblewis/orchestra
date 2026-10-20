"""What a worker knows about its machine: total and available memory, the load, and the resident memory of
its item processes (sampled once a second for all of them: /proc on Linux, one `ps` call on macOS)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time

LINUX = sys.platform.startswith("linux")


def _meminfo() -> dict[str, float]:
    out = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            out[k] = float(v.split()[0]) / 1024.0                 # kB -> MB
    return out


def mem_total_mb() -> float:
    if LINUX:
        return _meminfo()["MemTotal"]
    r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10)
    return int(r.stdout.strip()) / 1048576.0


def mem_available_mb() -> float:
    """What the OS could give a new process now (Linux: MemAvailable; macOS: free, inactive, speculative and
    purgeable pages)."""
    if LINUX:
        return _meminfo()["MemAvailable"]
    r = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10)
    page = int(re.search(r"page size of (\d+) bytes", r.stdout).group(1))
    pages = {}
    for line in r.stdout.splitlines()[1:]:
        k, _, v = line.partition(":")
        try:
            pages[k.strip()] = int(v.strip().rstrip("."))
        except ValueError:
            pass
    n = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
    return n * page / 1048576.0


def load1() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


def rss_mb(pids: list[int]) -> dict[int, float]:
    """The resident memory (MB) of each live pid."""
    out: dict[int, float] = {}
    if not pids:
        return out
    if LINUX:
        for pid in pids:
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            out[pid] = int(line.split()[1]) / 1024.0
                            break
            except OSError:
                pass
        return out
    r = subprocess.run(["ps", "-o", "pid=,rss=", "-p", ",".join(map(str, pids))], capture_output=True, text=True, timeout=10)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit():
            out[int(parts[0])] = int(parts[1]) / 1024.0
    return out


class Sampler:
    """Samples the resident memory of the registered pids every `every` seconds, keeping each one's latest and
    highest value (the highest since it was last reset)."""

    def __init__(self, every: float = 1.0):
        self.every = every
        self.lock = threading.Lock()
        self.pids: set[int] = set()
        self.now: dict[int, float] = {}
        self.high: dict[int, float] = {}
        self._stop = threading.Event()

    def watch(self, pid: int) -> None:
        with self.lock:
            self.pids.add(pid)

    def forget(self, pid: int) -> None:
        with self.lock:
            self.pids.discard(pid)
            self.now.pop(pid, None)
            self.high.pop(pid, None)

    def reset_high(self, pid: int) -> None:
        with self.lock:
            self.high[pid] = self.now.get(pid, 0.0)

    def get(self, pid: int) -> tuple[float, float]:
        """(latest, highest) MB."""
        with self.lock:
            return self.now.get(pid, 0.0), self.high.get(pid, 0.0)

    def sample(self) -> None:
        with self.lock:
            pids = list(self.pids)
        got = rss_mb(pids)
        with self.lock:
            for pid, mb in got.items():
                if pid in self.pids:
                    self.now[pid] = mb
                    self.high[pid] = max(self.high.get(pid, 0.0), mb)

    def run(self) -> None:
        while not self._stop.wait(self.every):
            try:
                self.sample()
            except Exception:                                  # noqa: BLE001  (a ps that failed: the next sample tries again)
                time.sleep(self.every)

    def start(self) -> None:
        threading.Thread(target=self.run, daemon=True, name="pool-rss").start()

    def stop(self) -> None:
        self._stop.set()
