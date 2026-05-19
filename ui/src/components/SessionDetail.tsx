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
  sessionPolicyLabel,
  sessionPolicyValueLabel,
  sessionStatusDisplayName,
  workflowProfileDisplayName,
} from "../sessionDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { Session, SessionBundle } from "../types";

type SessionDetailProps = {
  session: Session | null;
  bundle: SessionBundle | null;
  onRefresh: () => Promise<void>;
};

export function SessionDetail({
  session,
  bundle,
  onRefresh,
}: SessionDetailProps): JSX.Element {
  if (session === null || bundle === null) {
    return (
      <section className="panel panel-empty">
        <p className="eyebrow">No Session Selected</p>
        <h2>Choose a task session to inspect the factory state.</h2>
      </section>
    );
  }

  const blockerSummary = bundle.interactiveStateSummary?.summary;
  const currentOwner = session.current_owner ? roleDisplayName(session.current_owner) : "Not assigned yet";
  const currentStage = stageDisplayName(session.current_stage);
  const currentFocusTitle =
    session.status === "waiting_for_operator"
      ? "Operator attention needed"
      : session.status === "active"
        ? "Work is in progress"
        : session.status === "paused"
          ? "Session is paused"
          : session.status === "completed"
            ? "Session is complete"
            : "Session state";
  const currentFocusBody =
    session.status === "waiting_for_operator"
        ? blockerSummary ??
        `The flow is blocked at ${currentStage}. Check the operator actions and blocker panel first.`
      : session.status === "active"
        ? session.current_owner
          ? `The workflow is currently at ${currentStage} with ${currentOwner} owning the live lane.`
          : `The workflow is currently at ${currentStage}. No single lane has taken ownership yet.`
        : session.status === "paused"
          ? `The workflow is paused at ${currentStage}. Resume it when the external blocker is cleared.`
          : session.status === "completed"
            ? "The main flow has completed. Use follow-up actions only if new MR, QA, or snapshot updates arrive."
            : `Current stage: ${currentStage}.`;
  const roleCount = bundle.roles.length;
  const runningRoleCount = bundle.roles.filter((role) => role.status === "running").length;
  const blockedRoleCount = bundle.roles.filter((role) => role.status === "waiting").length;

  return (
    <section className="detail-layout">
      <div className="panel hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Current Session</p>
          <h1>{session.task_key}</h1>
          <p className="hero-meta">
            Profile: <strong>{workflowProfileDisplayName(session.workflow_profile)}</strong>
          </p>
          <p className="hero-meta">
            Stage: <strong>{stageDisplayName(session.current_stage)}</strong>
          </p>
          <p className="hero-meta">
            Owner: <strong>{currentOwner}</strong>
          </p>
        </div>
        <div className="hero-stats">
            <div className="metric-card">
              <span>Status</span>
              <strong>{sessionStatusDisplayName(session.status)}</strong>
            </div>
          <div className="metric-card">
            <span>Roles</span>
            <strong>{bundle.roles.length}</strong>
          </div>
          <div className="metric-card">
            <span>Artifacts</span>
            <strong>{bundle.artifacts.length}</strong>
          </div>
          <div className="metric-card">
            <span>Events</span>
            <strong>{bundle.events.length}</strong>
          </div>
        </div>
      </div>

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
              <span className="inline-pill">running lanes: {runningRoleCount}/{roleCount}</span>
              {blockedRoleCount > 0 ? (
                <span className="inline-pill">blocked lanes: {blockedRoleCount}</span>
              ) : null}
            </div>
          </div>
        </section>
        <section className="subpanel">
          <div className="subpanel-head">
            <strong>Session Policy</strong>
          </div>
          <div className="table-list">
            {Object.entries(session.policy).map(([key, value]) => (
              <div className="table-row" key={key}>
                <span>{sessionPolicyLabel(key)}</span>
                <strong>{sessionPolicyValueLabel(value)}</strong>
              </div>
            ))}
          </div>
        </section>
        <PlanningSummaryPanel
          planningSummary={bundle.planningSummary}
          workflowProfile={session.workflow_profile}
        />
      </div>

      <OperatorActions
        interactiveStateSummary={bundle.interactiveStateSummary}
        onRefresh={onRefresh}
        session={session}
      />

      <InteractiveStatePanel interactiveStateSummary={bundle.interactiveStateSummary} />
      <RoleStatusPanel roles={bundle.roles} workItems={bundle.workItems} />
      <SubtaskProgressPanel subtaskProgressSummary={bundle.subtaskProgressSummary} />
      <JiraSubtasksPanel
        jiraSubtasksSummary={bundle.jiraSubtasksSummary}
        subtaskGraphSummary={bundle.subtaskGraphSummary}
        subtaskProgressSummary={bundle.subtaskProgressSummary}
      />

      <FollowupContextPanel followupContext={bundle.followupContext} />
      <SubtaskGraphPanel subtaskGraphSummary={bundle.subtaskGraphSummary} />
      <PlanningArtifactPanel
        planningSummary={bundle.planningSummary}
        workflowProfile={session.workflow_profile}
      />
      <RuntimeSessionPanel
        onRefresh={onRefresh}
        runtimeStateSummary={bundle.runtimeStateSummary}
        session={session}
      />
      <ArtifactPanel artifacts={bundle.artifacts} events={bundle.events} />
    </section>
  );
}
