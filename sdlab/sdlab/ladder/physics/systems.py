"""The physical systems behind the physics cases: continuous-time ODEs that are not stock-and-flow
models, each with its drivers, the structure the physics says discovery should find, and the best
model SD Lab's forms can write for it (the reference).

A system is a `System`:

    stocks       the measured stocks [{id, name, unit, final?}], in order
    inputs       the measured inputs it is driven by (names; their values are data, as a page gives them)
    params       default parameters (a case may override any, or give a range [lo, hi] drawn from its seed)
    initial      (rng, p) -> the state at time 0 (one number per stock, in the stocks' order)
    drive        (rng_for, p, steps) -> Drive: the inputs as functions of continuous time and the
                 announced injections; drawn in order, so a longer run continues a shorter one
    rhs          (t, x, p, drive, mode) -> dx/dt
    levels       x -> the measured levels (the state, or the state with an offset that keeps it positive)
    hybrid       for a switching system: (mode0, guards(p, drive, mode) -> event functions, switch(mode, which))
    couplings    the physics' structure: [(receiver, source, sign, shape)], source a stock or an input;
                 sign "+", "-" or "±" (changes over the run); shape linear | sqrt | product | switch
    reference    (p) -> (flows(theta), theta0, bounds, how): SD Lab flows with free numbers, one per
                 physical term, started from the physics (the oracle knows it) and fitted by reference.py
    differs      one sentence: where the best SD model differs from the physics (None when it is exact)

Time is in steps (one recorded step = one unit of time).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


# ---- drivers ----

@dataclass
class Drive:
    """A run's drivers: each input a function of continuous time (vectorised), the times where any
    of them jumps (integer steps; the solver restarts there), and the announced injections."""

    funcs: dict[str, Callable] = field(default_factory=dict)
    jumps: list[float] = field(default_factory=list)
    injections: list[dict] = field(default_factory=list)       # {t, stock, amount}: added at the start of step t

    def value(self, name: str, t):
        return self.funcs[name](t)


def piecewise(rng: np.random.Generator, steps: int, lo: float, hi: float, hold: tuple[int, int], first: float | None = None):
    """A level that holds for a random whole number of steps (hold = [min, max]) and then jumps to a
    new random level in [lo, hi]; drawn in order, so a longer run continues a shorter one. Returns
    (function of t, jump times)."""
    starts, values = [0.0], [float(first) if first is not None else float(rng.uniform(lo, hi))]
    while starts[-1] < steps + 1:
        starts.append(starts[-1] + float(rng.integers(hold[0], hold[1] + 1)))
        values.append(float(rng.uniform(lo, hi)))
    s, v = np.array(starts), np.array(values)

    def f(t):
        return v[np.clip(np.searchsorted(s, np.asarray(t, dtype=float), side="right") - 1, 0, len(v) - 1)]

    return f, [float(x) for x in s[1:]]


def sine(base: float, amplitude: float, period: float, phase: float):
    def f(t):
        return base + amplitude * np.sin(2 * math.pi * (np.asarray(t, dtype=float) - phase) / period)
    return f


def added(*fs):
    def f(t):
        return sum(g(t) for g in fs)
    return f


# ---- the system description ----

@dataclass
class System:
    name: str
    title: str
    stocks: list[dict]
    inputs: list[str]
    params: dict[str, float]
    initial: Callable
    drive: Callable
    rhs: Callable
    couplings: list[tuple[str, str, str, str]]
    reference: Callable
    levels: Callable | None = None                 # state -> measured levels (default: the state itself)
    hybrid: tuple | None = None                    # (mode0(x, p, drive), guards(p, drive, mode), switch(mode, which))
    differs: str | None = None
    about: str = ""

    @property
    def ids(self) -> list[str]:
        return [s["id"] for s in self.stocks]

    def measured(self, x: np.ndarray) -> np.ndarray:
        """The measured levels of states x (stocks x times)."""
        return self.levels(x) if self.levels else x


def _prop(stock: str, k: float) -> dict:
    return {"form": "proportional", "stock": stock, "k": float(k)}


def _linear(c: float, terms: list[tuple[str, float]]) -> dict:
    return {"form": "linear", "c": float(c), "terms": [{"stock": s, "k": float(k)} for s, k in terms]}


def _flow(fid: str, a: str | None, b: str | None, rate: dict, **extra) -> dict:
    return {"id": fid, "from": a, "to": b, "rate": rate, **extra}


def _product(stock: str) -> list[dict]:
    """A linear effect that multiplies a rate by the stock's level (clamp(level / 1, 0, 1e12)): the
    product of two levels, exactly, in SD Lab's effect form."""
    return [{"stock": stock, "shape": "linear", "normal": 1.0, "min": 0.0, "max": 1e12}]


# ---- 1. a draining tank (Torricelli: outflow ~ sqrt(level)) ----

def _tank_drive(rng_for, p, steps):
    pump, jumps = piecewise(rng_for("pump"), steps, p["q_lo"], p["q_hi"], (30, 90))
    return Drive({"pump": pump}, jumps)


def _tank_ref(p):
    hbar = (0.5 * (p["q_lo"] + p["q_hi"]) / p["k"]) ** 2

    def flows(th):
        return [_flow("in", None, "H", _prop("pump", th[0]), input="pump"),
                _flow("h_out", "H", None, _linear(th[1], [("H", th[2])]))]
    k = p["k"] / (2 * math.sqrt(hbar))                  # the tangent of k sqrt(H) at the mean level
    return flows, [1.0, p["k"] * math.sqrt(hbar) / 2, k], [(0, -np.inf, 0), (np.inf,) * 3], \
        "the pump read as an inflow k x pump, the sqrt(H) outflow as a straight line c + k x H (floored at 0)"


TANK = System(
    name="draining-tank", title="Draining tank",
    about="A tank fed by a pump; water leaves through a hole at the bottom at a rate k sqrt(H) (Torricelli).",
    stocks=[{"id": "H", "name": "Water level", "unit": "cm"}], inputs=["pump"],
    params={"k": 0.5, "q_lo": 1.0, "q_hi": 3.0},
    initial=lambda rng, p: np.array([rng.uniform(2.0, 40.0)]),
    drive=_tank_drive,
    rhs=lambda t, x, p, d, m: np.array([d.value("pump", t) - p["k"] * math.sqrt(max(x[0], 0.0))]),
    couplings=[("H", "H", "-", "sqrt"), ("H", "pump", "+", "linear")],
    reference=_tank_ref,
    differs="The outflow is k sqrt(H); SD Lab's forms write it as a straight line c + k x H, right near the levels the run visits and wrong far from them (a lookup-table effect could bend it, at the price of its points).",
)


# ---- 2. two coupled tanks (the upper drains into the lower, both through holes) ----

def _tanks_ref(p):
    h1 = (0.5 * (p["q_lo"] + p["q_hi"]) / p["k1"]) ** 2
    h2 = (0.5 * (p["q_lo"] + p["q_hi"]) / p["k2"]) ** 2

    def flows(th):
        return [_flow("in", None, "H1", _prop("pump", th[0]), input="pump"),
                _flow("h1_h2", "H1", "H2", _linear(th[1], [("H1", th[2])])),
                _flow("h2_out", "H2", None, _linear(th[3], [("H2", th[4])]))]
    return flows, [1.0, p["k1"] * math.sqrt(h1) / 2, p["k1"] / (2 * math.sqrt(h1)), p["k2"] * math.sqrt(h2) / 2, p["k2"] / (2 * math.sqrt(h2))], \
        [(0, -np.inf, 0, -np.inf, 0), (np.inf,) * 5], "the pump as k x pump into H1, each sqrt flow as a straight line c + k x level (floored at 0)"


TANKS = System(
    name="coupled-tanks", title="Two coupled tanks",
    about="A pump fills the upper tank; it drains into the lower one at k1 sqrt(H1), which drains out at k2 sqrt(H2).",
    stocks=[{"id": "H1", "name": "Upper tank", "unit": "cm"}, {"id": "H2", "name": "Lower tank", "unit": "cm"}], inputs=["pump"],
    params={"k1": 0.5, "k2": 0.4, "q_lo": 1.0, "q_hi": 3.0},
    initial=lambda rng, p: np.array([rng.uniform(2.0, 40.0), rng.uniform(2.0, 60.0)]),
    drive=_tank_drive,
    rhs=lambda t, x, p, d, m: np.array([d.value("pump", t) - p["k1"] * math.sqrt(max(x[0], 0.0)),
                                        p["k1"] * math.sqrt(max(x[0], 0.0)) - p["k2"] * math.sqrt(max(x[1], 0.0))]),
    couplings=[("H1", "H1", "-", "sqrt"), ("H1", "pump", "+", "linear"), ("H2", "H1", "+", "sqrt"), ("H2", "H2", "-", "sqrt")],
    reference=_tanks_ref,
    differs="Both flows are k sqrt(level); SD Lab's forms write them as straight lines c + k x level.",
)


# ---- 3. Newton cooling towards a measured outside temperature ----

def _cool_drive(rng_for, p, steps):
    r = rng_for("outside")
    day = sine(p["ta_mean"], p["ta_swing"], 96.0, float(r.uniform(0, 96)))
    weather, jumps = piecewise(rng_for("weather"), steps, -4.0, 4.0, (60, 200), first=0.0)
    return Drive({"outside": added(day, weather)}, jumps)


def _cool_ref(p):
    def flows(th):
        return [_flow("in", None, "T", _prop("outside", th[0]), input="outside"),
                _flow("t_out", "T", None, _prop("T", th[1]))]
    return flows, [p["k"], p["k"]], [(0, 0), (np.inf, np.inf)], "heat in at k x outside, heat out at k x T (the gap k (outside - T) as two flows)"


COOLING = System(
    name="newton-cooling", title="Newton cooling",
    about="A body's temperature T relaxes towards the outside temperature at dT/dt = -k (T - outside); the outside follows a daily cycle and the weather.",
    stocks=[{"id": "T", "name": "Temperature", "unit": "degC"}], inputs=["outside"],
    params={"k": 0.03, "ta_mean": 12.0, "ta_swing": 5.0},
    initial=lambda rng, p: np.array([rng.uniform(40.0, 90.0)]),
    drive=_cool_drive,
    rhs=lambda t, x, p, d, m: np.array([-p["k"] * (x[0] - d.value("outside", t))]),
    couplings=[("T", "T", "-", "linear"), ("T", "outside", "+", "linear")],
    reference=_cool_ref,
)


# ---- 4. a mass-spring-damper (position and velocity, offset to stay positive) ----

def _spring_drive(rng_for, p, steps):
    r = rng_for("force")
    f, jumps = piecewise(r, steps, 0.0, p["f_max"], (40, 120), first=0.0)
    return Drive({"force": f}, jumps)


def _spring_ref(p):
    w2, c = p["w"] ** 2, 2 * p["zeta"] * p["w"]
    X0, V0 = p["x0"], p["v0"]

    def flows(th):
        return [_flow("in", None, "P", _prop("V", th[0])),
                _flow("p_out", "P", None, {"form": "constant", "value": float(th[1])}),
                _flow("v_in", None, "V", _linear(th[2], [("force", th[3])]), input="force"),
                _flow("v_out", "V", None, _linear(0.0, [("P", th[4]), ("V", th[5])]))]
    return flows, [1.0, V0, w2 * X0 + c * V0, 1.0, w2, c], [(0,) * 6, (np.inf,) * 6], \
        "P += V - V0 and V += (w2 X0 + c V0 + force) - (w2 P + c V), each sign a flow of its own"


SPRING = System(
    name="mass-spring-damper", title="Mass-spring-damper",
    about=("x'' = -w^2 x - 2 zeta w x' + force: a damped oscillator pushed by a measured force. Position and velocity "
           "are signed, so they are measured from a datum: P = x + X0 and V = v + V0 (both stay positive)."),
    stocks=[{"id": "P", "name": "Position above datum", "unit": "cm"}, {"id": "V", "name": "Velocity plus offset", "unit": "cm/step"}],
    inputs=["force"],
    params={"w": 0.1, "zeta": 0.25, "f_max": 0.03, "x0": 10.0, "v0": 1.0},
    initial=lambda rng, p: np.array([rng.uniform(-3.0, 3.0), rng.uniform(-0.3, 0.3)]),
    drive=_spring_drive,
    rhs=lambda t, x, p, d, m: np.array([x[1], -p["w"] ** 2 * x[0] - 2 * p["zeta"] * p["w"] * x[1] + d.value("force", t)]),
    couplings=[("P", "V", "+", "linear"), ("V", "P", "-", "linear"), ("V", "V", "-", "linear"), ("V", "force", "+", "linear")],
    reference=_spring_ref,
    differs=("Exact in SD Lab's forms only through offsets: the signed position and velocity are shifted by constants, so each "
             "signed term is split into two one-way flows and the offsets show up as constant flows."),
)


# ---- 5. Lotka-Volterra predator-prey ----

def _lv_ref(p):
    def flows(th):
        return [_flow("births", None, "X", _prop("X", th[0])),
                _flow("eaten", "X", None, {**_prop("X", th[1])}, effects=_product("Y")),
                _flow("born", None, "Y", {**_prop("Y", th[2])}, effects=_product("X")),
                _flow("deaths", "Y", None, _prop("Y", th[3]))]
    return flows, [p["a"], p["b"], p["d"], p["g"]], [(0,) * 4, (np.inf,) * 4], \
        "prey births a X, predation b X Y and predator births d X Y as proportional flows times a linear effect, deaths g Y"


LV = System(
    name="lotka-volterra", title="Lotka-Volterra predator-prey",
    about="Prey X grow at a X and are eaten at b X Y; predators Y are born at d X Y and die at g Y: closed cycles, no driver.",
    stocks=[{"id": "X", "name": "Prey", "unit": "animals"}, {"id": "Y", "name": "Predators", "unit": "animals"}], inputs=[],
    params={"a": 0.1, "b": 0.002, "d": 0.001, "g": 0.08},
    initial=lambda rng, p: np.array([rng.uniform(40.0, 140.0), rng.uniform(25.0, 80.0)]),
    drive=lambda rng_for, p, steps: Drive(),
    rhs=lambda t, x, p, d, m: np.array([p["a"] * x[0] - p["b"] * x[0] * x[1], p["d"] * x[0] * x[1] - p["g"] * x[1]]),
    couplings=[("X", "X", "±", "product"), ("X", "Y", "-", "product"), ("Y", "X", "+", "product"), ("Y", "Y", "±", "product")],
    reference=_lv_ref,
)


# ---- 6. a reaction chain A -> B -> C (first order), recharged in batches ----

def _chem_drive(rng_for, p, steps):
    r = rng_for("batches")
    out, t = [], 0
    while True:
        t += int(r.integers(p["every_lo"], p["every_hi"] + 1))
        amount = float(r.uniform(p["batch_lo"], p["batch_hi"]))
        if t > steps:
            break
        out.append({"t": t, "stock": "A", "amount": round(amount, 4)})
    return Drive({}, [float(j["t"] - 1) for j in out], out)


def _chem_ref(p):
    def flows(th):
        return [_flow("ab", "A", "B", _prop("A", th[0])), _flow("bc", "B", "C", _prop("B", th[1]))]
    return flows, [p["k1"], p["k2"]], [(0, 0), (np.inf, np.inf)], "two proportional moves"


CHEM = System(
    name="reaction-chain", title="Reaction chain A -> B -> C",
    about="First-order reactions A -> B at k1 A and B -> C at k2 B in a batch reactor, recharged with A at announced times; C is the product (nothing leaves it).",
    stocks=[{"id": "A", "name": "Reactant A", "unit": "mmol"}, {"id": "B", "name": "Intermediate B", "unit": "mmol"},
            {"id": "C", "name": "Product C", "unit": "mmol", "final": True}], inputs=[],
    params={"k1": 0.05, "k2": 0.03, "every_lo": 90, "every_hi": 160, "batch_lo": 50.0, "batch_hi": 150.0},
    initial=lambda rng, p: np.array([rng.uniform(50.0, 150.0), rng.uniform(0.0, 20.0), 0.0]),
    drive=_chem_drive,
    rhs=lambda t, x, p, d, m: np.array([-p["k1"] * x[0], p["k1"] * x[0] - p["k2"] * x[1], p["k2"] * x[1]]),
    couplings=[("A", "A", "-", "linear"), ("B", "A", "+", "linear"), ("B", "B", "-", "linear"), ("C", "B", "+", "linear")],
    reference=_chem_ref,
)


# ---- 7. a thermostat: on/off heating with hysteresis ----

def _thermo_drive(rng_for, p, steps):
    r = rng_for("outside")
    outside = sine(p["ta_mean"], p["ta_swing"], 96.0, float(r.uniform(0, 96)))
    rs = rng_for("setpoint")
    days = steps // 96 + 3
    day_set = [float(rs.choice([19.0, 20.0, 21.0, 22.0])) for _ in range(days)]

    def setpoint(t):
        t = np.asarray(t, dtype=float)
        k = np.floor(t).astype(int)
        hour = k % 96
        day = np.clip(k // 96, 0, days - 1)
        return np.where((hour >= 24) & (hour < 88), np.asarray(day_set)[day], p["night"])

    jumps = sorted({float(d * 96 + h) for d in range(days) for h in (24, 88)})
    return Drive({"outside": outside, "setpoint": setpoint}, [j for j in jumps if j > 0])


def _thermo_rhs(t, x, p, d, mode):
    return np.array([-p["k"] * (x[0] - d.value("outside", t)) + (p["power"] if mode else 0.0)])


def _thermo_guards(p, d, mode):
    """The event that ends the current mode: on, T reaches setpoint + band; off, T falls to setpoint - band."""
    if mode:
        return lambda t, x: x[0] - (d.value("setpoint", t) + p["band"])
    return lambda t, x: x[0] - (d.value("setpoint", t) - p["band"])


def _thermo_mode0(x, p, d):
    return bool(x[0] < d.value("setpoint", 0.0))


def _thermo_ref(p):
    def flows(th):
        return [_flow("heat_in", None, "T", _prop("outside", th[0]), input="outside"),
                _flow("t_out", "T", None, _prop("T", th[1])),
                _flow("heater", None, "T", _linear(th[2], [("setpoint", th[3]), ("T", -th[4])]), input="setpoint")]
    return flows, [p["k"], p["k"], 0.0, 0.2, 0.2], [(0, 0, -np.inf, 0, 0), (np.inf,) * 5], \
        "the losses as k x outside in and k x T out, the heater as a proportional controller max(0, c + ks x setpoint - kc x T)"


THERMO = System(
    name="thermostat", title="Thermostat with on/off control",
    about=("A room loses heat to the outside at k (T - outside); a heater of fixed power switches on when T falls below "
           "setpoint - band and off above setpoint + band. The setpoint (day and night) and the outside temperature are measured; "
           "whether the heater is on is not."),
    stocks=[{"id": "T", "name": "Room temperature", "unit": "degC"}], inputs=["outside", "setpoint"],
    params={"k": 0.01, "power": 0.25, "band": 1.0, "night": 16.0, "ta_mean": 6.0, "ta_swing": 4.0},
    initial=lambda rng, p: np.array([rng.uniform(10.0, 22.0)]),
    drive=_thermo_drive,
    rhs=_thermo_rhs,
    hybrid=(_thermo_mode0, _thermo_guards, lambda mode: not mode),
    couplings=[("T", "T", "-", "switch"), ("T", "outside", "+", "linear"), ("T", "setpoint", "+", "switch")],
    reference=_thermo_ref,
    differs=("The heater is on/off with hysteresis (it remembers whether it is on); SD Lab's forms have no switch with memory, "
             "so the best they write is a proportional controller floored at 0. Under control the outside temperature barely "
             "moves T (the heater's duty cycle absorbs it), so the best predicting SD model all but drops T <- outside."),
)


SYSTEMS: dict[str, System] = {s.name: s for s in (TANK, TANKS, COOLING, SPRING, LV, CHEM, THERMO)}


def levels_for(system: System, p: dict) -> Callable | None:
    """The state -> measured levels map for these parameters (the spring's offsets), or None (identity)."""
    if system.name == "mass-spring-damper":
        off = np.array([p["x0"], p["v0"]])
        return lambda x: x + off[:, None] if np.ndim(x) == 2 else x + off
    return None
