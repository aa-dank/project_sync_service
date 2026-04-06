"""
Configuration dataclass and loader for project_sync_service.
Reads from environment variables (and optional .env file via python-dotenv).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    """Load .env from the project root (two levels above this file's package)."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)


@dataclass
class FileMakerConfig:
    host: str
    user: str
    password: str
    database: str
    fetch_limit: int = 100_000
    timeout: int = 300
    verify_ssl: bool = False
    api_version: str = "v1"


@dataclass
class PostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass
class AppConfig:
    fm: FileMakerConfig
    pg: PostgresConfig
    log_level: str = "INFO"
    mappings_path: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent / "config" / "field_mappings.yaml")


def load_config() -> AppConfig:
    """Load and return application configuration from environment variables."""
    _load_env()

    fm = FileMakerConfig(
        host=_require("FM_HOST"),
        user=_require("FM_USER"),
        password=_require("FM_PASSWORD"),
        database=os.environ.get("FM_DATABASE", "UCPPC"),
        fetch_limit=int(os.environ.get("FM_FETCH_LIMIT", "100000")),
        timeout=int(os.environ.get("FM_TIMEOUT", "300")),
        verify_ssl=os.environ.get("FM_VERIFY_SSL", "false").lower() == "true",
        api_version=os.environ.get("FM_API_VERSION", "v1"),
    )

    pg = PostgresConfig(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", "5432")),
        database=os.environ.get("PG_DATABASE", "business_services_db"),
        user=_require("PG_USER"),
        password=_require("PG_PASSWORD"),
    )

    return AppConfig(
        fm=fm,
        pg=pg,
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set.")
    return value
