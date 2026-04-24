-- Migration 003: Add unique index required by CAAN sync upserts
-- Idempotent: safe to re-run (uses IF NOT EXISTS)
--
-- The CAAN sync uses PostgreSQL INSERT ... ON CONFLICT (caan).
-- PostgreSQL requires the ON CONFLICT target to match a unique or exclusion
-- constraint/index before the upsert can run.
--
-- If this statement fails, check for duplicate source values first:
--   SELECT caan, count(*) FROM caans GROUP BY caan HAVING count(*) > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_caans_caan_unique
    ON caans (caan);
