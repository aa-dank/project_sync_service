"""
Preflight validation: checks FM layouts/fields and PG connectivity before sync.
Used by the `project-sync validate` CLI command.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .db import Database
from .fm_adapter import FileMakerAdapter, FileMakerError
from .mappings import EntityMapping

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.failures) == 0


def run_preflight(
    fm: FileMakerAdapter,
    db: Database,
    mappings: dict[str, EntityMapping],
    fetch_limit: int,
) -> ValidationResult:
    result = ValidationResult()

    # 1. PostgreSQL connectivity
    _check_pg(db, result)

    # 2. FileMaker connectivity
    _check_fm(fm, result)

    # 3. FM layout existence and required field availability
    if "FileMaker unreachable" not in " ".join(result.failures):
        _check_fm_layouts(fm, mappings, fetch_limit, result)

    # 4. PostgreSQL table existence
    _check_pg_tables(db, mappings, result)

    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_pg(db: Database, result: ValidationResult) -> None:
    try:
        if db.ping():
            result.passed.append("PostgreSQL connection: OK")
        else:
            result.failures.append("PostgreSQL connection: FAILED — could not connect")
    except Exception as exc:
        result.failures.append(f"PostgreSQL connection: FAILED — {exc}")


def _check_fm(fm: FileMakerAdapter, result: ValidationResult) -> None:
    try:
        if fm.ping():
            result.passed.append("FileMaker connection: OK")
        else:
            result.failures.append("FileMaker connection: FAILED — could not connect")
    except Exception as exc:
        result.failures.append(f"FileMaker connection: FAILED — {exc}")


def _check_fm_layouts(
    fm: FileMakerAdapter,
    mappings: dict[str, EntityMapping],
    fetch_limit: int,
    result: ValidationResult,
) -> None:
    """Verify each entity's FM layout is accessible and spot-check required fields."""
    for entity_name, entity in mappings.items():
        layout = entity.fm_layout
        try:
            # Fetch a small sample to verify the layout and field names
            sample = fm.get_records(layout, limit=1)
            result.passed.append(f"FM layout '{layout}' ({entity_name}): accessible")

            if sample:
                _check_fm_fields(entity, sample[0], entity_name, result)
            else:
                result.warnings.append(
                    f"FM layout '{layout}' ({entity_name}): returned 0 records — cannot verify field names"
                )
        except FileMakerError as exc:
            result.failures.append(f"FM layout '{layout}' ({entity_name}): FAILED — {exc}")
        except Exception as exc:
            result.failures.append(f"FM layout '{layout}' ({entity_name}): ERROR — {exc}")


def _check_fm_fields(
    entity: EntityMapping,
    sample_record: dict[str, Any],
    entity_name: str,
    result: ValidationResult,
) -> None:
    """Compare expected FM fields against actual fields in a sample record."""
    actual_fields = set(sample_record.keys())
    for field_map in entity.fields:
        if field_map.fm in actual_fields:
            pass  # present and confirmed
        else:
            severity = "critical" if field_map.critical else "optional"
            # Related fields (containing "::") may be legitimately absent if relation has no match
            if "::" in field_map.fm:
                result.warnings.append(
                    f"  [{entity_name}] {severity.capitalize()} related field '{field_map.fm}' absent from sample record — "
                    f"may be a layout placement issue or empty relation."
                )
            else:
                if field_map.critical:
                    result.failures.append(
                        f"  [{entity_name}] Critical FM field '{field_map.fm}' NOT found in layout "
                        f"'{entity.fm_layout}' — sync for this entity should be blocked."
                    )
                else:
                    result.warnings.append(
                        f"  [{entity_name}] Optional FM field '{field_map.fm}' not found in layout "
                        f"'{entity.fm_layout}' — existing PG values will be preserved."
                    )


def _check_pg_tables(
    db: Database,
    mappings: dict[str, EntityMapping],
    result: ValidationResult,
) -> None:
    """Verify expected PG tables exist."""
    expected_tables = {m.pg_table for m in mappings.values()}
    for table in expected_tables:
        try:
            row = db.fetchone(
                "SELECT to_regclass(%s)::text AS tbl",
                (f"public.{table}",),
            )
            if row and row["tbl"]:
                result.passed.append(f"PG table '{table}': exists")
            else:
                result.failures.append(
                    f"PG table '{table}': NOT FOUND — create required tables/columns in PostgreSQL first"
                )
        except Exception as exc:
            result.failures.append(f"PG table '{table}': ERROR checking existence — {exc}")
