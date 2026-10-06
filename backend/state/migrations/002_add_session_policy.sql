ALTER TABLE sessions ADD COLUMN workflow_profile TEXT NOT NULL DEFAULT 'oneshot';
ALTER TABLE sessions ADD COLUMN policy_json TEXT NOT NULL DEFAULT '{}';
