"""A stock's id and name leave out label values with nothing to say (RabbitMQ's vhost ``/``), and
values another value already says (a queue named for its consumer and exchange)."""

import random

from orchestra.sd.discover import discover

T0 = 1_800_000_000.0


def test_a_vhost_of_slash_is_not_in_a_stocks_id_or_name():
    rng = random.Random(2)
    lab = {"machine": "rabbit.billing", "queue": "orders", "vhost": "/"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    dump = [("backlog", lab, pts(level)), ("published_total", lab, pts(ins)), ("acked_total", lab, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0)
    assert [(s.id, s.name) for s in m.stocks] == [("backlog_orders", "backlog (orders)")]
    assert all(not f.id.endswith("_") for f in m.flows), [f.id for f in m.flows]


def test_a_queue_named_for_its_consumer_and_exchange_is_said_once():
    rng = random.Random(3)
    lab = {"machine": "rabbit.analytics", "consumer": "analytics", "exchange": "clicks", "queue": "analytics.clicks", "vhost": "/"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    dump = [("backlog", lab, pts(level)), ("published_total", lab, pts(ins)), ("acked_total", lab, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0)
    assert [(s.id, s.name) for s in m.stocks] == [("backlog_analytics_clicks", "backlog (analytics.clicks)")]


PILES = {"workflow_pile_items": {"view": "count", "place": "pile"},
         "workflow_pile_moves_total": {"view": "moves", "starts": "to", "stops": "from"},
         "workflow_pile_oldest_seconds": {"view": "age"}}


def _prov(dump):
    from orchestra.sd.series import series_key
    return {series_key(n, lab): {"source": "own", "instrument": "piles", **PILES[n]} for n, lab, _ in dump if n in PILES}


def _piles(views: bool = True):
    rng = random.Random(4)
    lab = {"instrument": "piles", "workflow": "delivery_sail", "pile": "write.held", "step": "write", "place": "held"}
    move = {"instrument": "piles", "workflow": "delivery_sail"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    other = {**lab, "pile": "sail_check.waiting", "step": "sail_check", "place": "waiting"}
    dump = [("workflow_pile_items", lab, pts(level)), ("workflow_pile_items", other, pts([0] * 241)),
            ("workflow_pile_moves_total", {**move, "from": "<start>", "to": "write.held"}, pts(ins)),
            ("workflow_pile_moves_total", {**move, "from": "write.held", "to": "sail_check.waiting"}, pts(outs))]
    return discover(dump, start=T0, end=T0 + 240 * 60, step=60.0, provenance=_prov(dump) if views else None)


def test_a_place_its_count_view_names_is_named_by_the_labels_that_spell_it():
    """The owner (2026-11-01) read the pile ``write.held`` as a disk write: the instrument's count
    view names the place label (``pile``), and the labels whose values spell its value name it, in
    the order they spell it, then what they do not spell; no label's name is known to the core."""
    m = _piles()
    [st] = [s for s in m.stocks if s.series is not None]
    assert (st.id, st.name, st.evidence.get("named")) == ("workflow_pile_items_write_held_delivery_sail", "items held at write", "places")
    # a move is named by the places it leaves and enters, a stock or not ("sail_check (waiting)", never
    # sail_check.waiting nor "sail check"); a value no place spells is said as it is
    names = {f.counter.labels["to"]: (f.name, f.evidence.get("named")) for f in m.flows if f.counter}
    assert names["sail_check.waiting"] == ("write → sail_check", "places")
    assert names["write.held"] == ("start → write", "places")


def test_a_left_out_pile_that_holds_items_says_its_level_and_place():
    """R3 (:8606): 5 threads sat at unchecked, a level that never changed, and the diagram showed
    none of them. A left-out count of a place that holds items is recorded with its level."""
    rng = random.Random(4)
    lab = {"instrument": "piles", "workflow": "w", "pile": "write.held", "step": "write", "place": "held"}
    stuck = {**lab, "pile": "unchecked.waiting", "step": "unchecked", "place": "waiting"}
    empty = {**lab, "pile": "late.waiting", "step": "late", "place": "waiting"}
    level, ins, outs = [0], [0], [0]
    for _ in range(240):
        a, b = rng.randint(0, 3), rng.randint(0, 2) if level[-1] > 2 else 0
        ins.append(ins[-1] + a)
        outs.append(outs[-1] + b)
        level.append(level[-1] + a - b)
    pts = lambda vs: [(T0 + 60 * i, float(v)) for i, v in enumerate(vs)]
    move = {"instrument": "piles", "workflow": "w"}
    dump = [("workflow_pile_items", lab, pts(level)), ("workflow_pile_items", stuck, pts([5] * 241)),
            ("workflow_pile_items", empty, pts([0] * 241)),
            ("workflow_pile_moves_total", {**move, "from": "<start>", "to": "write.held"}, pts(ins)),
            ("workflow_pile_moves_total", {**move, "from": "write.held", "to": "<end>"}, pts(outs))]
    m = discover(dump, start=T0, end=T0 + 240 * 60, step=60.0, provenance=_prov(dump))
    held = m.discovery["held_levels"]
    assert [(v["place"], v["level"]) for v in held.values()] == [("unchecked.waiting", 5.0)]
    assert m.discovery["titles"][next(iter(held))] == "items waiting at unchecked"


def test_without_its_instruments_views_a_pile_is_named_by_its_series():
    m = _piles(views=False)
    [st] = [s for s in m.stocks if s.series is not None]
    assert st.name.startswith("workflow pile items (") and "named" not in st.evidence


def test_hidden_state_between_moves_that_name_places_is_named_by_them():
    from orchestra.sd.series import Series
    from orchestra.sd.titles import Places

    mv = lambda a, b: Series("workflow_pile_moves_total", {"instrument": "piles", "workflow": "delivery_sail", "from": a, "to": b}, [], [], True)
    pile = lambda st, pl: ("workflow_pile_items", {"instrument": "piles", "workflow": "delivery_sail", "pile": f"{st}.{pl}", "step": st, "place": pl})
    items = [pile("open_pr", "waiting"), pile("ci", "waiting"), pile("write", "held"), pile("review", "waiting")]
    ins, outs = [mv("write.held", "open_pr.waiting")], [mv("ci.waiting", "review.waiting")]
    same, nowhere = mv("open_pr.waiting", "review.waiting"), mv("<somewhere>", "review.waiting")
    from orchestra.sd.series import series_key
    prov = {series_key(n, lab): {"view": "count", "place": "pile"} for n, lab in items}
    prov.update({c.key: {"view": "moves", "starts": "to", "stops": "from"} for c in ins + outs + [same, nowhere]})
    places = Places([(n, lab, series_key(n, lab)) for n, lab in items], prov)
    assert places.between(ins, outs) == "items between open_pr and ci"
    assert places.between(ins, [same]) == "items waiting at open_pr"
    assert places.between(ins, [nowhere]) is None      # by its neighbours, then


def test_a_hidden_state_through_several_steps_is_named_by_its_first_and_last_and_lists_what_it_spans():
    """The owner (2026-11-01, "how are all of these considered one stock?") read "deliveries
    passing write held and sail_check waiting" as several things: a passage through several steps
    is "<noun> between <first> and <last>", never its places' states joined; the places it spans
    are listed beside it, in the order items pass them."""
    from itertools import pairwise

    from orchestra.sd.series import Series, series_key
    from orchestra.sd.titles import Places

    lab = {"instrument": "piles", "workflow": "delivery_sail"}
    mv = lambda a, b: Series("workflow_pile_moves_total", {**lab, "from": a, "to": b}, [], [], True)
    steps = [("write", "waiting"), ("write", "held"), ("open_pr", "waiting"), ("ci", "waiting"), ("review", "waiting"),
             ("sail_check", "waiting")]
    items = [("workflow_pile_items", {**lab, "pile": f"{a}.{b}", "step": a, "place": b}) for a, b in steps]
    chain = [mv(f"{a}.{b}", f"{c}.{d}") for (a, b), (c, d) in pairwise(steps)] + [mv("sail_check.waiting", "<end>")]
    prov = {series_key(n, x): {"view": "count", "place": "pile", "noun": "deliveries"} for n, x in items}
    prov.update({c.key: {"view": "moves", "starts": "to", "stops": "from"} for c in chain})
    rows = [(n, x, series_key(n, x)) for n, x in items] + [(c.name, c.labels, c.key) for c in chain]
    places = Places(rows, prov)
    ins, outs = [chain[0]], [chain[-1]]
    name = places.between(ins, outs)
    assert name == "deliveries between write and sail_check"
    assert "passing" not in name and "held" not in name
    assert places.spans(ins, outs) == ["write (held)", "open_pr (waiting)", "ci (waiting)", "review (waiting)",
                                       "sail_check (waiting)"]
    # entered and left at one place: what sits there
    assert places.between([chain[0]], [chain[1]]) == "deliveries held at write"


def test_a_series_of_the_age_view_is_the_age_of_its_place_never_its_name():
    from orchestra.sd.discover import _title
    from orchestra.sd.series import Series
    from orchestra.sd.titles import Places

    lab = {"workflow": "delivery_sail", "pile": "write.held", "step": "write", "place": "held"}
    pile, age = Series("workflow_pile_items", lab, [], [], False), Series("workflow_pile_oldest_seconds", lab, [], [], False)
    prov = {pile.key: {"source": "own", "instrument": "piles", "view": "count", "place": "pile"},
            age.key: {"source": "own", "instrument": "piles", "view": "age"}}
    places = Places([(x.name, x.labels, x.key) for x in (pile, age)], prov)
    assert _title(pile, places) == "items held at write"
    assert _title(age, places) == "age of items held at write"


def test_a_place_value_with_no_words_keeps_the_series_name_and_dashes_spell_like_underscores():
    # the R2 refuter: queue_depth{pile="3", shard="3"} was titled "3"; code-review.waiting fell back
    from orchestra.sd.discover import _title
    from orchestra.sd.series import Series
    from orchestra.sd.titles import Places

    num = Series("queue_depth", {"pile": "3", "shard": "3"}, [], [], False)
    dash = Series("workflow_pile_items", {"workflow": "w", "pile": "code-review.waiting", "step": "code-review", "place": "waiting"}, [], [], False)
    prov = {x.key: {"view": "count", "place": "pile"} for x in (num, dash)}
    places = Places([(x.name, x.labels, x.key) for x in (num, dash)], prov)
    assert _title(num, places).startswith("queue depth")
    assert _title(dash, places) == "items waiting at code-review"


def _pile_places(*workflows):

    from orchestra.sd.series import Series, series_key
    from orchestra.sd.titles import Places

    items, moves = [], []
    for wf in workflows:
        for st in ("write", "ci", "review"):
            for pl in ("waiting", "held"):
                items.append(("workflow_pile_items", {"instrument": "piles", "workflow": wf, "pile": f"{st}.{pl}", "step": st, "place": pl}))
        for a, b in (("<start>", "write.waiting"), ("write.waiting", "write.held"), ("write.held", "ci.waiting"),
                     ("ci.waiting", "review.waiting"), ("ci.waiting", "write.waiting")):
            moves.append(Series("workflow_pile_moves_total", {"instrument": "piles", "workflow": wf, "from": a, "to": b}, [], [], True))
    prov = {series_key(n, lab): {"view": "count", "place": "pile"} for n, lab in items}
    prov.update({c.key: {"view": "moves", "starts": "to", "stops": "from"} for c in moves})
    places = Places([*[(n, lab, series_key(n, lab)) for n, lab in items], *[(c.name, c.labels, c.key) for c in moves]], prov)
    return places, items, moves


def test_a_stock_is_what_sits_in_its_place_and_a_flow_is_the_move_in_words():
    """The owner (2026-11-01): "the names of all the system dynamics stocks are weird". A stock is
    what sits there, the noun its series counts, what is said of it there and where ("items held at
    review"), with no workflow when one is on the model; a move is between the things it leaves and
    enters, "sent back" when it goes nearer the start, and from outside in words."""
    from orchestra.sd.series import series_key

    places, items, moves = _pile_places("delivery_sail")
    level = {lab["pile"]: places.level(lab, series_key(n, lab), n) for n, lab in items}
    assert (level["write.waiting"], level["review.held"], level["ci.waiting"]) == ("items waiting at write", "items held at review", "items waiting at ci")
    move = {(c.labels["from"], c.labels["to"]): places.move(c.labels, c.key) for c in moves}
    assert move[("write.held", "ci.waiting")] == "write → ci"
    assert move[("ci.waiting", "review.waiting")] == "ci → review"
    assert move[("ci.waiting", "write.waiting")] == "ci → write (sent back)"
    assert move[("<start>", "write.waiting")] == "start → write"
    assert move[("write.waiting", "write.held")] == "write: waiting → held"


def test_two_workflows_with_a_step_of_one_name_say_whose_it_is():
    from orchestra.sd.series import series_key

    places, items, moves = _pile_places("delivery_sail", "hotfix")
    n, lab = next((n, lab) for n, lab in items if lab["workflow"] == "hotfix" and lab["pile"] == "write.held")
    assert places.level(lab, series_key(n, lab), n) == "items held at write (hotfix)"
    c = next(c for c in moves if c.labels["workflow"] == "hotfix" and c.labels["from"] == "write.held")
    assert places.move(c.labels, c.key) == "write → ci (hotfix)"


def test_a_series_its_name_and_labels_say_in_words():
    from orchestra.sd.discover import _named, _title
    from orchestra.sd.series import Series

    commits = Series("git_branch_commits", {"instrument": "git", "branch": "main"}, [], [], False)
    closed = Series("orchestra_events_total", {"type": "item.closed", "source": "supervisor"}, [], [], True)
    assert (_title(commits), _named(commits, None)) == ("commits on main", {"named": "words"})
    assert (_title(closed), _named(closed, None)) == ("item.closed events (supervisor)", {"named": "words"})
    assert _title(Series("queue_depth", {"queue": "orders"}, [], [], False)) == "queue depth (orders)"
