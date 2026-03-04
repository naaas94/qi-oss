-- QI schema update: source timestamp + observability fields for relevance digests
-- Version: 005

ALTER TABLE relevance_digests ADD COLUMN source_ts TIMESTAMP;
ALTER TABLE relevance_digests ADD COLUMN citation TEXT;
ALTER TABLE relevance_digests ADD COLUMN processing_duration_ms INTEGER;
ALTER TABLE relevance_digests ADD COLUMN status TEXT DEFAULT 'success';
ALTER TABLE relevance_digests ADD COLUMN error_message TEXT;

CREATE INDEX IF NOT EXISTS idx_relevance_source_ts ON relevance_digests(source_ts);
CREATE INDEX IF NOT EXISTS idx_relevance_status ON relevance_digests(status);

INSERT OR IGNORE INTO schema_version (version) VALUES (5);
