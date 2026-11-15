-- Black-box decision log index. Entries live in R2 under ledger/{seq:08d}.json; the Ledger
-- Durable Object is the only writer. This table is a copy for fast queries, never the record.
CREATE TABLE ledger (
  seq INTEGER PRIMARY KEY,
  hash TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  type TEXT NOT NULL,
  entity_id TEXT,
  timestamp TEXT NOT NULL, -- wall clock, ISO 8601 UTC
  summary TEXT NOT NULL,
  reviewed_seq INTEGER -- set on review entries: the seq they review
);
CREATE INDEX ledger_by_type ON ledger (type);
CREATE INDEX ledger_by_reviewed ON ledger (reviewed_seq);
CREATE INDEX ledger_by_entity ON ledger (entity_id, seq);
