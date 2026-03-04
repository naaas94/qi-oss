-- QI Initial Schema
-- Version: 001
-- Description: Core tables for DCI, notes, events, weekly retro, and artifacts

-- Daily Check-In table
CREATE TABLE IF NOT EXISTS dci (
    id INTEGER PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Core metrics (free float scale)
    energy REAL NOT NULL,
    mood REAL NOT NULL,
    sleep REAL NOT NULL,
    
    -- Focus & reflection
    primary_focus TEXT,
    one_win TEXT,
    one_friction TEXT,
    
    comment TEXT,
    residual JSON,
    metrics TEXT DEFAULT '{}'
);

-- Notes imported from SnR QC
CREATE TABLE IF NOT EXISTS notes_imported (
    id INTEGER PRIMARY KEY,
    snr_id TEXT UNIQUE,
    ts TIMESTAMP NOT NULL,
    text TEXT NOT NULL,
    
    -- SnR QC parsed fields (reused)
    snr_tags JSON,
    snr_sentiment TEXT,
    snr_entities JSON,
    snr_intent TEXT,
    snr_action_items JSON,
    snr_people JSON,
    snr_summary TEXT,
    snr_quality_score REAL,
    
    -- QI processing state
    qi_processed INTEGER DEFAULT 0,
    qi_event_id INTEGER,
    
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notes_ts ON notes_imported(ts);
CREATE INDEX IF NOT EXISTS idx_notes_processed ON notes_imported(qi_processed);

-- Structured events from notes
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TIMESTAMP NOT NULL,
    note_id INTEGER REFERENCES notes_imported(id),
    domain TEXT CHECK(domain IN ('health','career','social','cognition','nature','finance')),
    event_type TEXT CHECK(event_type IN ('win','friction','insight','compulsion','avoidance')),
    trigger TEXT,
    intensity INTEGER CHECK(intensity BETWEEN 1 AND 5),
    behavior TEXT,
    counterfactual TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

-- Weekly retrospective
CREATE TABLE IF NOT EXISTS weekly_retro (
    id INTEGER PRIMARY KEY,
    week_start DATE UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scoreboard JSON NOT NULL,
    wins JSON NOT NULL,
    frictions JSON NOT NULL,
    root_cause TEXT,
    one_change JSON NOT NULL,
    minimums JSON NOT NULL,
    commitment_met INTEGER
);

-- Report artifacts
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    window_start DATE NOT NULL,
    window_end DATE NOT NULL,
    input_snapshot JSON NOT NULL,
    features_snapshot JSON NOT NULL,
    output_json JSON NOT NULL,
    rendered_markdown TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    prompt_version TEXT,
    model_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_window ON artifacts(window_start, window_end);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
