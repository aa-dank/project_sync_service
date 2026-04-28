# AGENTS Instructions - project_sync_service

These instructions apply to coding agents working in this repository.

Standalone Python sync service that pulls project, CAAN, and contract data from FileMaker (UCPPC) into PostgreSQL (`business_services_db`). Runs via cron on a Linux server; no web server, no continuous loop.

## Commands

```bash
uv sync                          # install dependencies
uv run project-sync run          # full sync (all entities)
uv run project-sync run --entity caans     # single entity
uv run project-sync run --dry-run          # show diff without writing
uv run project-sync check        # test FM + PG connections
uv run project-sync validate     # preflight: verify FM layouts/fields + PG tables
uv run project-sync mappings     # show current field mappings (no credentials needed)
uv run project-sync status       # show row counts and last_synced_at per table
```

No test suite exists yet (`tests/` is empty). No linter is configured.

There is no `project-sync migrate` command. SQL files under `src/project_sync_service/migrations/` are retained as deployment/reference artifacts and are applied externally with database tooling such as `psql`.

## Architecture

Data flows one way: FileMaker -> this service -> PostgreSQL. No write-back to FM.

```
FileMakerAdapter (fm_adapter.py)
    |  get_records(layout) -> list[dict]
    v
mappings.py         load_mappings() -> EntityMapping
                    apply_mappings() -> list[dict] (pg-keyed)
    v
sync/{caans,projects,contracts,project_caans}.py
    |  compute_diff(fm_data, pg_data, match_keys) -> (to_add, to_update, to_remove)
    v
Database (db.py)
    |  bulk_upsert() / bulk_delete() / transaction()
    v
PostgreSQL (business_services_db)
```

**Sync must run in dependency order** - this is enforced by `ENTITY_ORDER` in `cli.py`:
1. `caans` - no dependencies
2. `projects` - no FK deps, but contracts and project_caans both need it populated first
3. `contracts` - resolves `project_id` from `projects` table at sync time
4. `project_caans` - resolves both `project_id` and `caan_id` at sync time

## Key conventions

### field_mappings.yaml is the single source of truth for what data flows where
All FM->PG column mappings live in `config/field_mappings.yaml`. When adding a new field, add it there first. The `EntityMapping` and `FieldMapping` dataclasses in `mappings.py` represent it in code.

### Lookup-only fields use a `_` prefix on the `pg` name
Fields with `pg: _<name>` are consumed at sync time but **never written to the database**. Example: `ProjectNumber` on contracts maps to `_project_number_lookup` - it is used to resolve `project_id` and then discarded. Checked via `FieldMapping.is_lookup_only`.

### Adding a new sync entity
1. Add its entry to `config/field_mappings.yaml`
2. Create `src/project_sync_service/sync/<entity>.py` following the pattern of the existing files (`PERSIST_COLUMNS`, `UPDATE_COLUMNS`, a `sync_<entity>()` function, a `_prepare_record()` helper)
3. Register it in `cli.py`: add to `ENTITY_ORDER` and `ENTITY_SYNCS`

### Transform functions are in mappings.py - not inline in sync code
All value coercions are registered in `TRANSFORM_REGISTRY`. Available transforms: `strip`, `boolean_yesno`, `boolean_closed`, `integer`, `decimal`, `date`. The `date` transform handles both proper FM Date fields (returned as `datetime.date` by fmrest) and Text fields containing date strings (e.g. `CertofOcc`) - it returns `None` on parse failure, never raises.

### FileMakerAdapter is a context manager
Always use it with `with FileMakerAdapter(cfg.fm) as fm:`. It logs out on exit. Layout switching rebuilds the underlying `fmrest.Server` (the library binds a server to one layout at construction time).

### Database uses explicit transactions for writes
Sync writes are wrapped in `with db.transaction():`. `Database.__exit__` commits on clean exit, rolls back on exception. Schema changes are not run by the service; apply SQL migration/reference files externally with the deployment database workflow.

### bulk_upsert always sets last_synced_at via the DB clock
All entity syncs pass `extra_set={"last_synced_at": "NOW()"}` to `bulk_upsert()`. This is set by the database server, not the app, and fires on every upsert - including records with no data changes - so it reflects when a record was last *confirmed* from FM.

### Sync identity keys are not all human-facing business keys
Do not assume project numbers are unique. FileMaker and PostgreSQL both contain duplicate project numbers, and some duplicates are legitimate/known FileMaker data. Projects should move toward `fmp_id_primary` as the transitional sync identity while FileMaker remains authoritative.

Current identity notes:
- `caans` syncs by `caan`; `caans.caan` has a unique index in PostgreSQL.
- `contracts` syncs by `fmp_id_primary`.
- `projects` historically synced by `number`, but this is unsafe because `projects.number` is not unique. Use the development backfill workflow before switching project sync to `fmp_id_primary`.
- `project_caans` currently resolves projects by project number; this remains ambiguous for duplicate project numbers and needs a future FileMaker-ID-based resolution if the layout exposes the project `ID_Primary`.

### Project fmp_id_primary backfill workflow
Use `development/backfill_project_fmp_ids.py` to backfill `projects.fmp_id_primary` from FileMaker. It is dry-run by default and only updates rows where normalized `(project number, project name)` is unique on both sides.

```bash
.venv/bin/python development/backfill_project_fmp_ids.py          # dry run
.venv/bin/python development/backfill_project_fmp_ids.py --apply  # write safe matches
```

Review duplicate/unmatched rows manually before changing project sync to use `fmp_id_primary`.

### Hard deletes - no soft delete pattern
`compute_diff()` returns `to_remove` for records present in PG but absent from FM. These are hard-deleted to maintain parity with FileMaker. There is no archive/soft-delete mechanism.

### Logging always includes a run correlation ID
`setup_logging()` in `utils.py` generates a UUID run ID and injects it into every log line via a `logging.Filter`. Call `setup_logging(cfg.log_level)` once at CLI command entry. Use `get_run_id()` if you need the ID elsewhere (e.g. for structured summaries).

### FM error types
`FileMakerAdapter` raises typed exceptions - prefer catching these over the raw `fmrest` exceptions:
- `FileMakerAuthError` - bad credentials (FM error 212)
- `FileMakerLayoutError` - layout not found/accessible (FM error 105)
- `FileMakerError` - everything else

### FM error 401 = empty result set, not an error
fmrest raises `FileMakerError` with "401" in the message for a valid query that returns zero records. The adapter catches this and returns `None`, which `get_records()` converts to `[]`.

### development/local/ is the drop zone for untracked local artifacts
`development/local/` is git-ignored and intended for anything that should never be committed: scratch scripts, ad-hoc query outputs, raw data exports, investigation notes, etc. Keep throwaway work here rather than in the tracked `development/` root. The directory is empty in the repo (git does not track empty dirs); add a `.gitkeep` if you need it to appear after a fresh clone.

## Reference documents (in `development/`)

- `PROJECT_SPECIFICATIONS.md` - canonical build contract; source of truth for all design decisions
- `DEVELOPMENT_JOURNAL.md` - per-session narrative log; add an entry when making significant changes
- `reference/FILEMAKER_SYSTEM_REFERENCE.md` - FM table occurrences, field types, relationship graph
- `reference/ARCHIVES_DB_AND_FILE_SERVER_REFERENCE.md` - PostgreSQL schema context for target tables
- `reference/fmp_database_design_report/UCPPC_ddr/UCPPC.html` - authoritative FM DDR; very large HTML file, extract only what you need
- `local/` - **not tracked**; drop zone for scratch scripts, raw exports, and investigation artifacts (git-ignored)

## FileMaker schema notes

- `CAANs.ID_Primary` is **Text** in FM (not Number like other tables); normalised to integer in PG as `fmp_id_primary`
- `Contracts.ProjectNumber` is **Number** in FM; `Projects.ProjectNumber` is **Text** - type mismatch to be aware of when matching
- `Projects.ProjectNumber` is not unique; do not add a unique constraint on `projects.number`
- `CertofOcc` on Contracts is a **Text** field despite holding dates - always use the `date` transform
- `Contracts Architect::Company_c` is a related field via the "Contracts Architect" table occurrence; it is absent (not null) from API responses when the relationship has no match - the adapter returns `None` for absent keys, which becomes NULL in PG
- Calculated FM fields (`ChangeOrders*`, `ChangeOrdersRevised*`) may return empty for records where underlying data is missing
