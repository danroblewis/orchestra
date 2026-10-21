"""The found model as a git diff of the truth (sdlab/ladder/diff.py, diff_text.py, diff_report.py): the
same lines, stat and hunk as the page's own logic (ladder-compare.js, ladder-draw.js), which node
checks here on the same fixtures when it is installed."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sdlab.ladder import diff as D
from sdlab.ladder import diff_report as R
from sdlab.ladder.diff_text import fmt, num_str, part_name, rate_text

STATIC = Path(__file__).resolve().parents[1] / "sdlab" / "static"

COFLOW = {"id": "x", "model": {"stocks": [{"id": "A"}, {"id": "B"}, {"id": "R"}], "flows": [
    {"id": "in", "from": None, "to": "A", "rate": {"form": "constant", "value": 10}},
    {"id": "ab", "from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.3}, "uses": [{"stock": "R", "per": 0.5}]},
    {"id": "b_out", "from": "B", "to": None, "rate": {"form": "proportional", "stock": "B", "k": 0.2}}]}}


def part(key, ok, found=True, t=1, f=1, err=None):
    return {"key": key, "kind": "x", "ok": ok, "found": found, "true": t, "found_value": f if found else None, "error": err}


FOUND = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 10.1}},
         {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.24}},
         {"from": "R", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.16}}]
SCORES = {"status": "fail", "parts": [part("outside -> A [const]", True, True, 10, 10.1), part("A -> B [A]", False, True, 0.3, 0.24, 0.2),
                                      part("uses R on A -> B", False, False, 0.5), part("B -> outside [B]", False, False, 0.2)],
          "spurious": [{"key": "R -> outside [A]", "value": 0.16}]}
HIDDEN = {"id": "h", "model": {"stocks": [{"id": "A"}, {"id": "B"}], "flows": [
    {"id": "ab", "from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.3}}]}}
HIDDEN_FOUND = [{"from": "A", "to": "A~B", "rate": {"form": "proportional", "stock": "A", "k": 0.3}},
                {"from": "A~B", "to": "B", "rate": {"form": "proportional", "stock": "A~B", "k": 0.2}}]
HIDDEN_SCORES = {"status": "fail", "parts": [part("A -> B [A]", False, False, 0.3)], "spurious": [{"key": "A -> (hidden) -> B", "value": {"k_in": 0.3, "delay": 5}}]}
EQUIV_SCORES = {"status": "equivalent", "parts": [part("outside -> A [const]", True), part("A -> B [A]", True), part("uses R on A -> B", False, False),
                                                  part("B -> outside [B]", True)], "spurious": [{"key": "R -> outside [A]", "value": 0.15}]}
EQUIV_FOUND = [{"from": "R", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.15}}]


def test_numbers_are_written_as_javascript_writes_them():
    assert [num_str(x) for x in (1e-7, 0.000001, 1.5e-7, 100.0, 0.1 + 0.2, 1e21, -2.5)] == ["1e-7", "0.000001", "1.5e-7", "100", "0.30000000000000004", "1e+21", "-2.5"]
    assert [fmt(x) for x in (None, 0, 1234.5, 0.0123456, 12.34567, 2.5e22, float("nan"))] == ["–", "0", "1,235", "0.0123", "12.35", "25,000,000,000,000,000,000,000", "NaN"]
    assert fmt({"mean": 0.4, "per_window": [0.5, 0.25]}) == "0.5 / 0.25"
    assert rate_text({"form": "linear", "c": 0, "terms": [{"stock": "A", "k": 0.1}, {"stock": "B", "k": -0.2}]}) == "0.1·A − 0.2·B"
    assert part_name("B -> outside [B]") == "the drain of B" and part_name("outside -> C [B]") == "the link B ⇒ C"


def test_lines_signs_and_notes():
    d = D.diff(COFLOW, FOUND, SCORES)
    assert [(x["sign"], x["ends"]) for x in d["lines"]] == [("~", "A -> B"), ("-", "B -> outside"), ("+", "R -> outside")]
    assert [x["sign"] for x in d["unchanged"]] == [" "] and d["unchanged"][0]["note"] == "found 10.1"
    wrong = d["lines"][0]
    assert wrong["note"].startswith("found 0.24·A: 0.24 for 0.3 (20% low); missed the co-flow")
    assert wrong["true_id"] == "ab" and wrong["true_eq"] == "0.3·A, uses 0.5 R each" and wrong["found_eq"] == "0.24·A"
    assert {"part": "A -> B [A]", "true": 0.3, "found": 0.24, "rel_error": 0.2, "ok": False, "found_it": True} in wrong["numbers"]
    assert d["lines"][2]["note"] == "invented 0.16·A"
    assert d["stat"] == {"removed": 1, "added": 1, "wrong": 1, "equivalent": 0}
    assert d["caption"] == "Differences: 1 removed · 1 added · 1 value wrong"
    assert d["hunk"]["stocks"] == ["A", "B", "R"]
    assert [(h["side"], h["index"]) for h in d["hunk"]["flows"]] == [("truth", 1), ("truth", 2), ("found", 2)]
    assert [f["cls"] for f in d["flows"]["truth"]] == ["ok", "wrong", "missing"]
    assert R.line_text(wrong).split() [:4] == ["~", "A", "->", "B"] and "A 0.3 -> 0.24 (20% off)" in R.line_text(wrong)


def test_a_stock_only_the_found_model_has_is_in_the_hunk():
    d = D.diff(HIDDEN, HIDDEN_FOUND, HIDDEN_SCORES)
    assert d["extra_stocks"] == ["A~B"]
    assert [x["sign"] for x in d["lines"]] == ["-", "+", "+"]
    assert d["hunk"]["stocks"] == ["A", "B", "A~B"]
    assert d["caption"] == "Differences: 1 removed · 2 added"


def test_equivalent_reading():
    d = D.diff(COFLOW, EQUIV_FOUND, EQUIV_SCORES)
    assert d["equivalent"] and d["stat"]["equivalent"] == 2
    assert [x["sign"] for x in d["lines"]] == ["=", "="]
    assert d["lines"][1]["note"].startswith("read as 0.15·A (equivalent to the co-flow")


def test_declared_boundary_decides_a_claim_in_the_hunk():
    found = [{"from": None, "to": "B", "rate": {"form": "constant", "value": 3}}]
    scores = {"status": "fail", "parts": [], "spurious": [{"key": "outside -> B [const]", "value": 3}]}
    undeclared = D.hunk(COFLOW, D.compare(COFLOW["model"], found, scores))
    declared = D.hunk({**COFLOW, "boundary": {}}, D.compare(COFLOW["model"], found, scores))
    assert undeclared["flows"][0]["cls"] == "claim" and declared["flows"][0]["cls"] == "spurious"


def test_summary_normalises_numbers_and_directions():
    d = D.diff(COFLOW, FOUND, SCORES)
    assert R.shape("0.03·inflight + 1,234·x − 1e-7·y") == "#·inflight + #·x − #·y"
    assert [R.norm(x) for x in d["lines"]] == ["~ A -> B  #·A, uses # R each  [A low, missed co-flow (A → B uses R)]",
                                               "- B -> outside  #·B", "+ R -> outside  invented #·A"]


def test_between_two_results():
    a = {**D.diff(COFLOW, FOUND, SCORES), "result": 1, "at": "2026-10-21T00:00", "code_commit": "aaa", "result_status": "fail"}
    better = [{**FOUND[0]}, {**FOUND[1], "rate": {"form": "proportional", "stock": "A", "k": 0.29}}]
    s2 = {**SCORES, "parts": [SCORES["parts"][0], part("A -> B [A]", False, True, 0.3, 0.29, 0.033), *SCORES["parts"][2:]], "spurious": []}
    b = {**D.diff(COFLOW, better, s2), "result": 2, "at": "2026-10-21T01:00", "code_commit": "bbb", "result_status": "fail"}
    got = R.between(a, b)
    assert [x["ends"] for x in got["fixed"]] == ["R -> outside"] and not got["new"]
    assert got["changed"][0]["numbers"][0]["closer"] is True
    assert {"ends": "R -> outside", "before": ["0.16·A"], "after": []} in got["flows"]
    text = R.between_text(got, "x s v")
    assert "fixed   + R -> outside" in text and "closer" in text


NODE = r"""
const fs = require("fs"), vm = require("vm");
const ctx = { window: { innerWidth: 1200 }, globalThis: {} }; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1] + "/ladder-compare.js", "utf8"), ctx);
ctx.window.SDLadder = ctx.globalThis.SDLadder || ctx.window.SDLadder; ctx.window.SDDiagram = {};
vm.runInContext(fs.readFileSync(process.argv[1] + "/ladder-draw.js", "utf8").replace("root.SDLadderDraw = {", "root.SDLadderDraw = { tStockIds,"), ctx);
const L = ctx.window.SDLadder, P = ctx.window.SDLadderDraw;
const out = JSON.parse(fs.readFileSync(0, "utf8")).map(([c, found, scores, dif]) => {
  const one = (cmp) => { const { dD } = P.diagrams(c, cmp, found), fo = P.focus(dD, P.tStockIds(c), cmp.api && cmp.api.hunk);
    return { lines: L.diffLines(cmp).map((l) => [l.sign, l.cls, l.ends, l.truth, l.note]), caption: P.diffStat(cmp),
      kept: fo.stocks.filter((s) => !s.faded).map((s) => s.id), shown: fo.flows.filter((f) => !f.faded).map((f) => [f.from ?? null, f.to ?? null, f.cls]) }; };
  const own = L.compare(c.model, found, scores);
  return { own: one(own), api: one(L.withDiff(own, dif, scores)) };
});
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_page_draws_the_same_diff_from_its_own_logic_and_from_the_server():
    cells = [(COFLOW, FOUND, SCORES), (HIDDEN, HIDDEN_FOUND, HIDDEN_SCORES), (COFLOW, EQUIV_FOUND, EQUIV_SCORES)]
    payload = [[c, f, s, D.diff(c, f, s)] for c, f, s in cells]
    got = json.loads(subprocess.run(["node", "-e", NODE, str(STATIC)], input=json.dumps(payload), capture_output=True, text=True, check=True).stdout)
    for (c, f, s, d), g in zip(payload, got):
        assert g["own"] == g["api"]
        assert g["own"]["caption"] == d["caption"]
        assert g["own"]["kept"] == d["hunk"]["stocks"]
        py = sorted([*d["lines"], *d["unchanged"]], key=lambda x: (x["side"] != "truth", x["index"]))
        assert [[x["cls"], x["ends"], x["note"]] for x in py] == [[cls, ends.replace(" → ", " -> "), note] for _, cls, ends, _, note in g["own"]["lines"]]
