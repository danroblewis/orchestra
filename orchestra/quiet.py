"""A machine gone quiet on the bus (the flow-keeping signal of
docs/proposals/agent-first-machines.md §5.1): the host says so with ``orchestra.machine.quiet``,
published as itself (``orchestra-host``), its ``subject`` the machine and its ``data``
``{machine, instance, last_seen, usual_gap, quiet_for, mode}``.

Quiet means what the Machines page means by not active (``cadence.py``): an instance that had a
cadence of its own (at least ``MIN_BEATS`` beats on the bus) and has now been silent longer than
``active_within`` its cadence. Observed only (AGENTS.md rule 2): beats are its events, never what
it says of itself; the one thing read from its announcement is its mode, so an instance that says
it is engaged ad hoc (a worker started per ticket) is never called quiet, its silence being its
nature. Orchestra's host itself and the instruments' old announcements are left out.

Announced once per silence: an instance heard again may be announced again when it next falls
silent. Instances already quiet when the host starts (it replays the bus first, ``settle``) are not
announced: their silence began before this host watched."""

from __future__ import annotations

import time
from collections import deque

from .cadence import BEATS, BURST_S, active_within, gaps
from .events import HOST, event_time, for_an_instrument, machine_and_instance

QUIET = "orchestra.machine.quiet"
ANNOUNCE = ("orchestra.machine.started", "orchestra.machine.subscribed")
MIN_BEATS = 3                     # two gaps: a cadence of its own, not one interval
AD_HOC = ("ad hoc", "ad_hoc", "ad-hoc")


class QuietWatch:
    def __init__(self):
        self.seen: dict[tuple[str, str], dict] = {}     # (machine, instance or "") -> last, beats, mode
        self.quiet: set[tuple[str, str]] = set()

    def observe(self, ev: dict, now: float | None = None) -> None:
        machine, instance = machine_and_instance(ev.get("source"))
        if not machine or machine == HOST or for_an_instrument(ev):
            return
        now = now if now is not None else time.time()
        seen = min(event_time(ev) or now, now)
        key = (machine, instance or "")
        rec = self.seen.get(key)
        if rec is None:
            rec = self.seen[key] = {"last": seen, "beats": deque([seen], maxlen=BEATS), "mode": None}
        else:
            if seen - rec["last"] > BURST_S and seen > rec["beats"][-1]:
                rec["beats"].append(seen)
            rec["last"] = max(rec["last"], seen)
        if ev.get("type") in ANNOUNCE:
            mode = (ev.get("data") or {}).get("mode")
            if isinstance(mode, str) and mode:
                rec["mode"] = mode
        self.quiet.discard(key)

    def _silent(self, rec: dict, now: float) -> float | None:
        """The instance's cadence when it is silent past it now; None otherwise."""
        if len(rec["beats"]) < MIN_BEATS or (rec["mode"] or "").lower() in AD_HOC:
            return None
        cadence = gaps(rec["beats"])
        return cadence if cadence and now - rec["last"] > active_within(cadence) else None

    def settle(self, now: float | None = None) -> None:
        """After the replay at start: whatever is quiet already was quiet before this host watched."""
        now = now if now is not None else time.time()
        self.quiet |= {k for k, rec in self.seen.items() if self._silent(rec, now) is not None}

    def check(self, now: float | None = None) -> list[dict]:
        """The instances that fell silent since the last check: each one's event data."""
        now = now if now is not None else time.time()
        out = []
        for key, rec in sorted(self.seen.items()):
            if key in self.quiet:
                continue
            cadence = self._silent(rec, now)
            if cadence is None:
                continue
            self.quiet.add(key)
            machine, instance = key
            out.append({"machine": machine, "instance": f"{machine}/{instance}" if instance else None,
                        "last_seen": rec["last"], "usual_gap": round(cadence, 3), "quiet_for": round(now - rec["last"], 3),
                        "mode": rec["mode"]})
        return out
