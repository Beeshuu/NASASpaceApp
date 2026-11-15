-- Incident-response Workflow instances, one per critical alert with a checklist. `stage` is the step it is on.
CREATE TABLE incidents (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  message TEXT NOT NULL,
  stage TEXT NOT NULL,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL
);
CREATE INDEX incidents_entity ON incidents (entity_id, created_ts);
