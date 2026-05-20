import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import { ActiveRuntimeOutputPanel } from "./ActiveRuntimeOutputPanel";
import { CompletedFollowupPanel } from "./CompletedFollowupPanel";
import { InteractiveStatePanel } from "./InteractiveStatePanel";
import { OperatorActions } from "./OperatorActions";
import { useToast } from "./ToastProvider";
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

type DeliveryFailureState = {
  stageLabel: string;
  summary: string;
  details: string | null;
} | null;

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

function runtimeConfigSummary(roleName: string, session: Session): string {
  const roleConfig = session.role_config[roleName];
  if (!roleConfig) {
    return "Runtime defaults";
  }

  const parts = [roleConfig.model, roleConfig.effort].filter(
    (value): value is string => typeof value === "string" && value.trim().length > 0,
  );
  if (parts.length > 0) {
    return parts.join(" · ");
  }
  return "Runtime defaults";
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

function workerStateLabel(
  role: Role,
  activeRoleIds: Set<number>,
  session: Session,
  bundle: SessionBundle,
): string {
  if (activeRoleIds.has(role.id)) {
    if (
      session.status === "waiting_for_operator" &&
      bundle.interactiveStateSummary?.available &&
      bundle.interactiveStateSummary.roleName === role.role_name
    ) {
      return "Waiting for operator";
    }
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
  const [workerMenuRoleName, setWorkerMenuRoleName] = useState<string | null>(null);
  const [workerActionBusyRoleName, setWorkerActionBusyRoleName] = useState<string | null>(null);
  const [workerActionError, setWorkerActionError] = useState<string | null>(null);
  const [deliveryFailure, setDeliveryFailure] = useState<DeliveryFailureState>(null);
  const [deliveryRetryBusy, setDeliveryRetryBusy] = useState(false);
  const { showToast, showActivity, clearActivity } = useToast();

  useEffect(() => {
    if (session === null || bundle === null) {
      setDeliveryFailure(null);
      return;
    }
    if (
      session.current_stage !== "mr_handoff_failed" &&
      session.current_stage !== "send_to_test_failed"
    ) {
      setDeliveryFailure(null);
      return;
    }

    const artifactType =
      session.current_stage === "mr_handoff_failed"
        ? "mr_handoff_stderr"
        : "send_to_test_stderr";
    const latestStderrArtifact = [...bundle.artifacts]
      .reverse()
      .find((artifact) => artifact.artifact_type === artifactType);

    if (!latestStderrArtifact) {
      setDeliveryFailure({
        stageLabel: stageDisplayName(session.current_stage),
        summary: "The delivery step failed, but no stderr artifact was captured.",
        details: null,
      });
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const artifactDetail = await apiClient.getArtifact(latestStderrArtifact.id);
        if (cancelled) {
          return;
        }
        setDeliveryFailure({
          stageLabel: stageDisplayName(session.current_stage),
          summary:
            session.current_stage === "mr_handoff_failed"
              ? "Merge request handoff could not complete."
              : "Send-to-test could not complete.",
          details: artifactDetail.content?.trim() || null,
        });
      } catch {
        if (cancelled) {
          return;
        }
        setDeliveryFailure({
          stageLabel: stageDisplayName(session.current_stage),
          summary: "The delivery step failed, but the stderr artifact could not be loaded.",
          details: null,
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bundle, session]);

  if (session === null || bundle === null) {
    return (
      <section className="panel panel-empty">
        <p className="eyebrow">No Session Selected</p>
        <h2>Choose a task session to inspect the factory state.</h2>
      </section>
    );
  }

  const activeSession = session;

  const visibleRoles = bundle.roles.filter((role) => role.role_name !== "task-coordinator");
  const interactiveOwnerRoleName =
    session.status === "waiting_for_operator" && bundle.interactiveStateSummary?.available
      ? bundle.interactiveStateSummary.roleName
      : null;
  const ownedRoleIds = new Set(
    bundle.workItems
      .filter((item) => item.status === "active" || item.status === "pending")
      .map((item) => item.owner_role_id),
  );
  const activeRoles = visibleRoles.filter(
    (role) =>
      role.status === "running" &&
      (
        session.current_owner === role.role_name ||
        interactiveOwnerRoleName === role.role_name ||
        ownedRoleIds.has(role.id)
      ),
  );
  const currentOwner = session.current_owner
    ? roleDisplayName(session.current_owner)
    : interactiveOwnerRoleName
      ? roleDisplayName(interactiveOwnerRoleName)
    : session.status === "active"
      ? "Awaiting assignment"
      : "Not assigned yet";
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
  const runtimeRoleIndex = new Map(
    (bundle.runtimeStateSummary?.roles ?? []).map((role) => [role.roleName, role]),
  );

  async function runWorkerAction(
    roleName: string,
    action: () => Promise<unknown>,
  ): Promise<void> {
    setWorkerActionBusyRoleName(roleName);
    setWorkerActionError(null);
    try {
      await action();
      setWorkerMenuRoleName(null);
      await onRefresh();
    } catch (err) {
      setWorkerActionError(err instanceof Error ? err.message : "Unknown request error");
    } finally {
      setWorkerActionBusyRoleName(null);
    }
  }

  async function copyDebugCommand(
    command: string | null | undefined,
    successMessage: string,
  ): Promise<void> {
    if (!command) {
      return;
    }
    try {
      await navigator.clipboard.writeText(command);
      showToast(successMessage);
      setWorkerMenuRoleName(null);
    } catch {
      showToast("Copy failed", "error");
    }
  }

  async function retryDeliveryStep(): Promise<void> {
    const activityLabel =
      activeSession.current_stage === "mr_handoff_failed"
        ? "Retrying MR handoff…"
        : "Retrying send to test…";
    setDeliveryRetryBusy(true);
    showActivity(activityLabel);
    try {
      if (activeSession.current_stage === "mr_handoff_failed") {
        await apiClient.createMr(activeSession.id);
      } else if (activeSession.current_stage === "send_to_test_failed") {
        await apiClient.sendToTest(activeSession.id);
      }
      await onRefresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Unknown request error", "error");
    } finally {
      clearActivity();
      setDeliveryRetryBusy(false);
    }
  }

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

      <>
      <InteractiveStatePanel
        interactiveStateSummary={bundle.interactiveStateSummary}
        onRefresh={onRefresh}
        sessionId={session.id}
      />

      <CompletedFollowupPanel
        artifacts={bundle.artifacts}
        events={bundle.events}
        onRefresh={onRefresh}
        session={session}
      />

      {deliveryFailure ? (
        <section className="panel">
          <div className="panel-header">
            <div>
              <p className="eyebrow">Recovery</p>
              <h3>{deliveryFailure.stageLabel}</h3>
            </div>
          </div>
          <div className="completed-followup-preview">
            <strong className="completed-followup-preview-title">{deliveryFailure.summary}</strong>
            <pre className="completed-followup-preview-body">
              {deliveryFailure.details ?? "No stderr details were captured for this failure."}
            </pre>
          </div>
          <div className="completed-followup-actions completed-followup-actions-separated">
            <button
              className="action-button"
              disabled={deliveryRetryBusy}
              onClick={() => void retryDeliveryStep()}
              type="button"
            >
              {activeSession.current_stage === "mr_handoff_failed" ? "Retry MR Handoff" : "Retry Send To Test"}
            </button>
          </div>
        </section>
      ) : null}

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
                const runtimeRole = runtimeRoleIndex.get(role.role_name) ?? null;
                const hasWorkerActions =
                  runtimeRole !== null &&
                  (runtimeRole.runtimeHandle !== null ||
                    runtimeRole.status === "stopped" ||
                    runtimeRole.tmuxAttachCommand !== null ||
                    runtimeRole.tmuxCaptureCommand !== null);
                const menuOpen = workerMenuRoleName === role.role_name;
                return (
                  <article
                    className={`progress-card workflow-pulse-card${isActive ? " workflow-pulse-card-active" : ""}`}
                    key={`worker-${role.id}`}
                  >
                    <div className="subpanel-head">
                      <strong className="workflow-pulse-role-name">{roleDisplayName(role.role_name)}</strong>
                      <span className={`status-pill status-${role.status === "running" ? "running" : role.status}`}>
                        {workerStateLabel(role, activeRoleIds, session, bundle)}
                      </span>
                    </div>
                    <p className="progress-card-title">{summary.title}</p>
                    <div className="workflow-pulse-runtime-row">
                      <p className="progress-card-body workflow-pulse-runtime">
                        {runtimeConfigSummary(role.role_name, session)}
                      </p>
                      {hasWorkerActions ? (
                        <div className="workflow-pulse-menu-anchor">
                          <button
                            aria-expanded={menuOpen}
                            aria-label={`Open actions for ${roleDisplayName(role.role_name)}`}
                            className="workflow-pulse-menu-button"
                            onClick={() =>
                              setWorkerMenuRoleName((current) =>
                                current === role.role_name ? null : role.role_name,
                              )
                            }
                            type="button"
                          >
                            ⋯
                          </button>
                          {menuOpen && runtimeRole ? (
                            <div className="workflow-pulse-menu">
                              <button
                                className="action-button"
                                disabled={
                                  workerActionBusyRoleName !== null ||
                                  runtimeRole.runtimeHandle === null ||
                                  runtimeRole.status === "stopped"
                                }
                                onClick={() =>
                                  void runWorkerAction(role.role_name, () =>
                                    apiClient.stopRuntimeRole(session.id, role.role_name),
                                  )
                                }
                                type="button"
                              >
                                Stop This Runtime
                              </button>
                              <button
                                className="action-button"
                                disabled={
                                  workerActionBusyRoleName !== null ||
                                  runtimeRole.status !== "stopped"
                                }
                                onClick={() =>
                                  void runWorkerAction(role.role_name, () =>
                                    apiClient.restartRuntimeRole(session.id, role.role_name),
                                  )
                                }
                                type="button"
                              >
                                Restart This Runtime
                              </button>
                              {runtimeRole.tmuxAttachCommand ? (
                                <button
                                  className="action-button"
                                  disabled={workerActionBusyRoleName !== null}
                                  onClick={() =>
                                    void copyDebugCommand(
                                      runtimeRole.tmuxAttachCommand,
                                      `${roleDisplayName(role.role_name)} console command copied`,
                                    )
                                  }
                                  type="button"
                                >
                                  Copy Console Command
                                </button>
                              ) : null}
                              {runtimeRole.tmuxCaptureCommand ? (
                                <button
                                  className="action-button"
                                  disabled={workerActionBusyRoleName !== null}
                                  onClick={() =>
                                    void copyDebugCommand(
                                      runtimeRole.tmuxCaptureCommand,
                                      `${roleDisplayName(role.role_name)} output command copied`,
                                    )
                                  }
                                  type="button"
                                >
                                  Copy Output Command
                                </button>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          ))}
        </div>
        {workerActionError ? <p className="error-banner">{workerActionError}</p> : null}

      </section>

      <ActiveRuntimeOutputPanel
        runtimeAvailable={bundle.runtimeStateSummary?.available === true}
        sessionId={session.id}
      />

      <OperatorActions
        interactiveStateSummary={bundle.interactiveStateSummary}
        onRefresh={onRefresh}
        runtimeStateSummary={bundle.runtimeStateSummary}
        session={session}
      />
      </>
    </section>
  );
}
