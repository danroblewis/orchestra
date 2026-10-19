"""A basic model run live: the ladder case's true model stepped by the ground-truth engine as the
clock ticks, so the page can watch it (and discovery) step by step.

The engine (sdlab/sdtruth.py, unchanged) makes a whole run at once from a seed; a run of n steps is
the first n steps of any longer run with the same seed (one random stream, the schedule and the
injections are fixed in time). So a live run is the engine's run with the case's seed, revealed one
step per tick: its first steps are exactly the case's recorded data in that variant (the ladder's
data.load uses the same model, seed and engine), and it goes on past the recorded length by asking
the engine for a longer run (twice as long each time it runs out, up to MAX_STEPS).

State lives in memory only (never in the case files): the step reached, the speed, whether it is
running. A run nobody has looked at for IDLE_SECONDS stops itself.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from . import basics
from .ladder import cases as casemod
from .sdtruth import Truth

MAX_STEPS = 200_000
IDLE_SECONDS = 180.0
FULL_SPEED_BATCH = 20          # steps per tick at full speed (then a short sleep, so the server stays responsive)


class BasicLiveRun:
    def __init__(self, model_id: str, variant: str | None):
        cid = basics.case_id(model_id)
        if cid is None:
            raise KeyError(model_id)
        self.model_id = model_id
        case = casemod.load(cid)
        self.variant = basics.variant_of(case, variant)
        model = casemod.truth_model(case, self.variant)
        self.seed = int(model["seed"])
        self.recorded_length = int(casemod.variant(case, self.variant)["steps"])
        with tempfile.TemporaryDirectory() as d:          # the engine reads its model from a file, once
            p = Path(d) / "truth.model.json"
            p.write_text(json.dumps(model))
            self.truth = Truth(p)
        self.lock = threading.Lock()
        self.data: dict | None = None
        self.horizon = 0
        self.t = 0
        self.running = False
        self.seconds_per_tick = 1.0
        self.stopped: dict | None = None
        self.seen = time.time()
        self.thread: threading.Thread | None = None

    # ---- the engine's run, long enough ----
    def _ensure(self, steps: int) -> None:
        if steps <= self.horizon:
            return
        h = min(max(self.recorded_length, 2 * self.horizon, steps), MAX_STEPS)
        self.data = self.truth.measured(self.seed, h)
        self.all_levels = self.truth.run(self.seed, h)["levels"]       # hidden stocks too: for comparing with the truth only
        self.horizon = h

    def data_until(self, steps: int) -> dict:
        """The run's first `steps` steps as the ladder's data (t, levels, all_levels, eras), for the scorer."""
        with self.lock:
            n = max(0, min(int(steps), self.t))
            d = self.data or {"t": [], "levels": {}, "eras": []}
            return {"t": d["t"][:n], "levels": {k: v[:n] for k, v in d["levels"].items()},
                    "all_levels": {k: v[:n] for k, v in (getattr(self, "all_levels", None) or {}).items()},
                    "eras": [e for e in d.get("eras") or [] if e["start"] <= max(n, 1)]}

    # ---- control ----
    def tick(self, n: int = 1) -> None:
        with self.lock:
            if self.t + n >= MAX_STEPS:
                n = MAX_STEPS - self.t
                self.running = False
                self.stopped = {"t": MAX_STEPS, "reason": f"a live run of a basic model stops at {MAX_STEPS} steps"}
            self._ensure(self.t + n)
            self.t += max(0, n)

    def start(self, seconds_per_tick: float | None = None) -> None:
        with self.lock:
            if seconds_per_tick is not None:
                self.seconds_per_tick = max(0.0, float(seconds_per_tick))
            if self.t >= MAX_STEPS:
                return
            self.running, self.stopped, self.seen = True, None, time.time()
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, name=f"basic-live-{self.model_id}", daemon=True)
                self.thread.start()

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def reset(self) -> None:
        with self.lock:
            self.running, self.t, self.stopped = False, 0, None

    def _loop(self) -> None:
        while True:
            with self.lock:
                if not self.running:
                    return
                if time.time() - self.seen > IDLE_SECONDS:      # nobody is watching: stop
                    self.running = False
                    return
                per = self.seconds_per_tick
            began = time.time()
            self.tick(FULL_SPEED_BATCH if per == 0 else 1)
            time.sleep(max(0.02, per - (time.time() - began)) if per else 0.02)

    # ---- what the page sees ----
    def snapshot(self, since: int = 0) -> dict:
        """The run so far in the shape of basics.snapshot (and runner.LiveRun.snapshot): the measured
        stocks' levels, every true flow's amount per step, the announced eras that have begun."""
        with self.lock:
            self.seen = time.time()
            t = self.t
            d = self.data if t else None
            k = max(0, min(int(since), t))
            series = {"t": list(range(k + 1, t + 1)), "levels": {}, "rates": {}, "load": {}}
            if d:
                series["levels"] = {s: col[k:t] for s, col in d["levels"].items()}
                series["rates"] = {f: col[k:t] for f, col in d["counters"].items()}
            eras = (d or {}).get("eras") or [{"start": 1, "label": "Start"}]
            out = {"running": self.running, "t": t, "seconds_per_tick": self.seconds_per_tick, "length": t, "variant": self.variant,
                   "live": True, "recorded_length": self.recorded_length, "series": series, "recent": [], "stopped": self.stopped, "errors": []}
        page = basics.model(self.model_id)
        out["eras"] = [{"n": i + 1, "start": e["start"], "label": e.get("label") or ("Start" if i == 0 else f"era {i + 1}"), "equations": [],
                        **({"model": page} if since == 0 else {})} for i, e in enumerate(eras) if i == 0 or e["start"] <= max(t, 1)]
        return out


class BasicLiveRuns:
    """The live runs of basic models, one per model and variant (each variant is its own run)."""

    def __init__(self):
        self.runs: dict[tuple[str, str], BasicLiveRun] = {}
        self.lock = threading.Lock()

    def get(self, model_id: str, variant: str | None) -> BasicLiveRun:
        v = basics.variant_of(basics.ladder.case(basics.case_id(model_id)), variant)
        with self.lock:
            r = self.runs.get((model_id, v))
            if r is None:
                r = self.runs[(model_id, v)] = BasicLiveRun(model_id, v)
            return r

    def running(self, model_id: str) -> BasicLiveRun | None:
        return next((r for (m, _), r in list(self.runs.items()) if m == model_id and r.running), None)

    def stop_all(self) -> None:
        for r in list(self.runs.values()):
            r.stop()


def compare(model_id: str, variant: str | None, flows: list[dict], data: dict) -> dict:
    """A found model against the case's truth on the data it was found from: the ladder scorer's
    equation parts (score.equations: each true number, the found one, whether it is right) and the
    repairs that would make it right (the strategy page's repairs module)."""
    from .ladder import score

    case = casemod.load(basics.case_id(model_id))
    v = basics.variant_of(case, variant)
    noise = casemod.variant(case, v)["noise"]
    eq = score.equations(case, noise, casemod.truth_model(case, v), flows, data)
    try:
        from .ladder.repairs import repairs
        rep = repairs(eq)
    except Exception:  # noqa: BLE001 - the parts alone are enough for the page
        rep = None
    return {"status": eq.get("status"), "parts": eq.get("parts") or [], "spurious": eq.get("spurious") or [],
            "negligible": eq.get("negligible") or [], "recall": eq.get("recall"), "precision": eq.get("precision"),
            "repairs": rep, "steps": len(data["t"])}
