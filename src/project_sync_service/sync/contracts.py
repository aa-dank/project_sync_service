"""
Contract sync: syncs contracts table from FileMaker Contracts layout.

Special logic:
- _project_fmp_id_lookup is used first to resolve contracts.project_id via projects.fmp_id_primary
- _project_number_lookup is used as a fallback resolver via projects.number
- ProjectNumber is NOT persisted in the contracts table
- Missing project references → project_id = NULL (with warning)
"""
from __future__ import annotations

import logging

from ..db import Database
from ..fm_adapter import FileMakerAdapter
from ..mappings import EntityMapping, MISSING, apply_mappings
from .base import SyncResult, compute_diff

logger = logging.getLogger(__name__)

PERSIST_COLUMNS = [
    "fmp_id_primary",
    "contract_number",
    "project_id",
    "contract_date",
    "ntp_start_date",
    "beneficial_occupancy_date",
    "substantial_completion_date",
    "certificate_of_occupancy_date",
    "noc_completion_date",
    "noc_recorded_date",
    "termination_date",
    "bid_date",
    "change_order_revised_expected_end",
    "cost_estimate",
    "original_contract_cost",
    "change_order_total",
    "change_order_revised_cost",
    "account_number",
    "funding_number",
    "original_project_duration",
    "change_order_time_total",
    "change_order_revised_duration",
    "contractor_org_name",
    "executive_design_org_name",
    "scope_description",
]

UPDATE_COLUMNS = [c for c in PERSIST_COLUMNS if c != "fmp_id_primary"]


def sync_contracts(
    entity: EntityMapping,
    fm: FileMakerAdapter,
    db: Database,
    fetch_limit: int,
    dry_run: bool = False,
) -> SyncResult:
    result = SyncResult(entity="contracts")

    raw_records = fm.get_records(entity.fm_layout, limit=fetch_limit)
    available_fields = set(raw_records[0].keys()) if raw_records else set()

    critical_fm_fields = {f.fm for f in entity.critical_fields}
    missing_critical = sorted(f for f in critical_fm_fields if f not in available_fields)
    if missing_critical:
        message = (
            "Contracts sync skipped: missing critical FM fields in layout "
            f"'{entity.fm_layout}': {', '.join(missing_critical)}"
        )
        logger.error(message)
        result.errors = 1
        result.error_details.append(message)
        return result

    fm_records = apply_mappings(raw_records, entity)

    # Build project lookup tables
    project_lookup_by_fmp_id, project_lookup_by_number = _build_project_lookups(db)

    # Resolve project_id for each contract record
    unresolved_count = 0
    fallback_count = 0
    for record in fm_records:
        project_fmp_id = record.get("_project_fmp_id_lookup")
        project_number_raw = record.get("_project_number_lookup")
        project_number = str(project_number_raw).strip() if project_number_raw is not None else None

        if project_fmp_id is not None and project_fmp_id in project_lookup_by_fmp_id:
            record["project_id"] = project_lookup_by_fmp_id[project_fmp_id]
            continue

        if project_number and project_number in project_lookup_by_number:
            fallback_count += 1
            record["project_id"] = project_lookup_by_number[project_number]
            logger.warning(
                "Contract fmp_id_primary=%s could not resolve by ID_Projects=%s; used ProjectNumber_lk='%s' fallback.",
                record.get("fmp_id_primary"),
                project_fmp_id,
                project_number,
            )
            continue

        unresolved_count += 1
        logger.warning(
            "Contract fmp_id_primary=%s could not resolve project (ID_Projects=%s, ProjectNumber_lk='%s'); setting project_id=NULL.",
            record.get("fmp_id_primary"),
            project_fmp_id,
            project_number,
        )
        record["project_id"] = None

    if fallback_count:
        logger.warning("Total contract→project resolutions using ProjectNumber_lk fallback: %d", fallback_count)
    if unresolved_count:
        logger.warning("Total unresolved contract→project references: %d", unresolved_count)

    pg_records = db.get_all("contracts", columns=["id"] + PERSIST_COLUMNS)

    existing_by_fmp_id = {
        row["fmp_id_primary"]: row
        for row in pg_records
        if row.get("fmp_id_primary") is not None
    }

    for record in fm_records:
        fmp_id = record.get("fmp_id_primary")
        existing = existing_by_fmp_id.get(fmp_id)
        for col in PERSIST_COLUMNS:
            if record.get(col, MISSING) is MISSING:
                record[col] = existing.get(col) if existing else None

    # Diff using fmp_id_primary as the stable match key
    to_add, to_update, to_remove = compute_diff(
        fm_data=fm_records,
        pg_data=pg_records,
        match_keys=entity.match_key,   # [fmp_id_primary]
    )

    logger.info("Contracts diff: +%d ~%d -%d", len(to_add), len(to_update), len(to_remove))

    if dry_run:
        result.added = len(to_add)
        result.updated = len(to_update)
        result.removed = len(to_remove)
        return result

    with db.transaction():
        upsert_records = [_prepare_record(r) for r in to_add + to_update]
        if upsert_records:
            db.bulk_upsert(
                table="contracts",
                records=upsert_records,
                conflict_columns=["fmp_id_primary"],
                update_columns=UPDATE_COLUMNS,
                extra_set={"last_synced_at": "NOW()"},
            )

        if to_remove:
            db.bulk_delete("contracts", to_remove, match_column="fmp_id_primary")

    result.added = len(to_add)
    result.updated = len(to_update)
    result.removed = len(to_remove)
    return result


def _build_project_lookups(db: Database) -> tuple[dict[int, int], dict[str, int]]:
    """Return mappings for project resolution by FM ID and by project number."""
    rows = db.get_all("projects", columns=["id", "number", "fmp_id_primary"])
    lookup_by_fmp_id: dict[int, int] = {}
    lookup_by_number: dict[str, int] = {}
    for row in rows:
        fmp_id = row.get("fmp_id_primary")
        if fmp_id is not None:
            lookup_by_fmp_id[int(fmp_id)] = row["id"]

        num = str(row["number"]).strip() if row["number"] else None
        if num:
            lookup_by_number[num] = row["id"]

    return lookup_by_fmp_id, lookup_by_number


def _prepare_record(r: dict) -> dict:
    return {c: (None if r.get(c, MISSING) is MISSING else r.get(c)) for c in PERSIST_COLUMNS}
