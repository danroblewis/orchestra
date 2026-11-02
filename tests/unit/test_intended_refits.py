"""The Changes panel's refits (sd/intended/view.py ``_reformed``) rank the flows whose fitted numbers
moved most, never one fitted from fewer events than a fit needs (its move is chance)."""

from types import SimpleNamespace as NS

from orchestra.sd.intended.view import _reformed


def eq(k, events):
    return NS(form="proportional", inputs=["s"], params={"k": k}, quality={"events": events}, origin="fitted", spec={})


def flow(fid, e):
    return NS(id=fid, src="s", dst=None, current=lambda: e)


def test_a_flow_fitted_from_one_event_is_never_ranked_as_a_refit():
    base_model = NS(flows=[flow("a", eq(1.0, 40)), flow("b", eq(1.0, 1))])
    model = NS(flows=[flow("a", eq(2.0, 40)), flow("b", eq(9.0, 1))])
    keys = NS(flows={"A": "a", "B": "b"})
    reforms, refits = _reformed(model, keys, base_model, keys)
    assert reforms == []
    assert [r["id"] for r in refits] == ["a"]           # b moved more, on one event: not ranked
