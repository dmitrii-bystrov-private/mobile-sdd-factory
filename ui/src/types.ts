export type Session = {
  id: number;
  task_key: string;
  status: string;
  current_stage: string;
  current_owner: string | null;
};

export type Role = {
  id: number;
  session_id: number;
  role_name: string;
  status: string;
  runtime_backend: string;
  runtime_handle: string | null;
};

export type EventItem = {
  id: number;
  session_id: number;
  event_type: string;
  producer_type: string;
  producer_id?: string | null;
  payload: Record<string, unknown>;
  correlation_id?: string | null;
};

export type Artifact = {
  id: number;
  session_id: number;
  role_id?: number | null;
  stage_name: string;
  artifact_type: string;
  path: string;
  metadata?: Record<string, unknown> | null;
};

export type WorkItem = {
  id: number;
  session_id: number;
  work_type: string;
  title: string;
  status: string;
  owner_role_id?: number | null;
  source_event_id?: number | null;
  priority: number;
};

export type SessionBundle = {
  roles: Role[];
  artifacts: Artifact[];
  events: EventItem[];
  workItems: WorkItem[];
};
