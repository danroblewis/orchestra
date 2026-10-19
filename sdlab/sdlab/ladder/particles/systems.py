"""The particle systems behind the particle cases. Each moves individual particles by explicit rules
(engine.py) and is measured as the count of particles in each region per step.

A system declares:

    ids          the regions (the measured stocks), in order
    inputs       its measured inputs: the expected arrivals per step (the dropper's or feeder's setting)
    tier         how its mean-field model may be used for scoring:
                   exact       every particle moves independently with fixed per-step probabilities,
                               so the expected counts follow the mean-field model exactly; the
                               probabilities are the rules' own numbers. Equations scored.
                   measured    the mean-field model is an approximation (well-mixed chambers, a
                               stirred reaction); its numbers are transition frequencies measured
                               over a very long run, and it is checked to track the average of many
                               particle runs within sampling error. Equations scored.
                   prediction  no mean-field model in SD Lab's forms is exact (a capacity gate, bins
                               that overflow, residence times that are not geometric); the measured
                               mean-field model is the reference, and only prediction is scored.
    params       the rules' numbers (a case may override any)
    drive        (p, rng, steps) -> Drive: inputs, announced injections, switches, announced eras
    start        (p, rng) -> Swarm: the particles at time 0
    step         (p, swarm, t, drive, rng) -> (src, dst, events): moves every particle present, adds
                 the step's arrivals; src/dst are the regions before/after of the particles present at
                 the start of the step (OUT when one left), events e.g. {"react": n}
    moves        (p) -> [(from, to | None, probability)]: the per-step move probabilities the rules
                 give (exact tier), or the moves the mean-field model has (measured, prediction)
    inflows      (p) -> [(input, region, share)]: arrivals per step = share x input
    reaction     (p) -> None or {"a", "b", "c", "kappa"}: A + B -> C at kappa x A x B per step
    switched     (p) -> {"closed": [(from, to)]}: moves shut while drive.switches["closed"] is set
    differs      where the mean-field SD model differs from the particles (None when exact)
"""

from __future__ import annotations

import numpy as np

from .engine import OUT, Drive, Hops, Swarm, batches, daily, piecewise, stirred_pairs


class System:
    name = ""
    title = ""
    about = ""
    tier = "exact"
    differs: str | None = None
    inputs: list[str] = []
    defaults: dict = {}

    def ids(self, p: dict) -> list[str]:
        raise NotImplementedError

    def moves(self, p: dict) -> list[tuple[str, str | None, float]]:
        return []

    def inflows(self, p: dict) -> list[tuple[str, str, float]]:
        return []

    def reaction(self, p: dict) -> dict | None:
        return None

    def switched(self, p: dict) -> dict:
        return {}

    def place(self, p: dict, region: int, n: int, rng: np.random.Generator) -> dict:
        """Per-particle state for n new particles in a region (a position, for a spatial system)."""
        return {}

    def hops(self, p: dict) -> Hops:
        ids = self.ids(p)
        ix = {s: i for i, s in enumerate(ids)}
        return Hops(len(ids), [(ix[a], ix[b] if b else OUT, q) for a, b, q in self.moves(p)], {ix[g]: m for g, m in (p.get("gates") or {}).items()})

    def arrive(self, p: dict, sw: Swarm, t: int, drive: Drive, rng: np.random.Generator) -> None:
        ix = {s: i for i, s in enumerate(self.ids(p))}
        for name, region, share in self.inflows(p):
            n = int(rng.poisson(max(0.0, share * float(drive.inputs[name][t - 1]))))
            if n:
                sw.add(np.full(n, ix[region]), **self.place(p, ix[region], n, rng))


def _rand_start(rng: np.random.Generator, ids: list[str], hi: dict[str, int], default: int) -> Swarm:
    n = [int(rng.integers(0, hi.get(s, default) + 1)) for s in ids]
    return Swarm(np.repeat(np.arange(len(ids), dtype=np.int32), n))


# ---- region hopping (exact) ----

class HopSystem(System):
    """Particles hop between regions with fixed probabilities (Hops); arrivals from the inputs."""

    def start(self, p, rng):
        return _rand_start(rng, self.ids(p), p.get("start_hi", {}), int(p.get("start_default", 20)))

    def step(self, p, sw, t, drive, rng):
        src = sw.reg.copy()
        dst = self._hops(p).step(sw.reg, rng)
        sw.reg = dst.copy()
        sw.keep(sw.reg != OUT)
        self.arrive(p, sw, t, drive, rng)
        return src, dst, {}

    def _hops(self, p):
        if getattr(self, "_hk", None) is not p:
            self._hk, self._h = p, self.hops(p)
        return self._h


class Galton(HopSystem):
    """A Galton board: balls dropped into the top peg bounce left or right through rows of pegs into bins."""

    name = "galton"
    title = "Galton board into draining bins"
    about = ("Balls are dropped into the top of a board (the dropper's rate follows a daily cycle on a level that "
             "shifts every few days). At each peg a ball falls to the next row with probability pf per step, to the "
             "right with probability q, else to the left; from the last row it lands in a bin. Each bin has a hole: "
             "every ball in it leaves with its own probability per step.")
    inputs = ["drop"]
    defaults = {"rows": 4, "pf": 0.6, "q": 0.55, "holes": [0.015, 0.02, 0.025, 0.02, 0.015], "base": [8.0, 20.0],
                "hold": [150, 400], "amp": 0.6, "start_default": 12, "start_bins": 500}

    def ids(self, p):
        r = int(p["rows"])
        return [f"P{i}{c}" for i in range(r) for c in range(i + 1)] + [f"B{c}" for c in range(r + 1)]

    def moves(self, p):
        r, pf, q = int(p["rows"]), float(p["pf"]), float(p["q"])
        out = []
        for i in range(r):
            for c in range(i + 1):
                left, right = (f"P{i + 1}{c}", f"P{i + 1}{c + 1}") if i + 1 < r else (f"B{c}", f"B{c + 1}")
                out += [(f"P{i}{c}", left, pf * (1 - q)), (f"P{i}{c}", right, pf * q)]
        out += [(f"B{c}", None, float(h)) for c, h in enumerate(p["holes"])]
        return out

    def inflows(self, p):
        return [("drop", "P00", 1.0)]

    def drive(self, p, rng, steps):
        lvl = piecewise(rng, steps, *p["base"], tuple(p["hold"]))
        return Drive(inputs={"drop": lvl * daily(steps, float(p["amp"]))})

    def start(self, p, rng):
        ids = self.ids(p)
        return _rand_start(rng, ids, {s: int(p["start_bins"]) for s in ids if s.startswith("B")}, int(p["start_default"]))


class Conveyor(HopSystem):
    """A vibrating conveyor of segments with a narrow chute (the bottleneck) in the middle."""

    name = "conveyor"
    title = "Conveyor with a bottleneck"
    about = ("Balls ride a vibrating conveyor of segments. Each step a ball hops to the next segment with probability "
             "p (the narrow chute: pb, so a queue builds in front of it); from the last segment it falls off the end. "
             "A feeder drops balls on the first segment at a rate that changes every few shifts, and batches are "
             "dumped there at announced times.")
    inputs = ["feed"]
    defaults = {"segments": 8, "p": 0.4, "bottleneck": 5, "pb": 0.07, "feed": [3.0, 12.0], "hold": [40, 160],
                "gap": [200, 450], "batch": [80, 200], "start_default": 40, "start_queue": 300}

    def ids(self, p):
        return [f"V{i + 1}" for i in range(int(p["segments"]))]

    def moves(self, p):
        ids = self.ids(p)
        return [(a, ids[i + 1] if i + 1 < len(ids) else None, float(p["pb"]) if i + 1 == int(p["bottleneck"]) else float(p["p"]))
                for i, a in enumerate(ids)]

    def inflows(self, p):
        return [("feed", "V1", 1.0)]

    def drive(self, p, rng, steps):
        feed = piecewise(rng, steps, *p["feed"], tuple(p["hold"]))
        return Drive(inputs={"feed": feed}, injections=batches(rng, steps, "V1", tuple(p["gap"]), tuple(p["batch"])))

    def start(self, p, rng):
        return _rand_start(rng, self.ids(p), {f"V{int(p['bottleneck'])}": int(p["start_queue"])}, int(p["start_default"]))


class Gate(HopSystem):
    """A hopper feeding a queue that drains through a gate passing at most m balls a step."""

    name = "gate"
    title = "Queue behind a capacity gate"
    tier = "prediction"
    differs = ("the gate passes at most m balls a step: the expected flow is E[min(Binomial(Q, p), m)], linear in Q "
               "when the queue is short and flat at m when it is long; SD Lab's forms have no min, so the mean-field "
               "model's proportional gate flow (measured over a long run) is right on average only")
    about = ("A feeder drops balls into a hopper H; each step a ball in the hopper slides into the queue Q with probability "
             "ph. Each ball in the queue tries the gate with probability pg, but at most m pass a step (the rest wait); "
             "they land in a tray D that empties through a hole.")
    inputs = ["feed"]
    defaults = {"ph": 0.25, "pg": 0.35, "m": 4, "pd": 0.04, "feed": [0.5, 5.5], "hold": [60, 200], "start_default": 30, "start_q": 80}

    def ids(self, p):
        return ["H", "Q", "D"]

    def moves(self, p):
        return [("H", "Q", float(p["ph"])), ("Q", "D", float(p["pg"])), ("D", None, float(p["pd"]))]

    def hops(self, p):
        return Hops(3, [(0, 1, float(p["ph"])), (1, 2, float(p["pg"])), (2, OUT, float(p["pd"]))], {1: int(p["m"])})

    def inflows(self, p):
        return [("feed", "H", 1.0)]

    def drive(self, p, rng, steps):
        return Drive(inputs={"feed": piecewise(rng, steps, *p["feed"], tuple(p["hold"]))})

    def start(self, p, rng):
        return _rand_start(rng, self.ids(p), {"Q": int(p["start_q"]), "D": 150}, int(p["start_default"]))


# ---- a stirred reaction ----

class Reaction(System):
    """A + B -> C in a stirred tank: particles meet in random cells and bind."""

    name = "reaction"
    title = "Sticky particles: A + B -> C in a stirred tank"
    tier = "measured"
    differs = ("binding needs an A and a B in the same cell: the expected number of bindings is close to, not "
               "exactly, kappa x A x B (two particles cannot both bind one partner, and E[A B] differs from "
               "E[A] E[B] by their covariance); kappa and the leaks are measured over a long run")
    about = ("A and B particles are fed into a stirred tank of `cells` cells. Each step every particle lands in a random "
             "cell; in each cell min(a, b) pairs meet and each binds into one C with probability `bind`. A and B also "
             "leak out (kA, kB) and C is drawn off (kC). The mean-field model is A -> C at kappa x A x B, using up one "
             "B per C (a product: a proportional rate times a linear effect of B, and a co-flow).")
    inputs = ["feedA", "feedB"]
    defaults = {"cells": 2000, "bind": 0.8, "kA": 0.02, "kB": 0.03, "kC": 0.05, "feedA": [3.0, 9.0], "feedB": [3.0, 9.0],
                "holdA": [80, 250], "holdB": [120, 300], "start_default": 120}

    def ids(self, p):
        return ["A", "B", "C"]

    def moves(self, p):
        return [("A", None, float(p["kA"])), ("B", None, float(p["kB"])), ("C", None, float(p["kC"]))]

    def inflows(self, p):
        return [("feedA", "A", 1.0), ("feedB", "B", 1.0)]

    def reaction(self, p):
        return {"a": "A", "b": "B", "c": "C", "kappa": float(p["bind"]) / float(p["cells"])}

    def drive(self, p, rng, steps):
        return Drive(inputs={"feedA": piecewise(rng, steps, *p["feedA"], tuple(p["holdA"])),
                             "feedB": piecewise(rng, steps, *p["feedB"], tuple(p["holdB"]))})

    def start(self, p, rng):
        return _rand_start(rng, self.ids(p), {}, int(p["start_default"]))

    def step(self, p, sw, t, drive, rng):
        return react_step(self, p, sw, t, drive, rng, Hops(3, [(0, OUT, float(p["kA"])), (1, OUT, float(p["kB"])), (2, OUT, float(p["kC"]))]), (0, 1, 2))


def react_step(system, p, sw, t, drive, rng, hops: Hops, abc: tuple[int, int, int]):
    """One step of hopping particles with A + B -> C among them: the bindings are drawn from the counts
    at the start of the step (stirred_pairs); the bound A become C, the bound B are used up; every other
    particle hops."""
    a, b, c = abc
    src = sw.reg.copy()
    ia, ib = np.flatnonzero(src == a), np.flatnonzero(src == b)
    n = stirred_pairs(rng, len(ia), len(ib), int(p["cells"]), float(p["bind"]))
    dst = hops.step(src, rng)
    if n:
        dst[rng.choice(ia, n, replace=False)] = c
        dst[rng.choice(ib, n, replace=False)] = OUT
    sw.reg = dst.copy()
    sw.keep(sw.reg != OUT)
    system.arrive(p, sw, t, drive, rng)
    return src, dst, {"react": n}


# ---- diffusion between chambers ----

class Chambers(System):
    """Particles random-walking on a lattice divided into chambers by walls with small openings."""

    name = "chambers"
    title = "Diffusion between chambers (unstirred)"
    tier = "prediction"
    differs = ("without stirring a chamber is not well mixed: particles near an opening are used up faster than the "
               "walk brings more, and one that has just crossed is still next to the opening and often crosses back, "
               "so no fixed per-step rate is right in every state; the mean-field model's rates (crossing frequencies "
               "over a long run) miss the particles' average by several percent (the case's check), far more than sampling error")
    about = ("Particles random-walk on an L x L lattice (`sub` times a step, each with probability `move`, one cell "
             "up, down, left or right; a wall stops it). Walls divide the box into n x n chambers; each wall has one opening of a "
             "few cells. A feeder releases particles at random cells of the first chamber; the last chamber has a "
             "drain where a particle is removed with probability `pd`. Two openings into the centre are shut for the "
             "second half of every period (announced).")
    inputs = ["feed"]
    defaults = {"n": 3, "size": 9, "move": 0.8, "sub": 10, "pd": 0.5, "drain": 2, "feed": [3.0, 8.0], "hold": [100, 300],
                # opening widths: vertical walls (row, between column c and c + 1), then horizontal walls (between row r and r + 1, column)
                "v": [[1, 2], [2, 1], [1, 2]], "h": [[2, 1, 2], [1, 2, 1]], "offset": 3,
                "shut": [["C12", "C22"], ["C21", "C22"]], "period": 400, "shut_from": 201, "start_default": 150, "measure_steps": 5000}

    def ids(self, p):
        n = int(p["n"])
        return [f"C{r + 1}{c + 1}" for r in range(n) for c in range(n)]

    def _neighbours(self, p):
        n = int(p["n"])
        out = []
        for r in range(n):
            for c in range(n - 1):
                out.append((f"C{r + 1}{c + 1}", f"C{r + 1}{c + 2}", int(p["v"][r][c])))
        for r in range(n - 1):
            for c in range(n):
                out.append((f"C{r + 1}{c + 1}", f"C{r + 2}{c + 1}", int(p["h"][r][c])))
        return out

    def moves(self, p):
        """The mean-field model's moves: each opening both ways, and the drain (their numbers are measured)."""
        out = []
        for a, b, _ in self._neighbours(p):
            out += [(a, b, 0.0), (b, a, 0.0)]
        n = int(p["n"])
        return out + [(f"C{n}{n}", None, 0.0)]

    def inflows(self, p):
        return [("feed", "C11", 1.0)]

    def switched(self, p):
        return {"closed": [tuple(x) for x in p["shut"]] + [tuple(reversed(x)) for x in p["shut"]]}

    def _geometry(self, p):
        if getattr(self, "_gk", None) is p:
            return self._g
        n, s, off = int(p["n"]), int(p["size"]), int(p["offset"])
        L = n * s
        passV = np.zeros((n - 1, L), dtype=bool)      # crossing between columns c*s + s - 1 and c*s + s, at row y
        passH = np.zeros((n - 1, L), dtype=bool)      # crossing between rows r*s + s - 1 and r*s + s, at column x
        owner = {}
        for r in range(n):
            for c in range(n - 1):
                ys = np.arange(r * s + off, r * s + off + int(p["v"][r][c]))
                passV[c, ys] = True
                owner[(f"C{r + 1}{c + 1}", f"C{r + 1}{c + 2}")] = ("v", c, ys)
        for r in range(n - 1):
            for c in range(n):
                xs = np.arange(c * s + off, c * s + off + int(p["h"][r][c]))
                passH[r, xs] = True
                owner[(f"C{r + 1}{c + 1}", f"C{r + 2}{c + 1}")] = ("h", r, xs)
        drain = np.zeros((L, L), dtype=bool)
        d = int(p["drain"])
        drain[L - d:, L - d:] = True                 # [y, x]: the far corner of the last chamber
        shutV, shutH = passV.copy(), passH.copy()
        for a, b in p["shut"]:
            kind, i, cells = owner[(a, b)] if (a, b) in owner else owner[(b, a)]
            (shutV if kind == "v" else shutH)[i, cells] = False
        self._gk, self._g = p, (n, s, L, passV, passH, shutV, shutH, drain)
        return self._g

    def place(self, p, region, k, rng):
        n, s = int(p["n"]), int(p["size"])
        r, c = np.divmod(np.asarray(region), n)
        return {"x": (c * s + rng.integers(0, s, size=k)).astype(np.int32), "y": (r * s + rng.integers(0, s, size=k)).astype(np.int32)}

    def start(self, p, rng):
        ids = self.ids(p)
        k = [int(rng.integers(0, int(p["start_default"]) + 1)) for _ in ids]
        reg = np.repeat(np.arange(len(ids), dtype=np.int32), k)
        sw = Swarm(np.zeros(0, dtype=np.int32), {"x": np.zeros(0, dtype=np.int32), "y": np.zeros(0, dtype=np.int32)})
        for i in range(len(ids)):
            sw.add(np.full(k[i], i), **self.place(p, i, k[i], rng))
        assert len(sw.reg) == len(reg)
        return sw

    def drive(self, p, rng, steps):
        feed = piecewise(rng, steps, *p["feed"], tuple(p["hold"]))
        t = np.arange(1, steps + 1)
        per, frm = int(p["period"]), int(p["shut_from"])
        closed = ((t - 1) % per) + 1 >= frm
        eras = []
        for k in range(2, steps + 1):
            if closed[k - 1] != closed[k - 2]:
                eras.append({"start": k, "label": "shut" if closed[k - 1] else "open"})
        return Drive(inputs={"feed": feed}, switches={"closed": closed}, eras=eras)

    def step(self, p, sw, t, drive, rng):
        n, s, L, passV, passH, shutV, shutH, drain = self._geometry(p)
        PV, PH = (shutV, shutH) if drive.switches["closed"][t - 1] else (passV, passH)
        x, y = sw.extra["x"].copy(), sw.extra["y"].copy()
        src = sw.reg.copy()
        m = len(x)
        if p.get("stir"):                              # a fan in every chamber: each particle starts the step anywhere in its own
            pos = self.place(p, src, m, rng)
            x, y = pos["x"], pos["y"]
        alive = np.ones(m, dtype=bool)
        for _ in range(int(p["sub"])):                 # `sub` lattice moves per recorded step
            go = alive & (rng.random(m) < float(p["move"]))
            d = rng.integers(0, 4, size=m)
            dx = np.where(go & (d == 0), 1, np.where(go & (d == 1), -1, 0))
            dy = np.where(go & (d == 2), 1, np.where(go & (d == 3), -1, 0))
            nx, ny = x + dx, y + dy
            ok = (nx >= 0) & (nx < L) & (ny >= 0) & (ny < L)
            cv = np.flatnonzero(ok & (dx != 0) & ((nx // s) != (x // s)))       # through a vertical wall
            ok[cv] = PV[np.minimum(x, nx)[cv] // s, y[cv]]
            ch = np.flatnonzero(ok & (dy != 0) & ((ny // s) != (y // s)))       # through a horizontal wall
            ok[ch] = PH[np.minimum(y, ny)[ch] // s, x[ch]]
            x = np.where(ok, nx, x).astype(np.int32)
            y = np.where(ok, ny, y).astype(np.int32)
            alive &= ~(drain[y, x] & (rng.random(m) < float(p["pd"])))
        reg = ((y // s) * n + (x // s)).astype(np.int32)
        dst = np.where(alive, reg, OUT).astype(np.int32)
        sw.reg, sw.extra["x"], sw.extra["y"] = dst.copy(), x, y
        sw.keep(alive)
        self.arrive(p, sw, t, drive, rng)
        return src, dst, {}


class StirredChambers(Chambers):
    """The chambers with a fan in each: at the start of every step each particle is anywhere in its chamber."""

    name = "stirred-chambers"
    title = "Diffusion between stirred chambers"
    tier = "exact"
    differs = None
    about = ("An L x L lattice divided into n x n chambers by walls, each wall with one opening of a few cells. A fan "
             "stirs every chamber: at the start of each step a particle is at a random cell of its chamber; it then "
             "takes one lattice step (with probability `move`, up, down, left or right; a wall stops it), passing to "
             "the next chamber only through an opening. A feeder releases particles into the first chamber; in the "
             "last a particle that ends the step on the drain is removed with probability `pd`. Two openings into the "
             "centre are shut for the second half of every period (announced). Crossing an opening of width w is a "
             "move at w / size^2 x move / 4 per step, each way.")
    defaults = {**Chambers.defaults, "size": 5, "sub": 1, "stir": True, "move": 0.8, "pd": 0.5, "drain": 2, "offset": 1,
                "v": [[1, 2], [3, 1], [2, 2]], "h": [[2, 1, 3], [1, 2, 1]], "feed": [3.0, 9.0], "start_default": 120}

    def moves(self, p):
        q = float(p["move"]) / 4 / int(p["size"]) ** 2
        out = []
        for a, b, w in self._neighbours(p):
            out += [(a, b, w * q), (b, a, w * q)]
        n = int(p["n"])
        return out + [(f"C{n}{n}", None, int(p["drain"]) ** 2 / int(p["size"]) ** 2 * float(p["pd"]))]


# ---- a gravity cascade with shelves and overflowing bins ----

class Shelves(System):
    """Balls falling through a field of tilted shelves into bins that overflow into their neighbours."""

    name = "shelves"
    title = "Gravity cascade over tilted shelves into overflowing bins"
    tier = "prediction"
    differs = ("a ball's time in a zone is a fall of fixed length plus rolls along shelves, not a geometric wait, and "
               "a full bin passes its arrivals to the next one: neither is a proportional flow, so the mean-field "
               "model (transition frequencies measured over a long run, a full bin's overflow averaged in) is a "
               "reference, not the truth")
    about = ("Balls drop from two hoppers into the top of a W x H field. Each step a free ball falls one row with "
             "probability pf, drifting a column left or right with probability jitter each; a ball resting on a tilted "
             "shelf rolls one cell downhill with probability roll and falls off its end. Below the field are four bins "
             "of capacity K with holes (each ball leaves with probability h a step); a ball arriving at a full bin "
             "rolls on to the next, and off the last one to the floor. The regions are 3 x 3 zones of the field and the bins.")
    inputs = ["drop"]
    defaults = {"W": 30, "H": 36, "pf": 0.85, "jitter": 0.12, "roll": 0.9, "K": 160, "h": 0.03, "base": [10.0, 22.0],
                "hold": [150, 400], "amp": 0.5, "split": 0.6, "hoppers": [[2, 7], [21, 27]],
                # shelves: [row, first column, last column, downhill direction]
                "shelves": [[5, 1, 9, 1], [8, 24, 28, -1], [16, 12, 22, -1], [20, 4, 9, -1], [28, 5, 12, -1], [31, 14, 25, 1]],
                "bins": [0, 8, 15, 23], "start_default": 20, "start_bins": 140}

    def ids(self, p):
        return [f"Z{r + 1}{c + 1}" for r in range(3) for c in range(3)] + [f"B{i + 1}" for i in range(len(p["bins"]))]

    def moves(self, p):
        """The mean-field model's moves: every zone to its possible neighbours below and beside, each zone of the
        bottom band to the bins under it and beside, a bin to the next (overflow) and out (numbers measured)."""
        W = int(p["W"])
        bins = list(p["bins"]) + [W]
        out = []
        for r in range(3):
            for c in range(3):
                z = f"Z{r + 1}{c + 1}"
                for cc in (c - 1, c + 1):
                    if 0 <= cc < 3:
                        out.append((z, f"Z{r + 1}{cc + 1}", 0.0))
                if r < 2:
                    for cc in (c - 1, c, c + 1):
                        if 0 <= cc < 3:
                            out.append((z, f"Z{r + 2}{cc + 1}", 0.0))
                else:
                    lo, hi = c * W // 3, (c + 1) * W // 3
                    for i in range(len(p["bins"])):
                        if bins[i] < hi + 1 and bins[i + 1] > lo - 1:
                            out.append((z, f"B{i + 1}", 0.0))
        for i in range(len(p["bins"])):
            out.append((f"B{i + 1}", None, 0.0))
        return out

    def inflows(self, p):
        W = int(p["W"])
        z = lambda x: f"Z1{min(2, int(x) * 3 // W) + 1}"     # noqa: E731
        (a0, _), (b0, _) = p["hoppers"]
        return [("drop", z(a0), float(p["split"])), ("drop", z(b0), 1 - float(p["split"]))]

    def _field(self, p):
        if getattr(self, "_fk", None) is p:
            return self._f
        W, H = int(p["W"]), int(p["H"])
        shelf = np.zeros((H + 1, W), dtype=bool)
        tilt = np.zeros((H + 1, W), dtype=np.int32)
        for row, a, b, d in p["shelves"]:
            shelf[row, a:b + 1] = True
            tilt[row, a:b + 1] = d
        binof = np.searchsorted(np.asarray(p["bins"]), np.arange(W), side="right") - 1
        self._fk, self._f = p, (W, H, shelf, tilt, binof)
        return self._f

    def place(self, p, region, k, rng):
        W, H, *_ = self._field(p)
        nz = 9
        if region >= nz:                               # a ball in a bin has no position
            return {"x": np.zeros(k, dtype=np.int32), "y": np.full(k, H, dtype=np.int32)}
        r, c = divmod(region, 3)
        x = c * W // 3 + rng.integers(0, W // 3, size=k)
        y = r * (H // 3) + rng.integers(0, H // 3, size=k)
        shelf = self._field(p)[2]
        y = np.where(shelf[y, x], y - 1, y)            # never inside a shelf
        return {"x": x.astype(np.int32), "y": y.astype(np.int32)}

    def _region(self, p, x, y):
        W, H, *_ = self._field(p)
        return ((np.minimum(y, H - 1) // (H // 3)) * 3 + np.minimum(x * 3 // W, 2)).astype(np.int32)

    def start(self, p, rng):
        ids = self.ids(p)
        sw = Swarm(np.zeros(0, dtype=np.int32), {"x": np.zeros(0, dtype=np.int32), "y": np.zeros(0, dtype=np.int32)})
        for i in range(len(ids)):
            k = int(rng.integers(0, (int(p["start_bins"]) if i >= 9 else int(p["start_default"])) + 1))
            sw.add(np.full(k, i), **self.place(p, i, k, rng))
        return sw

    def drive(self, p, rng, steps):
        lvl = piecewise(rng, steps, *p["base"], tuple(p["hold"]))
        return Drive(inputs={"drop": lvl * daily(steps, float(p["amp"]))})

    def arrive(self, p, sw, t, drive, rng):
        n = int(rng.poisson(max(0.0, float(drive.inputs["drop"][t - 1]))))
        if not n:
            return
        first = rng.random(n) < float(p["split"])
        (a0, a1), (b0, b1) = p["hoppers"]
        x = np.where(first, rng.integers(a0, a1 + 1, size=n), rng.integers(b0, b1 + 1, size=n)).astype(np.int32)
        y = np.zeros(n, dtype=np.int32)
        sw.add(self._region(p, x, y), x=x, y=y)

    def step(self, p, sw, t, drive, rng):
        W, H, shelf, tilt, binof = self._field(p)
        nb = len(p["bins"])
        src = sw.reg.copy()
        x, y = sw.extra["x"].copy(), sw.extra["y"].copy()
        m = len(src)
        dst = src.copy()
        inbin = src >= 9
        # bins: each ball leaves through the hole with probability h
        leak = inbin & (rng.random(m) < float(p["h"]))
        dst[leak] = OUT
        # the field: on a shelf roll, else fall (with a sideways drift)
        f = np.flatnonzero(~inbin)
        fx, fy = x[f], y[f]
        below = shelf[np.minimum(fy + 1, H), fx]
        u = rng.random(len(f))
        roll = below & (u < float(p["roll"]))
        fx = np.where(roll, np.clip(fx + tilt[np.minimum(fy + 1, H), fx], 0, W - 1), fx)
        fall = ~below & (u < float(p["pf"]))
        side = rng.random(len(f))
        jit = np.where(side < float(p["jitter"]), -1, np.where(side > 1 - float(p["jitter"]), 1, 0))
        nx = np.clip(fx + np.where(fall, jit, 0), 0, W - 1)
        ny = np.where(fall, fy + 1, fy)
        blocked = (ny < H) & shelf[np.minimum(ny, H), nx]
        nx = np.where(blocked, fx, nx)
        x[f], y[f] = nx, ny
        landed = f[ny >= H]
        dst[f] = np.where(ny >= H, -2, self._region(p, nx, ny))       # -2: landing in a bin this step
        # bins: the balls that stay, then the arrivals in random order, a full bin passing them on
        stay = np.bincount(dst[inbin & (dst != OUT)] - 9, minlength=nb)
        if len(landed):
            want = binof[x[landed]]
            order = rng.permutation(len(landed))
            room = int(p["K"]) - stay
            goes = np.empty(len(landed), dtype=np.int32)
            for j in order:
                b = int(want[j])
                while b < nb and room[b] <= 0:
                    b += 1
                if b < nb:
                    room[b] -= 1
                    goes[j] = 9 + b
                else:
                    goes[j] = OUT
            dst[landed] = goes
            y[landed] = H
        sw.reg, sw.extra["x"], sw.extra["y"] = dst.copy(), x.astype(np.int32), y.astype(np.int32)
        sw.keep(sw.reg != OUT)
        self.arrive(p, sw, t, drive, rng)
        return src, dst, {}


# ---- the large mixed plant ----

class Plant(System):
    """A Galton board, sorting chambers, a conveyor with a capacity gate and a reaction tank, chained."""

    name = "plant"
    title = "A ball plant: Galton board, sorting chambers, gated conveyor, reaction tank (32 regions)"
    tier = "prediction"
    differs = ("the conveyor's last segment passes at most m balls a step (a capacity gate, no min in SD Lab's forms) "
               "and the tank's binding is close to, not exactly, a product; the mean-field model's numbers are measured "
               "over a long run and it is the reference, not the truth")
    about = ("Balls dropped into a 4-row Galton board land in 5 bins whose holes empty into a 2 x 3 grid of sorting "
             "chambers (balls drift sideways and settle downward between them); the bottom chambers feed an 8-segment "
             "vibrating conveyor whose last segment passes at most m balls a step into a stirred tank, where each ball "
             "(A) may bind with a fed reagent B into C (A + B -> C); A and B leak and C is drawn off.")
    inputs = ["drop", "feedB"]
    defaults = {"pf": 0.6, "q": 0.55, "hole": 0.02, "side": 0.03, "down": 0.05, "up": 0.01, "exit": 0.04, "p": 0.4,
                "pg": 0.5, "m": 8, "cells": 2000, "bind": 0.8, "kA": 0.02, "kB": 0.03, "kC": 0.05,
                "base": [3.0, 7.0], "hold": [150, 400], "amp": 0.5, "feedB": [2.0, 7.0], "holdB": [120, 300], "start_default": 15}

    def ids(self, p):
        return ([f"P{i}{c}" for i in range(4) for c in range(i + 1)] + [f"B{c}" for c in range(5)] + [f"S{i + 1}" for i in range(6)]
                + [f"V{i + 1}" for i in range(8)] + ["A", "R", "C"])

    def moves(self, p):
        pf, q = float(p["pf"]), float(p["q"])
        out = []
        for i in range(4):
            for c in range(i + 1):
                left, right = (f"P{i + 1}{c}", f"P{i + 1}{c + 1}") if i + 1 < 4 else (f"B{c}", f"B{c + 1}")
                out += [(f"P{i}{c}", left, pf * (1 - q)), (f"P{i}{c}", right, pf * q)]
        h = float(p["hole"])
        out += [("B0", "S1", h), ("B1", "S1", h), ("B2", "S2", h), ("B3", "S3", h), ("B4", "S3", h)]
        sd, dn, up = float(p["side"]), float(p["down"]), float(p["up"])
        for a, b in (("S1", "S2"), ("S2", "S3"), ("S4", "S5"), ("S5", "S6")):
            out += [(a, b, sd), (b, a, sd)]
        for a, b in (("S1", "S4"), ("S2", "S5"), ("S3", "S6")):
            out += [(a, b, dn), (b, a, up)]
        out += [(s, "V1", float(p["exit"])) for s in ("S4", "S5", "S6")]
        out += [(f"V{i + 1}", f"V{i + 2}", float(p["p"])) for i in range(7)] + [("V8", "A", float(p["pg"]))]
        out += [("A", None, float(p["kA"])), ("R", None, float(p["kB"])), ("C", None, float(p["kC"]))]
        return out

    def inflows(self, p):
        return [("drop", "P00", 1.0), ("feedB", "R", 1.0)]

    def reaction(self, p):
        return {"a": "A", "b": "R", "c": "C", "kappa": float(p["bind"]) / float(p["cells"])}

    def hops(self, p):
        ids = self.ids(p)
        ix = {s: i for i, s in enumerate(ids)}
        return Hops(len(ids), [(ix[a], ix[b] if b else OUT, q) for a, b, q in self.moves(p)], {ix["V8"]: int(p["m"])})

    def drive(self, p, rng, steps):
        lvl = piecewise(rng, steps, *p["base"], tuple(p["hold"]))
        return Drive(inputs={"drop": lvl * daily(steps, float(p["amp"])), "feedB": piecewise(rng, steps, *p["feedB"], tuple(p["holdB"]))})

    def start(self, p, rng):
        return _rand_start(rng, self.ids(p), {f"B{c}": 150 for c in range(5)} | {f"S{i}": 150 for i in range(1, 7)}, int(p["start_default"]))

    def step(self, p, sw, t, drive, rng):
        if getattr(self, "_hk", None) is not p:
            self._hk, self._h = p, self.hops(p)
        ids = self.ids(p)
        return react_step(self, p, sw, t, drive, rng, self._h, (ids.index("A"), ids.index("R"), ids.index("C")))


SYSTEMS: dict[str, System] = {s.name: s for s in (Galton(), Conveyor(), StirredChambers(), Chambers(), Shelves(), Reaction(), Gate(), Plant())}
