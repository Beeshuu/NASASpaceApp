CREATE TABLE crew (
  entity_id TEXT PRIMARY KEY,
  last_seen INTEGER NOT NULL -- epoch ms of newest reading
);

-- Newest value per indicator, for cross-crew queries. Full history goes to Tiger Data (phase 12).
CREATE TABLE latest (
  entity_id TEXT NOT NULL,
  domain TEXT NOT NULL,
  metric TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT,
  source TEXT,
  ts INTEGER NOT NULL,
  PRIMARY KEY (entity_id, domain, metric)
);
