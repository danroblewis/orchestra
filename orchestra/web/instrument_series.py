"""An instrument's series as the Instruments page lists them (its drawer): every series labelled
``instrument=<name>`` (provenance, AGENTS.md rule 7) written within the window, with its latest
value and when it was written. Read from the metrics store, never from the instrument, which is
not run for the page. Each series a place of its instrument's views spells carries the ``title`` a
stock or a flow of it gets (``sd.titles``), so it reads the same on the Dynamics and Instruments pages."""

from __future__ import annotations

WINDOW_S = 3600.0          # a series not written for an hour is not listed: the instrument no longer prints it
LIMIT = 500                # the drawer lists at most this many; ``more`` says how many were left out
HIDDEN = ("instrument", "project")    # every series of one instrument and project carries them: said once


def instrument_series(metrics, name: str, now: float, window_s: float = WINDOW_S, views: tuple = ()) -> dict:
    """``{"ok", "series": [{name, labels, value, at, title?}], "more"}``, by name then labels.
    ``views``: the instrument's (``collect.views``), which name its places."""
    if metrics is None:
        return {"ok": False, "error": "the metrics store could not be opened"}
    try:
        got = metrics.recent("", {"instrument": name}, since=now - window_s, keep=1)
    except Exception as e:  # noqa: BLE001 - the drawer says why and shows the log
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    titles = _titles(got, name, views)
    rows = sorted(({"name": n, "labels": {k: v for k, v in labels.items() if k not in HIDDEN},
                    "value": pts[-1][1], "at": pts[-1][0], **({"title": t} if (t := titles.get(i)) else {})}
                   for i, (n, labels, pts) in enumerate(got) if pts),
                  key=lambda r: (r["name"], sorted(r["labels"].items())))
    return {"ok": True, "series": rows[:LIMIT], "more": max(0, len(rows) - LIMIT), "window_s": window_s}


def _titles(got: list, name: str, views: tuple) -> dict[int, str]:
    """Each series' title by its place in ``got``, where its instrument's places spell one."""
    if not views:
        return {}
    from ..collect.views import provenance
    from ..sd.series import series_key
    from ..sd.titles import Places

    key = lambda n, lab: series_key(n, {k: v for k, v in lab.items() if k != "project"})
    prov = provenance(got, {name: views}, key)
    places = Places([(n, lab, key(n, lab)) for n, lab, _ in got], prov)
    out = {}
    for i, (n, lab, _) in enumerate(got):
        k = key(n, lab)
        if t := (places.move(lab, k) if (prov.get(k) or {}).get("view") == "moves" else places.level(lab, k, n)):
            out[i] = t
    return out
