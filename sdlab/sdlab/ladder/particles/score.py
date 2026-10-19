"""Scoring a found model on a particle case (the physics view, never in the Tests pass rate).

  equations   (exact and measured tiers) the ladder's own equation scorer (score.equations) against the
              mean-field model: every part (a move, an inflow from an input, a product as an effect with
              its co-flow) right within the ladder's tolerances for counting noise, the oracle's standard
              errors included, nothing spurious. pass / equivalent / fail as for any case
  structure   the coupling graph of the found model against the mean-field model's (physics/structure.py)
  behaviour   skill@20 and skill@100 against what the particles did next (physics/score.py's grading),
              on the run discovery saw and on a fresh particle run from new initial counts and drivers
  long run    the found model run free for 5,000 steps against the particles (physics/score.py)
  reference   the mean-field model graded the same way (reference.py): the best possible forecasts on
              the exact tier

**status**: on the exact and measured tiers, the equations' status. On the prediction tier (no exact
mean-field model): pass when the fresh run's skill@20 and skill@100 are each within 5 points of the
reference's, or better; else fail.
"""

from __future__ import annotations

from .. import score as _ladder_score
from ..physics import score as _physics_score

GAP = 0.05


def grade(case: dict, flows: list[dict], clean: dict, fresh: dict, long: dict, inferred: dict | None = None) -> dict:
    return _physics_score.grade(case, flows, clean, fresh, long, inferred, case["particles"]["allowed"])


def score(case: dict, model: dict, flows: list[dict], d: dict, fresh: dict, long: dict, ref: dict, inferred: dict | None = None) -> dict:
    """Everything stored for one found model: the ladder's keys (status, recall, precision, right, of, parts,
    behaviour), `physics` (as on a physics case: couplings, long run, the reference) and `particles` (the
    tier, the equations' status, the gaps to the mean-field reference)."""
    pt = case["particles"]
    g = grade(case, flows, d, fresh, long, inferred)
    st, b = g["structure"], g["behaviour"]
    sk = _physics_score.skill
    f20, r20 = sk(b, "fresh", 20), sk(ref["behaviour"], "fresh", 20)
    f100, r100 = sk(b, "fresh", 100), sk(ref["behaviour"], "fresh", 100)
    gap20 = None if f20 is None or r20 is None else f20 - r20
    gap100 = None if f100 is None or r100 is None else f100 - r100
    near = gap20 is not None and gap100 is not None and gap20 >= -GAP and gap100 >= -GAP
    eq = _ladder_score.equations(case, "counts", model, flows, d) if pt["equations"] else None
    if eq is not None:
        out = dict(eq)
    else:
        out = {"status": "pass" if near else "fail", "pass": near, "equivalent": False, "recall": st["recall"], "precision": st["precision"],
               "right": st["right"], "of": st["of"], "parts": [], "spurious": [], "negligible": [], "windows": 1,
               "notes": [f"mean-field vs particles: {pt['differs']}"] if pt.get("differs") else []}
    ph = case["physics"]
    out["physics"] = {"system": ph["system"], "couplings": st["couplings"], "spurious": st["spurious"], "sampling": st["sampling"],
                      "structure_ok": st["ok"], "shape_right": st["shape_right"], "shape_of": st["shape_of"], "longrun": g["longrun"],
                      "near_reference": near, "gap20": gap20, "gap100": gap100,
                      "reference": {"how": ph["reference"]["how"], "behaviour": ref["behaviour"], "longrun": ref["longrun"],
                                    "structure_ok": ref["structure"]["ok"], "shape_right": ref["structure"]["shape_right"]}}
    out["particles"] = {"tier": pt["tier"], "equations": eq["status"] if eq is not None else None, "near_reference": near,
                        "gap20": gap20, "gap100": gap100, "coupling_right": st["right"], "coupling_of": st["of"]}
    out["behaviour"] = b
    return out
