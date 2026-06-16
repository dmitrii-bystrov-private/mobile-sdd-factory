import type { Role, RuntimeRoleStateSummary, WorkItem } from "./types";

const ON_DEMAND_DASHBOARD_ROLES = new Set<string>();

export function isOnDemandDashboardRole(roleName: string): boolean {
  return ON_DEMAND_DASHBOARD_ROLES.has(roleName);
}

export function shouldShowRoleOnDashboardByDefault(
  role: Role,
  context: {
    activeRoleIds?: Set<number>;
    currentOwner?: string | null;
    interactiveOwner?: string | null;
    workItems?: WorkItem[];
  } = {},
): boolean {
  if (role.role_name === "task-coordinator") {
    return false;
  }
  if (!isOnDemandDashboardRole(role.role_name)) {
    return true;
  }
  if (context.activeRoleIds?.has(role.id)) {
    return true;
  }
  if (context.currentOwner === role.role_name || context.interactiveOwner === role.role_name) {
    return true;
  }
  return (context.workItems ?? []).some(
    (item) =>
      item.owner_role_id === role.id &&
      (item.status === "active" || item.status === "pending" || item.status === "blocked"),
  );
}

export function shouldShowRuntimeRoleByDefault(role: RuntimeRoleStateSummary): boolean {
  if (role.roleName === "task-coordinator") {
    return false;
  }
  if (!isOnDemandDashboardRole(role.roleName)) {
    return true;
  }
  return role.liveState === "owner-active" || role.liveState === "dead-stale" || role.status !== "stopped";
}
