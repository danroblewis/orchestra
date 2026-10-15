"""The project's system-dynamics model as data, and the software foundry as its template.

A model is stocks and expected loops under ``.orchestra/model/`` in the target repository
(docs/proposals/software-foundry-model.md, section 5). Flows are never declared: the
detector (``foundrygraph``) derives them from the agents' wake rules and emits and the
stocks' filling and draining events. ``orchestra init`` writes the template; the
Supervisor curates it from then on through the model tools. Code holds only the instrument
kinds (``foundrymetrics``), the detector, and the renderer. No other module reads the
model files."""

from __future__ import annotations

import hashlib
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
    loss: bool = False                                      # a stock of machine loss (nothing of the product is found or made there): never a co-flow with the hidden stock
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

    carried_by: list[str] = field(default_factory=list)     # event types that carry its content onward without draining it (a deploy carries landed commits into a build)
    carried_to: dict = field(default_factory=dict)          # event type -> the stock it carries to, where the event fills more than one
    template_hash: str | None = None    # the content the template wrote; unchanged since means the template may update it

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
    template_hash: str | None = None    # the content the template wrote; unchanged since means the template may update it

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
    Stock("demand", "Demand", "tickets", "Work ordered and not started (OPEN). A blocked ticket waits with the planner and comes back here when it is re-planned.", ["ticket_created", "ticket_transition:OPEN"], ["ticket_transition:OPEN>IN_PROGRESS", "ticket_transition:OPEN>CANCELLED"], [],
          [{"kind": "tracker", "states": ["OPEN"]}], row="chain", pos=[62, 222], width=112),
    Stock("blocked", "Blocked", "tickets", "Tickets a worker could not finish, back with the planner (BLOCKED): the coordinator re-plans them into demand or cancels them.", ["ticket_transition:IN_PROGRESS>BLOCKED"], ["ticket_transition:BLOCKED>OPEN", "ticket_transition:BLOCKED>CANCELLED"], [],
          [{"kind": "tracker", "states": ["BLOCKED"]}], row="rework", pos=[62, 480], width=112),
    Stock("wip", "Work in progress", "changes", "Changes being worked now: tickets IN_PROGRESS, a first implementation or a fix. A pickup fills it, a submission moves the change on to review, a block sends it back to demand, and so does a restart after a turn limit (a loss: the ticket is picked up again). The chain counts changes everywhere; the commits ahead of main on each change's branch are the detail beside the level.", ["ticket_transition:OPEN>IN_PROGRESS", "ticket_transition:REJECTED>IN_PROGRESS"], ["ticket_transition:IN_PROGRESS>READY_FOR_REVIEW", "ticket_transition:CANCELLED", "ticket_transition:IN_PROGRESS>BLOCKED", "ticket_transition:IN_PROGRESS>OPEN"], [],
          [{"kind": "tracker", "states": ["IN_PROGRESS"]}], row="chain", pos=[290, 222], width=150),
    Stock("awaiting_review", "Awaiting review", "changes", "Submitted changes the reviewer has not judged yet (Reinertsen's queue; Ford & Sterman's work needing QA).",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:IN_REVIEW>APPROVED", "ticket_transition:IN_REVIEW>REJECTED"], [],
          [{"kind": "tracker", "states": ["READY_FOR_REVIEW", "IN_REVIEW"]}], row="chain", pos=[470, 222], width=130),
    Stock("undiscovered", "Undiscovered rework", "defects", "Defects in submitted and landed work that nobody has found. Hidden, so it wakes nobody; the agent whose verdict drains it inspects it. Only discovery drains it: a review rejection with a verdict, a gate rejection for a defect, and after landing a finding that names a defect. A landing does not drain it (the defects stay in landed work, undiscovered); a build failing or main failing the base check is not a finding by itself, since the host can cause either.",
          ["ticket_transition:READY_FOR_REVIEW"], ["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], [],
          [{"kind": "none", "reason": "its level needs a second, independent estimate of what remains hidden (capture-recapture between review and the gate); its measured outflows are the defects found in review and at the gate, and the escapes estimated from crashing builds and bug tickets; neither drains it as an event, since a build can fail for the host and a ticket need not name a defect"}],
          hidden=True, row="rework", pos=[330, 480], width=196),
    Stock("approved", "Awaiting the gate", "changes", "Approved changes queued for the merge gate.", ["ticket_transition:APPROVED"], ["gate_landed", "gate_rejected", "gate_conflict"], [],
          [{"kind": "tracker", "states": ["APPROVED", "MERGING"]}], row="chain", pos=[640, 222], width=120),
    Stock("known_rework", "Known rework", "changes", "Changes a reviewer or the gate sent back for a defect, waiting for the fix to be picked up (Ford & Sterman's work known to need rework; Lyneis & Ford's known rework). A send-back for a defect fills it; the fix pickup drains it into work in progress (Cooper's rework progress), so the chain conserves the change. The defect itself stays open until the fix lands: each chain box names how many of its changes carry one. A send-back without a verdict is not a defect and goes to Returned without a verdict.", ["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected"], ["ticket_transition:REJECTED>IN_PROGRESS", "ticket_transition:REJECTED>CANCELLED"], ["worker"],
          [{"kind": "known_rework"}], row="rework", pos=[600, 480], width=164),
    Stock("returned", "Returned without a verdict", "changes", "Changes sent back with no verdict: a review turn that ended at the limit, a gate run that timed out or failed to start, a merge conflict. Not rework (no defect was found); a machine loss. The re-pick moves the change back into work in progress and the turn is run again.", ["ticket_transition:IN_REVIEW>REJECTED", "gate_rejected", "gate_conflict"], ["ticket_transition:REJECTED>IN_PROGRESS", "ticket_transition:REJECTED>CANCELLED"], [],
          [{"kind": "returned"}], row="rework", pos=[780, 480], width=164, loss=True),
    Stock("landed", "Landed software", "commits", "Commits the gate put on main. The product; nothing drains it. A ticket's DONE is the same arrival seen from the tracker, so it is not a second inflow. A deploy carries the landed commits into a build without taking them off main.", ["gate_landed"], [], [],
          [{"kind": "landed"}], row="chain", pos=[810, 222], width=160, carried_by=["staging_deployed"], carried_to={"staging_deployed": "build"}),
    Stock("build", "Working build", "builds", "The staging build the acceptance suite ran against, and whether it is up. Drained when it fails in service or the health loop has to restart it; a broken main is the gate's problem, not the build's.", ["staging_deployed"], ["staging_failed", "staging_restarted"], [],
          [{"kind": "staging"}], row="chain", pos=[1000, 222], width=134),
    Stock("really_done", "Really done", "tests passing", "Acceptance tests that pass, not skipped, in the gate run that produced the deployed build. Actual progress, against DONE tickets as perceived progress. Filled when a build is deployed, since that run proved it; drained when the build fails in service or main's latest check fails; a process restart does not fail a test, so it does not drain it (it leaves the result unverified).",
          ["staging_deployed"], ["staging_failed", "gate_base_broken"], [], [{"kind": "gate_tests", "stage": "acceptance", "source": "deployed"}], row="chain", pos=[1190, 222], width=150),
    Stock("pipeline_blocked", "Pipeline blocked", "pauses", "The gate is paused: main itself failed the gate, or an operator paused the pipeline; the pipeline manager's resume drains it. One pause event per incident (a broken base also raises gate_base_broken, which is the wake-up, not the fill).", ["pipeline_paused"], ["pipeline_resumed"], [],
          [{"kind": "events", "initial": 0, "since": "2026-01-01T00:00:00Z"}], row="rework", pos=[900, 480], width=150),
    Stock("tests", "Verified behaviour", "tests", "Tests on main by stage from the last gate run that reflects main. Skipped tests are never counted. Filled by test authoring, which reaches main through a landing; a team that names the authoring declares its own event and adds it here.", [], [],
          [{"agent": "reviewer", "effect": "+"}, {"agent": "merge_gate", "effect": "+"}], [{"kind": "gate_tests", "source": "main"}], addition=True, row="capability", pos=[760, 52], width=200),
    Stock("resources", "Environment resources", "documents", "What the worker and reviewer read before working: AGENTS.md, README, team and role docs, decided lessons. Filled when agent-facing documents land; a devex team that decides lessons declares its own event (lesson_decided) and adds it here.", [], [],
          [{"agent": "worker", "effect": "-"}, {"agent": "reviewer", "effect": "+"}], [{"kind": "repo_docs", "globs": DOC_GLOBS}], addition=True, row="capability", pos=[292, 52], width=200),
]

TEMPLATE_LOOPS: list[Loop] = [
    Loop("review_rework", "rework cycle (review)", "", "known rework → the fix is picked up into work in progress → the worker re-submits → awaiting review → the reviewer finds the fix wrong → known rework: a conserved circuit of the change, with the defect co-flowing through undiscovered rework; a bad fix re-enters it (Rahmandad & Hu's task cycling); its balancing is in the first-order pairs on its stocks, which the detector names: the pickup that drains known rework is Cooper's rework progress", ["known_rework", "orchestra", "wip", "worker", "awaiting_review", "reviewer"],
         {"key": "review_bad_fix_fraction", "adverse": "up", "threshold": 0.5}, ["review_bad_fix_fraction", "fix_rounds"], "most fixes are rejected again by the reviewer: the reviewer's feedback is not reaching the worker", "Cooper 1980; Lyneis & Ford 2007; Rahmandad & Hu 2010 (task cycling)"),
    Loop("gate_rework", "rework cycle (gate)", "", "known rework → the fix is picked up → the worker re-submits → awaiting review → the reviewer approves → awaiting the gate → the gate finds the fix wrong → known rework; a good fix leaves the circuit at the gate's landing, and the balancing is in the first-order pairs on its stocks, which the detector names", ["known_rework", "orchestra", "wip", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"],
         {"key": "acceptance_defects_at_gate", "adverse": "up", "threshold": 0}, ["gate_distinct_defects", "acceptance_defects_at_gate", "gate_bad_fix_fraction"], "a defect reached the gate's acceptance stage, which the pre-review check does not run: add acceptance verification before review, waking on ticket_transition:READY_FOR_REVIEW", "Cooper 1980; Madachy 2008 (defect flow)"),
    Loop("capability", "capability", "B", "known rework → keeper → resources → worker injects less → undiscovered → reviewer → known rework", ["known_rework", "resources", "worker", "undiscovered", "reviewer"],
         {"key": "review_pass", "adverse": "down"}, ["review_pass", "review_miss_rate"], "the devex team declares lesson_decided (update_team emits), its keeper emits it when a lesson is decided, and resources lists it as an inflow", "Repenning & Sterman 2001 (work smarter)"),
    Loop("earlier_detection", "earlier detection", "", "landed → test author → tests → the gate finds more before landing, instead of in the field (earlier than after landing, not earlier than review); balancing through undiscovered rework, which the graph cannot close, so no polarity is claimed", ["landed", "tests", "merge_gate"],
         {"key": "defects_after_landing", "adverse": "up"}, ["defects_after_landing", "gate_distinct_defects"], "a team that writes tests declares an event for it (update_team emits), the test author emits it, and tests lists it as an inflow", "Orchestra's addition", addition=True),
    Loop("broken_base", "broken base", "B", "main fails the gate → the pipeline is blocked → the pipeline manager resumes it (the pause and its resume are a first-order pair; the gate then runs again)", ["pipeline_blocked", "pipeline_manager"],
         {"key": "hours_since_base_broken", "adverse": "up", "threshold": 1}, ["hours_since_base_broken", "base_broken"], "main's base check failed: nothing lands until the pipeline manager resumes the gate, once the cause (the host or main) is found; the banner gives the evidence for each", "Orchestra's own first-order controller (the pause and its resume)"),
    Loop("field_discovery", "discovery after landing", "", "a deployed build → someone exercises it and files what is wrong → demand → the worker fixes it → review → the gate → a new build; balancing through undiscovered rework (more escapes, more findings, fewer escapes left), which the graph cannot see, so no polarity is claimed. Today the pipeline manager closes it by hand when staging fails (it files a ticket), with no finding event", ["build", "demand", "orchestra", "wip", "worker", "awaiting_review", "reviewer", "approved", "merge_gate"],
         {"key": "defects_after_landing", "adverse": "up"}, ["defects_after_landing"], "nothing inspects a deployed build: create an agent woken by staging_deployed that drives the product and emits a finding event the team declares; list that event among undiscovered rework's outflows and demand's inflows", "Cooper 1980 (rework discovered in the field); the design's flow table, L → D"),
    Loop("firefighting", "firefighting", "R", "more rework takes the worker's time from first implementation and from care, so more defects are injected and more rework follows (Repenning & Sterman's capability trap; Rahmandad & Hu's task cycling). It runs through the worker's attention, which no event carries, so the map cannot draw it; its signal is the rework share against Repenning's tipping point of a third", [],
         {"key": "rework_share", "adverse": "up", "threshold": 0.33}, ["rework_share", "fix_rounds", "bad_fix_fraction"], "past the tipping point, adding producers feeds the loop: take the most cycled tickets out of the fix round (re-plan or split them), and close the capability loop so fixes stop recurring", "Repenning & Sterman 2001; Rahmandad & Hu 2010"),
    Loop("replanning", "re-planning", "", "a ticket is blocked (by the worker, or by Orchestra when the worker stops without a report) → it waits with the planner → the coordinator re-plans it into demand → Orchestra starts it again → the worker. When Orchestra makes the blocks, this is the recovery from a machine loss, not a work-design loop", ["wip", "worker", "blocked", "coordinator", "demand", "orchestra"],
         {"key": "replans", "adverse": "up", "threshold": 5}, ["replans", "starts", "blocks_by_orchestra_share"], "", "Orchestra's own"),
    Loop("wip_limit", "WIP limit", "B", "work in progress → a controller lowers capacity → fewer pickups → work in progress", ["wip", "flow_controller", "demand"],
         {"key": "conflicts_per_landing", "adverse": "up", "threshold": 1}, ["conflicts_per_landing", "landings"], "when conflicts outnumber landings, reduce what is in progress before adding producers. The controller is an agent with the capacity tool group, woken by ticket_transition:IN_PROGRESS, that emits capacity_changed; declare capacity_changed as an outflow of demand (fewer pickups) so the loop closes.", "Reinertsen 2009 (hypothesis: no controller yet; the operator changes capacity by hand, and a window with a handful of landings cannot show the effect)"),
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
        return {"stocks": self._load("stocks", Stock), "loops": self._load("loops", Loop), "source": str(self.root.relative_to(self.project.repo_root)), "unmarked": self.unmarked()}

    def write_template(self, *, force: bool = False) -> list[str]:
        """Write the software-foundry template. An existing element is kept unless forced, or
        unless it still reads exactly as a template wrote it (its ``template_hash`` matches its
        content): then the current template replaces it, so a project that never curated an
        element follows the template, and one that did keeps its own version."""
        written = []
        for sub, items in (("stocks", TEMPLATE_STOCKS), ("loops", TEMPLATE_LOOPS)):
            d = self.root / sub
            d.mkdir(parents=True, exist_ok=True)
            for it in items:
                p = d / f"{it.key}.json"
                body = template_marked(it)
                if p.exists() and not force:
                    try:
                        cur = json.loads(p.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
                    if cur == body or not _unchanged_since_template(cur):
                        continue
                p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
                written.append(str(p.relative_to(self.project.repo_root)))
        (self.root / "README.md").write_text(README, encoding="utf-8")
        if written:
            self.last_commit_note = commit_orchestra_files(self.project, "orchestra: system-dynamics model template")
        return written

    def unmarked(self) -> list[str]:
        """Elements that differ from the template and carry no template mark: written before
        the mark existed or by hand, so the template cannot tell curated from stale."""
        out = []
        for sub, items in (("stocks", TEMPLATE_STOCKS), ("loops", TEMPLATE_LOOPS)):
            for it in items:
                p = self.root / sub / f"{it.key}.json"
                if not p.exists():
                    continue
                try:
                    cur = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if not cur.get("template_hash") and cur != template_marked(it):
                    out.append(f"{sub[:-1]} {it.key}")
        return out

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


def _content_hash(d: dict) -> str:
    body = {k: v for k, v in d.items() if k != "template_hash"}
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def template_marked(item) -> dict:
    """The template element as written: its content plus the hash of that content."""
    d = item.to_dict()
    d["template_hash"] = _content_hash(d)
    return d


def _unchanged_since_template(d: dict) -> bool:
    return bool(d.get("template_hash")) and d["template_hash"] == _content_hash(d)


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
