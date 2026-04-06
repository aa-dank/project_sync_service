# project_sync_service

Standalone Python sync service that pulls project, CAAN, and contract data from the UCPPC FileMaker database and syncs it into `business_services_db` (PostgreSQL).

## Setup

```bash
# Copy and fill in credentials
cp .env.example .env

# Install dependencies
uv sync

# Run database migrations (creates contracts table, adds columns to projects/caans)
uv run project-sync migrate

# Validate FM layouts and PG connectivity before first sync
uv run project-sync validate
```

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

## Migrations

SQL migration scripts live in `src/project_sync_service/migrations/`. They are idempotent (safe to re-run). Run with `project-sync migrate`.

- `001_add_contracts_table.sql` — creates the `contracts` table
- `002_alter_existing_tables.sql` — adds new columns to `projects` and `caans`
