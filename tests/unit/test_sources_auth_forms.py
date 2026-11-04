"""The short form of a source's auth: one ``token_file`` and how its token is sent (``auth =
"bearer"``, ``"header:<Name>"``, ``"basic"`` with a ``user``), and each way it is refused."""

from __future__ import annotations

import pytest

from orchestra.sources.auth import Auth
from orchestra.sources.spec import load


def _load(tmp_path, **entry):
    (tmp_path / "repo").mkdir(exist_ok=True)
    specs = load({"sources": [{"name": "work", "url": "https://tenant.chronosphere.io/data/metrics/", "match": ['{__name__=~"[a-zA-Z_:].*"}'], **entry}]}, tmp_path / "repo")
    return specs.sources[0] if specs.sources else specs.refused["work"]


@pytest.fixture
def tok(tmp_path):
    p = tmp_path / "secrets" / "token"
    p.parent.mkdir()
    p.write_text("s3cr3t\n")
    return str(p)


@pytest.mark.parametrize("auth, user, header, value", [
    ("bearer", None, "Authorization", "Bearer s3cr3t"),
    ("header:API-Token", None, "API-Token", "s3cr3t"),
    ("basic", "chronosphere", "Authorization", "Basic Y2hyb25vc3BoZXJlOnMzY3IzdA=="),
])
def test_each_short_form_sends_the_token_from_the_file(tmp_path, tok, auth, user, header, value):
    s = _load(tmp_path, auth=auth, token_file=tok, **({"user": user} if user else {}))
    assert s.url == "https://tenant.chronosphere.io/data/metrics"      # the path is kept; the API is joined under it
    assert Auth(s.auth).headers() == {header: value}
    shown = str(Auth(s.auth).describe())
    assert "s3cr3t" not in shown and tok in shown


@pytest.mark.parametrize("entry, says", [
    ({"auth": "bearer"}, "needs token_file"),
    ({"auth": "header:API-Token"}, "needs token_file"),
    ({"auth": "bearer", "token_file": "/nowhere/token"}, "no such file"),
    ({"token_file": "TOK"}, "token_file goes with"),
    ({"auth": {"bearer_env": "T"}, "token_file": "TOK"}, "token_file goes with"),
    ({"auth": "oauth", "token_file": "TOK"}, "auth = 'oauth'"),
    ({"auth": "header:", "token_file": "TOK"}, "auth = 'header:'"),
    ({"auth": "basic", "token_file": "TOK"}, "needs user"),
    ({"auth": "bearer", "token_file": "TOK", "user": "me"}, "user goes with"),
    ({"token": "s3cr3t"}, "literal secret"),
])
def test_each_mistake_refuses_the_source_with_what_it_needs(tmp_path, tok, entry, says):
    entry = {k: (tok if v == "TOK" else v) for k, v in entry.items()}
    why = _load(tmp_path, **entry)
    assert isinstance(why, str) and says in why and "s3cr3t" not in why


def test_a_token_file_inside_the_repository_is_refused(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "token").write_text("s3cr3t")
    why = _load(tmp_path, auth="bearer", token_file=str(tmp_path / "repo" / "token"))
    assert isinstance(why, str) and "inside the repository" in why
