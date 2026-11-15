-- One row per checklist step a crew member marked done. A done step stays done: this is a log.
CREATE TABLE checklist_steps (
  alert_id TEXT NOT NULL,
  step INTEGER NOT NULL,
  entity_id TEXT NOT NULL,
  done_ts INTEGER NOT NULL, -- wall clock, epoch ms
  PRIMARY KEY (alert_id, step)
);
CREATE INDEX checklist_steps_by_entity ON checklist_steps (entity_id, done_ts);

CREATE TABLE checkins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id TEXT NOT NULL,
  ts INTEGER NOT NULL, -- mission clock: same clock as the crew member's readings
  created_at INTEGER NOT NULL, -- wall clock, epoch ms
  answers TEXT NOT NULL -- JSON, field id -> answer
);
CREATE INDEX checkins_by_entity ON checkins (entity_id, ts);
