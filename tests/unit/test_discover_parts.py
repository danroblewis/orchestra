"""Levels that are parts of one quantity (pods by region) and their total: a part is never
another part's or the total's twin, and a level is never balanced by the counters of another
level of the same name (a counter whose region is not the level's)."""

import random

from orchestra.sd.discover import discover

T0 = 1_800_000_000.0
STEP = 60.0
N = 240


def _walk(rng, moves: int) -> tuple[list[int], list[int], list[int]]:
    """A count of pods that starts and stops pods at ``moves`` random minutes: (level, started, stopped)."""
    at = set(rng.sample(range(1, N), moves))
    level, up, down = [3], [0], [0]
    for i in range(1, N + 1):
        d = (1 if rng.random() < 0.5 or level[-1] <= 1 else -1) if i in at else 0
        level.append(level[-1] + d)
        up.append(up[-1] + (d > 0))
        down.append(down[-1] + (d < 0))
    return level, up, down


def _series(name, labels, values):
    return (name, {"machine": "rig.search", "service": "search", **labels}, [(T0 + STEP * i, float(v)) for i, v in enumerate(values)])


def _dump(rng, *, a_counters: bool = True):
    a, a_up, a_down = _walk(rng, 100)
    b, b_up, b_down = _walk(rng, 15)
    dump = [_series("pods", {"region": "a"}, a), _series("pods", {"region": "b"}, b),
            _series("pods", {}, [x + y for x, y in zip(a, b)]),
            _series("pods_started_total", {"region": "b"}, b_up), _series("pods_stopped_total", {"region": "b"}, b_down),
            _series("pods_started_total", {}, [x + y for x, y in zip(a_up, b_up)]),
            _series("pods_stopped_total", {}, [x + y for x, y in zip(a_down, b_down)])]
    if a_counters:
        dump += [_series("pods_started_total", {"region": "a"}, a_up), _series("pods_stopped_total", {"region": "a"}, a_down)]
    return dump


def test_neither_the_parts_nor_the_total_is_left_out_as_the_others_twin():
    # whether the parts or the total should be kept when both balance is the owner's (priors, D4):
    # both stay, each with its own counters
    m = discover(_dump(random.Random(4)), start=T0, end=T0 + N * STEP, step=STEP)
    left = m.discovery["left_out"]
    assert not [k for k, why in left.items() if k.startswith("pods{") and why.startswith("the same as")], left
    regions = {s.series.labels.get("region") for s in m.stocks if s.series and s.series.name == "pods"}
    assert regions == {"a", "b", None}, left
    for s in m.stocks:
        region = s.series.labels.get("region")
        for b in s.evidence["balance"]:
            assert 'region="' not in b["series"] or f'region="{region}"' in b["series"], (s.id, b)


def test_a_level_is_never_balanced_by_another_regions_counters():
    rng = random.Random(7)
    dump = _dump(rng, a_counters=False)
    b = next(pts for n, lab, pts in dump if n == "pods" and lab.get("region") == "b")
    dump = [(n, lab, b if (n == "pods" and lab.get("region") == "a") else pts) for n, lab, pts in dump]   # a moves as b does
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP)
    a_key = 'pods{machine="rig.search",region="a",service="search"}'
    for s in m.stocks:
        if s.series and s.series.labels.get("region") == "a":
            assert not any('region="b"' in b["series"] for b in s.evidence["balance"]), s.evidence["balance"]
    assert not m.discovery["left_out"].get(a_key, "").startswith("the same as"), m.discovery["left_out"].get(a_key)
