"""A token made while others read it: every reader gets the same, whole token (it is linked into
place written, never created empty and filled afterwards)."""

import threading

from orchestra.tokens import owner_only


def test_concurrent_first_reads_all_get_the_same_whole_token(tmp_path):
    for trial in range(50):
        path = tmp_path / f"t{trial}" / "web.token"
        got: list[str] = []
        threads = [threading.Thread(target=lambda g=got, p=path: g.append(owner_only(p))) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(got) == 8 and all(got) and len(set(got)) == 1
        assert not [p for p in path.parent.iterdir() if p.name != "web.token"], "no temporary file left"
        assert oct(path.stat().st_mode & 0o777) == "0o600"
