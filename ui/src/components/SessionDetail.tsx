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

  return (
    <section className="detail-layout">
      <div className="panel hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Current Session</p>
          <h1>{session.task_key}</h1>
          <p className="hero-meta">
            Profile: <strong>{session.workflow_profile}</strong>
          </p>
          <p className="hero-meta">
            Stage: <strong>{session.current_stage}</strong>
          </p>
          <p className="hero-meta">
            Owner: <strong>{session.current_owner ? roleDisplayName(session.current_owner) : "unowned"}</strong>
          </p>
        </div>
        <div className="hero-stats">
          <div className="metric-card">
            <span>Status</span>
            <strong>{session.status}</strong>
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
            <strong>Session Policy</strong>
          </div>
          <div className="table-list">
            {Object.entries(session.policy).map(([key, value]) => (
              <div className="table-row" key={key}>
                <span>{key}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </section>
        <PlanningSummaryPanel
          planningSummary={bundle.planningSummary}
          workflowProfile={session.workflow_profile}
        />
      </div>

      <FollowupContextPanel followupContext={bundle.followupContext} />
      <InteractiveStatePanel interactiveStateSummary={bundle.interactiveStateSummary} />
      <RuntimeSessionPanel
        onRefresh={onRefresh}
        runtimeStateSummary={bundle.runtimeStateSummary}
        session={session}
      />
      <JiraSubtasksPanel
        jiraSubtasksSummary={bundle.jiraSubtasksSummary}
        subtaskGraphSummary={bundle.subtaskGraphSummary}
        subtaskProgressSummary={bundle.subtaskProgressSummary}
      />
      <SubtaskProgressPanel subtaskProgressSummary={bundle.subtaskProgressSummary} />
      <SubtaskGraphPanel subtaskGraphSummary={bundle.subtaskGraphSummary} />
      <PlanningArtifactPanel
        planningSummary={bundle.planningSummary}
        workflowProfile={session.workflow_profile}
      />
      <OperatorActions
        interactiveStateSummary={bundle.interactiveStateSummary}
        onRefresh={onRefresh}
        session={session}
      />
      <RoleStatusPanel roles={bundle.roles} workItems={bundle.workItems} />
      <ArtifactPanel artifacts={bundle.artifacts} events={bundle.events} />
    </section>
  );
}
