/**
 * Orchestra Pi extension: registers the tools an agent uses to talk to Orchestra.
 *
 * Which tools are registered depends on ORCHESTRA_ROLE (worker, reviewer, supervisor,
 * coordinator, pipeline_manager). Every tool shells out to `python -m orchestra api <cmd>`
 * against the project named by ORCHESTRA_REPO, so it works whether or not `orchestra run`
 * is up. See SPEC.md section 4.3.
 */

import { execFileSync } from "node:child_process";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ROLE = process.env.ORCHESTRA_ROLE ?? "";
const REPO = process.env.ORCHESTRA_REPO ?? "";
const TICKET = process.env.ORCHESTRA_TICKET ?? "";
const PYTHON = process.env.ORCHESTRA_PYTHON ?? "python3";

function api(command: string, args: Record<string, unknown>): string {
  try {
    const out = execFileSync(
      PYTHON,
      ["-m", "orchestra", "api", command, "--args", JSON.stringify(args)],
      {
        env: { ...process.env, ORCHESTRA_REPO: REPO, ORCHESTRA_ROLE: ROLE, ORCHESTRA_TICKET: TICKET },
        cwd: REPO || process.cwd(),
        encoding: "utf8",
        maxBuffer: 8 * 1024 * 1024,
        timeout: 60_000,
      },
    );
    return out.trim();
  } catch (err: any) {
    const stderr = err?.stderr?.toString?.() ?? "";
    const stdout = err?.stdout?.toString?.() ?? "";
    return JSON.stringify({ ok: false, error: (stdout || stderr || String(err)).trim().slice(-2000) });
  }
}

function tool(name: string, description: string, params: any, command = name) {
  return defineTool({
    name,
    label: name,
    description,
    parameters: params,
    async execute(_id, p) {
      const text = api(command, p as Record<string, unknown>);
      return { content: [{ type: "text", text }], details: undefined };
    },
  });
}

const S = (d: string) => Type.String({ description: d });
const OS = (d: string) => Type.Optional(Type.String({ description: d }));

export default function (pi: ExtensionAPI) {
  if (ROLE === "worker") {
    pi.registerTool(
      tool(
        "report_ticket",
        "Report the outcome of your work on this ticket. Call exactly once when you are finished. " +
          "READY_FOR_REVIEW means your changes are committed on your branch and ready for a reviewer. " +
          "BLOCKED means you cannot proceed; blocked_reason is required and must say what you need.",
        Type.Object({
          state: Type.Union([Type.Literal("READY_FOR_REVIEW"), Type.Literal("BLOCKED")]),
          summary: S("What you changed and why, in a few sentences"),
          blocked_reason: OS("Required when state is BLOCKED"),
        }),
      ),
    );
    return;
  }

  if (ROLE === "reviewer") {
    pi.registerTool(
      tool(
        "report_review",
        "Report your review verdict. Call exactly once when you are finished reading the change. " +
          "APPROVED means the code is correct, complete against the acceptance criteria, and consistent " +
          "with the repository. REJECTED must include specific, actionable feedback the worker can act on.",
        Type.Object({
          verdict: Type.Union([Type.Literal("APPROVED"), Type.Literal("REJECTED")]),
          summary: S("Short summary of the review"),
          feedback: OS("Required when REJECTED: concrete problems, with file and line where possible"),
        }),
      ),
    );
    return;
  }

  // Supervisor, Coordinator, Pipeline Manager share the ticket tools.
  pi.registerTool(tool("project_status", "Counts of tickets by state, milestones, active sessions, pipeline state.", Type.Object({})));
  pi.registerTool(tool("list_milestones", "List all milestones with id, name, status, and ticket counts.", Type.Object({})));
  pi.registerTool(
    tool("create_milestone", "Create a milestone to group tickets. Returns its id (M1, M2, ...).",
      Type.Object({ name: S("Short name"), description: OS("What this milestone is for") })),
  );
  pi.registerTool(
    tool("update_milestone", "Rename or re-describe a milestone.",
      Type.Object({ id: S("Milestone id"), name: OS("New name"), description: OS("New description"), order: Type.Optional(Type.Integer()) })),
  );
  pi.registerTool(
    tool("close_milestone", "Close a milestone. Only allowed when every ticket in it is DONE or CANCELLED. Irreversible.",
      Type.Object({ id: S("Milestone id") })),
  );
  pi.registerTool(
    tool("list_tickets", "List tickets, optionally filtered by state or milestone.",
      Type.Object({ state: OS("One of OPEN, BLOCKED, IN_PROGRESS, READY_FOR_REVIEW, IN_REVIEW, REJECTED, APPROVED, MERGING, DONE, CANCELLED"), milestone_id: OS("Milestone id") })),
  );
  pi.registerTool(tool("get_ticket", "Full detail of one ticket including its notes.", Type.Object({ id: S("Ticket id like ORC-12") })));
  pi.registerTool(
    tool(
      "create_ticket",
      "Create a ticket in an open milestone. The description must be a self-contained brief a worker can " +
        "implement without asking questions; acceptance lists how a reviewer will judge it done.",
      Type.Object({
        title: S("Short imperative title"),
        description: S("Self-contained implementation brief"),
        acceptance: S("Acceptance criteria, one per line"),
        milestone_id: S("Milestone id, e.g. M1"),
        priority: Type.Optional(Type.Integer({ description: "1 (first) .. 9 (last); default 5" })),
        depends_on: Type.Optional(Type.Array(Type.String(), { description: "Ticket ids that must be DONE first" })),
      }),
    ),
  );
  pi.registerTool(
    tool("update_ticket", "Edit a ticket's title, description, acceptance, priority, milestone, or dependencies.",
      Type.Object({
        id: S("Ticket id"), title: OS("New title"), description: OS("New description"), acceptance: OS("New acceptance criteria"),
        priority: Type.Optional(Type.Integer()), milestone_id: OS("Move to this open milestone"),
        depends_on: Type.Optional(Type.Array(Type.String())),
      })),
  );
  pi.registerTool(tool("add_note", "Append a note to a ticket.", Type.Object({ id: S("Ticket id"), text: S("Note text") })));
  pi.registerTool(tool("cancel_ticket", "Cancel a ticket that should not be done.", Type.Object({ id: S("Ticket id"), reason: S("Why") })));
  pi.registerTool(
    tool("unblock_ticket", "Move a BLOCKED ticket back to OPEN after resolving its blocker. Explain the resolution in note.",
      Type.Object({ id: S("Ticket id"), note: S("How the blocker was resolved") })),
  );
  if (ROLE === "pipeline_manager") {
    pi.registerTool(tool("get_gate_run", "Detail and logs of one merge gate run.", Type.Object({ id: S("Gate run id") })));
    pi.registerTool(tool("list_gate_runs", "Recent merge gate runs.", Type.Object({})));
    pi.registerTool(tool("get_staging_status", "Status and recent log of the staging environment.", Type.Object({})));
    pi.registerTool(tool("restart_staging", "Restart the staging process on its current build.", Type.Object({})));
    pi.registerTool(tool("resume_pipeline", "Resume the merge pipeline after a base-branch failure has been fixed.", Type.Object({ note: S("What was fixed") })));
  }
}
