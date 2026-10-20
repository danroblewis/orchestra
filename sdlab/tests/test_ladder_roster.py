from sdlab.ladder import runner


def test_roster_kubernetes_is_everything_less_the_eliminated():
    out = runner.roster("kubernetes")
    every = {s["name"] for s in runner.select_strategies("everything")[0] + runner.select_strategies("everything")[1]}
    got = {s["name"] for s in runner.select_strategies("roster:kubernetes")[0] + runner.select_strategies("roster:kubernetes")[1]}
    assert got == every - set(out)
    for name, e in out.items():
        assert e["kind"] in ("impossible", "duplicate", "not-entered") and e.get("reason") and e.get("rung")
        assert e["kind"] != "duplicate" or e.get("of") in got
