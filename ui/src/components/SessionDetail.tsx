import { useEffect, useState } from "react";

import { apiClient } from "../api/client";
import { ActiveRuntimeOutputPanel } from "./ActiveRuntimeOutputPanel";
import { CompletedFollowupPanel } from "./CompletedFollowupPanel";
import { InteractiveStatePanel } from "./InteractiveStatePanel";
import { OperatorActions } from "./OperatorActions";
import { useToast } from "./ToastProvider";
import { roleDescription, roleDisplayName } from "../roleDisplay";
import { isOnDemandDashboardRole, shouldShowRoleOnDashboardByDefault } from "../roleVisibility";
import {
  workflowProfileDisplayName,
} from "../sessionDisplay";
import { stageDisplayName } from "../stageDisplay";
import type { Role, RuntimeRoleStateSummary, Session, SessionBundle } from "../types";

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

function laneSummary(role: Role): { title: string } {
  return {
    title: roleDescription(role.role_name),
  };
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
    "convention-reviewer",
    "requirements-reviewer",
    "verification-coordinator",
    "doc-harvest-worker",
    "documentation-reviewer",
  ];
  const bugFullOrder = [
    "implementer",
    "bug-fixer",
    "convention-reviewer",
    "requirements-reviewer",
    "verification-coordinator",
    "doc-harvest-worker",
    "documentation-reviewer",
  ];
  const storyFullOrder = [
    "proposal-context-worker",
    "requirements-clarifier-worker",
    "acceptance-criteria-worker",
    "constraints-worker",
    "spec-verifier-worker",
    "task-decomposer-worker",
    "implementer",
    "convention-reviewer",
    "requirements-reviewer",
    "verification-coordinator",
    "doc-harvest-worker",
    "documentation-reviewer",
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
  runtimeRole: RuntimeRoleStateSummary | null,
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
  if (isOnDemandDashboardRole(role.role_name)) {
    if (role.status === "running" || runtimeRole?.liveState === "live-idle") {
      return "On-demand";
    }
    if (role.status === "stopped") {
      return "Sleeping";
    }
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
  const [activeRuntimeRoleName, setActiveRuntimeRoleName] = useState<string | null>(null);
  const [workerMenuRoleName, setWorkerMenuRoleName] = useState<string | null>(null);
  const [workerActionBusyRoleName, setWorkerActionBusyRoleName] = useState<string | null>(null);
  const [workerActionError, setWorkerActionError] = useState<string | null>(null);
  const [showAllWorkflowRoles, setShowAllWorkflowRoles] = useState(false);
  const [deliveryFailure, setDeliveryFailure] = useState<DeliveryFailureState>(null);
  const [deliveryRetryBusy, setDeliveryRetryBusy] = useState(false);
  const { showToast, showActivity, clearActivity } = useToast();
  const sessionId = session?.id ?? null;

  useEffect(() => {
    if (sessionId === null || bundle === null || bundle.runtimeStateSummary?.available !== true) {
      setActiveRuntimeRoleName(null);
      return;
    }
    const activeSessionId = sessionId;

    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function loadActiveRuntimeRole(): Promise<void> {
      try {
        const response = await apiClient.getActiveRuntimeOutput(activeSessionId);
        if (cancelled) {
          return;
        }
        setActiveRuntimeRoleName(response.available ? response.role_name : null);
      } catch {
        if (!cancelled) {
          setActiveRuntimeRoleName(null);
        }
      }
    }

    void loadActiveRuntimeRole();
    intervalId = setInterval(() => {
      void loadActiveRuntimeRole();
    }, 1000);

    return () => {
      cancelled = true;
      if (intervalId !== null) {
        clearInterval(intervalId);
      }
    };
  }, [bundle, sessionId]);

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

  const interactiveOwnerRoleName =
    session.status === "waiting_for_operator" && bundle.interactiveStateSummary?.available
      ? bundle.interactiveStateSummary.roleName
      : null;
  const ownedRoleIds = new Set(
    bundle.workItems
      .filter((item) => item.status === "active" || item.status === "pending")
      .map((item) => item.owner_role_id),
  );
  const baseRoles = bundle.roles.filter((role) => role.role_name !== "task-coordinator");
  const activeRoles = baseRoles.filter(
    (role) =>
      role.status === "running" &&
      (
        activeRuntimeRoleName === role.role_name ||
        session.current_owner === role.role_name ||
        interactiveOwnerRoleName === role.role_name ||
        ownedRoleIds.has(role.id)
      ),
  );
  const currentOwner = session.current_owner
    ? roleDisplayName(session.current_owner)
    : activeRuntimeRoleName
      ? roleDisplayName(activeRuntimeRoleName)
    : interactiveOwnerRoleName
      ? roleDisplayName(interactiveOwnerRoleName)
      : session.status === "active"
      ? "Awaiting assignment"
      : "Not assigned yet";
  const activeRoleIds = new Set(activeRoles.map((role) => role.id));
  const orderedRoles = [...baseRoles].sort((left, right) => {
    const orderDelta =
      roleFlowOrder(left.role_name, session.workflow_profile) -
      roleFlowOrder(right.role_name, session.workflow_profile);
    if (orderDelta !== 0) {
      return orderDelta;
    }
    return left.id - right.id;
  });
  const runtimeRoleIndex = new Map(
    (bundle.runtimeStateSummary?.roles ?? []).map((role) => [role.roleName, role]),
  );
  const visibleWorkflowRoles = orderedRoles.filter((role) => {
    if (showAllWorkflowRoles) {
      return true;
    }
    if (
      !shouldShowRoleOnDashboardByDefault(role, {
        activeRoleIds,
        currentOwner: session.current_owner,
        interactiveOwner: interactiveOwnerRoleName,
        workItems: bundle.workItems,
      })
    ) {
      return false;
    }
    const label = workerStateLabel(
      role,
      activeRoleIds,
      session,
      bundle,
      runtimeRoleIndex.get(role.role_name) ?? null,
    );
    return (
      label === "Active" ||
      label === "Waiting for operator" ||
      label === "Standing by" ||
      label === "On-demand"
    );
  });
  const visibleFirstColumnCount = Math.ceil(visibleWorkflowRoles.length / 2);
  const visibleWorkerColumns = [
    visibleWorkflowRoles.slice(0, visibleFirstColumnCount),
    visibleWorkflowRoles.slice(visibleFirstColumnCount),
  ];

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
              <a className="hero-link-button" href={session.jira_url} rel="noreferrer" target="_blank">
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
        runtimeStateSummary={bundle.runtimeStateSummary}
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
              {activeSession.current_stage === "mr_handoff_failed" ? "Retry MR handoff" : "Retry send to test"}
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
            <button
              className="action-button workflow-pulse-filter-button"
              onClick={() => setShowAllWorkflowRoles((current) => !current)}
              type="button"
            >
              {showAllWorkflowRoles ? "Hide inactive lanes" : "Show all lanes"}
            </button>
          </div>
        <div className="workflow-pulse-grid">
          {visibleWorkerColumns.map((column, columnIndex) => (
            <div className="workflow-pulse-column" key={`worker-column-${columnIndex}`}>
              {column.map((role) => {
                const summary = laneSummary(role);
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
                        {workerStateLabel(
                          role,
                          activeRoleIds,
                          session,
                          bundle,
                          runtimeRoleIndex.get(role.role_name) ?? null,
                        )}
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
                                Stop this runtime
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
                                Restart this runtime
                              </button>
                              <button
                                className="action-button"
                                disabled={
                                  workerActionBusyRoleName !== null ||
                                  (runtimeRole.status !== "running" && runtimeRole.status !== "stopped")
                                }
                                onClick={() =>
                                  void runWorkerAction(role.role_name, () =>
                                    apiClient.restartRuntimeRole(session.id, role.role_name, true),
                                  )
                                }
                                type="button"
                              >
                                Recreate with latest defaults
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
                                  Copy console command
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
                                  Copy output command
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
