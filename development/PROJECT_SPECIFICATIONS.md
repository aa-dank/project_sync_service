# Project Sync Service — Specification

## 1. Purpose

The **Project Sync Service** (`project_sync_service`) is a standalone Python application that synchronizes project-related data from the UCPPC FileMaker database into the PPDO archives PostgreSQL database (`business_services_db`).

It replaces the `fmp_caan_project_reconciliation_task` currently embedded in `archives_app`, and extends its scope to include **contract data** and additional fields on projects and CAANs.

### Goals

- Decouple project data synchronization from the Flask web application
- Add contract data to the PostgreSQL database (new `contracts` table)
- Sync additional project and CAAN fields not currently captured
- Provide a clean CLI interface for manual runs and diagnostics
- Run on the Linux production server via cron
- Facilitate eventual deprecation of the FileMaker system by having project data retrieval as an independent, well-documented module

## 2. Scope

### Data entities synced

1. **CAANs** — campus buildings/assets
2. **Projects** — construction projects
3. **Project-CAANs** — many-to-many relationship between projects and CAANs
4. **Contracts** — construction contracts (NEW)

### Out of scope (for initial version)

- ContractAmendments / ContractSubContracts (can be added later)
- People / Companies tables
- File content indexing (handled by archives_scraper)
- Any write-back to FileMaker

## 3. Architecture

### Standalone application

```
project_sync_service/
├── pyproject.toml              # uv project config
├── README.md
├── config/
│   ├── settings.py             # Config loading (env vars, .env file)
│   └── field_mappings.yaml     # FM→PG field mapping definitions (see §5)
├── src/
│   └── project_sync_service/
│       ├── __init__.py
│       ├── cli.py              # Click CLI entry point
│       ├── config.py           # Settings/config dataclass
│       ├── mappings.py         # Load and validate field_mappings.yaml
│       ├── fm_client.py        # FileMaker Data API client (wraps fmrest)
│       ├── db.py               # PostgreSQL connection and operations (psycopg3)
│       ├── sync/
│       │   ├── __init__.py
│       │   ├── base.py         # Base sync logic (fetch, diff, upsert pattern)
│       │   ├── caans.py        # CAAN sync
│       │   ├── projects.py     # Project sync
│       │   ├── project_caans.py # Project-CAAN join sync
│       │   └── contracts.py    # Contract sync
│       ├── migrations/         # SQL migration scripts
│       │   └── 001_add_contracts_table.sql
│       └── utils.py            # Shared utilities
└── tests/
```

### Data flow

```
FileMaker Server (UCPPC.fmp12)
    │
    │  FM Data API (REST, via fmrest)
    ▼
project_sync_service
    │
    │  psycopg3 (direct SQL)
    ▼
PostgreSQL (business_services_db)
```

### Sync ordering (dependency chain)

1. CAANs (no dependencies)
2. Projects (no FK deps in PG, but logically first)
3. Contracts (references projects via project linkage lookup)
4. Project-CAANs join (references both projects and CAANs)

## 4. Configuration

### Environment variables / .env file

```env
# FileMaker connection
FM_HOST=<filemaker_server_host>
FM_USER=<api_username>
FM_PASSWORD=<api_password>
FM_DATABASE=UCPPC

# PostgreSQL connection
PG_HOST=127.0.0.1
PG_PORT=5432
PG_DATABASE=business_services_db
PG_USER=archives_admin
PG_PASSWORD=<password>

# Optional
LOG_LEVEL=INFO
NO_PROXY=*

# FileMaker fetch controls
FM_FETCH_LIMIT=100000
```

### FileMaker layout names (in config or mapping file)

All layout names are configurable and must not be hard-coded in sync logic. The service assumes the selected layout for each entity includes all required fields for that entity's mapping.

```yaml
layouts:
  caans: caan_table
  projects: projects_table
  project_caans: caan_project_join
  contracts: Contracts         # Use existing "Contracts" layout; fall back to Import layouts if needed
```

## 5. Field Mapping File

A single YAML file (`field_mappings.yaml`) defines all FM→PG mappings. This is the authoritative source for what data flows where. If field or table names change in either system, this is the one place to update.

### Design rationale

YAML is the primary format for this mapping because:
- It's human-readable and editable by non-developers
- It separates configuration from code
- It's easy to version-control and diff
- The mapping is data, not behavior

Python (dataclasses/objects) may be used alongside YAML if mapping logic or transforms need to be colocated with the definitions.

### Structure

```yaml
# field_mappings.yaml
# Each top-level key is an entity type.
# fm_layout: the FileMaker layout to query
# pg_table: the PostgreSQL table to write to
# match_key: the field(s) used to identify existing records (for upsert)
# fields: list of field mappings
#   - fm: FileMaker field name (as returned by the API)
#     pg: PostgreSQL column name
#     transform: optional transformation to apply (e.g., "boolean_yesno", "strip", "integer")

caans:
  fm_layout: caan_table
  pg_table: caans
  match_key: [caan]
  fields:
    - fm: ID_Primary
      pg: fmp_id_primary
      transform: integer
    - fm: CAAN
      pg: caan
      transform: strip
    - fm: Name
      pg: name
      transform: strip
    - fm: Description
      pg: description
      transform: strip
    - fm: Address
      pg: address_street
      transform: strip
    - fm: City
      pg: address_city
      transform: strip
    - fm: Zip
      pg: address_zip
      transform: strip
    - fm: Area
      pg: area
      transform: strip

projects:
  fm_layout: projects_table
  pg_table: projects
  match_key: [number]
  fields:
    - fm: ID_Primary
      pg: fmp_id_primary
      transform: integer
    - fm: ProjectNumber
      pg: number
      transform: strip
    - fm: ProjectName
      pg: name
      transform: strip
    - fm: Drawings
      pg: drawings
      transform: boolean_yesno
    - fm: Status
      pg: closed
      transform: boolean_closed  # "Closed" → True, else False
    - fm: CampusClient
      pg: campus_client
      transform: strip

project_caans:
  fm_layout: caan_project_join
  pg_table: project_caans
  match_key: [project_number, caan]
  fields:
    - fm: "Projects::ProjectNumber"
      pg: project_number      # resolved to project_id at sync time
      transform: strip
    - fm: CAAN
      pg: caan                # resolved to caan_id at sync time
      transform: strip

contracts:
  fm_layout: Contracts         # Use existing "Contracts" layout; fall back to Import layouts if needed
  pg_table: contracts
  match_key: [fmp_id_primary]  # use FM ID_Primary for reliable matching
  fields:
    # --- System fields (required for sync infrastructure) ---
    - fm: ID_Primary
      pg: fmp_id_primary
      transform: integer
    - fm: ContractNumber
      pg: contract_number
      transform: integer
    # --- Linking (lookup-only; not persisted to contracts table) ---
    - fm: ProjectNumber
      pg: _project_number_lookup
      transform: strip
    # --- Dates ---
    - fm: ContractDate
      pg: contract_date
      transform: date
    - fm: StartDate
      pg: ntp_start_date       # NTP = Notice to Proceed
      transform: date
    - fm: BeneficialOccupancyDate
      pg: beneficial_occupancy_date
      transform: date
    - fm: SubstantialCompletionDate
      pg: substantial_completion_date
      transform: date
    - fm: CertofOcc
      pg: certificate_of_occupancy_date
      transform: date          # NOTE: CertofOcc is Text in FM; use date parser, treat unparseable as NULL
    - fm: CompletionDate
      pg: noc_completion_date  # NOC = Notice of Completion
      transform: date
    - fm: DateRecorded
      pg: noc_recorded_date
      transform: date
    - fm: TerminationDate
      pg: termination_date
      transform: date
    - fm: ProjectBidDate
      pg: bid_date
      transform: date
    - fm: ChangeOrdersRevisedDate
      pg: change_order_revised_expected_end
      transform: date          # Calculated field in FM
    # --- Financial ---
    - fm: Estimate
      pg: cost_estimate
      transform: decimal
    - fm: OriginalCost
      pg: original_contract_cost
      transform: decimal
    - fm: ChangeOrdersCostOfficial
      pg: change_order_total
      transform: decimal       # Calculated field in FM
    - fm: ChangeOrdersRevisedCost
      pg: change_order_revised_cost
      transform: decimal       # Calculated field in FM
    - fm: AccountNumber
      pg: account_number
      transform: strip
    - fm: CFRNumber
      pg: funding_number
      transform: strip
    # --- Duration ---
    - fm: OriginalTime
      pg: original_project_duration
      transform: integer       # days
    - fm: ChangeOrdersTimeOfficial
      pg: change_order_time_total
      transform: integer       # Calculated field in FM
    - fm: ChangeOrdersRevisedTime
      pg: change_order_revised_duration
      transform: integer       # Calculated field in FM
    # --- Parties & description ---
    - fm: CompanyName
      pg: contractor_org_name
      transform: strip
    - fm: "Contracts Architect::Company_c"
      pg: executive_design_org_name
      transform: strip         # RELATED FIELD from People table via "Contracts Architect" TO
    - fm: BFDescriptionofWork
      pg: scope_description
      transform: strip
```

### Transform functions

The `transform` value maps to a Python function:

- `strip` — `.strip()` whitespace and trailing `\r`
- `boolean_yesno` — map "Yes"/"No" (case-insensitive) to True/False, else None
- `boolean_closed` — map "Closed" (case-insensitive) to True, everything else to False
- `integer` — convert to int, None if empty/invalid
- `decimal` — convert to Decimal, None if empty/invalid
- `date` — if value is already a Python `date`, pass through unchanged; otherwise use a date parser (e.g., `dateutil.parser.parse`). Returns Python date on success, None on failure. This handles both proper FM Date fields and text fields containing date-like values (e.g., `CertofOcc`).

## 6. New PostgreSQL Schema

### New `contracts` table

```sql
CREATE TABLE contracts (
    id                                  SERIAL PRIMARY KEY,
    fmp_id_primary                      INTEGER UNIQUE,                -- FileMaker ID_Primary
    contract_number                     INTEGER,
    project_id                          INTEGER REFERENCES projects(id),
    -- Dates
    contract_date                       DATE,
    ntp_start_date                      DATE,          -- Notice to Proceed start
    beneficial_occupancy_date           DATE,
    substantial_completion_date         DATE,
    certificate_of_occupancy_date       DATE,          -- NOTE: source is Text in FM
    noc_completion_date                 DATE,          -- Notice of Completion
    noc_recorded_date                   DATE,
    termination_date                    DATE,
    bid_date                            DATE,
    change_order_revised_expected_end   DATE,          -- calculated in FM
    -- Financial
    cost_estimate                       NUMERIC(14,2),
    original_contract_cost              NUMERIC(14,2),
    change_order_total                  NUMERIC(14,2), -- calculated in FM
    change_order_revised_cost           NUMERIC(14,2), -- calculated in FM
    account_number                      VARCHAR,
    funding_number                      VARCHAR,       -- CFRNumber in FM
    -- Duration (days)
    original_project_duration           INTEGER,
    change_order_time_total             INTEGER,       -- calculated in FM
    change_order_revised_duration       INTEGER,       -- calculated in FM
    -- Parties & description
    contractor_org_name                 VARCHAR,
    executive_design_org_name           VARCHAR,       -- from related "Contracts Architect" TO
    scope_description                   TEXT,          -- BFDescriptionofWork in FM
    -- Sync metadata
    last_synced_at                      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_contracts_project_id ON contracts(project_id);
CREATE INDEX idx_contracts_fmp_id ON contracts(fmp_id_primary);
```

### Modifications to existing tables

```sql
-- Projects table additions
ALTER TABLE projects ADD COLUMN IF NOT EXISTS fmp_id_primary INTEGER UNIQUE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS closed BOOLEAN;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS campus_client VARCHAR;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;

-- CAANs table additions
ALTER TABLE caans ADD COLUMN IF NOT EXISTS fmp_id_primary INTEGER UNIQUE;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_street VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_city VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS address_zip VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS area VARCHAR;
ALTER TABLE caans ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
```

## 7. CLI Interface

Using `click` and `rich` for the command-line interface.

### Commands

```bash
# Full sync (all entities, in dependency order)
project-sync run

# Sync specific entity
project-sync run --entity caans
project-sync run --entity projects
project-sync run --entity contracts
project-sync run --entity project-caans

# Dry run (show what would change without writing)
project-sync run --dry-run

# Show current sync status / last run info
project-sync status

# Test connections (FM + PG)
project-sync check

# Run database migrations
project-sync migrate

# Show the current field mappings
project-sync mappings
```

### Output

Use `rich` for:
- Progress bars during sync
- Tables showing sync results (added/updated/removed counts)
- Color-coded status messages
- Error formatting

## 8. Sync Logic

### General pattern per entity

```python
def sync_entity(entity_config, fm_client, db_conn):
    # 1. Fetch all records from FileMaker
    fm_records = fm_client.get_all_records(entity_config.fm_layout)

    # 2. Apply field mappings and transforms
    mapped_records = apply_mappings(fm_records, entity_config.fields)

    # 3. Fetch existing records from PostgreSQL
    pg_records = db_conn.get_all(entity_config.pg_table)

    # 4. Compute diff
    to_add, to_update, to_remove = compute_diff(
        fm_data=mapped_records,
        pg_data=pg_records,
        match_keys=entity_config.match_key
    )

    # 5. Apply changes
    db_conn.bulk_upsert(entity_config.pg_table, to_add + to_update)
    db_conn.bulk_delete(entity_config.pg_table, to_remove)  # hard delete to maintain FM parity

    # 6. Return summary
    return SyncResult(added=len(to_add), updated=len(to_update), removed=len(to_remove))
```

### Contract-specific logic

Contracts need special handling to resolve the FM project reference:
1. Fetch contracts from FM (includes `ID_Projects` and `ProjectNumber`)
2. Look up the corresponding PG `projects.id` by matching on `ProjectNumber`
3. Set `contracts.project_id` to the PG project ID
4. If a contract references a project that doesn't exist in PG, log a warning and set `project_id = NULL`
5. Do not persist contract `ProjectNumber` in PostgreSQL; derive it from the linked project when needed.

## 9. Logging and Error Handling

- Use Python `logging` with configurable level
- Log to stdout (for cron capture) and optionally to a file
- Each sync run should produce a structured summary (JSON-serializable) including:
  - Timestamp, duration
  - Per-entity counts (added, updated, removed, errors)
  - Any error details
- Logging to stdout/file is sufficient for now (no PG sync_log table needed)

## 10. Deployment

### Linux server setup

```bash
# Install with uv
uv sync

# Manual run
uv run project-sync run

# Or via installed entry point
project-sync run
```

### Cron (scheduled sync)

```cron
# Run nightly at 2 AM
0 2 * * * /opt/app/project_sync_service/.venv/bin/project-sync run >> /var/log/project_sync.log 2>&1
```

Scheduled execution is cron-based; continuous loop mode is intentionally not part of this service.

## 11. Prerequisites / Manual Steps

Before the service can be built and run:

1. **Verify all selected FM layouts** expose all required fields for their entity mappings (projects, caans, project_caans, contracts).
2. **Verify the existing `Contracts` layout** exposes all needed fields including the related field `Contracts Architect::Company_c`. If some fields are missing, try `ImportContracts` or other Import layouts as fallback.
3. **Verify the selected `projects` layout** includes `CampusClient` if `campus_client` sync is enabled.
4. **Verify FM API credentials** — confirm the existing FM user account has access to all selected layouts.
5. **PostgreSQL admin access** — needed to run migrations (add `contracts` table, alter existing tables).

### Migration execution model

Migrations are idempotent and no-tracking:
- Scripts are safe to re-run using `IF NOT EXISTS` guards.
- The service does not maintain a migrations history table.
- `project-sync migrate` executes the numbered scripts directly.

## 12. Open Questions for User

All questions have been resolved. Decisions are recorded here for reference.

### Resolved decisions

1. **Contracts FM layout**: Use the existing `Contracts` layout. If it doesn't expose all needed fields, fall back to `ImportContracts` or other Import layouts. May need to combine data from multiple layout requests.
2. ~~**Contract fields subset**~~: RESOLVED — user provided specific field list (see §5).
3. ~~**Additional project fields**~~: RESOLVED — `Status` → `closed` (boolean: "Closed"→True, else False), `CampusClient` → `campus_client`. Location and Unit not needed.
4. ~~**Additional CAAN fields**~~: RESOLVED — Address→address_street, City→address_city, Zip→address_zip, Area→area.
5. **FM ID storage**: Yes. Column name: `fmp_id_primary` on all synced tables.
6. **Deletion policy**: Hard delete. Maintain parity with FileMaker — if a record is removed from FM, remove it from PG.
7. **File server location**: Not applicable. The project_sync_service does not handle file server location resolution. FM's FileServerLocation field and the filesystem scan approach are deprecated in this context. The existing `file_server_location` column on the projects table is managed by other processes.
8. **Mapping file format**: YAML as primary. Python can be used alongside if transforms or mapping logic need to be colocated.
9. **Sync results storage**: Logging to stdout/file is sufficient. No PG table needed.
10. **Database migrations**: Numbered SQL scripts, run via `project-sync migrate`.
11. **Project number uniqueness**: No UNIQUE constraint on `projects.number`.
12. **Contracts project number persistence**: Not stored in PostgreSQL `contracts`; derive via `contracts.project_id` -> `projects.number`.
13. **Projects status source values**: Confirmed `Open` / `Closed` only (dropdown controlled).
14. **Library set**: Use `psycopg3` and do not include `sqlalchemy` or `httpx`.
15. **FM fetch limit**: configurable via `FM_FETCH_LIMIT` (default 100000). Assumes expected data volumes stay below this threshold.

### Data quality notes for build agent

12. **`CertofOcc` is Text, not Date**: The FM field `CertofOcc` is a Text field. Use a date parser (e.g., `dateutil.parser.parse`); treat unparseable values as NULL — same as any missing date.

13. **`Contracts Architect::Company_c` is a related/calculated field**: This comes from the People base table via the "Contracts Architect" table occurrence. It will only be returned by the FM Data API if it is placed on the layout. If missing, it will simply be absent from the API response (not an error) — the sync should treat missing related fields as NULL.

14. **Layout field verification requirement**: Before first production sync, verify that each selected layout contains all required fields for that entity mapping.
