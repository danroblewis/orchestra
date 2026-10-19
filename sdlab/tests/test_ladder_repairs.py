"""repairs.py: the scorer's comparison read as the repairs that would make a found model right."""

from sdlab.ladder.repairs import parse, repairs


def part(key, true, found_value=None, ok=False, found=True, se=None, kind="move"):
    return {"key": key, "kind": kind, "found": found, "true": true, "found_value": found_value, "ok": ok, "error": None, "se": se}


def scores(parts, spurious=(), status="fail"):
    return {"status": status, "parts": list(parts), "spurious": list(spurious), "negligible": []}


def test_parse_keys():
    assert parse("B -> outside [B]") == {"kind": "flow", "from": "B", "to": None, "reader": "B"}
    assert parse("outside -> A [const]")["reader"] == "const"
    assert parse("uses R on A -> B") == {"kind": "uses", "stock": "R", "from": "A", "to": "B"}
    assert parse("A -> (hidden) -> B") == {"kind": "hidden", "from": "A", "to": "B"}


def test_number_repair_has_sign_and_percent_found_first():
    r = repairs(scores([part("B -> outside [B]", 0.2, 0.356, se=0.004), part("outside -> B [const]", 20.0, 20.1, ok=True)]))
    assert r["count"] == 1 and r["by"] == {"number": 1}
    it = r["items"][0]
    assert it["type"] == "number"
    assert abs(it["diff"] - 0.156) < 1e-12 and abs(it["rel"] - 0.78) < 1e-12
    assert it["text"] == "B → outside: 0.356·B, should be 0.2·B (+0.156, +78%)"
    assert it["short"] == "+0.156 (+78%)"
    assert it["limit"] == "method error" and it["se_source"] == "oracle"
    assert r["headline"] == "1 repair: 1 number"


def test_number_too_low_and_data_limited_by_the_bound():
    an = {"label": "data-limited", "parts": [{"part": "A -> B [A]", "window": 0, "crb_se": 0.05, "allowed": 0.03}]}
    r = repairs(scores([part("A -> B [A]", 0.5, 0.42, se=0.01)]), an)
    it = r["items"][0]
    assert it["short"] == "−0.08 (−16%)"
    assert it["se_source"] == "bound" and abs(it["z"] - 1.6) < 1e-9
    assert it["limit"] == "data-limited" and it["allowed"] == 0.03
    assert r["label"] == "data-limited"


def test_add_and_remove():
    r = repairs(scores([part("outside -> C [const]", 20.0, found=False, kind="outside inflow"), part("A -> B [A]", 0.1, 0.1, ok=True)],
                       [{"key": "C -> A [C]", "kind": "move", "value": 0.066, "size": 3.0}]))
    assert r["by"] == {"remove": 1, "add": 1}
    texts = [i["text"] for i in r["items"]]
    assert texts == ["remove: C → A (0.066·C)", "add: outside → C (20)"]
    assert r["headline"] == "2 repairs: 1 remove, 1 add"


def test_term_on_a_flow_that_is_otherwise_there():
    on = [part("A -> outside [A]", 0.2, 0.2, ok=True, kind="outside outflow")]
    r = repairs(scores(on + [part("A -> outside [const]", 3.0, found=False, kind="outside outflow")]))
    assert r["items"][0]["text"] == "add term to A → outside: 3"
    r = repairs(scores(on, [{"key": "A -> outside [B]", "kind": "outside outflow", "value": 0.05, "size": 2.0}]))
    assert r["items"][0]["text"] == "remove term from A → outside: 0.05·B"


def test_change_form_groups_a_missing_and_an_invented_flow_on_the_same_edge():
    r = repairs(scores([part("A -> outside [A]", 0.2, found=False, kind="outside outflow")],
                       [{"key": "A -> outside [B]", "kind": "outside outflow", "value": 0.1, "size": 5.0}]))
    assert r["count"] == 1 and r["by"] == {"form": 1}
    assert r["items"][0]["text"] == "change form: A → outside: 0.1·B, should be 0.2·A"


def test_equivalent_names_the_equivalence_and_whether_the_data_can_tell():
    an = {"label": "unidentifiable", "parts": [], "equivalences": [
        "the inflow 20 into A and its outflow 0.2 x A are one inflow 20 - 0.2 x A (a gap): the same mean change of every stock",
        "the link outside -> B reading A (0.1) with A's drain 0.2 is the move A -> B (0.1) with A's drain 0.1: the same mean change of every stock"]}
    r = repairs(scores([part("outside -> A [const]", 20.0, 20.0, ok=True), part("A -> outside [A]", 0.2, 0.1, se=1e-7),
                        part("outside -> B [A]", 0.1, found=False, kind="link"), part("B -> outside [B]", 0.2, 0.2, ok=True)],
                       [{"key": "A -> B [A]", "kind": "move", "value": 0.1, "size": 10.0}], status="equivalent"), an)
    assert r["by"] == {"remove": 1, "add": 1, "number": 1}
    eq = r["equivalence"]
    assert eq["unidentifiable"] and eq["texts"] == ["the link outside → B reading A (0.1) with A's drain 0.2 is the move A → B (0.1) with A's drain 0.1"]
    assert "cannot tell them apart" in eq["text"]
    assert all(i["limit"] == "equivalent" for i in r["items"])


def test_pass_and_no_model():
    assert repairs(scores([part("A -> B [A]", 0.1, 0.1, ok=True)], status="pass"))["headline"] == "no repairs"
    assert repairs(None)["count"] is None


def test_hidden_and_per_window_numbers():
    r = repairs(scores([part("A -> (hidden) -> B", {"k_in": 0.2, "delay": 4.0}, {"k_in": 0.3, "delay": 4.0}, kind="hidden"),
                        part("outside -> A [const]", {"mean": 10.0, "per_window": [5.0, 15.0]}, {"mean": 12.0, "per_window": [6.0, 18.0]}, kind="outside inflow")]))
    texts = [i["text"] for i in r["items"]]
    assert "A → (hidden) → B: k 0.3, delay 4, should be k 0.2, delay 4 (k +0.1, +50%; delay ±0, ±0.0%)" in texts
    assert "outside → A: 12, should be 10 (+2, +20%), on average over 2 windows" in texts
