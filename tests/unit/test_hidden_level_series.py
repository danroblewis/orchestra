"""A hidden state (an unmeasured passage, sd.passing) whose place has a count of its own that never
caught an item says so: its level series is named, with why it was not read as the level; a
state with no count written for its place keeps "no level measures it"."""

from orchestra.sd.accept import stock_trust
from orchestra.sd.passing import Passage, unread
from orchestra.sd.series import Series, series_key
from orchestra.sd.titles import Places

PILE = {"instrument": "piles", "workflow": "delivery_sail"}


def mv(a, b):
    return Series("workflow_pile_moves_total", {**PILE, "from": a, "to": b}, [], [], True)


def places(with_count: bool):
    items = [("workflow_pile_items", {**PILE, "pile": "write.held", "step": "write", "place": "held"})]
    if with_count:
        items.append(("workflow_pile_items", {**PILE, "pile": "sail.waiting", "step": "sail", "place": "waiting"}))
    prov = {series_key(n, lab): {"view": "count", "place": "pile"} for n, lab in items}
    moves = [mv("write.held", "sail.waiting"), mv("sail.waiting", "<end>")]
    prov.update({c.key: {"view": "moves", "starts": "to", "stops": "from"} for c in moves})
    return Places([*[(n, lab, series_key(n, lab)) for n, lab in items], *[(c.name, c.labels, c.key) for c in moves]], prov), moves


def passage(ins, outs):
    implied = Series("after_x", {}, [(0.0, 0.0)], [0.0, 0.0], False)
    return Passage(implied, ins, outs, False, 0, 9)


def test_no_count_for_the_place_keeps_no_level_measures_it():
    pl, (into, out) = places(with_count=False)
    assert pl.level_series([into], [out]) is None
    ev = passage([into], [out]).evidence(None)
    assert ev["hidden"] and "level_series" not in ev["passing"]
    assert "no level measures it" in ev["passing"]["note"]
    trust = stock_trust(None, None, {}, False, passage([into], [out]), None)
    assert trust["why"] == ["no series measures it: its level is what the counters imply"]


def test_a_count_that_reads_zero_at_every_step_is_named_with_why():
    pl, (into, out) = places(with_count=True)
    key = pl.level_series([into], [out])
    assert key == series_key("workflow_pile_items", {**PILE, "pile": "sail.waiting", "step": "sail", "place": "waiting"})
    level = Series("workflow_pile_items", {**PILE, "pile": "sail.waiting", "step": "sail", "place": "waiting"},
                   [(0.0, 0.0), (30.0, 0.0)], [0.0] * 10, False)
    u = unread(level, "items waiting at sail")
    assert u["level_series"] == key and u["level_title"] == "items waiting at sail"
    assert u["level_why"] == "written, but reads 0 at every step it was sampled: what enters leaves within a step"
    ev = passage([into], [out]).evidence(u)
    assert ev["passing"]["level_series"] == key and ev["passing"]["level_why"] == u["level_why"]
    assert "no level measures it" not in ev["passing"]["note"]
    assert "its level series items waiting at sail is written" in ev["passing"]["note"]
    trust = stock_trust(None, None, {}, False, passage([into], [out]), u)
    assert "no series measures it" not in trust["why"][0] and trust["score"] == 0.0


def test_a_count_that_changed_off_the_counters_says_how_often():
    level = Series("workflow_pile_items", {**PILE, "pile": "sail.waiting"}, [], [0.0, 1.0, 1.0, 0.0, 0.0], False)
    assert unread(level, None)["level_why"] == "written, but changed in only 2 steps, not with the counters' rises and falls"


def test_moves_into_two_places_name_no_one_count():
    pl, (into, _) = places(with_count=True)
    assert pl.level_series([into], [mv("write.held", "<end>")]) is None
