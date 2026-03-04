-- QI schema update: add relevance digests + processing flags
-- Version: 004

CREATE TABLE IF NOT EXISTS relevance_digests (
    id INTEGER PRIMARY KEY,
    item_type TEXT NOT NULL CHECK(item_type IN ('note', 'dci')),
    item_id INTEGER NOT NULL,
    relevant INTEGER NOT NULL DEFAULT 0,
    principle_ids JSON,
    kr_refs JSON,
    digest TEXT,
    model TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_type, item_id)
);

ALTER TABLE notes_imported ADD COLUMN qi_relevance_processed INTEGER DEFAULT 0;
ALTER TABLE dci ADD COLUMN relevance_processed INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_relevance_item ON relevance_digests(item_type, item_id);
CREATE INDEX IF NOT EXISTS idx_relevance_processed_at ON relevance_digests(processed_at);

INSERT OR IGNORE INTO schema_version (version) VALUES (4);
