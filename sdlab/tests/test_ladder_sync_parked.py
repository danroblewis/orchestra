"""Harness fixes from the kubernetes 303 review: `sync` covers parked (still active) strategies, and
the analyse text report handles a noisy variant's Kalman parameters."""

from sdlab.ladder import analysis_report, runner


def _fake(monkeypatch):
    listing = [{"name": n, "available": True, "hash": n} for n in ("main", "slow", "old")]
    monkeypatch.setattr(runner.catalog, "listing", lambda: listing)
    monkeypatch.setattr(runner, "parked", lambda: {"slow": "slow"})
    monkeypatch.setattr(runner, "retired", lambda: {"old": "gone"})


def test_all_skips_parked_but_sync_does_not(monkeypatch):
    _fake(monkeypatch)
    names = lambda spec, **kw: [s["name"] for s in runner.select_strategies(spec, **kw)[0]]  # noqa: E731
    assert names("all") == ["main"]
    assert names(None) == ["main"]
    assert names("all", parked_too=True) == ["main", "slow"]          # retired stay out
    assert names(None, parked_too=True) == ["main", "slow"]
    assert names("everything") == ["main", "slow"]
    assert names("main", parked_too=True) == ["main"]                 # a named list is taken as given


def test_text_report_handles_kalman_parameters():
    a = {"variant": "meas-short", "steps": 300, "noise": "meas", "label": "achievable", "design": [],
         "parameters": [{"name": "requests.k", "true": 1.0, "se_kalman": 0.0045, "unidentified": False}]}
    out = analysis_report.text(a)
    assert "requests.k" in out and "0.0045" in out and "(Kalman)" in out
    a["parameters"] = [{"name": "k", "true": 1.0, "crb_se": 0.003, "crb_se_mean_only": 0.004, "unidentified": True}]
    out = analysis_report.text(a)
    assert "mean only 0.004" in out and "NOT IDENTIFIED" in out
