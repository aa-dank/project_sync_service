"""
Project sync: syncs projects table from FileMaker projects_table layout.
"""
from __future__ import annotations

import logging
import re

from ..db import Database
from ..fm_adapter import FileMakerAdapter
from ..mappings import EntityMapping
from .base import SyncResult, compute_diff, fetch_and_map

logger = logging.getLogger(__name__)

PERSIST_COLUMNS = [
    "fmp_id_primary",
    "number",
    "name",
    "drawings",
    "closed",
]

UPDATE_COLUMNS = [
    "name",
    "drawings",
    "closed",
]


def sync_projects(
    entity: EntityMapping,
    fm: FileMakerAdapter,
    db: Database,
    fetch_limit: int,
    dry_run: bool = False,
) -> SyncResult:
    result = SyncResult(entity="projects")

    fm_records = fetch_and_map(fm, entity, fetch_limit)
    filtered_fm_records = [r for r in fm_records if _has_digits_in_project_number(r.get("number"))]
    skipped_count = len(fm_records) - len(filtered_fm_records)
    if skipped_count:
        logger.info(
            "Skipping %d FM project records with blank or digitless ProjectNumber.",
            skipped_count,
        )

    pg_records = db.get_all(
        "projects",
        columns=["id", "number", "name", "drawings", "closed", "fmp_id_primary"],
    )

    to_add, to_update, to_remove = compute_diff(
        fm_data=filtered_fm_records,
        pg_data=pg_records,
        match_keys=entity.match_key,   # [fmp_id_primary]
    )

    logger.info("Projects diff: +%d ~%d -%d", len(to_add), len(to_update), len(to_remove))

    if dry_run:
        result.added = len(to_add)
        result.updated = len(to_update)
        result.removed = len(to_remove)
        return result

    with db.transaction():
        upsert_records = [_prepare_record(r) for r in to_add + to_update]
        if upsert_records:
            db.bulk_upsert(
                table="projects",
                records=upsert_records,
                conflict_columns=["fmp_id_primary"],
                update_columns=UPDATE_COLUMNS,
                extra_set={"last_synced_at": "NOW()"},
            )

        if to_remove:
            db.bulk_delete("projects", to_remove, match_column="fmp_id_primary")

    result.added = len(to_add)
    result.updated = len(to_update)
    result.removed = len(to_remove)
    return result


def _prepare_record(r: dict) -> dict:
    return {c: r.get(c) for c in PERSIST_COLUMNS}


def _has_digits_in_project_number(value: object) -> bool:
    if value is None:
        return False
    return bool(re.search(r"\d", str(value).strip()))
