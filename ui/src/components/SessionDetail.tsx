import { useState } from "react";

import { ArtifactPanel } from "./ArtifactPanel";
import { FollowupContextPanel } from "./FollowupContextPanel";
import { InteractiveStatePanel } from "./InteractiveStatePanel";
import { JiraSubtasksPanel } from "./JiraSubtasksPanel";
import { OperatorActions } from "./OperatorActions";
import { PlanningArtifactPanel } from "./PlanningArtifactPanel";
import { PlanningSummaryPanel } from "./PlanningSummaryPanel";
import { RoleStatusPanel } from "./RoleStatusPanel";
import { RuntimeSessionPanel } from "./RuntimeSessionPanel";
import { SubtaskGraphPanel } from "./SubtaskGraphPanel";
import { SubtaskProgressPanel } from "./SubtaskProgressPanel";
import { roleDisplayName } from "../roleDisplay";
import {
  sessionStatusDisplayName,
  workflowProfileDisplayName,
} from "../sessionDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { EventItem, Role, Session, SessionBundle, WorkItem } from "../types";

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

function producerDisplayName(value: string): string {
  if (value === "coordinator") {
    return "Coordinator";
  }
  if (value === "role") {
    return "Role Runtime";
  }
  if (value === "operator") {
    return "Operator";
  }
  return humanizeEventType(value);
}

function relativeTimeLabel(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "Unknown time";
  }
  const diffMs = timestamp - Date.now();
  const diffMinutes = Math.round(diffMs / 60000);
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(diffMinutes) < 60) {
    return rtf.format(diffMinutes, "minute");
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return rtf.format(diffHours, "hour");
  }
  const diffDays = Math.round(diffHours / 24);
  return rtf.format(diffDays, "day");
}

function eventSummary(event: EventItem): string {
  switch (event.event_type) {
    case "task_started":
      return "Run started";
    case "task_prepared":
      return "Task snapshot prepared";
    case "role_input_dispatched":
      return "Worker started";
    case "implementation_requested":
      return "Implementation lane requested";
    case "self_review_requested":
      return "Self-review requested";
    case "self_review_correction_requested":
      return "Self-review corrections requested";
    case "boy_scout_requested":
      return "Boy Scout pass requested";
    case "verification_requested":
      return "Verification requested";
    case "verification_correction_requested":
      return "Verification corrections requested";
    case "mr_handoff_completed":
      return "MR handoff completed";
    case "send_to_test_completed":
      return "Sent to test";
    case "task_completed":
      return "Task completed";
    default:
      return humanizeEventType(event.event_type);
  }
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

  const blockerSummary = bundle.interactiveStateSummary?.summary;
  const currentStage = stageDisplayName(session.current_stage);
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
  const standbyRoles = visibleRoles.filter(
    (role) =>
      role.status === "running" &&
      !activeRoles.some((candidate) => candidate.id === role.id),
  );
  const waitingRoles = visibleRoles.filter((role) => role.status === "waiting");
  const currentOwner = session.current_owner
    ? roleDisplayName(session.current_owner)
    : session.status === "active"
      ? "Awaiting assignment"
      : "Not assigned yet";
  const hasAssignedOwner = session.current_owner !== null;
  const betweenLiveHandoffs =
    session.status === "active" && activeRoles.length === 0 && standbyRoles.length > 0;
  const currentFocusTitle =
    session.status === "waiting_for_operator"
      ? "Operator attention needed"
      : session.status === "active"
        ? activeRoles.length > 0
          ? `${currentStage} in progress`
          : hasAssignedOwner
            ? `${currentStage} is queued`
            : betweenLiveHandoffs
              ? "Awaiting next handoff"
              : "Preparing next lane"
        : session.status === "paused"
          ? "Session is paused"
          : session.status === "completed"
            ? "Session is complete"
            : "Session state";
  const currentFocusBody =
    session.status === "waiting_for_operator"
        ? blockerSummary ?? "The run is blocked and needs operator input before it can continue."
      : session.status === "active"
        ? activeRoles.length > 0
          ? `${currentOwner} is driving the live lane now.`
          : betweenLiveHandoffs
            ? "The workflow is between handoffs. Live runtimes are ready for the next stage to activate."
            : hasAssignedOwner
              ? `${currentOwner} owns the stage, but no lane is actively executing yet.`
              : "The run is active, but the next lane has not been assigned yet."
        : session.status === "paused"
          ? "The run is paused until the external blocker is cleared."
          : session.status === "completed"
            ? "The main flow has completed. Use follow-up actions only if new MR, QA, or snapshot updates arrive."
            : "Review the current stage and decide the next operator action.";
  const showRoleStatusPanel =
    bundle.workItems.length > 0 ||
    visibleRoles.some((role) => role.status !== "running");
  const showFollowupContextPanel = bundle.followupContext !== null;
  const runningRoleCount = activeRoles.length;
  const standbyRoleCount = standbyRoles.length;
  const blockedRoleCount = waitingRoles.length;
  const recentEvents = [...bundle.events].slice(-4).reverse();
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
            <h1>{session.task_key}</h1>
            {session.jira_url ? (
              <a className="hero-link hero-link-button" href={session.jira_url} rel="noreferrer" target="_blank">
                Open in Jira
              </a>
            ) : null}
          </div>
          <div className="hero-task-card">
            {session.task_title ? <p className="hero-title">{session.task_title}</p> : null}
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
        <div className="hero-stats">
            <div className="metric-card">
              <span>Status</span>
              <strong>{sessionStatusDisplayName(session.status)}</strong>
            </div>
          <div className="metric-card">
            <span>Active</span>
            <strong>{runningRoleCount}</strong>
          </div>
          <div className="metric-card">
            <span>Waiting</span>
            <strong>{blockedRoleCount}</strong>
          </div>
          <div className="metric-card">
            <span>Standing By</span>
            <strong>{standbyRoleCount}</strong>
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
      {session.workflow_profile === "story_full" ? (
        <div className="grid-two">
          <section className="subpanel">
            <div className="subpanel-head">
              <strong>Current Focus</strong>
              <span className={`status-pill status-${session.status}`}>
                {sessionStatusDisplayName(session.status)}
              </span>
            </div>
            <div className="stack-tight">
              <strong>{currentFocusTitle}</strong>
              <p>{currentFocusBody}</p>
              <div className="inline-pill-row">
                <span className="inline-pill">stage: {currentStage}</span>
                <span className="inline-pill">owner: {currentOwner}</span>
              </div>
            </div>
          </section>
          <PlanningSummaryPanel
            planningSummary={bundle.planningSummary}
            workflowProfile={session.workflow_profile}
          />
        </div>
      ) : (
        <section className="subpanel">
          <div className="subpanel-head">
            <strong>Current Focus</strong>
            <span className={`status-pill status-${session.status}`}>
              {sessionStatusDisplayName(session.status)}
            </span>
          </div>
          <div className="stack-tight">
            <strong>{currentFocusTitle}</strong>
            <p>{currentFocusBody}</p>
            <div className="inline-pill-row">
              <span className="inline-pill">stage: {currentStage}</span>
              <span className="inline-pill">owner: {currentOwner}</span>
            </div>
          </div>
        </section>
      )}

      <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Progress</p>
              <h3>Workflow Pulse</h3>
            </div>
          </div>
        <div className="grid-two progress-grid">
          <div className="subpanel">
            <div className="subpanel-head">
              <strong>Active Now</strong>
              <span className="badge badge-muted">{activeRoles.length}</span>
            </div>
            {activeRoles.length > 0 ? (
              <div className="progress-card-stack">
                {activeRoles.map((role) => {
                  const summary = laneSummary(role, bundle.workItems, session);
                  return (
                    <article className="progress-card" key={`active-${role.id}`}>
                      <div className="subpanel-head">
                        <strong>{roleDisplayName(role.role_name)}</strong>
                        <span className="status-pill status-running">Active</span>
                      </div>
                      <p className="progress-card-title">{summary.title}</p>
                      <p className="progress-card-body">{summary.body}</p>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="path-label">
                {betweenLiveHandoffs
                  ? "No lane is executing right now. Live runtimes are standing by for the next handoff."
                  : hasAssignedOwner
                    ? "No lane is executing right now, even though the stage already has an owner."
                    : "No lane has taken ownership yet. The workflow is still preparing the next assignment."}
              </p>
            )}
          </div>

          <div className="subpanel">
            <div className="subpanel-head">
              <strong>Standing By</strong>
              <span className="badge badge-muted">{standbyRoles.length}</span>
            </div>
            {standbyRoles.length > 0 ? (
              <div className="compact-role-list">
                {standbyRoles.map((role) => {
                  const summary = laneSummary(role, bundle.workItems, session);
                  return (
                    <article className="compact-role-card" key={`standby-${role.id}`}>
                      <div className="subpanel-head">
                        <strong>{roleDisplayName(role.role_name)}</strong>
                        <span className="status-pill status-running">Standing by</span>
                      </div>
                      <p className="progress-card-body">{summary.title}</p>
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="path-label">No live lanes are currently standing by.</p>
            )}
          </div>

          {waitingRoles.length > 0 ? (
            <div className="subpanel">
              <div className="subpanel-head">
                <strong>Waiting</strong>
                <span className="badge badge-muted">{waitingRoles.length}</span>
              </div>
              <div className="progress-card-stack">
                {waitingRoles.map((role) => {
                  const summary = laneSummary(role, bundle.workItems, session);
                  return (
                    <article className="progress-card" key={`waiting-${role.id}`}>
                      <div className="subpanel-head">
                        <strong>{roleDisplayName(role.role_name)}</strong>
                        <span className="status-pill status-waiting">Waiting</span>
                      </div>
                      <p className="progress-card-title">{summary.title}</p>
                      <p className="progress-card-body">{summary.body}</p>
                    </article>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>

        <div className="subpanel session-updates-panel">
          <div className="subpanel-head">
            <strong>Latest Activity</strong>
            <span className="badge badge-muted">{recentEvents.length}</span>
          </div>
          {recentEvents.length > 0 ? (
            <div className="table-list limited-list">
              {recentEvents.map((event) => (
                <div className="table-row" key={`recent-${event.id}`}>
                  <div>
                    <strong>{eventSummary(event)}</strong>
                    <p>{producerDisplayName(event.producer_type)}</p>
                  </div>
                  <small>{relativeTimeLabel(event.created_at)}</small>
                </div>
              ))}
            </div>
          ) : (
            <p className="path-label">No activity has been recorded yet.</p>
          )}
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
          <ArtifactPanel artifacts={bundle.artifacts} events={bundle.events} />
        </div>
      </section>
      ) : null}
    </section>
  );
}
