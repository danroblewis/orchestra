"""A discovered part's **key** (§3.1): what marks, ignores, suggestions, settling and new/removed
match by, since discovered ids are assigned by arrival order (``sd.discover.unique_id``).

- a stock's key is its series' name and the labels that say which thing it measures: the labels
  without ``NOT_IDENTITY`` (instrument, machine, source, project, instance) and without
  ``simulated``, so a renamed collector keeps the key and a real series takes over a
  placeholder's mark;
- a flow's key is its ends' keys and its counter's key (none for a net flow).

Parts the era carries from its prior (``sd.prior``) are not the era's own: ``own_keys`` leaves
them out. Each key counts once."""

from __future__ import annotations

from ..discover import NOT_IDENTITY
from ..prior import rests_on_prior
from ..series import series_key

LEFT_OUT = NOT_IDENTITY | {"simulated"}
OUTSIDE = "outside"


def ref_key(ref) -> str | None:
    if ref is None:
        return None
    return series_key(ref.name, {k: v for k, v in (ref.labels or {}).items() if k not in LEFT_OUT})


def stock_key(stock) -> str:
    return ref_key(stock.series) or f"stock:{stock.id}"


def flow_key(flow, keys_of_stocks: dict[str, str]) -> str:
    a = keys_of_stocks.get(flow.src, flow.src) if flow.src else OUTSIDE
    b = keys_of_stocks.get(flow.dst, flow.dst) if flow.dst else OUTSIDE
    counter = ref_key(flow.counter) or "+".join(sorted(filter(None, (ref_key(r) for r in flow.measured_by or []))))
    return f"{a} -> {b}" + (f" by {counter}" if counter else "")


def carried(model) -> tuple[set[str], set[str]]:
    """The ids of the stocks and flows the era carries from its prior."""
    return ({s.id for s in model.stocks if "prior" in (s.evidence or {})},
            {f.id for f in model.flows if "prior" in (f.evidence or {}) or rests_on_prior(f.current())})


class Keys:
    """A model's parts by key, and back: ``stocks`` and ``flows`` map key -> id (the first part
    with that key); ``own`` are the keys of the parts the era found itself."""

    def __init__(self, model):
        self.model = model
        self.stock_of_id = {s.id: stock_key(s) for s in model.stocks} if model else {}
        self.flow_of_id = {f.id: flow_key(f, self.stock_of_id) for f in model.flows} if model else {}
        self.stocks: dict[str, str] = {}
        self.flows: dict[str, str] = {}
        for sid, k in self.stock_of_id.items():
            self.stocks.setdefault(k, sid)
        for fid, k in self.flow_of_id.items():
            self.flows.setdefault(k, fid)
        cs, cf = carried(model) if model else (set(), set())
        self.own_stocks = {k for sid, k in self.stock_of_id.items() if sid not in cs}
        self.own_flows = {k for fid, k in self.flow_of_id.items() if fid not in cf}

    def of(self, part: str) -> dict[str, str]:
        return self.stocks if part == "stock" else self.flows

    def own(self, part: str) -> set[str]:
        return self.own_stocks if part == "stock" else self.own_flows

    def ends(self, key: str) -> tuple[str | None, str | None]:
        """A flow key's ends, as stock keys (None for outside)."""
        fid = self.flows.get(key)
        f = next((x for x in self.model.flows if x.id == fid), None) if self.model and fid else None
        if f is None:
            return None, None
        return (self.stock_of_id.get(f.src) if f.src else None, self.stock_of_id.get(f.dst) if f.dst else None)
