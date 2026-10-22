"""Demo 16, verify an AI agent's effect (sdlab/demos/agent_verify.py, agent_verify_des.py): the event simulation is
deterministic, keeps its counts consistent, gives the run with the agent and the run without it the same items
before the agent starts (common random numbers), and its log is the truth the verdicts read; the design's edit and
the verdict rules do what they say; the routes answer from the cache (skipped when it is absent:
`uv run python -m sdlab.demos.agent_verify precompute`)."""

import pytest

from sdlab.demos import agent_verify as A
from sdlab.demos import agent_verify_des as DES


def test_des_is_deterministic_and_conserves_items():
    a, b = DES.run(24 * 7, seed=3), DES.run(24 * 7, seed=3)
    assert a["samples"] == b["samples"] and a["events"] == b["events"]
    s = a["samples"]
    for i in range(len(a["t"])):                       # every item is in exactly one state
        assert s["queued"][i] + s["in_triage"][i] + s["in_fix"][i] + s["resolved"][i] == sum(s["new_items"][: i + 1])
    over = [i for i in range(len(a["t"])) if s["in_triage"][i] > s["engineers"][i] + 1e-6]
    assert max(s["in_triage"]) <= 5 and len(over) < 0.05 * len(a["t"])      # one item an engineer (a shift may end mid-triage)
    assert DES.run(24 * 7, seed=4)["samples"] != s


def test_agent_changes_nothing_before_it_starts_and_its_log_adds_up():
    without, good = A.des(None), A.des("good")
    for k in A.STOCKS + A.INPUTS:
        assert without["samples"][k][: A.T] == good["samples"][k][: A.T]
    assert without["samples"]["new_items"] == good["samples"]["new_items"]      # the same arrivals after it too
    c = good["counts"]
    assert c["agent_takes"] >= c["agent_resolves"] + c["agent_misroutes"] + c["agent_hands_off"] - DES.AGENTS["good"]["slots"]
    assert all(e[0] >= A.DEPLOY_H for e in good["events"] if e[1] == "agent")
    assert not any(e[1] == "agent" for e in without["events"])


def test_truth_reads_the_designed_shares_from_the_log():
    for v, cfg in DES.AGENTS.items():
        t = A.truth(v)
        assert t["resolve_share"] == pytest.approx(cfg["resolve"], abs=0.03)
        assert t["misroute_share"] == pytest.approx(cfg["misroute"], abs=0.02)
    assert A.truth("misrouting")["reopens_per_day"]["extra"] > 3 * A.reopen_allowance(A.truth("good")["new_per_day"])
    assert A.truth("good")["queue"]["change"] < -0.5


def test_design_edit_adds_the_agent_flow_and_speeds_triage():
    flows = [{"from": "queued", "to": "in_triage", "rate": {"form": "expr", "expr": "min(0.9 * queued, 0.6 * engineers)"}},
             {"from": "in_triage", "to": "resolved", "rate": {"form": "proportional", "stock": "in_triage", "k": 0.5}}]
    edited, edits = A.design_edit(flows)
    assert edited[1]["rate"]["k"] == pytest.approx(0.5 / A.DESIGN["note_factor"])
    assert "0.6" not in edited[0]["rate"]["expr"] and "0.9 * queued" in edited[0]["rate"]["expr"]
    assert edited[-1]["from"] == "queued" and edited[-1]["to"] == "resolved" and "new_items" in edited[-1]["rate"]["expr"]
    assert len(edits) == 3


def test_verdict_words():
    allow = 2.5
    ok = {"queue": -0.6, "hours_open": -0.4, "reopens_extra": 1.0, "met": [True, True, None]}
    assert A.word(ok, allow) == "yes"
    assert A.word({**ok, "met": [True, False]}, allow) == "partly"
    assert A.word({**ok, "queue": -0.2}, allow) == "no"                       # less than half the -50% target
    assert A.word({**ok, "reopens_extra": 10.0}, allow) == "no"               # a harmful side effect
    assert A.word({**ok, "reopens_extra": None}, allow) == "yes"              # not seen: not judged


needs_cache = pytest.mark.skipif(not A.available(), reason="no cached found model (run precompute)")


@needs_cache
def test_routes_answer_from_the_cache():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    ov = c.get("/api/demos/agent-verify/overview").json()
    assert ov["strategies"] and set(ov["variants"]) == {"good", "weak", "misrouting"}
    s = ov["strategies"][0]
    words = {}
    for v in ov["variants"]:
        r = c.get(f"/api/demos/agent-verify/verify?strategy={s}&variant={v}").json()
        words[v] = r["verdict"]["word"]
        assert len(r["verdict"]["claims"]) == 6 and len(r["charts"]["observed"]["queued"]) == len(r["charts"]["t_days"])
        assert r["log"] and r["true"]["new_items"] > 1000
    assert words == {"good": "yes", "weak": "partly", "misrouting": "no"}
    assert c.get(f"/api/demos/agent-verify/verify?strategy={s}&variant=nope").status_code == 404
