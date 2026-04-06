"""
CAAN sync: syncs caans table from FileMaker caan_table layout.
Note: CAANs.ID_Primary is Text in FM, normalised to integer (fmp_id_primary) in PG.
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
    "caan",
    "name",
    "description",
    "address_street",
    "address_city",
    "address_zip",
    "area",
]

UPDATE_COLUMNS = [
    "name",
    "description",
    "address_street",
    "address_city",
    "address_zip",
    "area",
    "fmp_id_primary",
]


def sync_caans(
    entity: EntityMapping,
    fm: FileMakerAdapter,
    db: Database,
    fetch_limit: int,
    dry_run: bool = False,
) -> SyncResult:
    result = SyncResult(entity="caans")

    fm_records = fetch_and_map(fm, entity, fetch_limit)
    pg_records = db.get_all("caans", columns=["id", "caan", "name", "description",
                                               "address_street", "address_city",
                                               "address_zip", "area", "fmp_id_primary"])

    to_add, to_update, to_remove = compute_diff(
        fm_data=fm_records,
        pg_data=pg_records,
        match_keys=entity.match_key,
    )

    logger.info("CAANs diff: +%d ~%d -%d", len(to_add), len(to_update), len(to_remove))

    if dry_run:
        result.added = len(to_add)
        result.updated = len(to_update)
        result.removed = len(to_remove)
        return result

    with db.transaction():
        # Upsert (add + update)
        upsert_records = [_prepare_record(r) for r in to_add + to_update]
        if upsert_records:
            db.bulk_upsert(
                table="caans",
                records=upsert_records,
                conflict_columns=["caan"],
                update_columns=UPDATE_COLUMNS,
                extra_set={"last_synced_at": "NOW()"},
            )

        # Hard delete — build minimal records with 'caan' for matching
        if to_remove:
            db.bulk_delete("caans", to_remove, match_column="caan")

    result.added = len(to_add)
    result.updated = len(to_update)
    result.removed = len(to_remove)
    return result


def _prepare_record(r: dict) -> dict:
    return {c: r.get(c) for c in PERSIST_COLUMNS}
