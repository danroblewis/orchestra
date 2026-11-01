"""The fields the agents' design tools send (task C8): a declared stock's or effect's
``description``, and what a measurement option names (``bearer_env``, ``system``, ``series``,
``url``, ``command``), stored as sent and checked as text; a credential only by its variable."""

import pytest

from orchestra.sd.intended import IntentError
from orchestra.sd.store import ModelStore

OWNER = {"author": "owner", "source": "supervisor", "quote": "I'm going to create a Features stock."}
SUPERVISOR = {"author": "supervisor", "source": "supervisor", "reason": "a guess"}


def store(tmp_path):
    return ModelStore(tmp_path / "model").intended()


@pytest.mark.parametrize("part", ["stock", "effect"])
def test_a_declared_level_keeps_its_description(tmp_path, part):
    s = store(tmp_path)
    s.apply([{"op": f"declare_{part}", "name": "Features", "description": "features that pass acceptance"}], OWNER)
    el = s.read()["layer"][f"{part}s"]["features"]
    assert el["description"] == "features that pass acceptance"


def test_a_description_is_optional_and_revised_like_any_field(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    assert s.read()["layer"]["stocks"]["features"]["description"] is None
    s.apply([{"op": "declare_stock", "id": "features", "name": "Features", "description": "what works"}], OWNER)
    el = s.read()["layer"]["stocks"]["features"]
    assert el["description"] == "what works" and el["latest"]["before"] == {"description": None}


def test_a_description_is_text(tmp_path):
    with pytest.raises(IntentError, match="description"):
        store(tmp_path).apply([{"op": "declare_stock", "name": "Features", "description": 3}], OWNER)


OPTION = {"key": "a", "title": "Jira's done count", "kind": "source", "how": "count DONE issues", "cost": "1 request/min",
          "clearance": "needs approval", "bearer_env": "WORK_TOKEN", "system": "jira", "series": "jira_issues{state=\"DONE\"}",
          "url": "https://jira.example.com/rest/api/2/search", "command": None}


def _measure(s, option):
    s.apply([{"op": "record_measurement", "part": "stock", "id": "features", "options": [option]}], SUPERVISOR)
    return s.read()["layer"]["stocks"]["features"]["measure"]["options"][0]


def test_an_option_keeps_what_it_names(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    assert _measure(s, OPTION) == OPTION


@pytest.mark.parametrize("bad", ["sk-live-0123456789abcdef!", "Bearer abc", "", 7])
def test_an_options_credential_is_named_by_its_variable_never_given(tmp_path, bad):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    with pytest.raises(IntentError, match="bearer_env"):
        _measure(s, {**OPTION, "bearer_env": bad})


def test_an_options_url_carries_no_password(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    with pytest.raises(IntentError, match="password"):
        _measure(s, {**OPTION, "url": "https://me:hunter2@jira.example.com/"})


@pytest.mark.parametrize("field", ["system", "series", "url", "command"])
def test_what_an_option_names_is_text(tmp_path, field):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    with pytest.raises(IntentError, match=field):
        _measure(s, {**OPTION, field: ["not", "text"]})


def test_an_unknown_option_field_is_still_refused(tmp_path):
    s = store(tmp_path)
    s.apply([{"op": "declare_stock", "name": "Features"}], OWNER)
    with pytest.raises(IntentError, match="unknown field"):
        _measure(s, {**OPTION, "token": "abc"})
