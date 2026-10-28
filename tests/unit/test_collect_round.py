"""One collector round (orchestra/collect/round.py): a command's output, or a URL's body, as points."""

import http.server
import os
import threading
import time

import pytest

from orchestra.collect.round import collect, points_of
from orchestra.collect.spec import Collector


def script(repo, name, body):
    path = repo / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return f"./{name}"


def test_a_command_that_prints_two_series(tmp_path):
    cmd = script(tmp_path, "disk.sh", 'echo "# TYPE disk_free_bytes gauge"\n'
                                      'echo "disk_free_bytes{volume=\\"/\\"} 100"\n'
                                      'echo "repo_dir $(basename "$ORCHESTRA_REPO") 1"\n'   # not a sample: skipped
                                      'echo "files_total 3 1761500000000"\n'
                                      'echo "timeout_s $ORCHESTRA_COLLECT_TIMEOUT"\n'      # its own timeout, passed in
                                      'echo oops >&2\n')
    log = tmp_path / "logs" / "disk.log"
    r = collect(Collector("disk", "collect", cmd, 60, 5), tmp_path, "proj", log)
    assert r.error is None
    by = {p.series: p for p in r.points}
    assert by["disk_free_bytes"].labels == {"volume": "/", "project": "proj", "instrument": "disk"}
    assert by["disk_free_bytes"].value == 100.0 and abs(by["disk_free_bytes"].ts - time.time()) < 5
    assert by["files_total"].ts == 1761500000.0
    assert by["timeout_s"].value == 5
    assert len(r.bad) == 1
    assert "oops" in log.read_text()                                     # standard error goes to its log


def test_a_failing_command_writes_nothing(tmp_path):
    cmd = script(tmp_path, "bad.sh", 'echo "x 1"\nexit 3\n')
    r = collect(Collector("bad", "collect", cmd, 60, 5), tmp_path, "proj", tmp_path / "bad.log")
    assert r.points == [] and r.error == "exited with code 3"


def test_a_slow_command_is_killed_at_its_timeout(tmp_path):
    marker = tmp_path / "child.pid"
    cmd = script(tmp_path, "slow.sh", f'echo "x 1"\nsleep 30 &\necho $! > {marker}\nwait\n')
    t0 = time.time()
    r = collect(Collector("slow", "collect", cmd, 60, 0.5), tmp_path, "proj", tmp_path / "slow.log")
    assert time.time() - t0 < 5
    assert r.points == [] and "timeout" in r.error
    child = int(marker.read_text())
    with pytest.raises(ProcessLookupError):                               # what it started was killed too
        for _ in range(50):
            os.kill(child, 0)
            time.sleep(0.05)


def test_a_command_that_cannot_run(tmp_path):
    (tmp_path / "noexec.sh").write_text("echo x 1\n")
    r = collect(Collector("n", "collect", "./noexec.sh", 60, 5), tmp_path, "proj", tmp_path / "n.log")
    assert "chmod +x" in r.error
    r = collect(Collector("m", "collect", "./missing.sh", 60, 5), tmp_path, "proj", tmp_path / "m.log")
    assert r.error.startswith("cannot run")
    script(tmp_path, "here.sh", "echo x 1\n")
    r = collect(Collector("h", "collect", "here.sh", 60, 5), tmp_path, "proj", tmp_path / "h.log")
    assert "write ./here.sh" in r.error                                   # not looked up in the repository, as in a shell


def test_orchestra_series_are_refused_and_the_rest_kept(tmp_path):
    cmd = script(tmp_path, "mixed.sh", 'echo "orchestra_disk_bytes 5"\necho "orchestra_disk_bytes{a=\\"b\\"} 6"\necho "disk_bytes 5"\n')
    r = collect(Collector("mixed", "collect", cmd, 60, 5), tmp_path, "proj", tmp_path / "mixed.log")
    assert [p.series for p in r.points] == ["disk_bytes"]
    assert r.refused == ["orchestra_disk_bytes"]


def test_the_instrument_adds_its_provenance_and_keeps_the_targets_own_labels():
    # the target's own `machine` label is the measured system's dimension of the data: kept as it
    # was; a label Orchestra sets is never overwritten, it is kept as exported_<name>
    r = points_of(Collector("disk", "collect", "x"), 'a{machine="other",project="p2",instrument="i",k="v"} 1\n'
                  'a{machine="other",project="p2",instrument="i",k="v"} 2\n', "proj", 100.0)
    assert [(p.value, p.labels) for p in r.points] == [(2.0, {"machine": "other", "exported_project": "p2", "exported_instrument": "i",
                                                              "k": "v", "project": "proj", "instrument": "disk"})]


class _Handler(http.server.BaseHTTPRequestHandler):
    body = b""
    status = 200

    def do_GET(self):
        self.send_response(self.status)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def test_a_scrape_round(server, tmp_path):
    _Handler.body, _Handler.status = b'# TYPE queue_depth gauge\nqueue_depth{queue="in"} 4\njobs_done_total 9\n', 200
    url = f"http://127.0.0.1:{server.server_address[1]}/metrics"
    r = collect(Collector("app", "scrape", url, 30, 5), tmp_path, "proj", tmp_path / "app.log")
    assert r.error is None
    assert {(p.series, p.value) for p in r.points} == {("queue_depth", 4.0), ("jobs_done_total", 9.0)}
    assert all(p.labels["instrument"] == "app" and p.labels["project"] == "proj" for p in r.points)

    _Handler.status = 500
    r = collect(Collector("app", "scrape", url, 30, 5), tmp_path, "proj", tmp_path / "app.log")
    assert r.points == [] and r.error == "answered 500"


def test_a_scrape_of_nothing_fails(tmp_path):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    srv.server_close()                                                    # the port is free: nothing answers
    r = collect(Collector("app", "scrape", f"http://127.0.0.1:{port}/metrics", 30, 2), tmp_path, "proj", tmp_path / "app.log")
    assert r.points == [] and r.error.startswith("cannot fetch")
