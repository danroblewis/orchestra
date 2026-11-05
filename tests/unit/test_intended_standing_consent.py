"""The owner's standing consent (AGENTS.md rule 9 as amended 2026-11-04, consent.py): ``[intended]
settle_own`` in the private overlay lets a named author confirm or discard its own proposals and
pending changes, recorded as its own (``confirmed.by`` the author, ``standing_consent``, its
reason), never as the owner's; without it nothing changes; what is the owner's stays the owner's;
the owner discards what was confirmed so; no plugin sets the consent through ``config_edit``."""

import subprocess
from types import SimpleNamespace

import pytest

from orchestra import plugins
from orchestra.config import OVERLAY_ENV, ConfigError, init_project, load_project
from orchestra.sd.intended import IntentError, requests
from orchestra.sd.intended.machines_view import intent_of
from orchestra.sd.store import ModelStore

SUP = {"author": "supervisor", "source": "supervisor", "reason": "designed for the owner's review queue"}
OWNER = {"author": "owner", "source": "supervisor", "quote": "yes, that one"}
WHERE = "[intended] settle_own in /state/orchestra.local.toml"
FCI = "feature_count_improver"


class Bus:
    def publish(self, type_, data, **kw):
        return {"id": kw["id"]}


def store(tmp_path, authors=("supervisor",)):
    cfg = SimpleNamespace(settle_own=tuple(authors), settle_own_from=WHERE if authors else None, announce_hold=3)
    return ModelStore(tmp_path / "model").intended(SimpleNamespace(config=cfg))


def machine(mid=FCI):
    return {"op": "propose_machine", "id": mid, "kind": "universal", "engagement": {"mode": "continuous"},
            "receives": ["session.settled"]}


def confirm(mid=FCI, **kw):
    return {"op": "confirm", "part": "machine", "id": mid, **kw}


def test_without_the_setting_the_author_cannot_settle_its_own_proposal(tmp_path):
    s = store(tmp_path, authors=())
    s.apply([machine()], SUP)
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([confirm()], SUP)
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([{"op": "discard", "part": "machine", "id": FCI}], SUP)
    assert s.read()["layer"]["machines"][FCI]["state"] == "proposed"


def test_with_it_the_author_confirms_its_own_recorded_as_its_own(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUP)
    s.apply([confirm()], SUP)
    m = s.read()["layer"]["machines"][FCI]
    assert m["state"] == "declared"
    assert m["confirmed"]["by"] == "supervisor" and m["confirmed"]["by"] != "owner"
    assert m["confirmed"]["standing_consent"] == WHERE and m["confirmed"]["reason"] == SUP["reason"]
    line = s.journal()[-1]
    assert line["provenance"]["author"] == "supervisor" and line["provenance"]["standing_consent"] == WHERE
    assert line["provenance"]["reason"] == SUP["reason"]
    assert "standing_consent" not in s.journal()[0]["provenance"]     # the proposal itself used none
    # the API field the Machines page reads says who confirmed, and under what
    it = intent_of(m, s.read()["layer"], True, None, None, {})
    assert it["confirmed"]["by"] == "supervisor" and it["confirmed"]["standing_consent"] == WHERE


def test_a_standing_settle_needs_the_authors_reason_and_names_only_the_named(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUP)
    with pytest.raises(IntentError, match="carries the author's reason"):
        s.apply([confirm()], {"author": "supervisor", "source": "supervisor"})
    other = {"author": "workflows", "source": "workflows", "reason": "a workflow's own machine"}
    s.apply([machine("wf")], other)
    with pytest.raises(IntentError, match="confirmed by the owner"):    # not named in settle_own
        s.apply([confirm("wf")], other)
    with pytest.raises(IntentError, match="confirmed by the owner"):    # named, but the proposal is another's
        s.apply([confirm("wf")], SUP)


def test_the_author_discards_its_own_proposal_and_its_own_pending_change(tmp_path):
    s = store(tmp_path)
    s.apply([machine(), machine("other")], SUP)
    s.apply([{"op": "discard", "part": "machine", "id": "other"}], SUP)
    assert "other" not in s.read()["layer"]["machines"]
    s.apply([confirm()], SUP)
    c = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "A"}}], SUP)["changes"][0]["change"]
    s.apply([confirm(change=c)], SUP)
    assert s.read()["layer"]["machines"][FCI]["title"] == "A"


def test_the_owners_elements_stay_the_owners(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], OWNER)                                       # the owner's own proposal
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([confirm()], SUP)
    s.apply([machine("mine")], SUP)                                   # the Supervisor's, which the owner confirmed
    s.apply([confirm("mine")], OWNER)
    c = s.apply([{"op": "revise_machine", "id": "mine", "set": {"title": "B"}}], SUP)["changes"][0]["change"]
    assert s.read()["layer"]["machines"]["mine"]["pending"]           # a change to the owner's waits
    with pytest.raises(IntentError, match="confirmed by the owner"):
        s.apply([confirm("mine", change=c)], SUP)
    with pytest.raises(IntentError, match="the owner declared this"):
        s.apply([{"op": "retract", "part": "machine", "id": "mine"}], SUP)
    s.apply([{"op": "declare_stock", "id": "queue", "name": "Queue"}], OWNER)
    with pytest.raises(IntentError, match="the owner declared this"):
        s.apply([{"op": "retract", "part": "stock", "id": "queue"}], SUP)


def test_the_owners_pending_change_still_overrides(tmp_path):
    s = store(tmp_path)
    s.apply([machine()], SUP)
    s.apply([confirm()], SUP)
    mine = s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "S"}}], SUP)["changes"][0]["change"]
    s.apply([{"op": "revise_machine", "id": FCI, "set": {"title": "O"}}], OWNER)
    with pytest.raises(IntentError, match="touches the same fields"):
        s.apply([confirm(change=mine)], SUP)


def test_the_owner_discards_what_the_author_confirmed_so(tmp_path):
    s = store(tmp_path)
    s.apply([machine(), machine("two")], SUP)
    s.apply([confirm(), confirm("two")], SUP)
    rid = requests.publish(s, Bus(), {"control": "discard", "part": "machine", "id": FCI})["id"]   # no 409: the owner's to undo
    s.apply([{"op": "discard", "part": "machine", "id": FCI}], {**SUP, "request": rid})
    assert FCI not in s.read()["layer"]["machines"]
    assert ("machine", FCI) not in requests.unanswered(s)
    s.apply([{"op": "discard", "part": "machine", "id": "two"}], OWNER)                          # or in their own words
    assert "two" not in s.read()["layer"]["machines"]
    s.apply([machine("three")], SUP)
    s.apply([confirm("three")], OWNER)
    with pytest.raises(IntentError, match="not proposed: there is nothing to discard") as e:     # the owner's own: retract
        requests.publish(s, Bus(), {"control": "discard", "part": "machine", "id": "three"})
    assert e.value.status == 409


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    monkeypatch.delenv(OVERLAY_ENV, raising=False)
    monkeypatch.delenv("ORCHESTRA_REPO", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "orchestra.toml").write_text('[metrics]\nurl = "file"\n')
    return init_project(r)


def test_the_consent_is_read_only_from_the_owners_overlay(project):
    (project.repo_root / "orchestra.toml").write_text('[metrics]\nurl = "file"\n[intended]\nsettle_own = ["supervisor"]\n')
    assert load_project(project.repo_root).config.settle_own == ()            # committed in the repository: ignored
    project.overlay_file.write_text('[intended]\nsettle_own = ["supervisor"]\n')
    cfg = load_project(project.repo_root).config
    assert cfg.settle_own == ("supervisor",) and cfg.settle_own_from == f"[intended] settle_own in {project.overlay_file}"
    assert load_project(project.repo_root).intended.standing == {"authors": ("supervisor",), "from": cfg.settle_own_from}
    live = project.intended                                   # a running host's store follows the owner's edit
    project.overlay_file.write_text('# taken back\n')
    assert live.standing is None
    project.overlay_file.write_text('[intended]\nsettle_own = ["owner"]\n')
    with pytest.raises(ConfigError, match="other than the owner"):
        load_project(project.repo_root)


def test_no_plugin_gives_itself_the_consent(project):
    for target in ("overlay", "repo"):
        with pytest.raises(ConfigError, match="standing consent"):
            project.config_edit.set("intended.settle_own", ["supervisor"], target=target)
    project.overlay_file.write_text('[intended]\nsettle_own = ["supervisor"]\n')
    project.reload_config()
    with pytest.raises(ConfigError, match="standing consent"):
        project.config_edit.unset("intended.settle_own", target="overlay")
    assert project.config_edit.set("intended.max_instances", 10, target="overlay").changed   # the rest of [intended] is not held
