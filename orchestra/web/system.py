"""The host's resources for the Dashboard's host panel (``/api/system``): CPU, memory, disk, load,
and on Apple hosts the GPU's utilization with a short history."""

from __future__ import annotations

import time

import psutil
from fastapi import FastAPI

from ..config import Project


def install(app: FastAPI, project: Project) -> None:
    gpu_history: list[dict] = []

    def gpu_sample() -> dict | None:
        """Apple GPU utilization from the IOAccelerator performance counters (no sudo).
        Returns None on non-Apple hosts or when ioreg is unavailable."""
        import plistlib
        import shutil
        import subprocess
        if not shutil.which("ioreg"):
            return None
        try:
            raw = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-a"], capture_output=True, timeout=3, check=False).stdout
            items = plistlib.loads(raw) if raw else []
        except Exception:  # noqa: BLE001 - a host without this tool has no GPU reading
            return None
        for it in items:
            ps = it.get("PerformanceStatistics") or {}
            if "Device Utilization %" in ps:
                return {"name": it.get("IOClass", "GPU"), "utilization": int(ps.get("Device Utilization %", 0)),
                        "renderer": int(ps.get("Renderer Utilization %", 0)), "tiler": int(ps.get("Tiler Utilization %", 0)),
                        "memory_used": int(ps.get("In use system memory", 0)), "memory_alloc": int(ps.get("Alloc system memory", 0))}
        return None

    @app.get("/api/system")
    def system(gpu_window: int = 240) -> dict:
        """Host utilization. Sync so the CPU sampling interval runs in a worker thread.
        gpu_window is the seconds of GPU history to return (kept for up to one hour)."""
        gpu = gpu_sample()
        if gpu is not None:
            gpu_history.append({"t": time.time(), "u": gpu["utilization"]})
            del gpu_history[:-1800]
        cutoff = time.time() - max(30, min(gpu_window, 3600))
        vm = psutil.virtual_memory()
        try:
            disk = psutil.disk_usage(str(project.repo_root))
        except OSError:
            disk = psutil.disk_usage("/")
        load = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0)
        return {
            "cpu_percent": psutil.cpu_percent(percpu=True, interval=0.25),
            "load": [round(x, 2) for x in load],
            "memory": {"percent": vm.percent, "used": vm.used, "total": vm.total},
            "disk": {"percent": disk.percent, "used": disk.used, "total": disk.total, "path": str(project.repo_root)},
            "gpu": gpu,
            "gpu_history": [p for p in gpu_history if p["t"] >= cutoff],
            "gpu_window": max(30, min(gpu_window, 3600)),
            "now": time.time(),
        }
