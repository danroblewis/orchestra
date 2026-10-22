"""The demos' model view (sdlab/demos/view.py): every measured stock and every flow of a stored found model, beside
the data and the simulation's true amounts."""

import pytest

from sdlab.demos import view as V


def _have():
    try:
        V._view("ladder", (("case", "310-k8s-memory-oom"), ("strategy", "milp"), ("variant", "none-long")))
        return True
    except Exception:                                                  # noqa: BLE001
        return False


@pytest.mark.skipif(not _have(), reason="no stored passing milp result on 310 none-long in this store")
def test_the_view_of_a_passing_model_matches_its_truth():
    v = V._view("ladder", (("case", "310-k8s-memory-oom"), ("strategy", "milp"), ("variant", "none-long")))
    assert len(v["stocks"]) == 11 and "leak" in v["hidden"]
    both = [f for f in v["flows"] if f["status"] == "both"]
    assert len(both) == len(v["flows"]) and max(f["error"] for f in both) < 0.02
    assert max(v["one_step_error"].values()) < 0.01


def test_an_unknown_source_is_refused():
    with pytest.raises(KeyError):
        V._view("nope", ())
