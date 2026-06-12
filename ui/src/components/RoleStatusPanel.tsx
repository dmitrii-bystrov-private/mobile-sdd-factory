import { roleDisplayName } from "../roleDisplay";
import { shouldShowRoleOnDashboardByDefault } from "../roleVisibility";
import type { Role, WorkItem } from "../types";

type RoleStatusPanelProps = {
  roles: Role[];
  workItems: WorkItem[];
};

function roleStatusSummary(status: string): string {
  switch (status) {
    case "running":
      return "Working";
    case "waiting":
      return "Waiting";
    case "stopped":
      return "Stopped";
    case "completed":
      return "Completed";
    default:
      return status;
  }
}

function workTypeDisplayName(workType: string): string {
  switch (workType) {
    case "implementation":
      return "Implementation";
    case "self_review_correction":
      return "Self Review Correction";
    case "boy_scout_correction":
      return "Code Scout Correction";
    case "documentation_review":
      return "Documentation Review";
    case "documentation_review_correction":
      return "Documentation Review Correction";
    case "verification_correction":
      return "Verification Correction";
    case "correction":
      return "General Correction";
    case "followup":
      return "Follow-up";
    case "verification":
      return "Verification";
    case "review":
      return "Review";
    case "self_review":
      return "Self Review";
    case "boy_scout":
      return "Code Scout";
    default:
      return workType.replace(/_/g, " ");
  }
}

function workItemStatusDisplayName(status: string): string {
  switch (status) {
    case "pending":
      return "Queued";
    case "active":
      return "In progress";
    case "completed":
      return "Completed";
    case "blocked":
      return "Blocked";
    default:
      return status;
  }
}

function roleStateHeadline(role: Role, assignedItems: WorkItem[]): string {
  const activeItem = assignedItems.find((item) => item.status === "active") ?? null;
  const queuedItem = assignedItems.find((item) => item.status === "pending") ?? null;
  if (activeItem) {
    return `Working on ${workTypeDisplayName(activeItem.work_type).toLowerCase()}`;
  }
  if (queuedItem) {
    return `Queued for ${workTypeDisplayName(queuedItem.work_type).toLowerCase()}`;
  }
  switch (role.status) {
    case "running":
      return "Ready for handoff";
    case "waiting":
      return "Waiting on upstream progress";
    case "completed":
      return "Finished current assignment";
    case "stopped":
      return "Runtime not active";
    default:
      return roleStatusSummary(role.status);
  }
}

export function RoleStatusPanel({
  roles,
  workItems,
}: RoleStatusPanelProps): JSX.Element {
  const visibleRoles = roles.filter((role) =>
    shouldShowRoleOnDashboardByDefault(role, { workItems }),
  );

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Workers</p>
          <h3>Worker Status</h3>
          <p className="path-label">
            Track which workers are active, which ones are waiting, and what work they currently own.
          </p>
        </div>
      </div>

      <div className="stack">
        <div className="grid-two">
          {visibleRoles.map((role) => {
            const assignedItems = workItems.filter((item) => item.owner_role_id === role.id);
            const activeItem = assignedItems.find((item) => item.status === "active") ?? null;
            const queuedItem = assignedItems.find((item) => item.status === "pending") ?? null;
            return (
              <article className="subpanel" key={role.id}>
                <div className="subpanel-head">
                  <strong>{roleDisplayName(role.role_name)}</strong>
                  <span className={`status-pill status-${role.status}`}>
                    {roleStatusSummary(role.status)}
                  </span>
                </div>
                <p>{roleStateHeadline(role, assignedItems)}</p>
                {activeItem ? (
                  <div className="worker-note">
                    <span className="worker-note-label">Active work</span>
                    <strong>{activeItem.title}</strong>
                  </div>
                ) : null}
                {!activeItem && queuedItem ? (
                  <div className="worker-note">
                    <span className="worker-note-label">Queued next</span>
                    <strong>{queuedItem.title}</strong>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>

        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Current Work Queue</strong>
            <span className="badge badge-muted">{workItems.length}</span>
          </div>
          {workItems.length > 0 ? (
            <div className="table-list">
              {workItems.map((item) => (
                <div className="table-row" key={item.id}>
                  <div>
                    <strong>{item.title}</strong>
                    <p>{workTypeDisplayName(item.work_type)}</p>
                  </div>
                  <span className={`status-pill status-${item.status}`}>
                    {workItemStatusDisplayName(item.status)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="path-label">No queued work items right now.</p>
          )}
        </div>
      </div>
    </section>
  );
}
