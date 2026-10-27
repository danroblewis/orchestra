"""The system dynamics model (the factory): stocks, flows, equations, machines, eras.

Principles (docs/proposals/system-dynamics-core.md, docs/proposals/orchestra-kernel.md §2a):

- A **stock** is a measured quantity: it is bound to a series in the metrics store.
- A **flow** moves material between stocks (or from or to outside). It is bound to a cumulative
  counter series when one exists; its **equation** is observed (fitted or discovered), and every
  equation records its **origin**: ``fitted`` (with method, window and quality), ``discovered``,
  or ``declared`` (an assumption, labelled as one until it is fitted).
- A **machine** is a record of something outside Orchestra and outside the model (an agent, a
  program, a team, a device). It is attributed to flows as a hypothesis and observed through
  series. A machine never defines a flow's equation.
- An **era** is a stretch of time with one configuration; fits are per era.

The JSON form follows SD Lab's model format (MODEL.md) where the concepts coincide (stocks, flows
with from/to, machines) and adds what Orchestra needs (series bindings, equation origins, machine
records, eras)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SeriesRef:
    """A series a stock, flow or machine is bound to, and where it came from: ``source`` is
    ``own`` (the project's metrics store) or a ``[[sources]]`` name, with the final ``query`` that
    reads it there, its ``kind``, its ``origin`` (inferred from which family and view, rewritten by
    which script, or declared) and its measured ``resolution_s``. Versions saved before sources
    carry only the name and labels: their series are the own store's."""

    name: str
    labels: dict[str, str] = field(default_factory=dict)
    source: str | None = None
    query: str | None = None
    kind: str | None = None
    origin: list[str] | None = None
    resolution_s: float | None = None
    unit: str | None = None


@dataclass
class Equation:
    form: str                           # constant | proportional | linear (more forms as inference grows)
    params: dict[str, float]            # constant: {"c"}; proportional: {"k"}; linear: {"c", "k"}; per the model's time unit
    origin: str                         # fitted | discovered | declared
    method: str = ""                    # e.g. "poisson-mle" for fitted
    window: tuple[float, float] | None = None   # unix seconds the fit used
    era: str | None = None
    quality: dict[str, float] = field(default_factory=dict)   # se, loglik, dispersion, events, hours
    inputs: list[str] = field(default_factory=list)            # what the form reads: stock ids, or input:<name> for a measured input
    spec: dict[str, Any] = field(default_factory=dict)         # the full rate as SD Lab writes it (terms, effects, expr), when it found it
    sources: list[str] = field(default_factory=list)           # where the series it was fitted on came from (own, or a [[sources]] name)


@dataclass
class Stock:
    id: str
    name: str
    unit: str = "items"
    series: SeriesRef | None = None
    evidence: dict[str, Any] = field(default_factory=dict)    # how it was found, when discovered: fit of the balance, steps


@dataclass
class Flow:
    id: str
    name: str
    src: str | None                     # stock id, or None for outside
    dst: str | None
    counter: SeriesRef | None = None    # cumulative count of what moved
    equations: list[Equation] = field(default_factory=list)   # one per era once fitted
    measured_by: list[SeriesRef] = field(default_factory=list)  # every counter it sums, when several flows look like one from the levels
    evidence: dict[str, Any] = field(default_factory=dict)      # how its ends were chosen, when discovered: other stocks' claims, co-flows

    def current(self) -> Equation | None:
        return self.equations[-1] if self.equations else None


@dataclass
class Machine:
    id: str
    name: str
    kind: str                           # machine (discovered: the metrics do not say what it is) | agent | program | person | team | device | external
    description: str = ""
    attributed: list[str] = field(default_factory=list)       # flow ids: hypotheses, validated by fits across eras
    observed_by: list[SeriesRef] = field(default_factory=list)
    bootstrap: bool = False             # Orchestra's own host


@dataclass
class Era:
    id: str
    start: float
    label: str


@dataclass
class Model:
    id: str
    name: str
    description: str = ""
    time_unit: str = "hour"
    stocks: list[Stock] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=list)
    eras: list[Era] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)   # when discovered: window, step, what was left out and why

    def stock(self, sid: str) -> Stock:
        return next(s for s in self.stocks if s.id == sid)

    def flow(self, fid: str) -> Flow:
        return next(f for f in self.flows if f.id == fid)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for f in d["flows"]:                  # SD Lab's names for the ends
            f["from"], f["to"] = f.pop("src"), f.pop("dst")
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Model:
        def ref(r):
            return SeriesRef(**r) if r else None
        return cls(
            id=d["id"], name=d["name"], description=d.get("description", ""), time_unit=d.get("time_unit", "hour"),
            stocks=[Stock(s["id"], s["name"], s.get("unit", "items"), ref(s.get("series")), dict(s.get("evidence") or {}))
                    for s in d.get("stocks", [])],
            flows=[Flow(f["id"], f["name"], f.get("from"), f.get("to"), ref(f.get("counter")),
                        [Equation(**{**e, "window": tuple(e["window"]) if e.get("window") else None,
                                     "inputs": list(e.get("inputs") or []), "spec": dict(e.get("spec") or {}),
                                     "sources": list(e.get("sources") or [])})
                         for e in f.get("equations", [])], [SeriesRef(**r) for r in f.get("measured_by") or []],
                        dict(f.get("evidence") or {}))
                   for f in d.get("flows", [])],
            machines=[Machine(m["id"], m["name"], m["kind"], m.get("description", ""), list(m.get("attributed", [])),
                              [SeriesRef(**r) for r in m.get("observed_by", [])], bool(m.get("bootstrap", False)))
                      for m in d.get("machines", [])],      # past versions carry "engagement": [] too, which nothing fills: ignored
            eras=[Era(**e) for e in d.get("eras", [])],
            discovery=dict(d.get("discovery") or {}),
        )

    def check(self) -> list[str]:
        """Structural problems: ids used twice, flows naming unknown stocks, machines attributed to
        unknown flows. Everything keyed by id (the graph, the machines' lists, the simulator) needs
        each id once."""
        ids = {s.id for s in self.stocks}
        fids = {f.id for f in self.flows}
        errs = [f"stock id {sid} is used {n} times" for sid, n in Counter(s.id for s in self.stocks).items() if n > 1]
        errs += [f"flow id {fid} is used {n} times" for fid, n in Counter(f.id for f in self.flows).items() if n > 1]
        errs += [f"flow {f.id}: unknown stock {end}" for f in self.flows for end in (f.src, f.dst) if end and end not in ids]
        errs += [f"machine {m.id}: attributed to unknown flow {a}" for m in self.machines for a in m.attributed if a not in fids]
        errs += [f"flow {f.id} connects nothing" for f in self.flows if not f.src and not f.dst]
        if sum(m.bootstrap for m in self.machines) > 1:
            errs.append("more than one bootstrap machine")
        return errs
