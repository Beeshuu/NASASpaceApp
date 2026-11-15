-- NASA DONKI space weather events. Raw JSON is cached in R2 under donki/<kind>/<month>.json.
CREATE TABLE sw_events (
  id TEXT PRIMARY KEY, -- DONKI activity id, e.g. 2024-05-10T07:12:00-CME-001
  type TEXT NOT NULL, -- FLR, CME, SEP or GST
  time INTEGER NOT NULL, -- epoch ms
  data TEXT NOT NULL -- JSON: normalized fields, including the ids DONKI links this event to
);
CREATE INDEX sw_events_by_time ON sw_events (time);

-- Which (kind, month) chunks have been fetched, and when.
CREATE TABLE sw_months (
  kind TEXT NOT NULL,
  month TEXT NOT NULL, -- YYYY-MM
  fetched_at INTEGER NOT NULL,
  PRIMARY KEY (kind, month)
);
