"""A credential never shows and never travels: a malformed secret (a line break in a token file or
a variable) is refused naming only where it came from, so no status, discovery record or check
output carries it; and a redirect to another server is not followed, so the credentials are not
sent there."""

from __future__ import annotations

import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fake_prometheus import FakePrometheus
from helpers import project, source_toml, world

from orchestra import cli
from orchestra.metrics import for_project
from orchestra.sd.rediscover import aligned, rediscover
from orchestra.sources import SourceError
from orchestra.sources.auth import Auth, AuthSpec
from orchestra.sources.catalogue import Catalogue
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load

SECRET = "SECRET-LINE-ONE"


def test_a_two_line_token_file_never_reaches_a_status_a_record_or_the_check(tmp_path, monkeypatch, capsys):
    end = math.floor(time.time() / 60) * 60
    dump, _ = world(end, 120, regions={"us-east": 1.0})
    fake = FakePrometheus(dump, token=SECRET)
    tok = tmp_path / "tok"
    tok.write_text(f"{SECRET}\nsecond-line\n")
    try:
        p = project(tmp_path, monkeypatch, source_toml(fake.url, auth=f'auth = {{ bearer_file = "{tok}" }}'))
        start, stop = aligned(end - 7200, end, 60.0)
        reading = Catalogue(p, for_project(p)).read(start, stop, 60.0)
        assert SECRET not in json.dumps(reading.status) and SECRET not in json.dumps(reading.missing)
        assert "line break or control character" in reading.missing["rig"] and str(tok) in reading.missing["rig"]
        assert cli.main(["--repo", str(p.repo_root), "sources", "check"]) == 0
        checked = capsys.readouterr().out
        assert SECRET not in checked and "line break" in checked
        r = rediscover(p, for_project(p))
    finally:
        fake.close()
    assert r.version is None and "rig" in r.model.discovery["not_saved"]
    assert SECRET not in (p.state_dir / "model" / "discovered.json").read_text()


@pytest.mark.parametrize("auth, env", [
    ({"bearer_env": "TOK"}, f"{SECRET}\r\nX-Injected: 1"),
    ({"header": {"name": "API-Token", "value_env": "TOK"}}, f"{SECRET}\x1b[0m"),
    ({"header": {"name": "X-Scope-OrgID", "value": f"{SECRET}\nX-Injected: 1"}}, None),
])
def test_a_control_character_in_any_credential_is_refused_by_where_it_came_from(monkeypatch, auth, env):
    if env is not None:
        monkeypatch.setenv("TOK", env)
    with pytest.raises(SourceError) as e:
        Auth(AuthSpec.parse(auth)).headers()
    assert SECRET not in str(e.value) and "line break or control character" in str(e.value)


class _Recorder:
    """A server that answers 302 to ``target`` (when given) and records every request's headers."""

    def __init__(self, target: str | None = None):
        self.seen: list[dict] = []
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _go(self):
                rec.seen.append(dict(self.headers))
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                if target:
                    self.send_response(302)
                    self.send_header("Location", target + self.path)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = json.dumps({"status": "success", "data": {"resultType": "matrix", "result": []}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _go

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_a_redirect_to_another_server_is_not_followed_and_carries_no_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("TOK", SECRET)
    elsewhere = _Recorder()
    redirector = _Recorder(target=elsewhere.url)
    try:
        specs = load({"sources": [{"name": "work", "url": redirector.url, "auth": {"bearer_env": "TOK"}}]}, tmp_path / "repo")
        src = PrometheusSource(specs.sources[0])
        with pytest.raises(SourceError) as e:
            src.query_range("up", 0, 60, 60)
    finally:
        redirector.close()
        elsewhere.close()
    assert redirector.seen and redirector.seen[0].get("Authorization") == f"Bearer {SECRET}"
    assert elsewhere.seen == [] and "302" in str(e.value) and "another server" in str(e.value)
    assert SECRET not in str(e.value)

