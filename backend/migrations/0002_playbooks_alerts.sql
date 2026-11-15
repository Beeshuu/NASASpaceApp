-- Playbook text lives in R2. This table tracks versions and which one is active.
CREATE TABLE playbooks (
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  r2_key TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (name, version)
);

CREATE TABLE alerts (
  id TEXT PRIMARY KEY, -- entity_id:rule_id:fired_ts
  entity_id TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  metric TEXT NOT NULL,
  severity TEXT NOT NULL,
  message TEXT NOT NULL,
  value REAL NOT NULL,
  baseline REAL,
  detail TEXT NOT NULL, -- JSON: the full alert, including what each action recorded
  playbook TEXT NOT NULL, -- name@version that fired it
  fired_ts INTEGER NOT NULL,
  cleared_ts INTEGER
);
CREATE INDEX alerts_by_entity ON alerts (entity_id, fired_ts);
