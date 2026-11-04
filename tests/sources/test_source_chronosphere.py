"""A store read as Chronosphere serves the Prometheus API: under a path prefix
(``https://<tenant>.chronosphere.io/data/metrics/api/v1/...``), with its token in a file outside
the repository, sent as the source's ``auth`` says, and without the endpoints its docs do not list
(``label/<name>/values``, ``metadata``). The header goes on every request; the token goes nowhere
else: not a status, a check's output, a record or a file under Orchestra's home or state."""

from __future__ import annotations

import json
import math
import time

import pytest
from fake_prometheus import FakePrometheus
from helpers import project, source_toml, world

from orchestra import cli
from orchestra.metrics import for_project
from orchestra.sd.rediscover import aligned
from orchestra.sources.catalogue import Catalogue

SECRET = "chrono-SECRET-0123456789"
PREFIX = "/data/metrics"


MATCH = "match = ['{__name__=~\"app_.*|http_.*|k8s_.*\"}']"   # no name index: a match-everything listing would be every series


def _files_hold(root, needle: str) -> list[str]:
    return [str(p) for p in root.rglob("*") if p.is_file() and needle.encode() in p.read_bytes()]


@pytest.mark.parametrize("auth, fake_kw", [
    ('auth = "bearer"', {}),
    ('auth = "header:API-Token"', {"header": "API-Token"}),
    ('auth = "basic"\nuser = "chronosphere"', {"basic_user": "chronosphere"}),
])
def test_a_chronosphere_shaped_store_is_read_under_its_prefix_with_the_token_sent_and_never_shown(tmp_path, monkeypatch, capsys, auth, fake_kw):
    end = math.floor(time.time() / 60) * 60
    dump, _ = world(end, 120, regions={"us-east": 1.0})
    fake = FakePrometheus(dump, token=SECRET, prefix=PREFIX, **fake_kw)
    fake.missing = {"label_values", "metadata"}
    tok = tmp_path / "secrets" / "chronosphere-token"
    tok.parent.mkdir()
    tok.write_text(SECRET + "\n")
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url + PREFIX + "/", auth=f'{auth}\ntoken_file = "{tok}"',
                                         extra=MATCH))
        start, stop = aligned(end - 7200, end, 60.0)
        reading = Catalogue(p, for_project(p)).read(start, stop, 60.0)
        assert cli.main(["--repo", str(p.repo_root), "sources", "check"]) == 0
        checked = capsys.readouterr().out
    finally:
        fake.close()
    assert not reading.missing, reading.missing
    assert any(n.startswith("rig:") for n, _, _ in reading.dump), reading.status
    assert fake.seen and all(path.startswith(PREFIX + "/api/v1/") for path, _ in fake.seen)
    header = fake.header if not fake_kw.get("basic_user") else "Authorization"
    assert all(h.get(header.lower()) for _, h in fake.seen)          # the credential went with every request
    assert SECRET not in json.dumps(reading.status, default=str) and SECRET not in checked
    assert _files_hold(tmp_path / "home", SECRET) == []        # state, records, the store's shared bucket
    assert _files_hold(p.repo_root, SECRET) == []
