import pytest

from sdlab.ladder import caseformat


CASE = "title: t\nlevel: 1\ntags: [x]\ntests: t\n{extra}stocks:\n  A: 10\nflows:\n  outside -> A: 1\n"


def test_a_case_may_set_its_own_timeout():
    out = caseformat.compile_case(CASE.format(extra="timeout: 900\n"), "t.yaml")
    assert out["timeout"] == 900.0


def test_a_bad_timeout_is_refused():
    with pytest.raises(caseformat.CaseError):
        caseformat.compile_case(CASE.format(extra="timeout: 0\n"), "t.yaml")
