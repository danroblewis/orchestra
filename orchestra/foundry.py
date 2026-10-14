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
        unknown = sorted(set(d) - set(cls.__dataclass_fields__))
        if unknown:
            raise OrgError(f"stock {d.get('key', '?')}: unknown field(s) {unknown}; known: {sorted(cls.__dataclass_fields__)}")
        return cls(**d)


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
        from .foundrymetrics import SIGNAL_KEYS
        key = (self.signal or {}).get("key")
        if key and key not in SIGNAL_KEYS:
            raise OrgError(f"loop {self.key}: signal {key!r} is not a computed signal; one of {', '.join(sorted(SIGNAL_KEYS))}")
        for k in self.readings:
            if k not in SIGNAL_KEYS:
                raise OrgError(f"loop {self.key}: reading {k!r} is not a computed signal; one of {', '.join(sorted(SIGNAL_KEYS))}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Loop:
        unknown = sorted(set(d) - set(cls.__dataclass_fields__))
        if unknown:
            raise OrgError(f"loop {d.get('key', '?')}: unknown field(s) {unknown}; known: {sorted(cls.__dataclass_fields__)}")
        return cls(**d)


# -- the template: a software foundry (the golden configuration in tests/unit/test_foundry_golden.py)

DOC_GLOBS = ["AGENTS.md", "README.md", "CLAUDE.md", ".orchestra/teams/*.md", ".orchestra/roles/*.md", ".orchestra/spaces/*/lessons/decided/*.md"]

TEMPLATE_STOCKS: list[Stock] = [
    Stock("demand", "Demand", "tickets", "Work ordered and not started, including tickets blocked back to the planner.", ["ticket_created", "ticket_transition:OPEN", "ticket_transition:IN_PROGRESS>BLOCKED"], ["ticket_transition:IN_PROGRESS", "ticket_transition:CANCELLED"], [],
          [{"kind": "tracker", "states": ["OPEN", "BLOCKED"]}], row="chain", pos=[62, 222], width=112),
    Stock("wip", "Work in progress", "commits ahead of main", "Commits on ticket branches that have not landed, whatever state the ticket is in; the landing drains it, and a ticket blocked back to the planner leaves it. The level is counted in commits (git); the filling event is a ticket pickup, so the link is symbolic.", ["ticket_transition:IN_PROGRESS"], ["gate_landed", "ticket_transition:CANCELLED", "ticket_transition:IN_PROGRESS>BLOCKED"], [],
          [{"kind": "git_ahead"}], row="chain", pos=[290, 222], width=150),
    Stock("awaiting_review", "Awaiting review", "changes", "Submitted changes the reviewer has not judged yet (Reinertsen's queue; Ford & Sterman's work needing QA).",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:IN_REVIEW>APPROVED", "ticket_transition:IN_REVIEW>REJECTED"], [],
          [{"kind": "tracker", "states": ["READY_FOR_REVIEW", "IN_REVIEW"]}], row="chain", pos=[470, 222], width=130),
    Stock("undiscovered", "Undiscovered rework", "defects", "Defects in submitted and landed work that nobody has found. Hidden; only discovery drains it (a review rejection with a verdict, a gate rejection, a defect found after landing); an approval carries them on.",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected", "defect_escaped"], [],
          [{"kind": "none", "reason": "its level needs a second, independent estimate of what remains hidden (capture-recapture between review and the gate); the outflows (found in review, at the gate, after landing) are measured"}],
          hidden=True, row="rework", pos=[330, 480], width=196),
    Stock("approved", "Awaiting the gate", "changes", "Approved changes queued for the merge gate.", ["ticket_transition:APPROVED"], ["gate_landed", "gate_rejected", "gate_conflict"], [],
          [{"kind": "tracker", "states": ["APPROVED", "MERGING"]}], row="chain", pos=[640, 222], width=120),
    Stock("known_rework", "Known rework", "send-backs", "Changes a reviewer or the gate sent back for a defect and not yet re-submitted; the re-submission drains it.", ["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], ["ticket_transition:READY_FOR_REVIEW"], ["worker"],
          [{"kind": "pending_defects"}], row="rework", pos=[600, 480], width=164),
    Stock("landed", "Landed software", "commits", "Commits the gate put on main. The product; nothing drains it. A ticket's DONE is the same arrival seen from the tracker.", ["gate_landed", "ticket_transition:DONE"], [], [],
          [{"kind": "landed"}], row="chain", pos=[810, 222], width=160),
    Stock("build", "Working build", "builds", "The staging build the acceptance suite ran against, and whether it is up. Drained when it fails in service or the health loop has to restart it; a broken main is the gate's problem, not the build's.", ["staging_deployed"], ["staging_failed", "staging_restarted"], [],
          [{"kind": "staging"}], row="chain", pos=[1000, 222], width=134),
    Stock("really_done", "Really done", "acceptance tests passing", "Acceptance tests that pass, not skipped, in the gate run that produced the deployed build. Actual progress, against DONE tickets as perceived progress. Filled when a build is deployed, since that run proved it; drained when the build fails in service or main's latest check fails.",
          ["staging_deployed"], ["staging_failed", "staging_restarted", "gate_base_broken"], [], [{"kind": "gate_tests", "stage": "acceptance", "source": "deployed"}], row="chain", pos=[1190, 222], width=150),
    Stock("pipeline_blocked", "Pipeline blocked", "pauses", "The gate is paused: main itself failed the gate, or an operator paused the pipeline; the pipeline manager's resume drains it. One pause event per incident (a broken base also raises gate_base_broken, which is the wake-up, not the fill).", ["pipeline_paused"], ["pipeline_resumed"], [],
          [{"kind": "events", "initial": 0, "since": "2026-01-01T00:00:00Z"}], row="rework", pos=[900, 480], width=150),
    Stock("tests", "Verified behaviour", "tests", "Tests on main by stage from the last gate run that reflects main. Skipped tests are never counted. Filled by test authoring, which reaches main through a landing; a team that names the authoring declares its own event and adds it here.", ["gate_landed"], [],
          [{"agent": "reviewer", "effect": "+"}, {"agent": "merge_gate", "effect": "+"}], [{"kind": "gate_tests", "source": "main"}], addition=True, row="capability", pos=[760, 52], width=200),
    Stock("resources", "Environment resources", "documents", "What the worker and reviewer read before working: AGENTS.md, README, team and role docs, decided lessons. Filled when agent-facing documents land; a devex team that decides lessons declares its own event (lesson_decided) and adds it here.", ["gate_landed"], [],
          [{"agent": "worker", "effect": "-"}, {"agent": "reviewer", "effect": "+"}], [{"kind": "repo_docs", "globs": DOC_GLOBS}], addition=True, row="capability", pos=[292, 52], width=200),
]

TEMPLATE_LOOPS: list[Loop] = [
    Loop("review_rework", "rework cycle (review)", "", "known rework → worker re-submits → awaiting review → reviewer → known rework (the defect co-flows through undiscovered rework)", ["known_rework", "worker", "awaiting_review", "reviewer"],
         {"key": "bad_fix_fraction", "adverse": "up", "threshold": 0.5}, ["bad_fix_fraction", "fix_rounds"], "most fixes are rejected again: the reviewer's feedback is not reaching the worker", "Cooper 1980; Lyneis & Ford 2007"),
    Loop("gate_rework", "rework cycle (gate)", "", "known rework → worker re-submits → awaiting review → reviewer → awaiting the gate → gate → known rework", ["known_rework", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"],
         {"key": "acceptance_defects_at_gate", "adverse": "up", "threshold": 0}, ["gate_distinct_defects", "acceptance_defects_at_gate"], "a defect reached the gate's acceptance stage, which the pre-review check does not run: add acceptance verification before review, waking on ticket_transition:READY_FOR_REVIEW", "Cooper 1980; Madachy 2008 (defect flow)"),
    Loop("capability", "capability", "B", "known rework → keeper → resources → worker injects less → undiscovered → reviewer → known rework", ["known_rework", "resources", "worker", "undiscovered", "reviewer"],
         {"key": "review_pass", "adverse": "down"}, ["review_pass", "review_miss_rate"], "the devex team declares lesson_decided (update_team emits), its keeper emits it when a lesson is decided, and resources lists it as an inflow", "Repenning & Sterman 2001 (work smarter)"),
    Loop("earlier_detection", "earlier detection", "", "landed → test author → tests → gate runs them → landed", ["landed", "tests", "merge_gate"],
         {"key": "defects_before_gate_share", "adverse": "down"}, ["defects_before_gate_share"], "a team that writes tests declares an event for it (update_team emits), the test author emits it, and tests lists it as an inflow", "Orchestra's addition", addition=True),
    Loop("broken_base", "broken base", "B", "main fails the gate → the pipeline is blocked → the pipeline manager resumes it → the gate runs again", ["pipeline_blocked", "pipeline_manager", "merge_gate"],
         {"key": "base_broken", "adverse": "up"}, ["base_broken"], "main failed the gate: nothing lands until it is repaired; the pipeline manager owns this", "Abdel-Hamid & Madnick 1991 (errors build errors)"),
    Loop("replanning", "re-planning", "", "worker blocks a ticket back to demand → the coordinator re-plans it → Orchestra starts it again", ["wip", "worker", "demand", "orchestra"],
         {"key": "starts", "adverse": "down"}, ["starts"], "", "Orchestra's own"),
    Loop("wip_limit", "WIP limit", "B", "work in progress → a controller lowers capacity → fewer pickups → work in progress", ["wip", "flow_controller", "demand"],
         {"key": "conflicts_per_landing", "adverse": "up", "threshold": 1}, ["conflicts_per_landing"], "conflicts outnumber landings: reduce what is in progress before adding producers. The controller is an agent with the capacity tool group, woken by ticket_transition:IN_PROGRESS, that emits capacity_changed; declare capacity_changed as an outflow of demand (fewer pickups) so the loop closes.", "Reinertsen 2009 (hypothesis: no controller yet; the operator has acted by hand)"),
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
            except (json.JSONDecodeError, TypeError, OrgError):
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
  Its `signal` names a computed signal (acceptance_defects_at_gate, bad_fix_fraction, base_broken, conflicts_per_landing, defects_after_landing, defects_before_gate_share, defects_found_after_landing, fix_rounds, gate_defects, gate_distinct_defects, gate_pass, hours_lost, landed_per_worker_hour, restarts, review_defects, review_miss_rate, review_pass, reviewer_timeout_share, rework_share, starts, worker_hours_lost, worker_timeout_share) and the direction that is adverse.
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


def agents_for_detection(project, agents: dict) -> dict:
    """The org's agents with the events their tools and teams let them cause folded into
    ``emits`` (``org.effective_emits``), so a product owner that files tickets fills demand."""
    import copy

    from .org import all_teams, effective_emits
    from .roles import role_store
    roles = {r.name: r for r in role_store(project).list()}
    teams = all_teams(project)
    out = {}
    for name, ag in agents.items():
        c = copy.copy(ag)
        c.emits = list(effective_emits(ag, roles, teams)) if not ag.builtin else list(ag.emits or [])
        out[name] = c
    return out
