"""
Project-CAAN join sync: syncs project_caans many-to-many table.

FM source fields:
  Projects::ProjectNumber → project_number (resolved to project_id)
  CAAN                    → caan          (resolved to caan_id)

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
        proj_num = str(record.get("project_number", "") or "").strip()
        caan_code = str(record.get("caan", "") or "").strip()

        project_id = project_lookup.get(proj_num)
        caan_id = caan_lookup.get(caan_code)

        if not project_id or not caan_id:
            unresolved += 1
            logger.debug(
                "Skipping project_caan: project_number='%s' caan='%s' — unresolvable.",
                proj_num, caan_code,
            )
            continue

        resolved.append({
            "project_number": proj_num,
            "caan": caan_code,
            "project_id": project_id,
            "caan_id": caan_id,
        })

    if unresolved:
        logger.warning("Skipped %d project_caan records that couldn't be resolved.", unresolved)

    # Fetch existing PG join rows for diff (use project_id + caan_id as keys)
    pg_records_raw = db.get_all("project_caans", columns=["project_id", "caan_id"])
    # Enrich PG records with business-key fields for diff comparison
    # We diff on project_number+caan (string keys) mapped back from IDs
    project_id_to_num = {v: k for k, v in project_lookup.items()}
    caan_id_to_code = {v: k for k, v in caan_lookup.items()}
    pg_records = [
        {
            "project_number": project_id_to_num.get(r["project_id"], ""),
            "caan": caan_id_to_code.get(r["caan_id"], ""),
            "project_id": r["project_id"],
            "caan_id": r["caan_id"],
        }
        for r in pg_records_raw
    ]

    to_add, _, to_remove = compute_diff(
        fm_data=resolved,
        pg_data=pg_records,
        match_keys=["project_number", "caan"],
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


def _build_project_lookup(db: Database) -> dict[str, int]:
    rows = db.get_all("projects", columns=["id", "number"])
    return {
        str(r["number"]).strip(): r["id"]
        for r in rows
        if r["number"]
    }


def _build_caan_lookup(db: Database) -> dict[str, int]:
    rows = db.get_all("caans", columns=["id", "caan"])
    return {
        str(r["caan"]).strip(): r["id"]
        for r in rows
        if r["caan"]
    }
