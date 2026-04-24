# Development Journal — project_sync_service

A running log of development sessions, build decisions, and technical notes for future reference.

---

## Entry 001 — Initial Build
**Date:** 2026-04-06
**Author:** GitHub Copilot (claude-sonnet-4.6)

---

### Prompt that initiated this build

```
Goal:
Build the first working version of a standalone Python sync service that pulls data from FileMaker (UCPPC) and syncs it into PostgreSQL (business_services_db), following the project specs and references below.

Read these files/folders first, in order:
1. development/PROJECT_SPECIFICATIONS.md
2. development/reference/RESEARCH_INSIGHTS.md
3. development/reference/FILEMAKER_SYSTEM_REFERENCE.md
4. development/reference/ARCHIVES_DB_AND_FILE_SERVER_REFERENCE.md
5. development/reference/FMP.py
6. development/reference/fmp_database_design_report

How to use each source:
- PROJECT_SPECIFICATIONS.md:
  Canonical build contract. Follow architecture, CLI commands, sync ordering, migration model, mapping strategy, and resolved decisions.
- RESEARCH_INSIGHTS.md:
  Practical implementation guidance, known caveats, and confirmed technical decisions from earlier analysis.
- FILEMAKER_SYSTEM_REFERENCE.md:
  Domain/system behavior for FileMaker, including table occurrence semantics and field-level caveats.
- ARCHIVES_DB_AND_FILE_SERVER_REFERENCE.md:
  PostgreSQL target context and current table expectations relevant to sync writes.
- FMP.py:
  Shared FileMaker helper baseline; adapt its patterns into project-local production code.
- fmp_database_design_report (DDR folder):
  Ground-truth FileMaker schema verification source. Use this to validate:
  - Exact field names and data types (for mapping correctness)
  - Relationship directions and join keys (especially Projects ↔ Contracts and ProjectCAANs links)
  - Layout/table-occurrence context when API field behavior is ambiguous
  - Presence and naming of related fields (for example Contracts Architect::Company_c)
  - Candidate layout options when an expected field is missing from a layout

DDR usage instructions:
- Treat DDR as authoritative for schema facts when docs disagree.
- Prefer checking UCPPC_ddr/UCPPC.html (and related DDR pages) before coding uncertain mappings.
- If a required field or relationship cannot be confirmed in DDR, mark it as a blocker in the final report.
- Do not copy DDR HTML into source code; extract only the required schema facts and encode them in mappings/tests/docs.
- If a field appears in DDR but not via Data API output, treat it as a likely layout-placement issue and surface it in validation output.
- Careful about preserving context when using the UCPPC_ddr/UCPPC.html — it's very large HTML which can pollute context if not careful.

Critical implementation rules:
- Keep production code under src/project_sync_service.
- Create a project-local FM adapter based on FMP.py patterns (retry, token/session handling, layout switching, timeout control), but harden it for this service.
- Do not runtime-import from development/reference.
- Use psycopg3, click, pyyaml, python-dotenv.
- Keep mapping-driven sync via YAML field mappings.
- Enforce idempotent sync and hard-delete parity with FileMaker.
- Do not persist contracts.project_number; resolve via project_id relation.
- Add and wire a validate command for preflight checks (layouts, required fields, FM/PG connectivity).
- Keep logging structured and include a run correlation id.
- Handle CertofOcc as text-date parse with NULL fallback.
- Treat missing related FM fields as NULL (example: Contracts Architect::Company_c).

Expected deliverables in this run:
- Working initial codebase scaffold and core sync flow.
- SQL migration scripts for contracts table and project/caans column additions.
- field_mappings.yaml matching resolved mappings from spec.
```

---

### What was built

This session produced the first working version of the sync service. The full package scaffold was created under `src/project_sync_service/`, all CLI commands were wired, migration scripts were written, and the field mappings YAML was finalised. The package installs cleanly via `uv sync` and all imports and CLI commands were verified working.

**Files created:**

| File | Description |
|---|---|
| `pyproject.toml` | Updated with all runtime dependencies and `project-sync` entry point |
| `config/field_mappings.yaml` | Authoritative FM→PG field mapping config for all 4 entities |
| `.env.example` | Template for environment variable configuration |
| `README.md` | Usage and setup documentation |
| `src/project_sync_service/__init__.py` | Package init |
| `src/project_sync_service/config.py` | Settings dataclass; loads from env vars / `.env` |
| `src/project_sync_service/mappings.py` | YAML loader, FieldMapping/EntityMapping dataclasses, all transform functions |
| `src/project_sync_service/fm_adapter.py` | FileMaker Data API adapter (hardened from FMP.py) |
| `src/project_sync_service/db.py` | PostgreSQL wrapper (psycopg3): get_all, bulk_upsert, bulk_delete, run_migration_file |
| `src/project_sync_service/preflight.py` | Preflight validation: FM layouts/fields + PG table checks |
| `src/project_sync_service/utils.py` | Logging setup with run correlation ID; structured summary helper |
| `src/project_sync_service/cli.py` | All 6 CLI commands: run, check, validate, migrate, mappings, status |
| `src/project_sync_service/sync/__init__.py` | Sync subpackage init |
| `src/project_sync_service/sync/base.py` | SyncResult, compute_diff(), fetch_and_map() |
| `src/project_sync_service/sync/caans.py` | CAAN sync |
| `src/project_sync_service/sync/projects.py` | Project sync |
| `src/project_sync_service/sync/contracts.py` | Contract sync with project_id resolution |
| `src/project_sync_service/sync/project_caans.py` | Project-CAAN join sync with ID resolution |
| `src/project_sync_service/migrations/001_add_contracts_table.sql` | Idempotent CREATE TABLE for contracts |
| `src/project_sync_service/migrations/002_alter_existing_tables.sql` | Idempotent ALTER TABLE for projects + caans |

---

### Technical notes and things to know

#### fmrest library version
The latest available version of `fmrest` on PyPI is **1.1.2**, not anything higher. The initial pyproject.toml specified `>=1.5.0` (based on spec assumptions) which caused `uv sync` to fail. Corrected to `>=1.1.2`. Worth verifying this is the version actually in use on the production server before deploying.

#### fmrest Foundset iteration
The reference `FMP.py` helper converts Foundsets to pandas DataFrames via `.to_df()`. This service avoids pandas entirely — instead, it iterates the `Foundset` object directly with `for record in foundset: dict(record)`. This works with fmrest 1.1.2 and keeps the dependency footprint lean. If fmrest ever changes iteration behaviour, `fm_adapter._foundset_to_dicts()` is the one place to fix.

#### FM adapter: layout switching
`fmrest.Server` is bound to a layout at construction time — you can't switch layouts on an existing server instance (despite the `.layout` property). The adapter handles this by logging out and constructing a new `Server` object when a different layout is requested. This matches the pattern in `FMP.py` and is the correct approach.

#### contracts.project_number is NOT stored
Per spec: `ProjectNumber` on the Contracts FM record is mapped to `_project_number_lookup` (underscore prefix = lookup-only). It's used at sync time to resolve `contracts.project_id` via a `projects` table lookup, then discarded. Never persisted to the DB. To get a contract's project number from PG, join `contracts → projects` on `project_id`.

#### CertofOcc is a Text field
`CertofOcc` in FileMaker's Contracts table is defined as **Text**, not Date, despite holding date-like values. The `date` transform uses `dateutil.parser.parse()` with a None fallback on failure. This is handled uniformly — the `date` transform works identically for proper FM Date fields (which come back as Python `datetime.date` objects via fmrest) and for text fields that happen to contain dates.

#### Contracts Architect::Company_c — related field absence
This is a related field pulled via the "Contracts Architect" table occurrence (People base table). The FM Data API only returns it if it is physically placed on the layout. If the record's relationship has no match, the field is absent from the API response (not null — just absent). The adapter handles this correctly: `fm_record.get(field_map.fm)` returns `None` for absent keys, which propagates as NULL to PG. The preflight validator raises a warning (not a failure) for absent related fields in sample records.

#### Sync dependency order
The sync must run in this order due to FK dependencies in the project_id resolution:
1. `caans` — no dependencies
2. `projects` — no FK deps in PG, but contracts/project_caans both reference it
3. `contracts` — needs `projects` populated so `project_id` can be resolved
4. `project_caans` — needs both `projects` and `caans` populated

Skipping or reordering will cause FK resolution warnings or NULL project_ids in contracts.

#### bulk_upsert and last_synced_at
The `db.bulk_upsert()` method accepts an `extra_set` dict for additional SET clauses. All entity syncs pass `{"last_synced_at": "NOW()"}` so the timestamp is updated by the DB server (not the app clock) on every upsert, including no-change "updates". This is intentional — it lets you tell when a record was last *confirmed* from FM, not just when it last *changed*.

#### Hard deletes
Records removed from FileMaker are hard-deleted from PG on the next sync. `compute_diff()` identifies them as `to_remove` (present in PG, absent from FM). The `bulk_delete()` method uses `DELETE … WHERE match_column = ANY(%s)` which is efficient for bulk operations. No soft-delete/archive pattern is implemented.

#### Idempotency
All SQL is `INSERT … ON CONFLICT … DO UPDATE`, so syncs are safe to run multiple times. Migration scripts use `IF NOT EXISTS` throughout. Running `project-sync migrate` twice is harmless.

#### Python version mismatch
The server's `.python-version` pin file says `3.14`, but the actual available Python at build time was `3.10.12` (system) and `3.14.2` (uv-managed). `uv` used `3.14.2` when creating the venv. `pyproject.toml` requires `>=3.11`. This should be fine in production, but worth confirming the uv-managed Python version is available on the production server or that the venv is built there.

#### mappings command is credential-free
The `project-sync mappings` command was designed to not require FM or PG credentials (it only reads the YAML file). This makes it safe to run in any environment for a quick sanity check of the mapping config.

---

### What is NOT yet done (follow-on work)

- **Tests** — no unit or integration tests were written in this session. The `tests/` directory exists but is empty. Priority follow-on work.
- **DDR verification of FM field names** — the mapping field names were taken from the spec and cross-referenced against `FILEMAKER_SYSTEM_REFERENCE.md`. The full DDR HTML (`UCPPC_ddr/UCPPC.html`) was not deeply parsed during this build. A follow-on session should use the DDR to confirm:
  - `SubstantialCompletionDate` (spec uses this; FM reference mentions `SubstantialCompletion` — verify exact name on the Contracts layout)
  - `BeneficialOccupancyDate` (similar — FM reference mentions `BeneficialOccupancy`)
  - `DateRecorded` — confirm this is the correct FM field name for NOC recorded date
  - That `ChangeOrdersRevisedDate`, `ChangeOrdersCostOfficial`, `ChangeOrdersRevisedCost`, `ChangeOrdersTimeOfficial`, `ChangeOrdersRevisedTime` are all accessible on the `Contracts` layout (they're calculated fields)
  - That `Contracts Architect::Company_c` is placed on the `Contracts` layout

---

## Entry 002 — Remove database migration functionality
**Date:** 2026-04-09
**Author:** GitHub Copilot (claude-sonnet-4.6)

---

### What changed

The built-in database migration command (`project-sync migrate`) has been removed. Database schema management is now handled externally via `psql` and is no longer a concern of this service.

**Files modified:**

| File | Change |
|---|---|
| `src/project_sync_service/cli.py` | Removed the `migrate` CLI command and its implementation |
| `src/project_sync_service/db.py` | Removed `Database.run_migration_file()` method and unused `pathlib.Path` import |
| `src/project_sync_service/preflight.py` | Updated missing-table failure message to remove reference to `project-sync migrate` |
| `.vscode/launch.json` | Removed the `migrate` debug launch configuration |
| `README.md` | Removed migrate step from setup instructions; replaced "Migrations" section with "Database Schema" note |

The SQL scripts themselves (`migrations/001_add_contracts_table.sql`, `migrations/002_alter_existing_tables.sql`) are retained in the repository for historical reference.

### Reason

Schema changes are applied directly with `psql` as part of the deployment workflow. Running migrations through the application service added complexity without benefit and created a misleading impression that the service was responsible for schema ownership.
- **First production run** — run `project-sync validate` before first live sync to confirm layout field availability.
- **ContractAmendments / ContractSubContracts** — out of scope for this version; can be added as `sync/contract_amendments.py` etc. following the same pattern.

---

## Entry 003 — Resilient handling for missing layout fields
**Date:** 2026-04-23
**Author:** GitHub Copilot (GPT-5.3-Codex)

---

### What changed

Contracts sync and preflight were updated so the service no longer assumes every mapped field is always present on the configured FileMaker layout.

**Behavior now:**

- Fields can be marked `critical: true` in `config/field_mappings.yaml`.
- Missing **critical** fields block that entity sync (for contracts: skip writes and log an error).
- Missing **optional** fields do not fail sync; existing PostgreSQL values are preserved.
- Preflight reports missing optional fields as warnings and missing critical fields as failures.

### Files updated

| File | Change |
|---|---|
| `config/field_mappings.yaml` | Marked contracts `ID_Primary`, `ContractNumber`, and `ProjectNumber` as `critical: true` |
| `src/project_sync_service/mappings.py` | Added `critical` flag support and a `MISSING` sentinel for absent FM fields |
| `src/project_sync_service/preflight.py` | Missing-field checks now differentiate critical failures vs optional warnings |
| `src/project_sync_service/sync/contracts.py` | Added runtime critical-field gate and preservation of existing DB values for missing optional fields |

### Why this matters

This prevents accidental data loss when a layout temporarily omits non-critical fields. Previously, absent fields could be interpreted as `None` and overwrite populated values in PostgreSQL.
