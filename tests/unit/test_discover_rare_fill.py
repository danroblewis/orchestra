"""A passage whose fill is rare (sd.passing): the few orders a customer sends back are judged with
the rest of the passage, so the state they leave does not come and go with one event."""

import random
from itertools import accumulate

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import Series, discover
from orchestra.sd.passing import passages

T0 = 1_800_000_000.0


def board(store, rejects: int, minutes: int = 60, seed: int = 5, shelf: tuple[str, ...] = ()):
    """Orders are placed into waiting, start onto the shelf, are picked up into accepting and leave
    it within a third of a second: accepted (gone) or rejected (back to waiting). ``rejects`` of the
    pickups, spread through the window, are rejected. Every series is written each second before
    that second's events; accepting also reads 1 at the pickup and 0 when the customer decides.
    ``shelf``: the counters the shelf writes rather than the board."""
    rng = random.Random(seed)
    lab = {"project": "p", "machine": "board"}
    at = lambda k, v, t: Point(k, v, t, {"project": "p", "machine": "shelf"} if k in shelf else lab)
    lv = {"waiting": 0, "on_shelf": 0}
    n = dict.fromkeys(["placed_total", "started_total", "picked_up_total", "accepted_total", "rejected_total"], 0)
    sent_back = {9 + 10 * i for i in range(rejects)}
    pts = []
    for i in range(minutes * 60):
        t = T0 + i
        pts += [at(k, v, t) for k, v in [*n.items(), *lv.items(), ("accepting", 0)]]
        if rng.random() < 0.018:
            lv["waiting"] += 1
            n["placed_total"] += 1
        if lv["waiting"] and rng.random() < 0.02 * lv["waiting"]:
            lv["waiting"] -= 1
            lv["on_shelf"] += 1
            n["started_total"] += 1
        if lv["on_shelf"] and rng.random() < 0.03 * lv["on_shelf"]:
            lv["on_shelf"] -= 1
            n["picked_up_total"] += 1
            out = "rejected_total" if n["picked_up_total"] in sent_back else "accepted_total"
            n[out] += 1
            lv["waiting"] += 1 if out == "rejected_total" else 0
            pts += [at("picked_up_total", n["picked_up_total"], t + 0.3), at("accepting", 1, t + 0.3),
                    at(out, n[out], t + 0.6), at("accepting", 0, t + 0.6)]
    store.write(pts)
    return discover(store.dump("", {"project": "p"}), start=T0, end=T0 + minutes * 60, step=30), n


def test_a_rare_fill_joins_a_passage_its_measured_state_and_free_outflow_vouch_for(tmp_path):
    m, n = board(FileMetrics(tmp_path / "m.jsonl"), rejects=4)
    assert n["rejected_total"] == 4 and n["picked_up_total"] >= 50, n
    ends = {f.id: (f.src, f.dst) for f in m.flows}
    assert ends["picked_up_total"] == ("on_shelf", "accepting"), ends
    assert ends["accepted_total"] == ("accepting", None), ends
    assert ends["rejected_total"] == ("accepting", "waiting"), ends
    accepting = m.stock("accepting")
    assert accepting.series is not None and accepting.evidence["passing"]["out_of_step_steps"] == 0


def test_a_rare_fill_joins_a_passage_its_measured_state_alone_vouches_for(tmp_path):
    # the shelf counts the pickups and the acceptances, the board only the returns: no free counter
    # of the returns' machine is among the outs, and the accepting level's raw points say it all
    m, _ = board(FileMetrics(tmp_path / "m.jsonl"), rejects=4, shelf=("picked_up_total", "accepted_total"))
    ends = {f.id: (f.src, f.dst) for f in m.flows}
    assert (ends["picked_up_total"], ends["rejected_total"]) == (("on_shelf", "accepting"), ("accepting", "waiting")), ends
    rises, falls = m.stock("accepting").evidence["passing"]["rises_at_ins"], m.stock("accepting").evidence["passing"]["falls_at_outs"]
    assert rises[0] == rises[1] > 0 and falls[0] == falls[1] > 0


def test_windows_whose_rare_fill_counts_six_and_four_give_the_same_stocks(tmp_path):
    six, _ = board(FileMetrics(tmp_path / "six.jsonl"), rejects=6)
    four, _ = board(FileMetrics(tmp_path / "four.jsonl"), rejects=4)
    assert {s.id for s in six.stocks} == {s.id for s in four.stocks} == {"waiting", "on_shelf", "accepting"}
    assert {f.id: (f.src, f.dst) for f in six.flows} == {f.id: (f.src, f.dst) for f in four.flows}


def test_a_rare_fill_without_a_measured_state_needs_a_free_counter_of_its_machine():
    cum = lambda xs: [0.0, *accumulate(xs)]
    mk = lambda name, xs, m: Series(name, {"machine": m}, [], cum(xs), True)
    picked = [1.0 if i % 2 == 0 else 0.0 for i in range(120)]
    sent_back = [1.0 if i in (10, 40, 70, 100) else 0.0 for i in range(120)]
    kept = [a - b for a, b in zip(picked, sent_back)]
    lv = lambda name: Series(name, {"machine": "board"}, [], [3.0] * 121, False)
    where = {"start": T0, "end": T0 + 3600, "step": 30, "machine_of": lambda s: s.labels["machine"]}

    def joined(accepted_by: str, picked_by: str = "board") -> list:
        picked_up, rejected = mk("picked_up_total", picked, picked_by), mk("rejected_total", sent_back, "board")
        accepted = mk("accepted_total", kept, accepted_by)
        found = [(lv("on_shelf"), [(picked_up, -1)], 1.0, 1.0), (lv("waiting"), [(rejected, 1)], 1.0, 1.0)]
        got = passages(found, [picked_up, rejected, accepted], [], **where)
        return [([c.name for c in p.ins], sorted(c.name for c in p.outs), p.measured) for p in got]

    # the board's own free counter of the other way out vouches for its four returns
    assert joined("board") == [(["picked_up_total"], ["accepted_total", "rejected_total"], False)]
    # the drain's machine's free counter does not: nothing of the returns' machine says they pass
    assert joined("shelf", picked_by="shelf") == []
