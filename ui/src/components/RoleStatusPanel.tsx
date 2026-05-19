import { roleDisplayName } from "../roleDisplay";
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
    case "correction":
      return "Correction";
    case "followup":
      return "Follow-up";
    case "verification":
      return "Verification";
    case "review":
      return "Review";
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

export function RoleStatusPanel({
  roles,
  workItems,
}: RoleStatusPanelProps): JSX.Element {
  const visibleRoles = roles.filter((role) => role.role_name !== "task-coordinator");

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Roles And Work</h3>
          <p className="path-label">
            Track which lanes are active and what work is currently queued for them.
          </p>
        </div>
      </div>

      <div className="stack">
        <div className="grid-two">
          {visibleRoles.map((role) => (
            <article className="subpanel" key={role.id}>
              <div className="subpanel-head">
                <strong>{roleDisplayName(role.role_name)}</strong>
                <span className={`status-pill status-${role.status}`}>
                  {roleStatusSummary(role.status)}
                </span>
              </div>
              <p>{roleStatusSummary(role.status)}</p>
            </article>
          ))}
        </div>

        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Work Items</strong>
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
