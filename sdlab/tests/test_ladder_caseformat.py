"""The ladder's compact case format (sdlab/ladder/caseformat.py): every construct compiles to the
JSON case it stands for, mistakes are reported with their line, the 25 converted cases are exactly
the JSON cases they replaced, and the CLI's new and check work."""

import hashlib
import json

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import cli
from sdlab.ladder.caseformat import CaseError, compile_case

HEAD = """\
title: T
level: 1
tags: [x]
tests: t
stocks: {A: 0, B: 0, C: 50}
"""


def flows(body: str, stocks: str | None = None) -> list[dict]:
    text = HEAD if stocks is None else HEAD.replace("{A: 0, B: 0, C: 50}", stocks)
    return compile_case(text + "flows:\n" + body)["model"]["flows"]


def one(expr: str) -> dict:
    f = flows(f"  A -> B: {expr}\n")[0]
    return {k: v for k, v in f.items() if k not in ("id", "from", "to")}


# ---- every construct ----

def test_the_whole_case():
    c = compile_case(HEAD + "seed: 4\nflows:\n  outside -> A: 20\n")
    assert c == {"title": "T", "level": 1, "tags": ["x"], "tests": "t",
                 "model": {"seed": 4, "stocks": [{"id": "A", "initial": 0}, {"id": "B", "initial": 0}, {"id": "C", "initial": 50}],
                           "flows": [{"id": "in", "from": None, "to": "A", "rate": {"form": "constant", "value": 20}}]}}


@pytest.mark.parametrize("expr, want", [
    ("20", {"form": "constant", "value": 20}),
    ("2.5", {"form": "constant", "value": 2.5}),
    ("1e-3", {"form": "constant", "value": 0.001}),
    ("0.5 * A", {"form": "proportional", "stock": "A", "k": 0.5}),
    ("A * 0.5", {"form": "proportional", "stock": "A", "k": 0.5}),
    ("A", {"form": "proportional", "stock": "A", "k": 1}),
    ("A / 4", {"form": "proportional", "stock": "A", "k": 0.25}),
    ("max(0, 0.5 * A)", {"form": "proportional", "stock": "A", "k": 0.5}),
    ("(300 - B) / 5", {"form": "gap", "stock": "B", "goal": 300, "time": 5}),
    ("30 - 0.25 * A", {"form": "linear", "c": 30, "terms": [{"stock": "A", "k": -0.25}]}),
    ("2 + 0.01 * A + 0.02 * B", {"form": "linear", "c": 2, "terms": [{"stock": "A", "k": 0.01}, {"stock": "B", "k": 0.02}]}),
    ("0.01 * A + 0.02 * B", {"form": "linear", "terms": [{"stock": "A", "k": 0.01}, {"stock": "B", "k": 0.02}]}),
    ("0.1 * A - 5", {"form": "linear", "c": -5, "terms": [{"stock": "A", "k": 0.1}]}),
    ("max(0, 0.2 * A - 30)", {"form": "linear", "c": -30, "terms": [{"stock": "A", "k": 0.2}]}),
    ("available", {"form": "available"}),
    ("available(A)", {"form": "available", "stock": "A"}),
])
def test_rates(expr, want):
    assert one(expr) == {"rate": want}
    assert type(one(expr)["rate"].get("value", 0)) is type(want.get("value", 0)), "20 stays an int, as JSON has it"


def test_effects_and_coflows():
    assert one("0.3 * A * effect(C, linear, normal=50, max=2)") == {
        "rate": {"form": "proportional", "stock": "A", "k": 0.3}, "effects": [{"stock": "C", "shape": "linear", "normal": 50, "max": 2}]}
    assert one("0.3 * A * effect(C, table, [[0, 0.2], [50, 1], [100, 1.4]])")["effects"] == [
        {"stock": "C", "shape": "table", "points": [[0, 0.2], [50, 1], [100, 1.4]]}]
    assert one("0.3 * A * effect(C, normal=50, min=0.5)")["effects"] == [{"stock": "C", "normal": 50, "min": 0.5}]
    two = one("0.3 * A * effect(C, linear, normal=50) * effect(B, table, points=[[0, 1], [10, 0]])")
    assert [e["stock"] for e in two["effects"]] == ["C", "B"], "several effects multiply, in order"
    assert one("0.5 * A uses(C, 0.5)") == {"rate": {"form": "proportional", "stock": "A", "k": 0.5}, "uses": [{"stock": "C", "per": 0.5}]}
    both = one("0.5 * A * effect(C, linear, normal=50, max=2) uses(C, 0.5) uses(B, 1)")
    assert len(both["effects"]) == 1 and both["uses"] == [{"stock": "C", "per": 0.5}, {"stock": "B", "per": 1}]


def test_flow_ids_ends_and_names():
    fs = flows("  outside -> A: 1\n  outside -> B: 1\n  A -> B: 0.1 * A\n  A -> C as rework: 0.1 * A\n  C -> outside: 0.1 * C\n")
    assert [(f["id"], f["from"], f["to"]) for f in fs] == [
        ("in", None, "A"), ("b_in", None, "B"), ("ab", "A", "B"), ("rework", "A", "C"), ("c_out", "C", None)]
    long = flows("  outside -> Work: 1\n  Work -> Done: 0.1 * Work\n", stocks="{Work: 0, Done: 0}")
    assert [f["id"] for f in long] == ["in", "work_done"]
    named_first = flows("  outside -> A as orders: 1\n  outside -> B: 1\n")
    assert [f["id"] for f in named_first] == ["orders", "b_in"], "the first flow from outside takes 'in' even when named"


def test_two_flows_with_the_same_ends():
    fs = flows("  A -> B: 0.1 * A\n  A -> B as fast: 0.2 * A\n")
    assert [f["id"] for f in fs] == ["ab", "fast"]
    as_list = flows("  - A -> B: 0.1 * A\n  - A -> B as fast: 0.2 * A\n")
    assert as_list == fs, "a list of one-key mappings works the same"


def test_long_forms_pass_through():
    fs = flows("  A -> B:\n    rate: 0.5 * A\n    ratio: 2\n    name: Move\n  B -> outside:\n    rate: {form: constant, value: 3}\n")
    assert fs[0] == {"id": "ab", "from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.5}, "ratio": 2, "name": "Move"}
    assert fs[1]["rate"] == {"form": "constant", "value": 3}
    c = compile_case(HEAD.replace("{A: 0, B: 0, C: 50}", "{A: 0 final, H: 5 hidden, B: {initial: 1.5, hidden: true, unit: cups}}")
                     + "flows:\n  H -> A: 0.1 * H\n")
    assert c["model"]["stocks"] == [{"id": "A", "initial": 0, "final": True}, {"id": "H", "initial": 5, "measured": False},
                                    {"id": "B", "initial": 1.5, "measured": False, "unit": "cups"}]


def test_schedule_injections_variants_tolerance():
    c = compile_case(HEAD + """\
seed: 9
variants: {noise: [counts], lengths: {short: 300}}
tolerance: {rel: 0.2}
flows:
  outside -> A: 10
  A -> B: 0.5 * A
  A -> B as slow: 0.1 * A
schedule:
  every: 200
  at 1 low: {outside -> A: 10}
  at 50 "second machine" announced: {ab: 0.6 * A, slow: 0.2 * A}
  at 101 announced:
    in: 30
  at 150:
injections: [{t: 100, stock: A, amount: 500}]
""")
    assert c["variants"] == {"noise": ["counts"], "lengths": {"short": 300}} and c["tolerance"] == {"rel": 0.2}
    assert c["model"]["schedule"] == {"every": 200, "changes": [
        {"t": 1, "label": "low", "set": {"in": {"form": "constant", "value": 10}}},
        {"t": 50, "label": "second machine", "set": {"ab": {"form": "proportional", "stock": "A", "k": 0.6},
                                                     "slow": {"form": "proportional", "stock": "A", "k": 0.2}}, "announce": True},
        {"t": 101, "set": {"in": {"form": "constant", "value": 30}}, "announce": True},
        {"t": 150, "set": {}}]}
    assert c["model"]["injections"] == [{"t": 100, "stock": A_, "amount": 500} for A_ in ["A"]]
    assert "variants" not in compile_case(HEAD + "variants: default\nflows:\n  outside -> A: 1\n")


# ---- mistakes ----

# (A * B, A ^ 2, 1 + 2 + A, (A - 300) / 5 and max(1, A) were errors here until queue item 2d made every
# other rate an expression: tests/test_engine_2d.py checks that they compile to one now)
@pytest.mark.parametrize("body, line, words", [
    ("  A -> B: 0.5 ** A\n", 7, "expected a number"),
    ("  A -> B: 0.5 * Z\n", 7, "unknown stock 'Z'"),
    ("  A -> B: 0.5 * A * effect(C, cubic)\n", 7, "linear or table"),
    ("  A -> B: 0.5 * A * effect(C, table)\n", 7, "points"),
    ("  A -> B: 0.5 * A * effect(C, linear, slope=2)\n", 7, "no 'slope'"),
    ("  A -> B: 0.5 * A uses(C)\n", 7, "uses takes"),
    ("  A -> B: 0.5 * A + uses(C, 1)\n", 7, ""),
    ("  A -> Z: 1\n", 7, "unknown stock 'Z'"),
    ("  A => B: 1\n", 7, "is not 'A -> B'"),
    ("  outside -> outside: 1\n", 7, "one end"),
    ("  outside -> A: 1\n  outside -> A: 2\n", 8, "appears twice"),
    ("  A -> B: 1\n  A -> B as ab: 2\n", 8, "is taken"),
    ("  outside -> A: 1\n  bogus: 2\n", 8, "is not 'A -> B'"),
    ("  A -> B:\n    ratio: 2\n", 7, "needs a rate"),
    ("  A -> B: [1, 2]\n", 7, "not [1, 2]"),
])
def test_errors_name_the_line(body, line, words):
    with pytest.raises(CaseError) as e:
        compile_case(HEAD + "flows:\n" + body, "x.yaml")
    assert str(e.value).startswith(f"x.yaml:{line}: ") and words in str(e.value), str(e.value)


@pytest.mark.parametrize("text, words", [
    (HEAD + "flow:\n  outside -> A: 1\n", "x.yaml:6: unknown key 'flow'"),
    (HEAD, "needs flows"),
    (HEAD.replace("{A: 0, B: 0, C: 50}", "{A: lots}") + "flows:\n  outside -> A: 1\n", "x.yaml:5: stock A"),
    (HEAD.replace("{A: 0, B: 0, C: 50}", "{A: 0 secret}") + "flows:\n  outside -> A: 1\n", "unknown word 'secret'"),
    (HEAD + "flows:\n  outside -> A: 1\nschedule:\n  every: 10\n  at 1: {nope: 2}\n", "x.yaml:10: no flow 'nope'"),
    (HEAD + "flows:\n  outside -> A: 1\nschedule:\n  every: 10\n  when 1: {in: 2}\n", "is not 'at T"),
    (HEAD + "flows:\n  A -> B: 1\n  A -> B as x: 1\nschedule:\n  at 1: {A -> B: 2}\n", "ambiguous"),
    (HEAD + "flows:\n  A -> B: 1\nschedule:\n  at 1:\n    ab: 2 * A uses(B, 1)\n", "rate only"),
    (HEAD + "flows:\n  A -> B: 1\ninjections: [{t: 1, stock: Q, amount: 2}]\n", "unknown stock 'Q'"),
    (HEAD + "flows:\n  A -> B: 1\ninjections: [{t: 1, amount: 2}]\n", "injections is a list"),
    ("title: [unclosed\n", "x.yaml:2: not valid YAML"),
    ("- a list\n", "a case is a mapping"),
])
def test_case_errors(text, words):
    with pytest.raises(CaseError) as e:
        compile_case(text, "x.yaml")
    assert words in str(e.value), str(e.value)


# ---- the converted cases ----

# sha256 (first 16 hex) of each case's canonical JSON (sort_keys, no spaces) as it was in its .json
# file before it became .yaml (commit eb2cd65). The YAML compiles to exactly that. A case changed on
# purpose since then makes its line fail: update the line (cases.spec(id) gives the new dict).
CONVERTED = {
    "001-inflow-only": "6c8463eb9b10b698",
    "002-inflow-outflow": "92dbbca22027be86",
    "003-chain-2": "f28a76779d62cc45",
    "004-chain-3": "87cd2b45692f7fa5",
    "005-chain-4": "a6e0b24f38638b31",
    "006-chain-exit-middle": "aab88743a3173dc2",
    "007-link": "c78db84a1446bca6",
    "008-link-loop": "377a4a04febb357c",
    "009-births-and-deaths": "4842560f9e85873f",
    "010-loop-branch": "b68693e3990e9b28",
    "011-goal-gap": "56c3f67276f8ea09",
    "012-rework": "764ebaf34244518a",
    "013-merge": "eb88961eab9f5555",
    "014-split": "6a60e5fcb362487a",
    "015-hidden-stock": "cf1e11d0e4024348",
    "016-coflow": "79bce77c0c1fae42",
    "017-linear-effect": "ff9fcfc41768bc3f",
    "018-table-effect": "fd04286502137649",
    "019-announced-era": "7e33fa39e106a7e0",
    "020-unannounced-step": "f4c73e6313f1583e",
    "021-daily-inflow": "f441b70e5c3e1e42",
    "022-pulse": "a25ec14344999af9",
    "023-injection": "95b733d0968e901f",
    "024-floor-binds": "0bdc20fb08b88992",
    "025-runs-empty": "6dfb081dcf5314e3",
}


@pytest.mark.parametrize("case_id", sorted(CONVERTED))
def test_each_converted_case_is_the_json_it_replaced(case_id):
    assert casemod.case_files()[case_id].suffix == ".yaml"
    canonical = json.dumps(casemod.spec(case_id), sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest()[:16] == CONVERTED[case_id]


def test_the_hash_is_of_the_model_not_the_file(tmp_path, monkeypatch):
    folder = tmp_path / "cases"
    folder.mkdir()
    monkeypatch.setattr(casemod, "CASES", folder)
    src = (casemod.Path(casemod.__file__).parent / "cases" / "004-chain-3.yaml").read_text()
    (folder / "004-chain-3.yaml").write_text(src)
    yaml_hash = casemod.load("004-chain-3")["hash"]
    (folder / "004-chain-3.yaml").write_text(src.replace("flows:", "# a comment\nflows:").replace("0.5 * A", "A * 0.5"))
    assert casemod.load("004-chain-3")["hash"] == yaml_hash, "how a case is written does not matter"
    spec = casemod.spec("004-chain-3")
    (folder / "004-chain-3.yaml").unlink()
    (folder / "004-chain-3.json").write_text(json.dumps(spec, indent=2))
    assert casemod.load("004-chain-3")["hash"] == yaml_hash, "nor which format"
    spec["model"]["flows"][1]["rate"]["k"] = 0.4
    (folder / "004-chain-3.json").write_text(json.dumps(spec))
    assert casemod.load("004-chain-3")["hash"] != yaml_hash
    (folder / "004-chain-3.yaml").write_text(src)
    with pytest.raises(CaseError, match="written twice"):
        casemod.case_files()


# ---- the CLI ----

def test_new_writes_a_case_that_checks(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "cases"
    folder.mkdir()
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    monkeypatch.setattr(casemod, "CASES", folder)
    src = casemod.Path(casemod.__file__).parent / "cases" / "003-chain-2.yaml"
    (folder / src.name).write_text(src.read_text())
    assert cli.main(["new", "my-case", "--title", "Mine"]) == 0
    assert capsys.readouterr().out.strip() == str(folder / "004-my-case.yaml")
    c = casemod.load("004-my-case")
    assert c["title"] == "Mine" and c["level"] == 2
    assert cli.main(["check"]) == 0
    assert "004-my-case: ok" in capsys.readouterr().out
    (folder / "005-broken.yaml").write_text("title: x\nstocks: {A: 0}\nflows:\n  outside -> A: 2 *\n")
    assert cli.main(["check"]) == 1
    assert "005-broken: 005-broken.yaml:4: flow outside -> A: expected a number" in capsys.readouterr().out
