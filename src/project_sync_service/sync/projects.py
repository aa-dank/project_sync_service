"""
Project sync: syncs projects table from FileMaker projects_table layout.
"""
from __future__ import annotations

import logging

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
    "fmp_id_primary",
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
    pg_records = db.get_all(
        "projects",
        columns=["id", "number", "name", "drawings", "closed", "fmp_id_primary"],
    )

    to_add, to_update, to_remove = compute_diff(
        fm_data=fm_records,
        pg_data=pg_records,
        match_keys=entity.match_key,   # [number]
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
                conflict_columns=["number"],
                update_columns=UPDATE_COLUMNS,
                extra_set={"last_synced_at": "NOW()"},
            )

        if to_remove:
            db.bulk_delete("projects", to_remove, match_column="number")

    result.added = len(to_add)
    result.updated = len(to_update)
    result.removed = len(to_remove)
    return result


def _prepare_record(r: dict) -> dict:
    return {c: r.get(c) for c in PERSIST_COLUMNS}
