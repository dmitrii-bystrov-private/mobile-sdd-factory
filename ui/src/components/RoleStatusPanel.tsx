import { roleDisplayName } from "../roleDisplay";
import type { Role, WorkItem } from "../types";

type RoleStatusPanelProps = {
  roles: Role[];
  workItems: WorkItem[];
};

export function RoleStatusPanel({
  roles,
  workItems,
}: RoleStatusPanelProps): JSX.Element {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h3>Roles And Work</h3>
        </div>
      </div>

      <div className="stack">
        <div className="grid-two">
          {roles.map((role) => (
            <article className="subpanel" key={role.id}>
              <div className="subpanel-head">
                <strong>{roleDisplayName(role.role_name)}</strong>
                <span className={`status-pill status-${role.status}`}>
                  {role.status}
                </span>
              </div>
              <p>{role.runtime_backend}</p>
              <small>{role.runtime_handle ?? "no handle"}</small>
            </article>
          ))}
        </div>

        <div className="subpanel">
          <div className="subpanel-head">
            <strong>Work Items</strong>
            <span className="badge badge-muted">{workItems.length}</span>
          </div>
          <div className="table-list">
            {workItems.map((item) => (
              <div className="table-row" key={item.id}>
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.work_type}</p>
                </div>
                <span className={`status-pill status-${item.status}`}>
                  {item.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
