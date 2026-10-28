"""How persistently each stock is found: the share of recent discoveries that found it with the same flows.

A true stock and its flows are found again window after window; a coincidence of one window comes
and goes as the window moves (the metrics lab's review r1: moving a window five minutes turned 16
stocks into 22). The host rediscovers every few minutes, so each discovery's stocks and the
counters of their balances (or a net flow's driver) are remembered, the last ``KEEP`` of them, in
the model store's ``recent_stocks`` record, and each new stock's trust records the share of those
that found it the same way (``sd.stocktrust.with_persistence``). It is a component of the trust
score once ``ENOUGH`` discoveries are remembered. Successive windows overlap, so this measures
stability as the window slides, not independent confirmation."""

from __future__ import annotations

from .model import Model
from .stocktrust import with_persistence

RECORD = "recent_stocks"
KEEP = 12
ENOUGH = 3


def signature(stock) -> str:
    """What a stock was found as: its balance's counters with their signs, or its net flow's form."""
    ev = stock.evidence or {}
    if nf := ev.get("net_flow"):
        return f"net:{nf.get('form')}:{nf.get('driver')}"
    terms = sorted(f"{'+' if b['sign'] > 0 else '-'}{b['series']}" for b in ev.get("balance") or [])
    return ("hidden:" if ev.get("hidden") else "") + "|".join(terms)


def apply(store, model: Model, at: float) -> None:
    """Record each stock's persistence in its trust, then remember this discovery."""
    rec = store.read_record(RECORD) or {}
    runs = [r for r in rec.get("runs") or [] if r.get("at", 0) < at][-KEEP:]
    for st in model.stocks:
        if "trust" not in (st.evidence or {}):
            continue
        sig = signature(st)
        seen = sum(1 for r in runs if r.get("stocks", {}).get(st.id) == sig)
        st.evidence["trust"] = with_persistence(st.evidence["trust"], seen, len(runs), ENOUGH)
    runs.append({"at": at, "stocks": {st.id: signature(st) for st in model.stocks}})
    store.write_record(RECORD, {"runs": runs[-KEEP:]})
