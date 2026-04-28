"""
PostgreSQL connection and operations for project_sync_service.
Uses psycopg3 (psycopg) — direct SQL, no ORM.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator

import psycopg
from psycopg.rows import dict_row

from .config import PostgresConfig

logger = logging.getLogger(__name__)


class Database:
    """Manages a single psycopg3 connection to PostgreSQL."""

    def __init__(self, config: PostgresConfig) -> None:
        self._config = config
        self._conn: psycopg.Connection | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                host=self._config.host,
                port=self._config.port,
                dbname=self._config.database,
                user=self._config.user,
                password=self._config.password,
                row_factory=dict_row,
            )
            logger.debug("Connected to PostgreSQL %s/%s", self._config.host, self._config.database)

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def ping(self) -> bool:
        """Return True if the database is reachable."""
        try:
            self.connect()
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("PG ping failed: %s", exc)
            return False

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, *_: Any) -> None:
        if self._conn and not self._conn.closed:
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
        self.close()

    @contextmanager
    def transaction(self) -> Generator["Database", None, None]:
        self.connect()
        try:
            yield self
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_all(self, table: str, columns: list[str] | None = None) -> list[dict[str, Any]]:
        """Fetch all rows from a table."""
        self.connect()
        col_expr = ", ".join(columns) if columns else "*"
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT {col_expr} FROM {table}")  # noqa: S608
            return cur.fetchall()

    def execute(self, sql: str, params: Any = None) -> None:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def fetchone(self, sql: str, params: Any = None) -> dict | None:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, sql: str, params: Any = None) -> list[dict]:
        self.connect()
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    # ------------------------------------------------------------------
    # Sync operations
    # ------------------------------------------------------------------

    def bulk_upsert(
        self,
        table: str,
        records: list[dict[str, Any]],
        conflict_columns: list[str],
        update_columns: list[str],
        extra_set: dict[str, str] | None = None,
    ) -> int:
        """
        INSERT … ON CONFLICT (conflict_columns) DO UPDATE SET …
        extra_set: additional INSERT values and SET clauses expressed as
        {column: sql_expr} (e.g. last_synced_at).
        Returns number of rows affected.
        """
        if not records:
            return 0

        self.connect()
        cols = list(records[0].keys())
        insert_cols = list(cols)
        value_exprs = [f"%({c})s" for c in cols]
        if extra_set:
            for col, expr in extra_set.items():
                if col not in insert_cols:
                    insert_cols.append(col)
                    value_exprs.append(expr)

        col_names = ", ".join(insert_cols)
        placeholders = ", ".join(value_exprs)
        conflict_target = ", ".join(conflict_columns)

        set_clauses = [f"{c} = EXCLUDED.{c}" for c in update_columns]
        if extra_set:
            set_clauses += [f"{col} = {expr}" for col, expr in extra_set.items()]

        if not set_clauses:
            # Nothing to update — treat as INSERT IGNORE
            do_update = "NOTHING"
        else:
            do_update = "UPDATE SET " + ", ".join(set_clauses)

        sql = (
            f"INSERT INTO {table} ({col_names})\n"
            f"VALUES ({placeholders})\n"
            f"ON CONFLICT ({conflict_target}) DO {do_update}"
        )

        total = 0
        with self._conn.cursor() as cur:
            for record in records:
                cur.execute(sql, record)
                total += cur.rowcount
        return total

    def bulk_delete(
        self,
        table: str,
        records: list[dict[str, Any]],
        match_column: str,
    ) -> int:
        """
        Hard-delete rows from table where match_column IN (values from records).
        Returns number of deleted rows.
        """
        if not records:
            return 0

        self.connect()
        values = [r[match_column] for r in records]
        # Use ANY for cleaner parameterisation
        sql = f"DELETE FROM {table} WHERE {match_column} = ANY(%s)"  # noqa: S608
        with self._conn.cursor() as cur:
            cur.execute(sql, (values,))
            return cur.rowcount
