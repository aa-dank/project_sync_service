-- Migration 002: Add new columns to existing projects and caans tables
-- Idempotent: safe to re-run (uses IF NOT EXISTS)

-- Projects table additions
ALTER TABLE projects ADD COLUMN IF NOT EXISTS fmp_id_primary   INTEGER UNIQUE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS closed           BOOLEAN;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS campus_client    VARCHAR;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_synced_at   TIMESTAMPTZ;

-- CAANs table additions
ALTER TABLE caans ADD COLUMN IF NOT EXISTS fmp_id_primary      INTEGER UNIQUE;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_street      VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_city        VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_zip         VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS area                VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS last_synced_at      TIMESTAMPTZ;
