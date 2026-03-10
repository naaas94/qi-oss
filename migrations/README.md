# Database migrations

SQL migrations are applied in order by numeric prefix (`001_`, `003_`, …). The application tracks the current schema version in the `schema_version` table.

**Note:** Migration `002` was intentionally removed or merged in the past; the sequence 001 → 003 → 004 → 005 → 006 is correct.
