"""Sparse own data widens the window (sd.rediscover.sparse_window): the standing demo ran from
2026-11-02 with one ticket every four hours, beside agents' counters that count every minute, so no
counter was short of events and the 60-minute window was never widened; its levels moved in too
few live steps and no version was ever saved. When every level judged moved in fewer than
MIN_STEPS live steps and the own series span longer, the window widens in whole multiples of the
configured one, the step scaled alike, to the shortest that holds MIN_STEPS moving steps."""

from __future__ import annotations

from types import SimpleNamespace

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd import rediscover as rd
from orchestra.sd.strategies import CONSERVATION

NOW = 1_800_000_000.0


def _project(tmp_path):
    return SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=30.0,
        discovery_every=300.0, eras_from=None, prior_for=None))


def _board(tmp_path, hours: float, every_h: float) -> FileMetrics:
    """A board's level and its two counters, written each minute for ``hours`` up to now: one
    ticket added every ``every_h`` hours, each moved out two hours and three minutes later; and an agents' counter
    that counts a few turns every minute, so no window is short of counted events."""
    adds = [NOW - hours * 3600 + (k + 0.5) * every_h * 3600 for k in range(int(hours / every_h))]
    m, pts = FileMetrics(tmp_path / "m.jsonl"), []
    board = {"instrument": "board", "board": "b", "project": "p"}
    for i in range(int(hours * 60) + 1):
        t = NOW - hours * 3600 + 60 * i
        na, no = sum(x <= t for x in adds), sum(x + 7380 <= t for x in adds)
        pts += [Point("board_items", float(na - no), t, board), Point("board_items_added_total", float(na), t, board),
                Point("board_items_moved_total", float(no), t, board),
                Point("agent_turns_total", float(3 * i + i // 7), t, {"instrument": "agents", "project": "p"})]
    m.write(pts)
    return m


def test_one_move_every_four_hours_over_two_days_gets_a_model_by_a_widened_window(tmp_path):
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 48.0, 4.0), now=NOW, collectors=[])
    d = r.model.discovery
    assert r.version == 1 and r.model.stocks, d.get("level_steps")
    w = d["widened"]
    assert w["from_s"] == 3600.0 and w["sparse"] == {"from_s": 3600.0, "needed": 5}
    assert 3600.0 < d["window_s"] <= 48 * 3600.0 and d["step_s"] / d["window_s"] == 30.0 / 3600.0   # the step scaled alike
    assert d["window_s"] % 3600.0 == 0 and "widened for sparse data" in w["why"]


def test_dense_data_keeps_the_default_window(tmp_path):
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 48.0, 0.1), now=NOW, collectors=[])
    d = r.model.discovery
    assert r.model.stocks and "widened" not in d and d["window_s"] == 3600.0 and d["step_s"] == 30.0
    assert d["level_steps"]["levels"] >= 1 and not d["level_steps"]["sparse"]


def test_sparse_data_no_longer_than_the_window_is_not_widened(tmp_path):
    r = rd.rediscover(_project(tmp_path), _board(tmp_path, 1.0, 4.0), now=NOW, collectors=[])
    assert "widened" not in r.model.discovery and r.model.discovery["window_s"] == 3600.0


def test_the_era_bounds_the_sparse_window():
    m = rd.Model("system", "The system")
    m.discovery = {"level_steps": {"levels": 1, "sparse": {"x": 1}, "needed": 5}}
    moves = [(NOW - 48 * 3600 + 60 * i, float((i // 240) % 2)) for i in range(48 * 60)]     # a move every 4 h
    reading = SimpleNamespace(dump=[("x", {}, moves)], provenance={})
    w = rd.sparse_window(m, reading, 3600.0, 30.0, NOW, None)
    assert w is not None and w[0] >= 16 * 3600 and w[1] == 30.0 * w[0] / 3600.0
    assert rd.sparse_window(m, reading, 3600.0, 30.0, NOW, NOW - 6 * 3600) is None          # 6 h of era: never five moves
    m.discovery["level_steps"]["levels"] = 2                                                  # one level had the steps
    assert rd.sparse_window(m, reading, 3600.0, 30.0, NOW, None) is None
