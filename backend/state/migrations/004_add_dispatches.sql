CREATE TABLE IF NOT EXISTS dispatches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  role_id INTEGER NOT NULL,
  work_item_id INTEGER NOT NULL,
  stage_name TEXT NOT NULL,
  dispatch_token TEXT NOT NULL UNIQUE,
  hydration_version INTEGER NOT NULL,
  runtime_handle TEXT,
  status TEXT NOT NULL,
  error_text TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(session_id) REFERENCES sessions(id),
  FOREIGN KEY(role_id) REFERENCES roles(id),
  FOREIGN KEY(work_item_id) REFERENCES work_items(id)
);

CREATE INDEX IF NOT EXISTS idx_dispatches_target
ON dispatches(session_id, role_id, work_item_id, stage_name, id DESC);

CREATE INDEX IF NOT EXISTS idx_dispatches_status
ON dispatches(status, session_id, role_id);
