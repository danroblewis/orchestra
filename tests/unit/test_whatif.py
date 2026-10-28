"""What if (sd/whatif.py): a change's prediction against no change, with a band, the limits it
meets and where the model is not to be trusted.

- on a model with a known solution, the trajectories are the analytic ones;
- on the bakery's model (``fixtures/sd/bakery-whatif.json.gz``: the conservation discovery of the
  bakery's export, round 6, over the hour before 1793046690, and the web server's history at its
  end), a faster bottleneck moves its stocks the way a reader expects, and the answer is what the
  model's own simulation (``sd.simulate``) gives for the same model, changed the same way;
- weak, declared, net and replayed equations are not trusted;
- the web endpoint answers what the function answers, and changes nothing."""

import copy
import gzip
import json
import math
import subprocess
import time
from pathlib import Path

import pytest

from orchestra.sd.model import Equation, Flow, Model, Stock
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")

BAKERY = Path(__file__).parent.parent / "fixtures" / "sd" / "bakery-whatif.json.gz"
C, K, L0 = 2.0, 0.1, 5.0           # per minute: in at C, out at K × the level


def queue(**quality) -> Model:
    q = {"events": 400.0, "dispersion": 1.0, **quality}
    return Model("m", "m", time_unit="minute", stocks=[Stock("q", "queue")],
                 flows=[Flow("in", "in", None, "q", equations=[Equation("constant", {"c": C}, "fitted", "poisson-mle", quality=dict(q))]),
                        Flow("out", "out", "q", None, equations=[Equation("proportional", {"k": K}, "fitted", "poisson-mle",
                                                                          inputs=["q"], quality=dict(q))])])


def history(level: float = L0, now: float = 3600.0, lo: float | None = None, hi: float | None = None) -> dict:
    pts = [[0.0, lo if lo is not None else level], [now / 2, hi if hi is not None else level], [now, level]]
    return {"at": now, "start": 0.0, "stocks": {"q": pts}, "flows": {}, "inputs": {}}


def analytic(c: float, k: float, l0: float, t_s: float) -> float:
    return c / k + (l0 - c / k) * math.exp(-k * t_s / 60)


def what_if(m, h, ivs, **kw):
    from orchestra.sd.whatif import what_if as run
    return run(m, h, ivs, **kw)


@pytest.mark.parametrize(("iv", "c", "k", "l0"), [
    ({"kind": "scale_flow", "flow": "in", "factor": 1.5}, 1.5 * C, K, L0),
    ({"kind": "add_flow", "flow": "in", "amount": 1.0}, C + 1.0, K, L0),
    ({"kind": "add_flow", "flow": "in", "amount": -0.5}, C - 0.5, K, L0),
    ({"kind": "scale_flow", "flow": "out", "factor": 2.0}, C, 2 * K, L0),
    ({"kind": "set_param", "flow": "out", "param": "k", "value": 0.05}, C, 0.05, L0),
    ({"kind": "set_stock", "stock": "q", "level": 40.0}, C, K, 40.0),
])
def test_one_stock_with_an_inflow_and_a_proportional_outflow_follows_its_analytic_solution(iv, c, k, l0):
    r = what_if(queue(), history(), [iv], horizon_s=3600, step_s=1, members=0)
    s = r["stocks"]["q"]
    for t, base, changed in zip(r["t"], s["baseline"]["central"], s["intervention"]["central"]):
        assert base == pytest.approx(analytic(C, K, L0, t), rel=2e-3, abs=1e-3)
        assert changed == pytest.approx(analytic(c, k, l0, t), rel=2e-3, abs=1e-3)
    assert r["stocks"]["q"]["difference"]["central"][-1] == pytest.approx(analytic(c, k, l0, 3600) - analytic(C, K, L0, 3600), abs=0.05)


def test_the_steps_are_euler_steps_exactly():
    # step g minutes: L ← L + C g − K g L, so L_n = C/K + (L0 − C/K)(1 − K g)^n
    r = what_if(queue(), history(), [], horizon_s=600, step_s=60, members=0)
    for n, v in enumerate(r["stocks"]["q"]["baseline"]["central"]):
        assert v == pytest.approx(C / K + (L0 - C / K) * (1 - K) ** n, abs=1e-3)


def test_an_input_changed_moves_what_reads_it():
    m = Model("m", "m", time_unit="minute", stocks=[Stock("q", "queue")],
              flows=[Flow("in", "in", None, "q", equations=[Equation("proportional", {"k": 1.0}, "fitted", inputs=["input:demand"],
                                                                      quality={"events": 400.0})]),
                     Flow("out", "out", "q", None, equations=[Equation("proportional", {"k": K}, "fitted", inputs=["q"],
                                                                        quality={"events": 400.0})])])
    h = {**history(), "inputs": {"demand": [[0.0, 2.0], [3600.0, 2.0]]}}
    for iv, c in (({"kind": "set_input", "input": "demand", "value": 3.0}, 3.0), ({"kind": "scale_input", "input": "demand", "factor": 0.5}, 1.0)):
        r = what_if(m, h, [iv], horizon_s=3600, step_s=1, members=0)
        assert r["stocks"]["q"]["baseline"]["central"][-1] == pytest.approx(analytic(2.0, K, L0, 3600), rel=2e-3)
        assert r["stocks"]["q"]["intervention"]["central"][-1] == pytest.approx(analytic(c, K, L0, 3600), rel=2e-3)


def test_the_band_comes_from_the_recorded_error_and_holds_the_central_run():
    sure = what_if(queue(events=10_000.0), history(), [{"kind": "scale_flow", "flow": "in", "factor": 1.5}], horizon_s=3600, members=64)
    loose = what_if(queue(events=25.0), history(), [{"kind": "scale_flow", "flow": "in", "factor": 1.5}], horizon_s=3600, members=64)
    assert loose["band"]["spread"]["in"]["rel"] == pytest.approx(1 / 5)          # sqrt(1 / 25 events)
    assert sure["band"]["spread"]["in"]["rel"] == pytest.approx(1 / 100)
    width = lambda r, run: r["stocks"]["q"][run]["hi"][-1] - r["stocks"]["q"][run]["lo"][-1]
    assert width(loose, "intervention") > 5 * width(sure, "intervention") > 0
    for r in (sure, loose):
        for run in ("baseline", "intervention", "difference"):
            b = r["stocks"]["q"][run]
            assert b["lo"][-1] <= b["central"][-1] <= b["hi"][-1]
    # the same draws for both runs: the difference's band is narrower than either run's
    assert width(loose, "difference") < width(loose, "intervention")
    again = what_if(queue(events=25.0), history(), [{"kind": "scale_flow", "flow": "in", "factor": 1.5}], horizon_s=3600, members=64)
    assert again == loose                                              # seeded: the same question, the same answer


def test_a_stock_drained_below_zero_meets_its_floor():
    r = what_if(queue(), history(), [{"kind": "scale_flow", "flow": "in", "factor": 0.0},
                                     {"kind": "add_flow", "flow": "out", "amount": 1.0}], horizon_s=3600, step_s=15,
                bounds={"q": (2.0, None)})
    floor = next(x for x in r["limits"] if x["run"] == "intervention" and x["kind"] == "floor")
    # out at 0.1 q + 1 per minute, nothing in: q = (L0 + 10) e^(−0.1 t) − 10 reaches 0 at t = 10 ln(1.5) min
    assert floor["at_s"] == pytest.approx(600 * math.log(1.5), abs=20) and floor["new"] and floor["members"] == 1.0
    assert min(r["stocks"]["q"]["intervention"]["central"]) == 0.0
    below = next(x for x in r["limits"] if x["run"] == "intervention" and x["kind"] == "below bound")
    assert below["bound"] == 2.0 and below["at_s"] < floor["at_s"]
    assert not any(x["run"] == "baseline" for x in r["limits"])


def test_leaving_the_observed_range_is_extrapolation():
    r = what_if(queue(), history(level=20.0, lo=15.0, hi=25.0), [{"kind": "scale_flow", "flow": "in", "factor": 3.0}], horizon_s=7200)
    s = r["stocks"]["q"]
    assert not s["trusted"] and any(w.startswith("extrapolation: leaves the observed range 15–25") for w in s["why"])
    calm = what_if(queue(), history(level=20.0, lo=15.0, hi=25.0), [{"kind": "scale_flow", "flow": "in", "factor": 1.05}], horizon_s=7200)
    assert calm["stocks"]["q"]["trusted"] and calm["trusted"]


@pytest.mark.parametrize(("change", "says"), [
    (lambda m: setattr(m.flows[0].equations[0], "origin", "declared"), "declared: an assumption"),
    (lambda m: [f.equations[0].quality.update(events=6.0) for f in m.flows], "fitted on 6 events"),
    (lambda m: m.flows[0].equations[0].quality.update(r2=0.2, stretches=40.0), "fitted at R² 0.20"),
    (lambda m: m.flows[0].evidence.update(net_flow_of="q"), "a net flow"),
    (lambda m: setattr(m.flows[0], "equations", [Equation("expr", {}, "discovered", spec={"form": "expr", "expr": "2"})]), "replayed"),
])
def test_a_weak_or_declared_equation_is_not_trusted(change, says):
    # the history spans the run, so nothing else counts against it
    m = queue()
    change(m)
    assert what_if(queue(), history(lo=0.0, hi=25.0), [], horizon_s=600)["trusted"]
    r = what_if(m, history(lo=0.0, hi=25.0), [{"kind": "scale_flow", "flow": "out", "factor": 1.01}], horizon_s=600)
    assert not r["trusted"] and not r["stocks"]["q"]["trusted"]
    flow = next(x for x in r["not_trusted"] if x["kind"] == "flow")
    assert flow["id"] == "in" and any(says in w for w in flow["why"])
    assert any(says in w for w in r["stocks"]["q"]["why"])


def test_a_declared_equation_gets_a_wide_band_said_as_assumed():
    m = queue()
    m.flows[0].equations[0].origin = "declared"
    r = what_if(m, history(), [], horizon_s=600)
    assert r["band"]["spread"]["in"]["rel"] == 0.5 and "assumed" in r["band"]["spread"]["in"]["how"]


def test_a_hidden_stock_and_a_model_that_misses_its_own_history_are_not_trusted():
    m = queue()
    m.stocks.append(Stock("h", "hidden", evidence={"hidden": True}))
    m.flows.append(Flow("leak", "leak", "q", "h", equations=[Equation("proportional", {"k": 0.01}, "fitted", inputs=["q"],
                                                                      quality={"events": 400.0})]))
    # the queue was measured going up and down, which a constant inflow and a proportional outflow never do
    h = history()
    h["stocks"]["q"] = [[t, 5.0 + 4 * math.sin(t / 300)] for t in range(0, 3601, 15)]
    r = what_if(m, h, [], horizon_s=600)
    assert any(w.startswith("hidden") for w in r["stocks"]["h"]["why"])
    assert any("misses its measured level" in w for w in r["stocks"]["q"]["why"])
    assert not r["trusted"]


def test_bad_questions_say_what_is_wrong():
    from orchestra.sd.whatif import check
    for iv, says in (({"kind": "scale_flow", "flow": "nope", "factor": 2}, "no flow 'nope'"),
                     ({"kind": "explode"}, "unknown intervention"),
                     ({"kind": "scale_flow", "flow": "in"}, "needs factor"),
                     ({"kind": "scale_flow", "flow": "in", "factor": -1}, "at least 0"),
                     ({"kind": "set_input", "input": "x", "value": 1}, "no input 'x'")):
        with pytest.raises(ValueError, match=says):
            check(queue(), history(), [iv])
    with pytest.raises(ValueError, match="no parameter 'z'"):
        what_if(queue(), history(), [{"kind": "set_param", "flow": "out", "param": "z", "value": 1}])
    with pytest.raises(ValueError, match="no stock"):
        what_if(queue(), history(), [], stocks=["nope"])


# the bakery

def bakery() -> tuple[Model, dict]:
    with gzip.open(BAKERY, "rt") as fh:
        d = json.load(fh)
    return Model.from_json(d["model"]), d["history"]


def test_on_the_bakery_a_faster_bottleneck_moves_its_stocks_as_a_reader_expects():
    m, h = bakery()
    # orders pile up waiting (2 → 13 over the next half hour): assigning them to bakers faster
    # empties the waiting queue and, at first, fills the ovens
    r = what_if(m, h, [{"kind": "scale_flow", "flow": "bakery_orders_assigned_total", "factor": 1.5}], horizon_s=1800,
                stocks=["bakery_orders_waiting", "bakery_orders_baking"])
    waiting, baking = (r["stocks"][s]["difference"] for s in ("bakery_orders_waiting", "bakery_orders_baking"))
    assert waiting["central"][-1] < 0 and waiting["hi"][-1] < 0 and max(waiting["central"]) <= 1e-9
    assert max(baking["central"][:5]) > 0.1
    rate = r["flows"]["bakery_orders_assigned_total"]
    assert rate["intervention"] == pytest.approx(1.5 * rate["baseline"])
    # baking faster empties the ovens and, at first, fills inspection
    r = what_if(m, h, [{"kind": "scale_flow", "flow": "bakery_orders_baked_total", "factor": 1.5}], horizon_s=1800,
                stocks=["bakery_orders_baking", "bakery_orders_inspecting"])
    baking, inspecting = (r["stocks"][s]["difference"] for s in ("bakery_orders_baking", "bakery_orders_inspecting"))
    assert baking["central"][-1] < 0 and baking["hi"][-1] < 0
    assert max(inspecting["central"][:5]) > 0.1


def test_on_the_bakery_the_answer_is_the_models_own_simulation():
    from orchestra.sd.simulate import simulate

    m, h = bakery()
    r = what_if(m, h, [{"kind": "scale_flow", "flow": "bakery_orders_baked_total", "factor": 1.5}],
                horizon_s=1800, step_s=15, members=0, points=0)
    same = simulate(m, h, now=h["at"], start=h["start"], horizon_s=1800, step_s=15)["projection"]
    changed = copy.deepcopy(m)
    changed.flow("bakery_orders_baked_total").current().params["k"] *= 1.5
    faster = simulate(changed, h, now=h["at"], start=h["start"], horizon_s=1800, step_s=15)["projection"]
    for sid, s in r["stocks"].items():
        assert s["baseline"]["central"] == pytest.approx([v for _, v in same[sid]], abs=1e-3)
        assert s["intervention"]["central"] == pytest.approx([v for _, v in faster[sid]], abs=1e-3)


def test_on_the_bakery_weak_flows_are_named_and_rare_ones_do_not_condemn_a_busy_stock():
    m, h = bakery()
    r = what_if(m, h, [{"kind": "scale_flow", "flow": "bakery_orders_assigned_total", "factor": 1.5}], horizon_s=1800)
    weak = {x["id"]: x["why"] for x in r["not_trusted"] if x["kind"] == "flow"}
    assert weak["bakery_bake_leases_expired_total"] == ["fitted on 3 events"]
    assert r["stocks"]["bakery_orders_waiting"]["trusted"]      # its rare flows carry under a tenth of its busiest
    assert not r["stocks"]["bakery_orders_accepting"]["trusted"]
    assert any("misses its measured level" in w for w in r["stocks"]["bakery_orders_accepting"]["why"])


def test_the_command_line_reads_its_words_and_prints_a_table():
    from orchestra.sd import whatif_report as report

    ivs = report.interventions("in", 1.5, None, ["q=3"], [], [], ["out.k=0.2"])
    assert ivs == [{"kind": "scale_flow", "flow": "in", "factor": 1.5}, {"kind": "set_stock", "stock": "q", "level": "3"},
                   {"kind": "set_param", "flow": "out", "param": "k", "value": "0.2"}]
    assert report.bounds(["q=:30", "p=1:"]) == {"q": (None, 30.0), "p": (1.0, None)}
    with pytest.raises(ValueError, match="need --flow"):
        report.interventions(None, 1.5)
    r = what_if(queue(), history(), ivs, horizon_s=1800, label={"version": 3})
    text = "\n".join(report.table(r))
    assert "flow in × 1.5" in text and "version 3" in text and "q " in text and "verdict:" in text


# the web endpoint

def _project(tmp_path, monkeypatch):
    from orchestra.config import init_project, load_project
    from orchestra.metrics import Point, for_project
    from orchestra.sd.model import SeriesRef
    from orchestra.sd.store import ModelStore

    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    init_project(repo)
    project = load_project(repo)
    lab = {"machine": "board"}
    now = time.time()
    for_project(project).write([Point("queue_depth", 10 + 5 * math.sin(ago / 400), now - ago, {**lab, "project": project.key})
                                for ago in range(3000, 0, -30)])
    m = queue()
    m.stocks[0].series = SeriesRef("queue_depth", lab)
    models = ModelStore.for_state(project.state_dir)
    models.save(m, note="test")
    models.write_discovery(m)
    return project, m


def test_the_endpoint_answers_what_the_function_answers_and_changes_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from orchestra.sd.store import ModelStore
    from orchestra.sd.whatif import what_if as run
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer

    project, m = _project(tmp_path, monkeypatch)
    models = ModelStore.for_state(project.state_dir)
    before = sorted((p.name, p.stat().st_mtime) for p in models.dir.iterdir())
    c = TestClient(create_app(project), headers=bearer(project))
    body = {"interventions": [{"kind": "scale_flow", "flow": "in", "factor": 1.5}], "horizon_s": 1800, "members": 8,
            "bounds": {"q": [None, 30]}}
    deadline = time.time() + 30
    while time.time() < deadline:
        h = c.get("/api/dynamics/history").json()
        if h.get("ok") and h["stocks"].get("q"):
            got = c.post("/api/dynamics/whatif", json=body).json()
            if got.get("ok") and got["now"] == h["at"]:
                break
        time.sleep(0.2)
    assert got["ok"], got
    want = run(m, h, body["interventions"], horizon_s=1800, members=8, bounds={"q": (None, 30)},
               label={"version": None, "latest_discovery_at": got["model"]["latest_discovery_at"], "current_version": 1})
    assert got == {"ok": True, **json.loads(json.dumps(want))}
    assert c.post("/api/dynamics/whatif", json={"interventions": [{"kind": "scale_flow", "flow": "nope", "factor": 2}]}).json() == {
        "ok": False, "error": "no flow 'nope' in the model; its flows: in, out"}
    assert sorted((p.name, p.stat().st_mtime) for p in models.dir.iterdir()) == before      # no version saved, nothing rewritten


def test_orchestra_sd_whatif_prints_the_table_or_the_json(tmp_path, monkeypatch, capsys):
    from orchestra import cli

    project, _ = _project(tmp_path, monkeypatch)
    argv = ["--repo", str(project.repo_root), "sd", "whatif", "--flow", "in", "--scale", "1.5", "--horizon", "10m"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "what if flow in × 1.5" in out and "10 min ahead" in out and "verdict:" in out
    assert cli.main([*argv, "--json", "--members", "4"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["band"]["members"] == 4 and r["stocks"]["q"]["start"]["baseline"] == pytest.approx(10 + 5 * math.sin(30 / 400), abs=0.5)
    assert cli.main([*argv[:4], "--flow", "nope", "--scale", "2"]) == 2
    assert "no flow 'nope'" in capsys.readouterr().err
