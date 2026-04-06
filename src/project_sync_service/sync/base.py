"""
Base sync logic: fetch-diff-upsert pattern shared by all entity syncs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..mappings import EntityMapping, apply_mappings

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    entity: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"{self.entity}: +{self.added} updated={self.updated} "
            f"removed={self.removed} errors={self.errors}"
        )


def compute_diff(
    fm_data: list[dict],
    pg_data: list[dict],
    match_keys: list[str],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Compare FM and PG records by match_keys.

    Returns:
        to_add    — records in FM but not in PG
        to_update — records in both FM and PG (content may have changed)
        to_remove — records in PG but not in FM (for hard delete)
    """
    pg_index: dict[tuple, dict] = {
        _make_key(r, match_keys): r for r in pg_data
    }
    fm_index: dict[tuple, dict] = {
        _make_key(r, match_keys): r for r in fm_data
    }

    to_add: list[dict] = []
    to_update: list[dict] = []

    for key, fm_record in fm_index.items():
        if key not in pg_index:
            to_add.append(fm_record)
        else:
            to_update.append(fm_record)

    to_remove: list[dict] = [
        pg_record for key, pg_record in pg_index.items()
        if key not in fm_index
    ]

    return to_add, to_update, to_remove


def _make_key(record: dict, keys: list[str]) -> tuple:
    """Build a tuple key from specified fields, normalising values for comparison."""
    return tuple(
        str(record.get(k, "")).strip().lower() if record.get(k) is not None else ""
        for k in keys
    )


def fetch_and_map(fm_adapter: Any, entity: EntityMapping, fetch_limit: int) -> list[dict]:
    """Fetch FM records for an entity and apply field mappings."""
    raw_records = fm_adapter.get_records(entity.fm_layout, limit=fetch_limit)
    mapped = apply_mappings(raw_records, entity)
    logger.debug("Mapped %d FM records for entity '%s'.", len(mapped), entity.name)
    return mapped
