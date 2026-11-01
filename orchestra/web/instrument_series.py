"""An instrument's series as the Instruments page lists them (its drawer): every series labelled
``instrument=<name>`` (provenance, AGENTS.md rule 7) written within the window, with its latest
value and when it was written. Read from the metrics store, never from the instrument, which is
not run for the page; the page names each series as the Dynamics page names a stock or a flow
(sd-graph.js), so a pile reads "write (held) · delivery sail" in both places."""

from __future__ import annotations

WINDOW_S = 3600.0          # a series not written for an hour is not listed: the instrument no longer prints it
LIMIT = 500                # the drawer lists at most this many; ``more`` says how many were left out
HIDDEN = ("instrument", "project")    # every series of one instrument and project carries them: said once


def instrument_series(metrics, name: str, now: float, window_s: float = WINDOW_S) -> dict:
    """``{"ok", "series": [{name, labels, value, at}], "more"}``, by name then labels."""
    if metrics is None:
        return {"ok": False, "error": "the metrics store could not be opened"}
    try:
        got = metrics.recent("", {"instrument": name}, since=now - window_s, keep=1)
    except Exception as e:  # noqa: BLE001 - the drawer says why and shows the log
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    rows = sorted(({"name": n, "labels": {k: v for k, v in labels.items() if k not in HIDDEN},
                    "value": pts[-1][1], "at": pts[-1][0]} for n, labels, pts in got if pts),
                  key=lambda r: (r["name"], sorted(r["labels"].items())))
    return {"ok": True, "series": rows[:LIMIT], "more": max(0, len(rows) - LIMIT), "window_s": window_s}
