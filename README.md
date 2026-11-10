# project_sync_service

Standalone Python sync service that pulls project, CAAN, and contract data from the UCPPC FileMaker database and syncs it into `business_services_db` (PostgreSQL).

## Setup

Use uv 0.13.7 or newer and Python 3.15. The `.python-version` file pins
Python 3.15.2; `uv sync` downloads it automatically when needed. Update an
existing uv installation with its installation method (`uv self update` for
the standalone installer).

```bash
# Copy and fill in credentials
cp .env.example .env

# Install the pinned Python version and locked dependencies
uv sync --locked

# Validate FM layouts and PG connectivity before first sync
uv run project-sync validate
```

When upgrading an existing deployment, run `uv sync --locked` from the project
root to rebuild `.venv` with the pinned Python version. Then run
`uv run project-sync validate` and `uv run project-sync run --dry-run` before
the next scheduled sync.

## Usage

```bash
# Full sync (all entities in dependency order: caans → projects → contracts → project-caans)
uv run project-sync run

# Sync a single entity
uv run project-sync run --entity caans
uv run project-sync run --entity projects
uv run project-sync run --entity contracts
uv run project-sync run --entity project-caans

# Dry run — show what would change without writing
uv run project-sync run --dry-run

# Check FM + PG connections
uv run project-sync check

# Show sync status (row counts, last synced timestamps)
uv run project-sync status

# Display current field mappings
uv run project-sync mappings

# Run preflight validation
uv run project-sync validate
```

## Cron (nightly at 2 AM)

```cron
0 2 * * * /opt/app/project_sync_service/.venv/bin/project-sync run >> /var/log/project_sync.log 2>&1
```

## Configuration

All settings are read from environment variables (or a `.env` file in the project root). See `.env.example`.

## Field Mappings

`config/field_mappings.yaml` is the authoritative source for FM → PG field mappings. Edit this file to change what data flows where. Run `project-sync mappings` to inspect the current mappings.

## Database Schema

This service expects the target PostgreSQL schema to already exist. Apply any required DDL changes directly with your database workflow (for example via `psql`) before running `project-sync validate` or `project-sync run`.

Migration scripts live in `src/project_sync_service/migrations/`. Apply them in numeric order. In particular, `003_add_sync_business_key_constraints.sql` adds the unique index required by the CAAN sync upsert on `caans.caan`.
