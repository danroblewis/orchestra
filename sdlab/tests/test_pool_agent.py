"""What agents use of the pool (pool/agent.py): run's and sync's size guard, submit's refusals, job's summary."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from sdlab.ladder import cli
from sdlab.ladder.pool import agent, gitcode


def _items(n, mode="run"):
    return [{"case": "001-x", "variant": "none-short", "strategy": f"s{i}", "mode": mode} for i in range(n)]


def _args(**kw):
    base = dict(strategies="lna", cases="tag:loop", exclude_cases=None, variants=None, local=False)
    return SimpleNamespace(**{**base, **kw})


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "local-runs.log"
    monkeypatch.setenv("SDLAB_LOCAL_RUNS_LOG", str(p))
    return p


def test_a_small_run_goes_ahead(monkeypatch, log):
    monkeypatch.setattr(agent, "busy_seconds", lambda items: 30.0)
    assert agent.guard(_args(), _items(10), "run")
    assert not log.exists()


def test_too_many_items_is_refused_with_the_submit_command(monkeypatch, log, capsys):
    monkeypatch.setattr(agent, "busy_seconds", lambda items: pytest.fail("not needed above the item limit"))
    assert not agent.guard(_args(), _items(agent.SMALL_ITEMS + 1), "sync")
    err = capsys.readouterr().err
    assert "uv run sdlab-ladder submit --strategies lna --cases tag:loop --stale" in err and "--local" in err
    assert not log.exists()


def test_too_much_time_is_refused(monkeypatch, log, capsys):
    monkeypatch.setattr(agent, "busy_seconds", lambda items: agent.SMALL_SECONDS + 1)
    assert not agent.guard(_args(), _items(3), "run")
    assert "--stale" not in capsys.readouterr().err                  # run: every cell again, as submit's default


def test_local_overrides_and_is_logged(monkeypatch, log):
    monkeypatch.setattr(agent, "busy_seconds", lambda items: 900.0)
    assert agent.guard(_args(local=True), _items(5), "run")
    entry = json.loads(log.read_text().splitlines()[-1])
    assert entry["command"] == "run" and entry["items"] == 5 and entry["busy_seconds"] == 900.0


def test_the_cli_refuses_a_large_run_before_running(monkeypatch, log):
    from sdlab.ladder import runner
    monkeypatch.setattr(runner, "plan", lambda *a, **k: _items(agent.SMALL_ITEMS + 5))
    monkeypatch.setattr(runner, "execute", lambda *a, **k: pytest.fail("ran"))
    assert cli.main(["run", "--strategies", "matrix", "--cases", "001", "--quiet"]) == 3


def test_busy_seconds_counts_runs_and_rescores(monkeypatch):
    from sdlab.ladder import cost, timing
    monkeypatch.setattr(timing, "table", lambda: SimpleNamespace(latest={}))
    monkeypatch.setattr(timing, "case_sets", lambda ids: {})
    monkeypatch.setattr(timing, "Estimator", lambda t, sets: None)
    monkeypatch.setattr(cost, "estimate", lambda keys, mode, est: {"seconds": len(keys) * (10.0 if mode == "run" else 1.0)})
    assert agent.busy_seconds(_items(2) + _items(3, "rescore")) == 23.0


# ---- submit ----

def _submit_args(**kw):
    base = dict(strategies="matrix", cases="001", exclude_cases=None, variants=None, stale=False, ref=None, by="t", note=None,
                priority=100, timeout=300, check_tree="all", behind_ok=False, estimate_only=False, server="http://x")
    return SimpleNamespace(**{**base, **kw})


def test_submit_refuses_uncommitted_code(monkeypatch, capsys):
    monkeypatch.setattr(gitcode, "resolve", lambda ref: "a" * 40)
    monkeypatch.setattr(gitcode, "checkout_head", lambda: "a" * 40)
    monkeypatch.setattr(gitcode, "dirty", lambda names, harness: ["sdlab/sdlab/discovery/strategies/matrix.py"])
    monkeypatch.setattr(agent, "_call", lambda *a, **k: pytest.fail("submitted"))
    assert agent.submit(_submit_args(ref="sdlab")) == 1
    assert "matrix.py" in capsys.readouterr().err


def test_submit_refuses_a_branch_behind_the_main_line(monkeypatch, capsys):
    monkeypatch.setattr(gitcode, "resolve", lambda ref: {"feat": "b" * 40, "sdlab": "c" * 40}[ref])
    monkeypatch.setattr(gitcode, "checkout_head", lambda: "c" * 40)
    monkeypatch.setattr(gitcode, "is_ancestor", lambda a, b: False)
    monkeypatch.setattr(agent, "_git", lambda *a: "3")
    monkeypatch.setattr(agent, "_call", lambda *a, **k: pytest.fail("submitted"))
    assert agent.submit(_submit_args(ref="feat")) == 1
    assert "lacks 3 commits" in capsys.readouterr().err


def test_submit_sends_fresh_unless_stale(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(gitcode, "resolve", lambda ref: "c" * 40)
    monkeypatch.setattr(gitcode, "checkout_head", lambda: "d" * 40)
    monkeypatch.setattr(agent, "_estimate", lambda a: (4, 10.0))

    def call(server, method, path, body=None, token=True):
        sent.append(body)
        return 202, {"job": {"id": 7, "commit": "c" * 40, "ref": body["ref"], "state": "planning"}}
    monkeypatch.setattr(agent, "_call", call)
    assert agent.submit(_submit_args(ref="sdlab")) == 0
    assert agent.submit(_submit_args(ref="sdlab", stale=True)) == 0
    assert [b["fresh"] for b in sent] == [True, False]
    assert "job 7 at" in capsys.readouterr().out


# ---- job ----

JOB = {"id": 5, "kind": "agent", "by": "t", "priority": 100, "commit": "c" * 40, "state": "done", "total": 3, "error": None,
       "created": "2026-10-20T10:00:00.000Z", "started": "2026-10-20T10:00:00.000Z", "finished": "2026-10-20T10:01:30.000Z",
       "counts": {"queued": 0, "leased": 0, "done": 2, "reused": 1, "error": 0, "cancelled": 0}, "statuses": {}}
RESULTS = [{"item_id": 1, "case": "001", "variant": "none-short", "strategy": "matrix", "status": "pass", "seconds": 0.5, "machine": "node2", "slot": 3},
           {"item_id": 2, "case": "002", "variant": "none-short", "strategy": "matrix", "status": "fail", "seconds": 0.7, "machine": "mac", "slot": 1},
           {"item_id": 3, "case": "003", "variant": "none-short", "strategy": "matrix", "state": "reused", "status": "pass"}]


def test_the_summary_is_runs():
    assert agent.summary(JOB, RESULTS) == "job 5: 3 done in 90.0 s: 2 pass, 1 fail (1 reused)"


def test_job_wait_polls_until_it_ends(monkeypatch, capsys):
    states = iter(["running", "running", "done"])

    def call(server, method, path, body=None, token=True):
        if path.endswith("/results?full=0") or path.endswith("/results?full=1"):
            return 200, {"results": RESULTS}
        return 200, {"job": {**JOB, "state": next(states)}}
    monkeypatch.setattr(agent, "_call", call)
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)
    a = SimpleNamespace(job=5, wait=True, json=False, quiet=False, every=0, server="http://x")
    assert agent.job(a) == 0
    out, err = capsys.readouterr()
    assert out.strip().splitlines()[-1] == "job 5: 3 done in 90.0 s: 2 pass, 1 fail (1 reused)"
    assert err.count("[1/3]") == 1 and "on node2/3" in err
