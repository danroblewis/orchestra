"""Core page: the external stores (``[[sources]]``), Orchestra's adaptors to other time-series
stores, which the owner counts as part of the core (2026-11-03).

This reads them only through ``orchestra.sources`` (AGENTS.md rules 5 and 8), imported when first
asked rather than with this module, so a broken ``orchestra.sources`` shows on this section instead
of taking the Core page down. The section's rows come from files (``sources.stores``); its queries
and label lookups are bounded and logged by ``sources.asking``. Every call runs in this module's
own workers under a time limit, never Core's probes', so a slow or unreachable store shows as an
error on its row, and the host, bus and metrics cards stand."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

STATUS_TIMEOUT = 4.0          # the rows: files only
READ_TIMEOUT = 9.0            # a query or a lookup: the sources' own deadline (asking.DEADLINE_S) and a margin


class Stores:
    def __init__(self, core):
        self.core = core                    # CoreProbe: project, and its log
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="core-stores")

    def _guard(self, timeout: float, fn, *args, **kw) -> dict:
        try:
            return self._pool.submit(fn, *args, **kw).result(timeout=timeout)
        except FutureTimeout:
            return {"ok": False, "error": f"timed out after {timeout:g} s"}
        except Exception as e:  # noqa: BLE001 - shown on the section, the rest of the page stands
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def status(self) -> dict:
        def go():
            from ..sources import stores
            return stores.status(self.core.project)
        out = self._guard(STATUS_TIMEOUT, go)
        if not out.get("ok"):
            out["error"] = f"the external stores cannot be read: {out.get('error')}"
        return out

    def _spec(self, name: str):
        from ..sources.spec import for_project
        spec = next((s for s in for_project(self.core.project).sources if s.name == name), None)
        if spec is None:
            raise LookupError(f"no usable [[sources]] entry named {name!r}")
        return spec

    def _read(self, name: str, what: str, call) -> dict:
        def go():
            from ..sources import asking
            return call(asking, self._spec(name), Path(self.core.project.state_dir))
        out = self._guard(READ_TIMEOUT, go)
        self.core._note(f"store {name}", f"{what}: " + ("ok" if out.get("ok") else str(out.get("error"))[:300]),
                        "info" if out.get("ok") or out.get("refused") else "error")
        return out

    def query(self, name: str, q: str, *, instant: bool, minutes: float | None, limit: int | None) -> dict:
        return self._read(name, f"{'instant' if instant else 'range'} query {q[:120]!r}",
                          lambda a, spec, state: a.query(state, spec, q, instant=instant, minutes=minutes, limit_n=limit))

    def labels(self, name: str, selector: str, minutes: float | None, limit: int | None) -> dict:
        return self._read(name, f"label names of {selector[:120]!r}",
                          lambda a, spec, state: a.labels(state, spec, selector, minutes=minutes, limit_n=limit))

    def values(self, name: str, label: str, selector: str, minutes: float | None, limit: int | None) -> dict:
        return self._read(name, f"values of {label} in {selector[:120]!r}",
                          lambda a, spec, state: a.values(state, spec, label, selector, minutes=minutes, limit_n=limit))
