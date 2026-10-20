"""none-long only confirms a current none-short pass (the user, 2026-10-20)."""

from sdlab.ladder import cases as casemod, runner


def test_confirm_of_names_the_short_noise_free_run():
    c = casemod.load("001-inflow-only")
    by = {v["name"]: v for v in c["variants"]}
    assert runner.confirm_of(c, by["none-long"]) == "none-short"
    for name in ("none-short", "counts-short", "counts-long"):
        assert runner.confirm_of(c, by[name]) is None


def test_plan_skips_none_long_without_a_short_pass(monkeypatch):
    s = [x for x in runner.select_strategies("matrix")[0]]
    monkeypatch.setattr(runner.store, "latest", lambda *a, **k: [])          # nothing stored: the short run is not there yet
    items = runner.plan(["001-inflow-only"], s)
    assert {i["variant"] for i in items} >= {"none-short"} and "none-long" not in {i["variant"] for i in items}
    assert "none-long" in {i["variant"] for i in runner.plan(["001-inflow-only"], s, every_variant=True)}
    assert "none-long" in {i["variant"] for i in runner.plan(["001-inflow-only"], s, ["none-long"])}
