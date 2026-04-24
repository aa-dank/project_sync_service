"""
Contract sync: syncs contracts table from FileMaker Contracts layout.

Special logic:
- _project_number_lookup is used to resolve contracts.project_id via projects.number
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

    # Build project number → PG project id lookup table
    project_lookup = _build_project_lookup(db)

    # Resolve project_id for each contract record
    unresolved_count = 0
    for record in fm_records:
        proj_num_raw = record.get("_project_number_lookup")
        proj_num = str(proj_num_raw).strip() if proj_num_raw is not None else None
        if proj_num and proj_num in project_lookup:
            record["project_id"] = project_lookup[proj_num]
        else:
            if proj_num:
                unresolved_count += 1
                logger.warning(
                    "Contract fmp_id_primary=%s references project '%s' not found in PG; setting project_id=NULL.",
                    record.get("fmp_id_primary"),
                    proj_num,
                )
            record["project_id"] = None

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


def _build_project_lookup(db: Database) -> dict[str, int]:
    """Return a mapping of project number (string) → PG projects.id."""
    rows = db.get_all("projects", columns=["id", "number"])
    lookup: dict[str, int] = {}
    for row in rows:
        num = str(row["number"]).strip() if row["number"] else None
        if num:
            lookup[num] = row["id"]
    return lookup


def _prepare_record(r: dict) -> dict:
    return {c: (None if r.get(c, MISSING) is MISSING else r.get(c)) for c in PERSIST_COLUMNS}
