"""Stocks the operator declared: a ``[[series]]`` level and the counters declared as its inflows and
outflows (``stock = "<name>"`` with ``role = "level" | "inflow" | "outflow"``), carried in the
reading's provenance (``orchestra.sources``).

A declaration is a hypothesis, tried first: before any search, the level is balanced by exactly
the declared counters, ``Δlevel = Σ inflows − Σ outflows``. When that fits, it is the level's
balance and is judged by the same evidence as any other (``sd.identify``, ``sd.accept``): enough
units, a fit that holds on each half of the window, the level reproduced over time, and the shift
null. Nothing is chosen, so nothing is dropped by the halves' vote; the declared counters are
only tested. When it does not fit, the level is searched like any other, and the reason it is left
out (if it is) says what the declared balance fitted. A declared stock records that its balance was
declared (AGENTS.md rule 6: its origin), never that it was discovered; its flows are still fitted.

The level and its flows may come from different stores at different resolutions (a queue read
every 15 s from one, the emails sent counted once a minute in another, a minute late): the balance
is then judged on the stretches between the slowest counter's writes (``sd.discover.coarse``), and
only where every one of its series has data."""

from __future__ import annotations

from dataclasses import dataclass, field

SIGNS = {"inflow": 1, "outflow": -1}


@dataclass
class Pin:
    """One declared stock: its name, its level's key, and its declared flows (series, sign)."""

    name: str
    level: str
    terms: list = field(default_factory=list)
    missing: list[str] = field(default_factory=list)     # declared flows the reading does not hold, or that are not counters

    def record(self) -> dict:
        return {"stock": self.name, "origin": "declared",
                "balance": [{"series": c.key, "sign": sg} for c, sg in self.terms],
                **({"missing": self.missing} if self.missing else {})}


def declared(series: list, provenance: dict) -> tuple[dict[str, Pin], dict[str, str]]:
    """The declared stocks by their level's key, and why any declaration could not be used (by
    series key): a stock with no level or more than one, or no flow the reading holds."""
    by_stock: dict[str, dict[str, list]] = {}
    for s in series:
        st = (provenance.get(s.key) or {}).get("stock")
        if isinstance(st, dict) and st.get("name") and st.get("role"):
            by_stock.setdefault(st["name"], {}).setdefault(st["role"], []).append(s)
    pins, problems = {}, {}
    for name, roles in sorted(by_stock.items()):
        levels = roles.get("level", [])
        flows = [(s, SIGNS[r]) for r in ("inflow", "outflow") for s in roles.get(r, [])]
        if len(levels) != 1:
            for s, _ in flows:
                problems[s.key] = (f"declared a flow of stock {name}, which has {'no level' if not levels else f'{len(levels)} levels'} "
                                   "declared: a stock's balance needs exactly one")
            for s in levels:
                problems[s.key] = f"declared the level of stock {name} with {len(levels)} levels: a stock's balance needs exactly one"
            continue
        pin = Pin(name, levels[0].key)
        for s, sign in flows:
            if s.counter:
                pin.terms.append((s, sign))
            else:
                pin.missing.append(s.key)
        if pin.terms:
            pins[pin.level] = pin
        else:
            problems[pin.level] = f"declared the level of stock {name}, with no counter declared as its inflow or outflow"
    return pins, problems
