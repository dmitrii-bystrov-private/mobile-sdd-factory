CREATE TABLE IF NOT EXISTS memory_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_type TEXT NOT NULL,
  status TEXT NOT NULL,
  platform TEXT NOT NULL,
  workflow_profile TEXT NOT NULL,
  source_session_id INTEGER NOT NULL,
  source_event_id INTEGER,
  summary TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  use_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(source_session_id) REFERENCES sessions(id),
  FOREIGN KEY(source_event_id) REFERENCES events(id)
);
