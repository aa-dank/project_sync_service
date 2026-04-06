# Research Insights for project_sync_service Build

This document captures technical findings from analyzing the existing archives_app codebase, the FileMaker DDR, and the PostgreSQL schema. It is intended for the AI agent performing the build.

## 1. Current Sync Implementation Analysis

The existing sync lives in `archives_app/archives_application/project_tools/project_tools_tasks.py` as `fmp_caan_project_reconciliation_task()`. It runs as a background task via Redis Queue (RQ).

### Shared helper module now available in this repo

The repository now includes `development/reference/FMP.py`, a reusable FileMaker helper used across projects. It should be treated as a reference baseline for this build and folded into a project-local adapter (`src/project_sync_service/fm_adapter.py`) so runtime code remains packaged under `src/`.

Observed capabilities from `FMP.py` worth preserving:
- Login retry workflow with token refresh handling.
- Explicit support for per-layout server context switching.
- Wrapper for retrying fmrest operations with assessment hooks.
- Configurable timeout and SSL verification controls.

Refinement targets when incorporating it:
- Remove pandas dependency from sync internals unless it provides clear value for a specific transform stage.
- Tighten exception semantics (raise typed errors with context, not generic `Exception`).
- Ensure retry loop covers all configured attempts.
- Keep helper methods focused on data retrieval/update primitives needed by the sync service.

### What it currently syncs

1. **CAANs**: Full two-way reconciliation. Adds CAANs present in FM but missing from PG; removes CAANs present in PG but missing from FM.
2. **Projects**: Same pattern — add missing, remove orphaned. Also updates `name` and `drawings` fields if `update_existing=True`.
3. **Project-CAANs join**: Reconciles the many-to-many relationship.

### What it does NOT sync (gaps the new service fills)

- Contract data (entirely absent from PG)
- Additional project fields beyond number/name/drawings/file_server_location
- Additional CAAN fields (Address, City, Zip, Area, Valid_flag)
- Project status
- Any FM audit timestamps

### FM Data API access pattern (from existing code)

```python
# Key constants from routes.py:
FILEMAKER_API_VERSION = 'v1'
FILEMAKER_CAAN_LAYOUT = 'caan_table'
FILEMAKER_PROJECTS_LAYOUT = 'projects_table'
FILEMAKER_PROJECT_CAANS_LAYOUT = 'caan_project_join'
FILEMAKER_TABLE_INDEX_COLUMN_NAME = 'ID_Primary'
VERIFY_FILEMAKER_SSL = False
DEFAULT_TASK_TIMEOUT = 18000  # 5 hours

# Connection:
fmrest.utils.TIMEOUT = 300
server = fmrest.Server(host, user=user, password=password,
                       database=db_name, layout=layout,
                       api_version='v1', verify_ssl=False)
server.login()
foundset = server.get_records(limit=100000)
df = foundset.to_df()
```

### FM field names used by the current sync

From `caan_table` layout:
- `CAAN`, `Name`, `Description`

From `projects_table` layout:
- `ProjectNumber`, `ProjectName`, `Drawings`

From `caan_project_join` layout:
- `Projects::ProjectNumber` (related field from Projects TO), `CAAN`

### File server location resolution (NOT APPLICABLE to project_sync_service)

The current archives_app sync resolves `file_server_location` by scanning the file server filesystem. **The project_sync_service will NOT do this.** File server location data in FileMaker is deprecated. The existing `file_server_location` column on the projects table is managed by other processes in the archives_app.

### Project number validation regex

```python
PROJECT_NUMBER_RE_PATTERN = r'\b\d{4,5}(?:[A-Z])?(?:-\d{3})?(?:[A-Z])?\b'
```
Matches: 4-5 digits, optional letter, optional dash-3digits, optional letter. Examples: "1200", "4932", "10638", "6300A", "1200-032".

### Drawings field mapping

The FM `Drawings` field is free-text. Current mapping:
```python
drawing_value_map = {"Yes": True, "yes": True, "YES": True,
                     "NO": False, "No": False, "no": False}
# Anything else → None
```

## 2. PostgreSQL Schema Details

### Current tables relevant to sync

**`projects`** (SQLAlchemy model: `ProjectModel`)
- `id` (Integer, PK, auto-increment)
- `number` (String, NOT NULL) — project number
- `name` (String, NOT NULL) — project name
- `file_server_location` (String, nullable) — relative path on file server
- `drawings` (Boolean, nullable)

**`caans`** (SQLAlchemy model: `CAANModel`)
- `id` (Integer, PK, auto-increment)
- `caan` (String, NOT NULL) — CAAN code
- `name` (String, nullable)
- `description` (String, nullable)

**`project_caans`** (association table, no model)
- `project_id` (Integer, FK → projects.id, PK)
- `caan_id` (Integer, FK → caans.id, PK)

### Key observations

- PostgreSQL uses auto-increment integer PKs, not the FM `ID_Primary` values
- The `project_caans` join uses PG IDs, not FM IDs — the sync resolves by matching on `project.number` and `caan.caan`
- No `contracts` table exists yet — this needs to be created
- No FM primary keys are stored in PG — matching is done by business keys (project number, CAAN code)
- The `projects.number` field is NOT unique-constrained in the schema (but is treated as unique in practice)
- Database: `business_services_db`, PostgreSQL 17
- Connection: localhost:5432, admin user `archives_admin`
- The app uses Flask-SQLAlchemy with models defined in `archives_application/models.py`

### Schema for new `contracts` table (to be created)

This is a new table. The project_sync_service will need to:
1. Create the table via migration or DDL
2. Populate it from FM data
3. Maintain it on subsequent sync runs

## 3. FileMaker API Considerations

### Layout requirements for contracts

There is **no `contracts_table` layout** in the current FM setup. Options:
1. **Create a new layout** in FileMaker (preferred — clean, purpose-built)
2. **Use `dev.Contracts`** or `script.Contracts` — but these may include unwanted fields or have access restrictions
3. The layout must be based on a Contracts table occurrence and include only the fields we need

### fmrest library notes

- `fmrest` handles token auth automatically (login/logout)
- `get_records(limit=N)` returns a `Foundset`; use `.to_df()` for pandas DataFrame
- Field names in the DataFrame match the FM field names exactly (including spaces and special characters)
- Related fields appear as `TableOccurrence::FieldName` (e.g., `Projects::ProjectNumber`)
- The library supports `find()` for filtered queries, not just `get_records()`
- `fmrest.utils.TIMEOUT` is a module-level setting affecting all connections
- The library creates a new session per `Server` instance

### Data volume expectations

- Projects: ~10K records — manageable in a single `get_records()` call
- CAANs: ~1.2K records — trivial
- ProjectCAANs: implied ~11K from PG `project_caans` count
- Contracts: ~5.7K records — manageable
- ContractAmendments: ~103 records — trivial
- ContractSubContracts: ~629 records — trivial

### FM Data API pagination

The `get_records()` call returns up to `limit` records. The service uses a configurable fetch limit (`FM_FETCH_LIMIT`, default `100000`) and assumes expected data volumes remain below this threshold.

## 4. Field Mapping Insights

### Projects: FM → PG mapping (current)

| FM Field (`projects_table`) | PG Column (`projects`) | Notes |
|---|---|---|
| `ProjectNumber` | `number` | Text in FM |
| `ProjectName` | `name` | |
| `Drawings` | `drawings` | Text→Boolean mapping |
| (resolved at sync time) | `file_server_location` | Not from FM directly |

### Projects: Confirmed additional field mappings (user-specified)

- `ID_Primary` → `fmp_id_primary` (Integer)
- `Status` → `closed` (Boolean: "Closed" → True, else False)
- `CampusClient` → `campus_client`

Not included: Location, Unit, FileServerLocation (deprecated in FM), ID_ProjectManager, ID_Inspector.

### CAANs: Confirmed additional field mappings (user-specified)

- `Address` → `address_street`
- `City` → `address_city`
- `Zip` → `address_zip`
- `Area` → `area`

Not included: `Valid_flag` (validity indicator) — not requested.

### Contracts: Confirmed field mappings (user-specified)

The Contracts table has 218 fields. The user selected the following subset (22 data fields + 2 persisted system fields + 1 lookup-only linking field):

**System/linking (added for sync infrastructure):**
- `ID_Primary` → `fmp_id_primary` (Integer)
- `ContractNumber` → `contract_number` (Integer)
- `ProjectNumber` → lookup-only value to resolve `project_id` at sync time (not persisted in `contracts` table)

**Dates:**
- `ContractDate` → `contract_date`
- `StartDate` → `ntp_start_date` (Notice to Proceed)
- `BeneficialOccupancyDate` → `beneficial_occupancy_date`
- `SubstantialCompletionDate` → `substantial_completion_date`
- `CertofOcc` → `certificate_of_occupancy_date` — **WARNING: Text field in FM, not Date**
- `CompletionDate` → `noc_completion_date` (Notice of Completion)
- `DateRecorded` → `noc_recorded_date`
- `TerminationDate` → `termination_date`
- `ProjectBidDate` → `bid_date`
- `ChangeOrdersRevisedDate` → `change_order_revised_expected_end` (Calculated in FM)

**Financial:**
- `Estimate` → `cost_estimate`
- `OriginalCost` → `original_contract_cost`
- `ChangeOrdersCostOfficial` → `change_order_total` (Calculated)
- `ChangeOrdersRevisedCost` → `change_order_revised_cost` (Calculated)
- `AccountNumber` → `account_number`
- `CFRNumber` → `funding_number`

**Duration (days):**
- `OriginalTime` → `original_project_duration`
- `ChangeOrdersTimeOfficial` → `change_order_time_total` (Calculated)
- `ChangeOrdersRevisedTime` → `change_order_revised_duration` (Calculated)

**Parties & description:**
- `CompanyName` → `contractor_org_name`
- `Contracts Architect::Company_c` → `executive_design_org_name` — **RELATED FIELD** from People table via "Contracts Architect" TO. Must be on the FM layout.
- `BFDescriptionofWork` → `scope_description`

**Build agent notes:**
- Several fields are Calculated in FM (ChangeOrders*, ChangeOrdersRevised*). These are read-only and may return empty if underlying data is missing.
- `CertofOcc` is Text in FM; use a date parser and treat unparseable values as NULL (same as any missing date).
- `Contracts Architect::Company_c` is a related field. If the relationship has no matching record, the API returns empty/null for that field — handle gracefully.

## 5. Reconciliation Strategy Considerations

### Current strategy (for reference)

The existing sync does a full-table comparison:
1. Fetch ALL records from FM
2. Fetch ALL records from PG
3. Compute set differences using pandas
4. Add missing records, remove orphaned records, update changed records
5. Commit in batches (per entity type)

### Considerations for the new service

- **Idempotency**: The sync should be safe to run repeatedly. Use upsert (INSERT ON CONFLICT UPDATE) patterns.
- **Deletion policy**: Hard delete. Records removed from FM are removed from PG to maintain parity.
- **Ordering**: CAANs should be synced before Projects (projects reference CAANs). Projects before Contracts (contracts reference projects). The ProjectCAANs join should be last.
- **Error handling**: The current sync wraps each entity type in try/except and continues. Errors are logged to a `recon_log` dict. The new service should follow a similar pattern.
- **Matching keys**: Since PG uses auto-increment IDs (not FM IDs), matching must be done on business keys:
  - CAANs: match on `caan` code
  - Projects: match on `number` (project number)
  - Contracts: match on `fmp_id_primary` (FM `ID_Primary`)
  - ProjectCAANs: match on project_number + caan code pair
- **Preflight safety checks**: Add a `project-sync validate` command to verify required layouts/fields and connectivity before migrations or scheduled runs.

### Storing FM primary keys

The project_sync_service will store FM `ID_Primary` as `fmp_id_primary` on all synced PG tables (projects, caans, contracts). For consistency across tables, CAAN `fmp_id_primary` is normalized to integer in PostgreSQL.

## 6. Deployment Environment

### Target: Linux server (ppdo-prod-app-1)

- OS: Linux (Ubuntu-based)
- PostgreSQL 17 on localhost:5432
- Python environment managed with `uv`
- Existing apps use systemd/supervisord for process management
- Cron for scheduled tasks

### Network considerations

- FileMaker Server is accessed over the internal network (not localhost)
- The `os.environ['no_proxy'] = '*'` line in the current sync suggests proxy bypass is needed
- SSL verification is disabled for FM connections

## 7. Library Choices

### Confirmed libraries (from user requirements)
- `fmrest` — FileMaker Data API client
- `psycopg3` (psycopg) — PostgreSQL driver
- `click` — CLI framework
- `rich` — Terminal formatting/output

### Additional likely needs
- `pyyaml` — for YAML mapping config (confirmed format)
- `python-dateutil` — for robust date parsing (handles Text-type date fields like `CertofOcc`)
- `python-dotenv` — for environment variable management
- `logging` — standard library logging (sufficient, no need for structlog)

## 8. Resolved Technical Decisions

All decisions finalized:

1. **Layouts and configurability**: Layout names are configurable and easy to change; verify each selected layout exposes all required fields.
2. **Contract fields**: 22 data fields + 2 persisted system fields + 1 lookup-only linking field (see §4 above).
3. **Additional project fields**: `Status`→`closed` (bool), `CampusClient`→`campus_client`.
4. **Additional CAAN fields**: Address→address_street, City→address_city, Zip→address_zip, Area→area.
5. **FM ID storage**: Yes, as `fmp_id_primary` on all synced tables; CAAN `fmp_id_primary` is normalized to integer for consistency.
6. **Deletion policy**: Hard delete to maintain FM parity.
7. **File server location**: Not applicable — project_sync_service does not handle this.
8. **Mapping file format**: YAML primary; Python alongside if needed for logic.
9. **Sync results storage**: Logging only (no PG table).
10. **Database migrations**: Numbered SQL scripts via `project-sync migrate`, idempotent and no-tracking.
11. **Project number uniqueness**: No UNIQUE constraint.
12. **Contracts project number storage**: Do not persist `project_number` in `contracts`; derive from linked `projects` row.
13. **Execution mode**: Cron-based scheduling only; no loop mode.
14. **Status field semantics**: Project status values are constrained to dropdown values `Open` and `Closed`.
15. **Libraries**: Use `psycopg3`; do not include `sqlalchemy` or `httpx`.
16. **Fetch limit assumption**: Use configurable `FM_FETCH_LIMIT` (default `100000`) and assume expected data volumes remain under this threshold.
17. **Shared FM module integration**: Incorporate and harden patterns from `development/reference/FMP.py` in a project-local adapter module, keeping the design reusable across projects.
