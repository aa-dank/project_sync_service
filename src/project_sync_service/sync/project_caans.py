"""
Project-CAAN join sync: syncs project_caans many-to-many table.

FM source fields:
    ID_Project → project_fmp_id (resolved to project_id via projects.fmp_id_primary)
    CAAN       → caan           (resolved to caan_id)

PG target table: project_caans (project_id, caan_id) — composite PK
"""
from __future__ import annotations

import logging

from ..db import Database
from ..fm_adapter import FileMakerAdapter
from ..mappings import EntityMapping
from .base import SyncResult, compute_diff, fetch_and_map

logger = logging.getLogger(__name__)


def sync_project_caans(
    entity: EntityMapping,
    fm: FileMakerAdapter,
    db: Database,
    fetch_limit: int,
    dry_run: bool = False,
) -> SyncResult:
    result = SyncResult(entity="project_caans")

    fm_records = fetch_and_map(fm, entity, fetch_limit)

    # Build lookup tables for resolution
    project_lookup = _build_project_lookup(db)
    caan_lookup = _build_caan_lookup(db)

    # Resolve IDs and build normalised records
    resolved: list[dict] = []
    unresolved = 0
    for record in fm_records:
        project_fmp_id = record.get("project_fmp_id")
        caan_code = str(record.get("caan", "") or "").strip()

        project_id = project_lookup.get(project_fmp_id)
        caan_id = caan_lookup.get(caan_code)

        if not project_id or not caan_id:
            unresolved += 1
            logger.debug(
                "Skipping project_caan: project_fmp_id='%s' caan='%s' — unresolvable.",
                project_fmp_id,
                caan_code,
            )
            continue

        resolved.append({
            "project_fmp_id": project_fmp_id,
            "project_id": project_id,
            "caan_id": caan_id,
        })

    if unresolved:
        logger.warning("Skipped %d project_caan records that couldn't be resolved.", unresolved)

    # Fetch existing PG join rows for diff
    pg_records = db.get_all("project_caans", columns=["project_id", "caan_id"])

    to_add, _, to_remove = compute_diff(
        fm_data=resolved,
        pg_data=pg_records,
        match_keys=["project_id", "caan_id"],
    )

    logger.info("ProjectCAANs diff: +%d -%d", len(to_add), len(to_remove))

    if dry_run:
        result.added = len(to_add)
        result.removed = len(to_remove)
        return result

    with db.transaction():
        for record in to_add:
            db.execute(
                "INSERT INTO project_caans (project_id, caan_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (record["project_id"], record["caan_id"]),
            )
        result.added = len(to_add)

        for record in to_remove:
            db.execute(
                "DELETE FROM project_caans WHERE project_id = %s AND caan_id = %s",
                (record["project_id"], record["caan_id"]),
            )
        result.removed = len(to_remove)

    return result


def _build_project_lookup(db: Database) -> dict[int, int]:
    rows = db.get_all("projects", columns=["id", "fmp_id_primary"])
    return {
        int(r["fmp_id_primary"]): r["id"]
        for r in rows
        if r["fmp_id_primary"] is not None
    }


def _build_caan_lookup(db: Database) -> dict[str, int]:
    rows = db.get_all("caans", columns=["id", "caan"])
    return {
        str(r["caan"]).strip(): r["id"]
        for r in rows
        if r["caan"]
    }
