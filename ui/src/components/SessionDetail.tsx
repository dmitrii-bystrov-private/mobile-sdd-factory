import { useState } from "react";

import { FollowupContextPanel } from "./FollowupContextPanel";
import { InteractiveStatePanel } from "./InteractiveStatePanel";
import { JiraSubtasksPanel } from "./JiraSubtasksPanel";
import { OperatorActions } from "./OperatorActions";
import { PlanningArtifactPanel } from "./PlanningArtifactPanel";
import { RoleStatusPanel } from "./RoleStatusPanel";
import { RuntimeSessionPanel } from "./RuntimeSessionPanel";
import { SubtaskGraphPanel } from "./SubtaskGraphPanel";
import { SubtaskProgressPanel } from "./SubtaskProgressPanel";
import { roleDisplayName } from "../roleDisplay";
import {
  workflowProfileDisplayName,
} from "../sessionDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { Role, Session, SessionBundle, WorkItem } from "../types";

type SessionDetailProps = {
  session: Session | null;
  bundle: SessionBundle | null;
  onRefresh: () => Promise<void>;
};

function humanizeEventType(value: string): string {
  return value
    .split("_")
    .filter((part) => part.length > 0)
    .map((part) => part[0].toUpperCase() + part.slice(1))
    .join(" ");
}

function workTypeSummary(workType: string): string {
  switch (workType) {
    case "implementation":
      return "Implementation work is active.";
    case "correction":
      return "A correction pass is active.";
    case "followup":
      return "Follow-up work is active.";
    case "verification":
      return "Verification work is active.";
    case "review":
      return "Review work is active.";
    default:
      return `${humanizeEventType(workType)} is active.`;
  }
}

function standbyExpectation(roleName: string, workflowProfile: Session["workflow_profile"]): string {
  switch (roleName) {
    case "verification-coordinator":
      return "Waiting for verification handoff.";
    case "code-reviewer":
      return "Waiting for self-review handoff.";
    case "code-scout":
      return "Waiting for Boy Scout handoff.";
    case "doc-harvest-worker":
      return "Waiting for doc-harvest handoff.";
    case "mr-comments-analyst-worker":
      return "Waiting for MR follow-up input.";
    case "bug-fixer":
      return "Waiting for bug-fix handoff.";
    case "proposal-context-worker":
    case "requirements-clarifier-worker":
    case "acceptance-criteria-worker":
    case "constraints-worker":
    case "spec-verifier-worker":
    case "story-spec-worker":
    case "task-decomposer-worker":
      return "Waiting for story-planning handoff.";
    case "implementer":
      return workflowProfile === "story_full"
        ? "Waiting for subtask execution handoff."
        : "Waiting for the next coding handoff.";
    default:
      return "Waiting for the next handoff.";
  }
}

function laneSummary(
  role: Role,
  workItems: WorkItem[],
  session: Session,
): { title: string; body: string } {
  const ownedWorkItem =
    workItems.find((item) => item.owner_role_id === role.id && item.status === "active") ??
    workItems.find((item) => item.owner_role_id === role.id && item.status === "pending") ??
    null;

  if (ownedWorkItem) {
    return {
      title: ownedWorkItem.title,
      body: workTypeSummary(ownedWorkItem.work_type),
    };
  }

  if (session.current_owner === role.role_name) {
    return {
      title: `Owning ${stageDisplayName(session.current_stage)}`,
      body: "This lane currently owns the live workflow stage.",
    };
  }

  switch (role.status) {
    case "running":
      return {
        title: standbyExpectation(role.role_name, session.workflow_profile),
        body: "This lane is live and ready for the next handoff.",
      };
    case "waiting":
      return {
        title: "Waiting for the next handoff",
        body: "This lane is waiting on upstream progress or operator input.",
      };
    case "stopped":
      return {
        title: "Stopped",
        body: "This lane is not currently running.",
      };
    case "completed":
      return {
        title: "Completed",
        body: "This lane has already finished its current work.",
      };
    default:
      return {
        title: humanizeEventType(role.status),
        body: "This lane reported a non-standard runtime state.",
      };
  }
}

function roleFlowOrder(roleName: string, workflowProfile: Session["workflow_profile"]): number {
  const oneshotOrder = [
    "implementer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];
  const bugFullOrder = [
    "implementer",
    "bug-fixer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];
  const storyFullOrder = [
    "proposal-context-worker",
    "requirements-clarifier-worker",
    "acceptance-criteria-worker",
    "constraints-worker",
    "spec-verifier-worker",
    "story-spec-worker",
    "task-decomposer-worker",
    "implementer",
    "code-reviewer",
    "verification-coordinator",
    "code-scout",
    "doc-harvest-worker",
    "mr-comments-analyst-worker",
  ];

  const orderedRoles =
    workflowProfile === "story_full"
      ? storyFullOrder
      : workflowProfile === "bug_full"
        ? bugFullOrder
        : oneshotOrder;

  const index = orderedRoles.indexOf(roleName);
  return index === -1 ? orderedRoles.length + 1 : index;
}

function workerStateLabel(role: Role, activeRoleIds: Set<number>): string {
  if (activeRoleIds.has(role.id)) {
    return "Active";
  }
  if (role.status === "running") {
    return "Standing by";
  }
  if (role.status === "waiting") {
    return "Waiting";
  }
  if (role.status === "stopped") {
    return "Stopped";
  }
  if (role.status === "completed") {
    return "Completed";
  }
  return humanizeEventType(role.status);
}

export function SessionDetail({
  session,
  bundle,
  onRefresh,
}: SessionDetailProps): JSX.Element {
  const [detailSurface, setDetailSurface] = useState<"workflow" | "runtime">("workflow");
  const [showWorkflowDetails, setShowWorkflowDetails] = useState(false);

  if (session === null || bundle === null) {
    return (
      <section className="panel panel-empty">
        <p className="eyebrow">No Session Selected</p>
        <h2>Choose a task session to inspect the factory state.</h2>
      </section>
    );
  }

  const visibleRoles = bundle.roles.filter((role) => role.role_name !== "task-coordinator");
  const ownedRoleNames = new Set(
    bundle.workItems
      .filter((item) => item.status === "active" || item.status === "pending")
      .map((item) => item.owner_role_id),
  );
  const activeRoles = visibleRoles.filter(
    (role) =>
      role.status === "running" &&
      (session.current_owner === role.role_name || ownedRoleNames.has(role.id)),
  );
  const currentOwner = session.current_owner
    ? roleDisplayName(session.current_owner)
    : session.status === "active"
      ? "Awaiting assignment"
      : "Not assigned yet";
  const showRoleStatusPanel =
    bundle.workItems.length > 0 ||
    visibleRoles.some((role) => role.status !== "running");
  const showFollowupContextPanel = bundle.followupContext !== null;
  const activeRoleIds = new Set(activeRoles.map((role) => role.id));
  const orderedRoles = [...visibleRoles].sort((left, right) => {
    const orderDelta =
      roleFlowOrder(left.role_name, session.workflow_profile) -
      roleFlowOrder(right.role_name, session.workflow_profile);
    if (orderDelta !== 0) {
      return orderDelta;
    }
    return left.id - right.id;
  });
  const firstColumnCount = Math.ceil(orderedRoles.length / 2);
  const workerColumns = [
    orderedRoles.slice(0, firstColumnCount),
    orderedRoles.slice(firstColumnCount),
  ];
  const workflowDetailCount = [
    bundle.subtaskProgressSummary !== null && bundle.subtaskProgressSummary.available,
    bundle.jiraSubtasksSummary !== null,
    showFollowupContextPanel,
    bundle.subtaskGraphSummary !== null && bundle.subtaskGraphSummary.available,
    bundle.planningSummary !== null && session.workflow_profile === "story_full",
  ].filter(Boolean).length;

  return (
    <section className="detail-layout">
      <div className="panel hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Current Session</p>
          <div className="hero-heading-row">
            <div className="hero-heading-main">
              <h1 className="hero-key">{session.task_key}</h1>
              {session.task_title ? <p className="hero-title">{session.task_title}</p> : null}
            </div>
            {session.jira_url ? (
              <a className="hero-link hero-link-button" href={session.jira_url} rel="noreferrer" target="_blank">
                Open in Jira
              </a>
            ) : null}
          </div>
          <div className="hero-status-strip">
            <div className="hero-status-item">
              <span>Profile</span>
              <strong>{workflowProfileDisplayName(session.workflow_profile)}</strong>
            </div>
            <div className="hero-status-item">
              <span>Stage</span>
              <strong>{stageDisplayName(session.current_stage)}</strong>
            </div>
            <div className="hero-status-item">
              <span>Owner</span>
              <strong>{currentOwner}</strong>
            </div>
          </div>
        </div>
      </div>

      <div className="session-detail-nav">
        <button
          className={`inline-pill inline-pill-button ${detailSurface === "workflow" ? "selected" : ""}`}
          onClick={() => setDetailSurface("workflow")}
          type="button"
        >
          Workflow
        </button>
        <button
          className={`inline-pill inline-pill-button ${detailSurface === "runtime" ? "selected" : ""}`}
          onClick={() => setDetailSurface("runtime")}
          type="button"
        >
          Runtime Tools
        </button>
      </div>

      {detailSurface === "workflow" ? (
        <>
      <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Progress</p>
              <h3>Workflow Pulse</h3>
            </div>
          </div>
        <div className="workflow-pulse-grid">
          {workerColumns.map((column, columnIndex) => (
            <div className="workflow-pulse-column" key={`worker-column-${columnIndex}`}>
              {column.map((role) => {
                const summary = laneSummary(role, bundle.workItems, session);
                const isActive = activeRoleIds.has(role.id);
                return (
                  <article
                    className={`progress-card workflow-pulse-card${isActive ? " workflow-pulse-card-active" : ""}`}
                    key={`worker-${role.id}`}
                  >
                    <div className="subpanel-head">
                      <strong>{roleDisplayName(role.role_name)}</strong>
                      <span className={`status-pill status-${role.status === "running" ? "running" : role.status}`}>
                        {workerStateLabel(role, activeRoleIds)}
                      </span>
                    </div>
                    <p className="progress-card-title">{summary.title}</p>
                    <p className="progress-card-body">{summary.body}</p>
                  </article>
                );
              })}
            </div>
          ))}
        </div>

      </section>

      <OperatorActions
        interactiveStateSummary={bundle.interactiveStateSummary}
        onRefresh={onRefresh}
        session={session}
      />

      <InteractiveStatePanel interactiveStateSummary={bundle.interactiveStateSummary} />
      {workflowDetailCount > 0 ? (
        <div className="advanced-disclosure">
          <button
            className="advanced-disclosure-toggle"
            onClick={() => setShowWorkflowDetails((current) => !current)}
            aria-expanded={showWorkflowDetails}
            type="button"
          >
            <div>
              <strong>Workflow Details</strong>
            </div>
            <div className="advanced-disclosure-meta">
              <small>{workflowDetailCount} detail panels</small>
              <span className={`chevron${showWorkflowDetails ? " expanded" : ""}`} aria-hidden="true" />
            </div>
          </button>
          {showWorkflowDetails ? (
            <div className="advanced-disclosure-body runtime-surface-stack">
              <SubtaskProgressPanel subtaskProgressSummary={bundle.subtaskProgressSummary} />
              <JiraSubtasksPanel
                jiraSubtasksSummary={bundle.jiraSubtasksSummary}
                subtaskGraphSummary={bundle.subtaskGraphSummary}
                subtaskProgressSummary={bundle.subtaskProgressSummary}
              />

              {showFollowupContextPanel ? (
                <FollowupContextPanel followupContext={bundle.followupContext} />
              ) : null}
              <SubtaskGraphPanel subtaskGraphSummary={bundle.subtaskGraphSummary} />
              <PlanningArtifactPanel
                planningSummary={bundle.planningSummary}
                workflowProfile={session.workflow_profile}
              />
              {showRoleStatusPanel ? (
                <RoleStatusPanel roles={bundle.roles} workItems={bundle.workItems} />
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
        </>
      ) : null}

      {detailSurface === "runtime" ? (
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Runtime</p>
            <h3>Runtime</h3>
          </div>
        </div>
        <div className="runtime-surface-stack">
          <RuntimeSessionPanel
            onRefresh={onRefresh}
            runtimeStateSummary={bundle.runtimeStateSummary}
            session={session}
          />
        </div>
      </section>
      ) : null}
    </section>
  );
}
