"""[[sources]] in orchestra.toml: every common credential from a variable or a file outside the
repository; a literal secret, user:pass@ in a URL, or a secret file in the repository refused."""

from __future__ import annotations

import base64
import shutil
import ssl
import subprocess

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources import SourceError
from orchestra.sources.auth import Auth
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load


def one(tmp_path, **src):
    specs = load({"sources": [{"name": "work", "url": "https://metrics.example:9443/data", **src}]}, tmp_path / "repo")
    return specs.sources[0] if specs.sources else None, specs.refused.get("work")


@pytest.mark.parametrize("src, why", [
    ({"auth": {"token": "abc"}}, "literal secret"),
    ({"auth": {"bearer": "abc"}}, "literal secret"),
    ({"token": "abc"}, "literal secret"),
    ({"url": "https://me:pw@metrics.example/"}, "user:pass@"),
    ({"auth": {"basic": {"user": "u", "password": "pw"}}}, "literal secret"),
    ({"auth": {"header": {"name": "API-Token", "value": "abc"}}}, "literal secret"),
    ({"auth": {"oauth2": {"token_url": "x"}}}, "not built yet"),
    ({"auth": {"client_cert": "/x.pem"}}, "both client_cert and client_key"),
    ({"prefix": "orchestra_x"}, "prefix"),
    ({"type": "influx"}, "only prometheus"),
])
def test_refused_with_the_reason(tmp_path, src, why):
    spec, refused = one(tmp_path, **src)
    assert spec is None and why in refused


def test_a_secret_file_inside_the_repository_is_refused(tmp_path):
    (tmp_path / "repo").mkdir()
    spec, refused = one(tmp_path, auth={"bearer_file": str(tmp_path / "repo" / "token")})
    assert spec is None and "inside the repository" in refused
    spec, refused = one(tmp_path, auth={"bearer_file": str(tmp_path / "token")})
    assert refused is None and spec.auth.kinds() == ["bearer"]


def test_every_kind_reads_its_credential_when_asked_and_never_shows_it(tmp_path, monkeypatch):
    (tmp_path / "pw").write_text("s3cret-pw\n")
    monkeypatch.setenv("WORK_TOKEN", "s3cret-token")
    spec, refused = one(tmp_path, auth={"bearer_env": "WORK_TOKEN", "header": {"name": "X-Scope-OrgID", "value": "tenant-1"}})
    assert refused is None
    a = Auth(spec.auth)
    assert a.headers() == {"Authorization": "Bearer s3cret-token", "X-Scope-OrgID": "tenant-1"}
    assert "s3cret" not in repr(a.describe()) and a.describe()["credentials"][0]["present"]
    spec, _ = one(tmp_path, auth={"basic": {"user": "orchestra", "password_file": str(tmp_path / "pw")}})
    assert Auth(spec.auth).headers()["Authorization"] == "Basic " + base64.b64encode(b"orchestra:s3cret-pw").decode()
    spec, _ = one(tmp_path, auth={"header": {"name": "API-Token", "value_env": "WORK_TOKEN"}})
    assert Auth(spec.auth).headers() == {"API-Token": "s3cret-token"}
    monkeypatch.delenv("WORK_TOKEN")
    with pytest.raises(SourceError, match="WORK_TOKEN is not set") as e:
        Auth(spec.auth).headers()
    assert "s3cret" not in str(e.value)


def test_declared_series_need_a_usable_source(tmp_path):
    specs = load({"sources": [{"name": "work", "url": "http://x:1"}],
                  "series": [{"source": "work", "name": "errors", "query": "sum(x)", "kind": "rate"},
                             {"source": "nope", "name": "y", "query": "y"},
                             {"source": "work", "name": "Bad-Name", "query": "y"}]}, tmp_path)
    assert [d.name for d in specs.declared] == ["errors"]
    assert set(specs.refused) == {"series[1]", "series[2]"}


@pytest.mark.skipif(not shutil.which("openssl"), reason="needs openssl to make test certificates")
def test_mtls_against_a_server_that_demands_a_client_certificate(tmp_path):
    d = tmp_path / "certs"
    d.mkdir()
    run = lambda *a: subprocess.run(["openssl", *a], cwd=d, check=True, capture_output=True)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "1", "-subj", "/CN=test-ca",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    (d / "san.cnf").write_text("subjectAltName=IP:127.0.0.1\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\n"
                               "extendedKeyUsage=serverAuth,clientAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
    for who in ("server", "me"):
        run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"{who}.key", "-out", f"{who}.csr", "-subj", f"/CN={who}")
        run("x509", "-req", "-in", f"{who}.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", f"{who}.pem",
            "-days", "1", "-extfile", "san.cnf")
    fake = FakePrometheus([("up", {"job": "x"}, [(1000.0, 1.0)])], tls=(d / "server.pem", d / "server.key", d / "ca.pem"))
    try:
        url = fake.url
        spec, refused = one(tmp_path, url=url, auth={"client_cert": str(d / "me.pem"), "client_key": str(d / "me.key"),
                                                      "ca_file": str(d / "ca.pem")})
        assert refused is None and spec.auth.kinds() == ["mtls"]
        assert isinstance(Auth(spec.auth).ssl_context(), ssl.SSLContext)
        assert PrometheusSource(spec).select("up", 0, 2000) == [({"__name__": "up", "job": "x"}, [(1000.0, 1.0)])]
        assert all(c["present"] for c in Auth(spec.auth).describe()["credentials"])
        bare, _ = one(tmp_path, url=url, auth={"ca_file": str(d / "ca.pem")})     # the server's CA, but no client certificate
        with pytest.raises(SourceError):
            PrometheusSource(bare).select("up", 0, 2000)
    finally:
        fake.close()
    spec, _ = one(tmp_path, auth={"client_cert": str(d / "me.pem"), "client_key": str(d / "missing.key")})
    with pytest.raises(SourceError, match="client certificate"):
        Auth(spec.auth).ssl_context()
