"""
Loads and validates field_mappings.yaml.
Provides transform functions for FM → PG data conversion.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transform functions
# ---------------------------------------------------------------------------

def _transform_strip(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().rstrip("\r").strip()
    return s if s else None


def _transform_boolean_yesno(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s == "yes":
        return True
    if s == "no":
        return False
    return None


def _transform_boolean_closed(value: Any) -> bool:
    """'Closed' → True, anything else (including None/empty) → False."""
    if value is None:
        return False
    return str(value).strip().lower() == "closed"


def _transform_integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        # FM sometimes returns floats for numeric fields
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


def _transform_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _transform_date(value: Any):
    """
    Convert a value to a Python date.
    Accepts: datetime.date, datetime.datetime, or a parseable string.
    Returns None for empty/unparseable values (e.g. CertofOcc text field).
    """
    import datetime

    if value is None or value == "":
        return None
    if isinstance(value, datetime.date):
        # datetime.datetime is a subclass of datetime.date; return just date
        if isinstance(value, datetime.datetime):
            return value.date()
        return value
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(str(value).strip()).date()
    except Exception:
        return None


TRANSFORM_REGISTRY: dict[str, Callable] = {
    "strip": _transform_strip,
    "boolean_yesno": _transform_boolean_yesno,
    "boolean_closed": _transform_boolean_closed,
    "integer": _transform_integer,
    "decimal": _transform_decimal,
    "date": _transform_date,
}


# ---------------------------------------------------------------------------
# Mapping dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FieldMapping:
    fm: str
    pg: str
    transform: str | None = None

    @property
    def is_lookup_only(self) -> bool:
        """Fields with pg names prefixed '_' are lookup-only (not written to DB)."""
        return self.pg.startswith("_")

    def apply(self, value: Any) -> Any:
        if self.transform is None:
            return value
        fn = TRANSFORM_REGISTRY.get(self.transform)
        if fn is None:
            logger.warning("Unknown transform '%s' for field '%s'; passing through raw.", self.transform, self.fm)
            return value
        return fn(value)


@dataclass
class EntityMapping:
    name: str
    fm_layout: str
    pg_table: str
    match_key: list[str]
    fields: list[FieldMapping]

    @property
    def persisted_fields(self) -> list[FieldMapping]:
        """Fields that are actually written to the DB (excludes lookup-only)."""
        return [f for f in self.fields if not f.is_lookup_only]

    @property
    def lookup_fields(self) -> list[FieldMapping]:
        return [f for f in self.fields if f.is_lookup_only]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_mappings(path: Path) -> dict[str, EntityMapping]:
    """Load field_mappings.yaml and return dict of entity name → EntityMapping."""
    with open(path, "r") as fh:
        raw = yaml.safe_load(fh)

    mappings: dict[str, EntityMapping] = {}
    for entity_name, entity_data in raw.items():
        fields = [
            FieldMapping(
                fm=str(f["fm"]),
                pg=str(f["pg"]),
                transform=f.get("transform"),
            )
            for f in entity_data.get("fields", [])
        ]
        mappings[entity_name] = EntityMapping(
            name=entity_name,
            fm_layout=entity_data["fm_layout"],
            pg_table=entity_data["pg_table"],
            match_key=entity_data["match_key"],
            fields=fields,
        )
    return mappings


def apply_mappings(fm_records: list[dict], entity: EntityMapping) -> list[dict]:
    """
    Apply field mappings and transforms to a list of raw FM records.
    Returns a list of dicts keyed by pg column names.
    """
    result = []
    for fm_record in fm_records:
        pg_record: dict[str, Any] = {}
        for field_map in entity.fields:
            raw_value = fm_record.get(field_map.fm)  # None if field absent (e.g. related field not on layout)
            pg_record[field_map.pg] = field_map.apply(raw_value)
        result.append(pg_record)
    return result
