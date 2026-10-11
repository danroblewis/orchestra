"""Staging: one long-lived instance of the most recent build that passed the gate.
SPEC.md section 7.5. Supervised by the loop; redeployed by the gate on every landing."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import Project
from .events import Events
from .model import now
from .store import LocalStore


def _probe(url: str, timeout: float = 4) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:
        return False


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Staging:
    def __init__(self, project: Project, store: LocalStore, events: Events):
        self.project = project
        self.store = store
        self.events = events
        self.cfg = project.config
        self.log_path = project.staging_dir / "staging.log"

    # -- state -----------------------------------------------------------------

    def state(self) -> dict:
        s = self.store.runtime().get("staging") or {}
        s.setdefault("status", "stopped")
        s["alive"] = _pid_alive(s.get("pid"))
        s["configured"] = self.cfg.staging_configured
        return s

    def _set(self, **fields) -> dict:
        def fn(d):
            st = d.setdefault("staging", {})
            st.update(fields)
            return dict(st)
        return self.store._mutate_runtime(fn)

    def _log(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{now()}] [orchestra] {line}\n")

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.cfg.staging_port}"

    def public_url(self) -> str | None:
        return f"https://{self.cfg.tunnel_hostname}" if self.cfg.tunnel_hostname else None

    # -- process control -------------------------------------------------------

    def stop(self) -> None:
        st = self.state()
        pid = st.get("pid")
        if _pid_alive(pid):
            self._log(f"stopping build {st.get('current_build_id')} (pid {pid})")
            if self.cfg.staging_stop:
                subprocess.run(self.cfg.staging_stop.format(port=self.cfg.staging_port, pid=pid), shell=True,
                               cwd=str(self.project.repo_root), capture_output=True, timeout=60)
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                pass
            for _ in range(20):
                if not _pid_alive(pid):
                    break
                time.sleep(0.5)
            if _pid_alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except OSError:
                    pass
        self._set(pid=None, status="stopped")

    def _start(self, build: dict) -> bool:
        port = self.cfg.staging_port
        cmd = self.cfg.staging_start.format(artifact=build.get("artifact_path", ""), port=port)
        self._log(f"starting build {build['id']} ({build.get('commit', '')[:10]}): {cmd}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        out = self.log_path.open("a", encoding="utf-8")
        proc = subprocess.Popen(cmd, shell=True, cwd=str(self.project.repo_root), stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
        self._set(pid=proc.pid, port=port, status="starting", current_build_id=build["id"],
                  local_url=self.local_url(), public_url=self.public_url(), deployed_at=now())
        url = self.local_url() + self.cfg.staging_health
        deadline = time.time() + self.cfg.staging_health_timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                self._log(f"process exited with {proc.returncode} before becoming healthy")
                self._set(status="failed", pid=None)
                return False
            if _probe(url):
                self._log(f"healthy at {url}")
                self._set(status="running", last_health_at=now())
                return True
            time.sleep(1)
        self._log(f"health probe {url} did not pass within {self.cfg.staging_health_timeout}s")
        self._set(status="failed")
        return False

    # -- tunnel ----------------------------------------------------------------

    def ensure_tunnel(self) -> bool:
        """Run the named cloudflared tunnel against the staging port and probe it."""
        name, host = self.cfg.tunnel_name, self.cfg.tunnel_hostname
        if not (name and host):
            return True
        public = f"https://{host}{self.cfg.staging_health}"
        if _probe(public):
            return True
        if not shutil.which("cloudflared"):
            self._log("cloudflared not on PATH; skipping tunnel")
            return False
        creds = Path("~/.cloudflared").expanduser()
        cred_file = next(iter(sorted(creds.glob("*.json"))), None)
        cfg = self.project.staging_dir / "tunnel.yml"
        cfg.write_text(f"tunnel: {name}\n" + (f"credentials-file: {cred_file}\n" if cred_file else "") +
                       f"ingress:\n  - hostname: {host}\n    service: {self.local_url()}\n  - service: http_status:404\n")
        st = self.state()
        if not _pid_alive(st.get("tunnel_pid")):
            self._log(f"starting cloudflared tunnel {name} -> {host}")
            out = (self.project.staging_dir / "tunnel.log").open("a", encoding="utf-8")
            proc = subprocess.Popen(["cloudflared", "--config", str(cfg), "tunnel", "run", name], stdout=out,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            self._set(tunnel_pid=proc.pid)
        deadline = time.time() + 45
        while time.time() < deadline:
            if _probe(public):
                self._log(f"tunnel healthy at {public}")
                return True
            time.sleep(3)
        self._log(f"tunnel probe {public} failed")
        return False

    # -- public ----------------------------------------------------------------

    def deploy(self, build: dict) -> bool:
        """Promote a build: stop the previous, start this one, probe health and tunnel.
        On failure restart the previous build and wake the Pipeline Manager."""
        if not self.cfg.staging_configured:
            return False
        prev_id = self.state().get("current_build_id")
        self.stop()
        ok = self._start(build) and self.ensure_tunnel()
        if ok:
            self._set(previous_build_id=prev_id)
            self.events.emit("staging_deployed", build=build["id"], commit=build.get("commit"),
                             local_url=self.local_url(), public_url=self.public_url())
            return True
        self.events.emit("staging_failed", build=build["id"])
        self.store.add_wakeup("pipeline_manager",
                              f"staging deploy of build {build['id']} failed (see staging log); rolled back")
        prev = self.store.runtime().get("builds", {}).get(prev_id or "")
        if prev:
            self.stop()
            self._log(f"rolling back to build {prev_id}")
            self._start(prev)
        return False

    def ensure_running(self) -> None:
        """Called every tick: restart a staging process that died."""
        if not self.cfg.staging_configured:
            return
        st = self.state()
        if st.get("status") in ("running", "starting") and not st["alive"]:
            build = self.store.runtime().get("builds", {}).get(st.get("current_build_id") or "")
            if build:
                self._log("staging process died; restarting")
                self._start(build)
                self.events.emit("staging_restarted", build=build["id"])
        elif st.get("status") == "running" and st["alive"]:
            if _probe(self.local_url() + self.cfg.staging_health):
                self._set(last_health_at=now())

    def restart(self) -> bool:
        build = self.store.runtime().get("builds", {}).get(self.state().get("current_build_id") or "")
        if not build:
            return False
        self.stop()
        return self._start(build)

    def logs(self, n: int = 20000) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")[-n:] if self.log_path.exists() else ""


def record_build(store: LocalStore, build: dict) -> None:
    store._mutate_runtime(lambda d: d.setdefault("builds", {}).__setitem__(build["id"], build))
