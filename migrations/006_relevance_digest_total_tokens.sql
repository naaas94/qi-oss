-- QI schema update: add total token count for relevance digest calls
-- Version: 006

ALTER TABLE relevance_digests ADD COLUMN total_tokens INTEGER;

CREATE INDEX IF NOT EXISTS idx_relevance_total_tokens ON relevance_digests(total_tokens);

INSERT OR IGNORE INTO schema_version (version) VALUES (6);
