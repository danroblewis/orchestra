"""Each stock's behaviour trust, measured at discovery and saved with the model: how far the model,
run forward from part-way through its own window, misses the measured level
(``sd.experiments.heldout``). It sits beside the stock's identity trust in its evidence
(``trust["behaviour"]``) and never changes it: a stock can be certain to exist, with a balance
that holds to the event, and still be projected badly by the equations of its flows. Forward runs
widen their band by it (``sd.experiments.forward``).

Read from the same readings discovery read (``dump``), on discovery's grid, so it costs a few
replays and no query. A model whose replay cannot run (an equation that does not compile) gets no
record, and says why in ``model.discovery["behaviour"]``."""

from __future__ import annotations

from .experiments.heldout import FRACTIONS, measure
from .experiments.history import read_window
from .experiments.language import EquationError
from .model import Model
from .series import series_key


def attach(model: Model, dump, start: float, end: float, step: float) -> None:
    """Add ``trust["behaviour"]`` to each measured stock the held-out runs could judge."""
    pts = {}
    for name, labels, points in dump:
        pts[series_key(name, labels)] = sorted(points)

    def raw(ref, a, b):
        return [(t, v) for t, v in pts.get(series_key(ref.name, ref.labels)) or [] if a <= t <= b]

    since = max(start, float((model.discovery or {}).get("fit_start") or start))
    try:
        history = read_window(model, raw, start, end, step, step)
        recs = measure(model, history, since, end, step)
    except (EquationError, ValueError, ArithmeticError, KeyError) as e:     # a replay that cannot run: no behaviour, and why
        model.discovery["behaviour"] = {"error": f"{type(e).__name__}: {e}"}
        return
    for st in model.stocks:
        if st.id in recs and isinstance(st.evidence.get("trust"), dict):
            st.evidence["trust"]["behaviour"] = recs[st.id]
    model.discovery["behaviour"] = {"from": since, "fractions": [round(f, 4) for f in FRACTIONS], "stocks": len(recs)}
