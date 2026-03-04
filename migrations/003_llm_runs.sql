-- QI schema update: add observability traces for LLM runs
-- Version: 003

CREATE TABLE IF NOT EXISTS llm_runs (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER REFERENCES artifacts(id),
    artifact_type TEXT,
    run_type TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    temperature REAL,
    think_enabled INTEGER,
    system_prompt TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    raw_output TEXT,
    done_reason TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_duration_ms INTEGER,
    load_duration_ms INTEGER,
    prompt_eval_duration_ms INTEGER,
    eval_duration_ms INTEGER,
    validation_passed INTEGER NOT NULL,
    validation_error TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_runs_artifact_id ON llm_runs(artifact_id);
CREATE INDEX IF NOT EXISTS idx_llm_runs_model ON llm_runs(model);
CREATE INDEX IF NOT EXISTS idx_llm_runs_created_at ON llm_runs(created_at);

INSERT OR IGNORE INTO schema_version (version) VALUES (3);
