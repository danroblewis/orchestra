"""The project's system-dynamics model as data, and the software foundry as its template.

A model is stocks and expected loops under ``.orchestra/model/`` in the target repository
(docs/proposals/software-foundry-model.md, section 5). Flows are never declared: the
detector (``foundrygraph``) derives them from the agents' wake rules and emits and the
stocks' filling and draining events. ``orchestra init`` writes the template; the
Supervisor curates it from then on through the model tools. Code holds only the instrument
kinds (``foundrymetrics``), the detector, and the renderer. No other module reads the
model files."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .org import OrgError, commit_orchestra_files

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
STOCK_KINDS = ("tracker", "pending_defects", "git_ahead", "landed", "gate_tests", "staging", "repo_docs", "turn_hours", "events", "probe", "judge", "none")
ROWS = ("capability", "chain", "rework")


@dataclass
class Stock:
    key: str
    name: str
    unit: str
    description: str = ""
    inflows: list[str] = field(default_factory=list)        # event types (type or type:filter) that fill it
    outflows: list[str] = field(default_factory=list)       # event types that drain it
    consumers: list[Any] = field(default_factory=list)      # agents that read it: "name" or {"agent", "effect": "+"|"-"}
    estimators: list[dict] = field(default_factory=list)    # [{kind, ...}], the first gives the level
    hidden: bool = False                                    # declared because the literature says it exists; never counted
    addition: bool = False                                  # not in the published models
    row: str = "chain"
    pos: list[float] | None = None                          # renderer hint [x, y]
    width: int | None = None
    team: str | None = None

    def validate(self) -> None:
        if not KEY_RE.match(self.key):
            raise OrgError(f"stock key {self.key!r}: snake_case, up to 40 characters")
        if self.row not in ROWS:
            raise OrgError(f"stock {self.key}: row must be one of {', '.join(ROWS)}")
        for e in self.estimators:
            if e.get("kind") not in STOCK_KINDS:
                raise OrgError(f"stock {self.key}: estimator kind {e.get('kind')!r} is not one of {', '.join(STOCK_KINDS)}")
            if e["kind"] == "events" and ("initial" not in e or "since" not in e):
                raise OrgError(f"stock {self.key}: an events estimator needs initial and since")
            if e["kind"] == "probe" and not e.get("command"):
                raise OrgError(f"stock {self.key}: a probe estimator needs a command")
        for c in self.consumers:
            if isinstance(c, dict) and c.get("effect", "+") not in ("+", "-"):
                raise OrgError(f"stock {self.key}: a consumer's effect is + or -")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Stock:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Loop:
    """A loop the model expects. The detector marks it detected when a cycle of the causal
    graph covers its nodes (stock keys and agent names); otherwise it is a hypothesis."""
    key: str
    name: str
    polarity: str = ""                  # B or R as claimed by the source; the detector computes its own
    structure: str = ""
    nodes: list[str] = field(default_factory=list)
    signal: dict = field(default_factory=dict)      # {key, adverse: up|down, threshold}
    readings: list[str] = field(default_factory=list)
    hint: str = ""
    source: str = ""
    addition: bool = False
    signature: str | None = None        # a detected cycle the Supervisor named, exactly

    def validate(self) -> None:
        if not KEY_RE.match(self.key):
            raise OrgError(f"loop key {self.key!r}: snake_case, up to 40 characters")
        if self.polarity not in ("B", "R", ""):
            raise OrgError(f"loop {self.key}: polarity is B, R, or empty")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Loop:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# -- the template: a software foundry (the golden configuration in tests/unit/test_foundry_golden.py)

DOC_GLOBS = ["AGENTS.md", "README.md", "CLAUDE.md", ".orchestra/teams/*.md", ".orchestra/roles/*.md", ".orchestra/spaces/*/lessons/decided/*.md"]

TEMPLATE_STOCKS: list[Stock] = [
    Stock("demand", "Demand", "tickets", "Work ordered and not started.", ["ticket_created", "ticket_transition:OPEN"], ["ticket_transition:IN_PROGRESS", "ticket_transition:CANCELLED"], [],
          [{"kind": "tracker", "states": ["OPEN", "BLOCKED"]}], row="chain", pos=[62, 222], width=112),
    Stock("wip", "Work in progress", "commits ahead of main", "Changes being built on ticket branches.", ["ticket_transition:IN_PROGRESS"], ["ticket_transition:READY_FOR_REVIEW"], [],
          [{"kind": "git_ahead"}], row="chain", pos=[290, 222], width=150),
    Stock("awaiting_review", "Awaiting review", "changes", "Submitted changes the reviewer has not judged yet (Reinertsen's queue; Ford & Sterman's work needing QA).",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:APPROVED", "ticket_transition:REJECTED"], [],
          [{"kind": "tracker", "states": ["READY_FOR_REVIEW", "IN_REVIEW"]}], row="chain", pos=[470, 222], width=130),
    Stock("undiscovered", "Undiscovered rework", "defects", "Defects in submitted and landed work that nobody has found. Hidden; only discovery drains it (a review rejection with a verdict, a gate rejection, a defect found after landing); an approval carries them on.",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:REJECTED", "gate_rejected", "staging_failed"], [],
          [{"kind": "none", "reason": "estimable only from defects found after landing (a test that passed before and fails on a new build, a bug ticket citing a landed commit); no such series yet"}],
          hidden=True, row="rework", pos=[330, 480], width=196),
    Stock("approved", "Awaiting the gate", "changes", "Approved changes queued for the merge gate.", ["ticket_transition:APPROVED"], ["gate_landed", "gate_rejected", "gate_conflict"], [],
          [{"kind": "tracker", "states": ["APPROVED", "MERGING"]}], row="chain", pos=[640, 222], width=120),
    Stock("known_rework", "Known rework", "send-backs", "Changes a reviewer or the gate sent back for a defect and not yet re-submitted; the re-submission drains it.", ["ticket_transition:REJECTED", "gate_rejected"], ["ticket_transition:READY_FOR_REVIEW"], ["worker"],
          [{"kind": "pending_defects"}], row="rework", pos=[600, 480], width=164),
    Stock("landed", "Landed software", "commits", "Commits the gate put on main. The product; nothing drains it.", ["gate_landed"], [], [],
          [{"kind": "landed"}], row="chain", pos=[810, 222], width=160),
    Stock("build", "Working build", "builds", "The staging build the acceptance suite ran against, and whether it is up.", ["staging_deployed"], ["staging_failed", "gate_base_broken"], [],
          [{"kind": "staging"}], row="chain", pos=[1000, 222], width=134),
    Stock("really_done", "Really done", "acceptance tests passing", "Acceptance tests that pass, not skipped, in the gate run that produced the deployed build. Actual progress, against DONE tickets as perceived progress. Filled when a build is deployed, since that run proved it.",
          ["staging_deployed"], [], [], [{"kind": "gate_tests", "stage": "acceptance", "source": "deployed"}], row="chain", pos=[1190, 222], width=150),
    Stock("tests", "Verified behaviour", "tests", "Tests on main by stage from the last gate run that reflects main. Skipped tests are never counted. Filled only by test authoring.", ["tests_added"], [],
          [{"agent": "reviewer", "effect": "+"}, {"agent": "merge_gate", "effect": "+"}], [{"kind": "gate_tests", "source": "main"}], addition=True, row="capability", pos=[760, 52], width=200),
    Stock("resources", "Environment resources", "documents", "What the worker and reviewer read before working: AGENTS.md, README, team and role docs, decided lessons.", ["lesson_decided"], [],
          [{"agent": "worker", "effect": "-"}, {"agent": "reviewer", "effect": "+"}], [{"kind": "repo_docs", "globs": DOC_GLOBS}], addition=True, row="capability", pos=[292, 52], width=200),
    Stock("agent_time", "Agent time", "agent-hours per day", "Turn time of agent sessions by activity, with losses beside it.", ["session_started"], ["session_settled"], [],
          [{"kind": "turn_hours"}], row="chain"),
]

TEMPLATE_LOOPS: list[Loop] = [
    Loop("review_rework", "rework cycle (review)", "", "known rework → worker → undiscovered → reviewer → known rework", ["known_rework", "worker", "undiscovered", "reviewer"],
         {"key": "bad_fix_fraction", "adverse": "up", "threshold": 0.5}, ["bad_fix_fraction", "fix_rounds"], "most fixes are rejected again: the reviewer's feedback is not reaching the worker", "Cooper 1980; Lyneis & Ford 2007"),
    Loop("gate_rework", "rework cycle (gate)", "", "known rework → worker → undiscovered → reviewer → awaiting the gate → gate → known rework", ["known_rework", "worker", "undiscovered", "reviewer", "approved", "merge_gate"],
         {"key": "acceptance_defects_at_gate", "adverse": "up", "threshold": 0}, ["gate_distinct_defects", "acceptance_defects_at_gate"], "a defect reached the gate's acceptance stage, which the pre-review check does not run: add acceptance verification before review, waking on ticket_transition:READY_FOR_REVIEW", "Cooper 1980; Madachy 2008 (defect flow)"),
    Loop("capability", "capability", "B", "known rework → keeper → resources → worker injects less → undiscovered → reviewer → known rework", ["known_rework", "resources", "worker", "undiscovered", "reviewer"],
         {"key": "review_pass", "adverse": "down"}, ["review_pass"], "", "Repenning & Sterman 2001 (work smarter)"),
    Loop("earlier_detection", "earlier detection", "", "landed → test author → tests → gate finds more → known rework → fixed → landed", ["landed", "tests", "merge_gate", "known_rework"],
         {"key": "defects_before_gate_share", "adverse": "down"}, ["defects_before_gate_share"], "", "Orchestra's addition", addition=True),
    Loop("broken_base", "broken base", "B", "build fails → pipeline manager → gate resumes → landed → build", ["build", "pipeline_manager", "merge_gate"],
         {"key": "base_broken", "adverse": "up"}, ["base_broken"], "main failed the gate: nothing lands until it is repaired; the pipeline manager owns this", "Abdel-Hamid & Madnick 1991 (errors build errors)"),
    Loop("replanning", "re-planning", "", "worker blocks → coordinator re-plans into demand → Orchestra starts it again", ["wip", "worker", "coordinator", "demand", "orchestra"],
         {"key": "starts", "adverse": "down"}, ["starts"], "", "Orchestra's own"),
    Loop("wip_limit", "WIP limit", "B", "work in progress → a controller throttles pickup → work in progress", ["wip", "flow_controller"],
         {"key": "conflicts_per_landing", "adverse": "up", "threshold": 1}, ["conflicts_per_landing"], "conflicts outnumber landings: reduce what is in progress before adding producers", "Reinertsen 2009 (hypothesis: no controller yet)"),
]


# -- the store -------------------------------------------------------------------------------

class ModelStore:
    """``.orchestra/model/{stocks,loops}/<key>.json`` in the target repository. Reads fall
    back to the template when the directory is absent, and say so."""

    def __init__(self, project) -> None:
        self.project = project
        self.root = project.repo_root / ".orchestra" / "model"
        self.last_commit_note = ""

    def exists(self) -> bool:
        return self.root.is_dir()

    def _load(self, sub: str, cls) -> list:
        out = []
        for p in sorted((self.root / sub).glob("*.json")):
            try:
                out.append(cls.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def load(self) -> dict[str, Any]:
        if not self.exists():
            return {"stocks": list(TEMPLATE_STOCKS), "loops": list(TEMPLATE_LOOPS), "source": "template (not in the repository yet: run `orchestra model init`)"}
        return {"stocks": self._load("stocks", Stock), "loops": self._load("loops", Loop), "source": str(self.root.relative_to(self.project.repo_root))}

    def write_template(self, *, force: bool = False) -> list[str]:
        """Write the software-foundry template; existing files are kept unless forced."""
        written = []
        for sub, items in (("stocks", TEMPLATE_STOCKS), ("loops", TEMPLATE_LOOPS)):
            d = self.root / sub
            d.mkdir(parents=True, exist_ok=True)
            for it in items:
                p = d / f"{it.key}.json"
                if p.exists() and not force:
                    continue
                p.write_text(json.dumps(it.to_dict(), indent=2) + "\n", encoding="utf-8")
                written.append(str(p.relative_to(self.project.repo_root)))
        (self.root / "README.md").write_text(README, encoding="utf-8")
        if written:
            self.last_commit_note = commit_orchestra_files(self.project, "orchestra: system-dynamics model template")
        return written

    def _save(self, sub: str, item) -> None:
        item.validate()
        if not self.exists():
            self.write_template()
        d = self.root / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{item.key}.json").write_text(json.dumps(item.to_dict(), indent=2) + "\n", encoding="utf-8")
        self.last_commit_note = commit_orchestra_files(self.project, f"orchestra: model {sub[:-1]} {item.key}")

    def get(self, kind: str, key: str):
        cls = {"stock": Stock, "loop": Loop}[kind]
        p = self.root / (kind + "s") / f"{key}.json"
        if self.exists() and p.exists():
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        for it in (TEMPLATE_STOCKS if kind == "stock" else TEMPLATE_LOOPS):
            if it.key == key and not self.exists():
                return it
        raise OrgError(f"no model {kind} {key!r}")

    def save(self, kind: str, item) -> None:
        if kind not in ("stock", "loop"):
            raise OrgError("kind is stock or loop")
        self._save(kind + "s", item)

    def delete(self, kind: str, key: str) -> None:
        if kind not in ("stock", "loop"):
            raise OrgError("kind is stock or loop")
        p = self.root / (kind + "s") / f"{key}.json"
        if not p.exists():
            raise OrgError(f"no model {kind} {key!r}")
        p.unlink()
        self.last_commit_note = commit_orchestra_files(self.project, f"orchestra: remove model {kind} {key}")


README = """# The system-dynamics model of this project

Orchestra draws the Agents page's foundry map and detects the project's feedback loops from
these files and the org (agents' wake rules and emits), and only from them. `orchestra init`
wrote the software-foundry template here as a starting point; the Supervisor curates it with
the model tools (`list_model`, `add_model_element`, `update_model_element`,
`remove_model_element`) when the project has outputs or limiting constraints of its own.

- `stocks/<key>.json`: what the project holds. `inflows` and `outflows` are the event types
  that fill and drain it; `consumers` are the agents that read it, each with the sign of the
  effect on that agent's output; `estimators` name an instrument kind (tracker,
  pending_defects, git_ahead, landed, gate_tests, staging, repo_docs, turn_hours, events,
  probe, judge, none) and its parameters; `hidden` stocks are declared because the model
  says they exist and are never shown as a count; `row` and `pos` are drawing hints.
- `loops/<key>.json`: a feedback loop the model expects, by its member stocks and agents.
  The detector marks it detected only when a cycle of the causal graph built from the
  stocks and the org covers those members; otherwise it stays a hypothesis. Cycles the
  detector finds that no loop names are listed for the Supervisor to name.

Flows are not declared. An agent woken by an arrival at one stock whose actions fill
another is a conversion between them, and the map draws it from the org.
"""


def load_model(project) -> dict[str, Any]:
    return ModelStore(project).load()


def as_dict(model: dict) -> dict:
    return {"stocks": [s.to_dict() for s in model["stocks"]], "loops": [lp.to_dict() for lp in model["loops"]], "source": model["source"]}


def model_probes(project, teams: dict) -> list:
    """The probes behind the model's probe estimators, named ``model_<stock>`` so the stock
    reading finds their state; run in the owning team's space when there is one."""
    from .probes import ProbeSpec, parse_interval
    out = []
    for st in load_model(project)["stocks"]:
        for e in st.estimators:
            if e.get("kind") != "probe" or not e.get("command"):
                continue
            team = teams.get(st.team) if st.team else None
            out.append(ProbeSpec(name=f"model_{st.key}", command=e["command"], every=parse_interval(e.get("every", "1h")), timeout=float(e.get("timeout", 120)),
                                 cwd=team.space_dir(project) if team else project.repo_root, team=st.team))
    return out
