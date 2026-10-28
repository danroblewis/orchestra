"""The experiments' Python API, for any machine (the agents' host, other Python machines), and
the one the HTTP API (``orchestra.endpoint.api``) calls, so both answer alike: every method takes
and returns plain JSON-able values.

    x = Experiments(project, source="curator")
    e = x.create("faster review", purpose="does pairing halve review time?")
    x.edit(e["id"], [{"op": "replace_flow", "id": "reviewed_total", "equation": "k * min(reviewing, 2 * reviewers)",
                      "params": {"k": 0.4}}])
    x.run(e["id"], "forward", horizon_s=7200)
    x.run(e["id"], "replay", span_s=86400)
    x.commit(e["id"], horizon="2h")          # a prediction; publish the change with its ``change`` id

The machine is ``source`` (its CloudEvents source): an experiment is its owner's to edit, commit
and discard; anyone may read one and run it. Configuration and state go through Orchestra's
objects only: the model store, the experiment store, the metrics store (read through the sources'
catalogue, ``sd.judge.reader``) and the bus (``sd.predictions``). Nothing here changes a machine,
the model or a metric: an experiment is a statement about the model, and a commit is a
prediction (AGENTS.md rule 9 keeps humans to reading it)."""

from __future__ import annotations

import copy
import re
import time

from ..model import Model
from ..store import ModelStore
from . import reads
from .language import EquationError, reference
from .reads import ReadError, base_model
from .store import ExperimentStore, NotFound

SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*(/[A-Za-z0-9][A-Za-z0-9_.:@-]*)?$")
MAX_TEXT = 2000
WINDOW = {"start", "end", "span_s", "era", "step_s"}
MODES = {"forward": {"horizon_s", "step_s", "members", "seed", "bounds", "stocks", "points"},
         "replay": WINDOW | {"points"},
         "inverse": WINDOW | {"targets", "hold", "new_flows", "max_changes", "deadline_s", "alternatives", "check"}}
LOG_SHOWN = 50
DEADLINE_MAX = 300.0
POINTS_MAX = 1001


class ExperimentError(ValueError):
    """What a caller asked for that cannot be done: ``status`` is the HTTP status it answers."""

    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _source(v) -> str:
    if not isinstance(v, str) or not SOURCE.match(v) or len(v) > 256:
        raise ExperimentError("source: the machine's CloudEvents source, <machine> or <machine>/<instance>")
    return v


def _text(v, what: str, required: bool = False) -> str:
    if v is None and not required:
        return ""
    if not isinstance(v, str) or (required and not v.strip()) or len(v) > MAX_TEXT:
        raise ExperimentError(f"{what}: {'a non-empty ' if required else 'a '}string of at most {MAX_TEXT} characters")
    return v.strip()


def _num(v, what: str, lo: float | None = None, hi: float | None = None, default=None):
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ExperimentError(f"{what}: a number")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ExperimentError(f"{what}: from {lo:g} to {hi:g}" if lo is not None and hi is not None else f"{what}: at least {lo:g}")
    return v


class Experiments:
    def __init__(self, project, source: str | None = None, *, metrics=None, events=None, history=None):
        """``metrics``: the project's store (default: opened when first needed); ``events``: the
        bus a commit publishes on (default: the project's); ``history``: ``(model, start, end) ->
        history`` in place of reading the metrics (tests)."""
        self.project = project
        self.source = _source(source) if source is not None else None
        self._metrics = metrics
        self._events = events
        self._history = history
        self.models = ModelStore.for_state(project.state_dir)
        self.store = ExperimentStore.for_state(project.state_dir)

    # ---- what it reads with
    @property
    def metrics(self):
        if self._metrics is None:
            from ...metrics import for_project
            self._metrics = for_project(self.project)
        return self._metrics

    def history(self, model: Model, start: float, end: float) -> dict:
        """The model's series over [start, end]: levels at the discovery step (coarser for long
        windows), flow rates every 30 s (coarser for long windows)."""
        if self._history is not None:
            return self._history(model, start, end)
        from ...web.background import stock_step
        from ..judge import reader
        from .history import read_window

        span = end - start
        step = max(stock_step(self.project.config.discovery_step), span / 2000.0)
        return read_window(model, reader(self.project, self.metrics), start, end, step, max(30.0, span / 500.0))

    def _who(self) -> str:
        if self.source is None:
            raise ExperimentError("this needs the machine's source: Experiments(project, source=...)", 400)
        return self.source

    # ---- reads
    def language(self) -> dict:
        return {"ok": True, "language": reference()}

    def model(self, version: int | None = None, raw: bool = False) -> dict:
        return reads.model(self.models, self._metrics_or_none(), version, raw)

    def _metrics_or_none(self):
        try:
            return self.metrics
        except Exception:  # noqa: BLE001 - the model is read without levels
            return None

    def versions(self) -> dict:
        return reads.versions(self.models)

    def eras(self) -> dict:
        return reads.eras(self.models)

    def observability(self, version: int | None = None) -> dict:
        return reads.observability(self.models, self.history, version)

    def series(self, ids, **kw) -> dict:
        return reads.series(self.models, self.history, ids, **kw)

    def predictions(self, pid: str | None = None) -> dict:
        return reads.predictions(self.models, pid)

    def check_equation(self, equation, params=None, experiment: str | None = None, version: int | None = None) -> dict:
        """Whether an equation parses against the model (or an experiment's draft), and what it reads."""
        from .forms import Names
        from .language import parse

        m = self._draft(self._get(experiment)) if experiment else base_model(self.models, version)[0]
        rec = self._get(experiment) if experiment else {}
        n = Names.of(m, list((rec.get("scenario") or {}).get("inputs") or {}))
        try:
            p = parse(equation, stocks=n.stocks, inputs=n.inputs, params=params)
        except EquationError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, **p.describe()}

    # ---- experiments
    def _get(self, eid: str) -> dict:
        try:
            return self.store.get(eid)
        except NotFound as e:
            raise ExperimentError(str(e), 404) from None

    @staticmethod
    def _draft(rec: dict) -> Model:
        return Model.from_json(rec["draft"])

    @staticmethod
    def _base(rec: dict) -> Model:
        return Model.from_json(rec["base"]["model"])

    def _mine(self, rec: dict, draft_only: bool = True) -> str:
        who = self._who()
        if rec["owner"] != who:
            raise ExperimentError(f"experiment {rec['id']} is {rec['owner']}'s: only its owner changes it", 403)
        if draft_only and rec["status"] != "draft":
            raise ExperimentError(f"experiment {rec['id']} is {rec['status']}: only a draft changes", 409)
        return who

    def view(self, rec: dict, *, base: bool = False) -> dict:
        from .views import diff, model_view

        draft, b = self._draft(rec), self._base(rec)
        d = diff(b, draft, rec.get("scenario"))
        out = {k: rec.get(k) for k in ("id", "owner", "title", "purpose", "status", "created_at", "updated_at", "prediction", "origin")}
        out["base"] = {k: v for k, v in rec["base"].items() if k != "model"}
        if base:
            out["base"]["model"] = model_view(b)
        out["draft"] = model_view(draft, extra_inputs=list((rec.get("scenario") or {}).get("inputs") or {}))
        out["scenario"] = rec.get("scenario")
        out["changes"] = d["edits"]
        out["log"] = rec.get("log", [])[-LOG_SHOWN:]
        out["runs"] = rec.get("runs", [])
        return out

    def list(self, owner: str | None = None, status: str | None = None) -> dict:
        rows = []
        for r in self.store.all():
            if (owner and r.get("owner") != owner) or (status and r.get("status") != status):
                continue
            rows.append({k: r.get(k) for k in ("id", "owner", "title", "status", "created_at", "updated_at", "origin")}
                        | {"base": {k: v for k, v in r["base"].items() if k != "model"}, "runs": len(r.get("runs", [])),
                           "prediction": (r.get("prediction") or {}).get("id")})
        return {"ok": True, "experiments": rows}

    def create(self, title: str, purpose: str = "", version: int | None = None, *, origin: dict | None = None,
               model: Model | None = None, base: dict | None = None, eid: str | None = None) -> dict:
        """A draft copied from the current era's latest model (or ``version``)."""
        who = self._who()
        title, purpose = _text(title, "title", True), _text(purpose, "purpose")
        if base is None:
            try:
                b, label = base_model(self.models, version)
            except ReadError as e:
                raise ExperimentError(str(e), e.status) from None
            base = {"label": label, "era": b.era, "model": b.to_json()}
        now = time.time()
        rec = {"id": eid or self.store.new_id(), "owner": who, "title": title, "purpose": purpose, "status": "draft",
               "created_at": now, "updated_at": now, "base": base,
               "draft": (model.to_json() if model is not None else copy.deepcopy(base["model"])),
               "scenario": {"inputs": {}, "levels": {}}, "log": [], "runs": [], "prediction": None, "origin": origin}
        self.store.put(rec)
        return {"ok": True, "experiment": self.view(rec)}

    def get(self, eid: str, base: bool = False) -> dict:
        return {"ok": True, "experiment": self.view(self._get(eid), base=base)}

    def diff(self, eid: str) -> dict:
        from .views import diff
        rec = self._get(eid)
        return {"ok": True, "diff": diff(self._base(rec), self._draft(rec), rec.get("scenario"))}

    def edit(self, eid: str, edits) -> dict:
        """A batch of edits (``edits``), applied atomically or refused whole with the reason."""
        from .edits import EditError, apply

        with self.store.locked(self._get(eid)["id"]):
            rec = self._get(eid)
            who = self._mine(rec)
            try:
                d = apply(self._draft(rec), rec.get("scenario"), self._base(rec), edits, rec["id"], who)
            except EditError as e:
                rec["log"].append({"at": time.time(), "by": who, "edits": edits if isinstance(edits, list) else None, "ok": False,
                                   "error": str(e), "index": e.index})
                self.store.put(rec)
                raise ExperimentError(str(e), 422, index=e.index) from None
            rec["draft"], rec["scenario"] = d.model.to_json(), d.scenario
            rec["log"].append({"at": time.time(), "by": who, "edits": edits, "ok": True})
            self.store.put(rec)
        return {"ok": True, "experiment": self.view(rec), **self.diff(eid)}

    def discard(self, eid: str) -> dict:
        with self.store.locked(self._get(eid)["id"]):
            rec = self._get(eid)
            who = self._mine(rec)
            rec["status"] = "discarded"
            rec["log"].append({"at": time.time(), "by": who, "discarded": True, "ok": True})
            self.store.put(rec)
        return {"ok": True, "experiment": self.view(rec)}

    # ---- runs
    def run(self, eid: str, mode: str, **options) -> dict:
        """One run of the experiment, recorded with it: ``forward`` (``horizon_s``, ``members``,
        ``seed``, ``bounds``, ``stocks``, ``points``), ``replay`` (a past window: ``start`` and
        ``end``, or ``span_s`` back from now, or ``era``; ``points``) or ``inverse`` (a window,
        ``targets``, ``hold``, ``new_flows``, ``max_changes``, ``deadline_s``, ``alternatives``,
        ``check``): the inverse's answer is a new experiment, the caller's."""
        from .views import diff

        rec = self._get(eid)
        who = self._who()
        if mode not in MODES:
            raise ExperimentError(f"mode: one of {', '.join(MODES)}")
        if extra := sorted(set(options) - MODES[mode]):
            raise ExperimentError(f"{mode} takes {', '.join(sorted(MODES[mode]))}; not {', '.join(extra)}")
        base, draft = self._base(rec), self._draft(rec)
        began = time.time()
        try:
            if mode == "forward":
                result = self._forward(rec, base, draft, options)
            elif mode == "replay":
                result = self._replay(base, draft, options)
            else:
                result = self._inverse(rec, draft, options, who)
        except EquationError as e:
            raise ExperimentError(str(e), 422) from None
        except (ValueError, TypeError) as e:
            if isinstance(e, ExperimentError):
                raise
            raise ExperimentError(str(e), 400) from None
        rid = self.store.new_run_id()
        run = {"id": rid, "experiment": rec["id"], "mode": mode, "at": began, "by": who, "elapsed_s": round(time.time() - began, 3),
               "options": {k: v for k, v in options.items() if k not in ("history",)}, "diff": diff(base, draft, rec.get("scenario")),
               "result": result}
        self.store.put_run(rec["id"], run)
        with self.store.locked(rec["id"]):
            rec = self._get(eid)
            rec["runs"].append({"id": rid, "mode": mode, "at": began, "by": who, "summary": _summary(mode, result)})
            self.store.put(rec)
        return {"ok": True, "run": run}

    def runs(self, eid: str) -> dict:
        return {"ok": True, "runs": self._get(eid).get("runs", [])}

    def run_result(self, eid: str, rid: str) -> dict:
        try:
            return {"ok": True, "run": self.store.get_run(eid, rid)}
        except NotFound as e:
            raise ExperimentError(str(e), 404) from None

    def _window(self, options: dict) -> tuple[float, float]:
        start, end = options.get("start"), options.get("end")
        if options.get("era"):
            from .. import eras as era_record
            eras = era_record.recorded(self.models)
            e = next((x for x in eras if x.id == options["era"]), None)
            if e is None:
                raise ExperimentError(f"no era {options['era']}", 404)
            nxt = next((x.start for x in sorted(eras, key=lambda x: x.start) if x.start > e.start), None)
            start, end = e.start, nxt or time.time()
        end = float(_num(end, "end", default=time.time()))
        start = float(_num(start, "start", default=end - float(_num(options.get("span_s"), "span_s", 60.0, reads.SPAN_MAX, 3600.0))))
        if not end > start or end - start > reads.SPAN_MAX:
            raise ExperimentError("the window must end after it starts, and span at most 90 days")
        return start, end

    def _forward(self, rec: dict, base: Model, draft: Model, o: dict) -> dict:
        from .forward import forward
        from .views import diff

        horizon = float(_num(o.get("horizon_s"), "horizon_s", 1.0, 366 * 86400.0, 3600.0))
        now = time.time()
        h = self.history(_union(base, draft), now - 3600.0, now)
        d = diff(base, draft, rec.get("scenario"))
        changed = [r["id"] for r in d["flows"]["changed"] + d["flows"]["added"]]
        bounds = {k: tuple(v) for k, v in (o.get("bounds") or {}).items()}
        return forward(base, draft, h, rec.get("scenario"), horizon_s=horizon, step_s=_num(o.get("step_s"), "step_s", 1.0, 86400.0),
                       members=int(_num(o.get("members"), "members", 0, 200, 24)), seed=int(_num(o.get("seed"), "seed", 0, 2**31, 0)),
                       bounds=bounds, points=int(_num(o.get("points"), "points", 2, POINTS_MAX, 61)), stocks=o.get("stocks"),
                       changed=changed)

    def _replay(self, base: Model, draft: Model, o: dict) -> dict:
        from .replay import replay

        start, end = self._window(o)
        h = self.history(_union(base, draft), start, end)
        return replay(base, draft, h, start=start, end=end, step_s=_num(o.get("step_s"), "step_s", 1.0, 86400.0),
                      points=int(_num(o.get("points"), "points", 2, POINTS_MAX, 121)))

    def _inverse(self, rec: dict, draft: Model, o: dict, who: str) -> dict:
        from . import inverse as inv

        start, end = self._window(o)
        h = self.history(draft, start, end)
        deadline = float(_num(o.get("deadline_s"), "deadline_s", 1.0, DEADLINE_MAX, 60.0))
        try:
            sol = inv.solve(draft, h, o.get("targets") or [], hold=o.get("hold") or [], start=start, end=end,
                            step_s=_num(o.get("step_s"), "step_s", 1.0, 86400.0), new_flows=bool(o.get("new_flows", False)),
                            max_changes=int(_num(o.get("max_changes"), "max_changes", 1, 8, 3)), deadline_s=deadline,
                            alternatives=int(_num(o.get("alternatives"), "alternatives", 0, 8, 3)))
        except inv.InverseError as e:
            raise ExperimentError(str(e), 400) from None
        rep = inv.report(sol, draft, h)
        changes = sol["stages"][-1]["changes"]
        new_id = self.store.new_id()
        solved = inv.apply(draft, sol, changes, f"experiment {new_id} by the inverse solver for {who}")
        if o.get("check", True) and changes:
            rep["uniqueness"] = inv.uniqueness(draft, solved, h, rep["changes"], start, end, deadline=sol["deadline"])
        else:
            rep["uniqueness"] = {"checked": False, "why": "not asked" if changes else "no change was found"}
        u = rep["uniqueness"]
        rep["ambiguous"] = bool(any(a["met"] for a in rep["alternatives"]) or (u.get("checked") and not u.get("consistent")))
        targets = "; ".join(f"{t['id']} {t['kind']} {t['value']:g}" for t in rep["targets"] if t["kind"] != "hold")
        made = self.create(f"inverse of {rec['id']}: {targets}"[:MAX_TEXT], f"the smallest change the inverse solver found under which "
                           f"a replay of {start:.0f}–{end:.0f} meets: {targets}", origin={"experiment": rec["id"], "mode": "inverse"},
                           model=solved, base=copy.deepcopy(rec["base"]), eid=new_id)
        rep["experiment"] = made["experiment"]["id"]
        return {"mode": "inverse", **rep}

    # ---- commit
    def commit(self, eid: str, horizon, change: str | None = None, subject: str | None = None, members: int = 24) -> dict:
        """The experiment as a prediction (``sd.predictions``) of the change the caller will make:
        its edits become the expected edits (``expect.expectations``), its forward run over the
        horizon the predicted trajectories. Publish the change with the ``change`` id returned."""
        from ...config import ConfigError, parse_duration
        from .. import predictions as P
        from .expect import expectations
        from .forward import forward, trajectories
        from .views import diff

        with self.store.locked(self._get(eid)["id"]):
            rec = self._get(eid)
            who = self._mine(rec)
            try:
                horizon_s = float(horizon) if isinstance(horizon, (int, float)) and not isinstance(horizon, bool) else parse_duration(horizon, 0.0)
            except ConfigError as e:
                raise ExperimentError(f"horizon: {e}") from None
            if not horizon_s > 0:
                raise ExperimentError("horizon: how long after the change to judge it (seconds, or a duration such as \"2h\")")
            base, draft = self._base(rec), self._draft(rec)
            expect = expectations(base, draft, rec.get("scenario"))
            traj, why = None, None
            try:
                now = time.time()
                h = self.history(_union(base, draft), now - 3600.0, now)
                d = diff(base, draft, rec.get("scenario"))
                r = forward(base, draft, h, rec.get("scenario"), horizon_s=horizon_s, members=members, points=121,
                            changed=[x["id"] for x in d["flows"]["changed"] + d["flows"]["added"]])
                traj = trajectories(r)
            except Exception as e:  # noqa: BLE001 - the host simulates the previous era's model when it judges
                why = f"{type(e).__name__}: {e}"
            try:
                made = P.Predictions(self.project, source=who, events=self._events).record(expect, horizon_s, change=change,
                                                                                         trajectories=traj, subject=subject or rec["id"])
            except P.PredictionError as e:
                raise ExperimentError(f"the prediction: {e}", 422) from None
            rec["status"] = "committed"
            rec["prediction"] = {"id": made["id"], "change": made.get("change"), "horizon_s": horizon_s, "made_at": made.get("made_at"),
                                 "trajectories": traj is not None, **({"no_trajectories": why} if why else {})}
            rec["log"].append({"at": time.time(), "by": who, "committed": made["id"], "ok": True})
            self.store.put(rec)
        return {"ok": True, "prediction": made, "change": made.get("change"), "experiment": self.view(rec)}

    def prediction(self, eid: str) -> dict:
        """The prediction a committed experiment became, with its verdict once judged."""
        rec = self._get(eid)
        if not rec.get("prediction"):
            raise ExperimentError(f"experiment {eid} is {rec['status']}: it has made no prediction", 404)
        try:
            return {"ok": True, **self.predictions(rec["prediction"]["id"])}
        except ReadError:
            return {"ok": True, "prediction": {**rec["prediction"], "status": "not yet recorded"}}


def _union(base: Model, draft: Model) -> Model:
    """A model with the stocks and flows of both, for reading the history of either."""
    m = copy.deepcopy(base)
    have_s, have_f = {s.id for s in m.stocks}, {f.id for f in m.flows}
    m.stocks += [copy.deepcopy(s) for s in draft.stocks if s.id not in have_s]
    m.flows += [copy.deepcopy(f) for f in draft.flows if f.id not in have_f]
    return m


def _summary(mode: str, r: dict) -> dict:
    if mode == "forward":
        return {"horizon_s": r["horizon_s"], "trusted": r["trusted"], "limits": len(r["limits"]),
                "stocks": {sid: {"base": (s["base"] or {}).get("central", [None])[-1], "experiment": (s["experiment"] or {}).get("central", [None])[-1]}
                           for sid, s in list(r["stocks"].items())[:32]}}
    if mode == "replay":
        return {"window": [r["start"], r["end"]], **r["summary"]}
    return {"reached": r["reached"], "count": r["count"], "experiment": r.get("experiment"), "ambiguous": r.get("ambiguous"),
            "stopped": r.get("stopped")}
