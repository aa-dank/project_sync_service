"""
FileMaker adapter for project_sync_service.

This module keeps the sync service's small FileMaker interface stable while
delegating the actual Data API behavior to the shared bs_fmp_sdk package.
"""
from __future__ import annotations

import logging
from typing import Any

from bs_fmp_sdk import FileMakerClient
from bs_fmp_sdk import FileMakerConfig as SdkFileMakerConfig
from bs_fmp_sdk import FileMakerAuthError, FileMakerError, FileMakerLayoutError

from .config import FileMakerConfig

logger = logging.getLogger(__name__)


class FileMakerAdapter:
    """
    Compatibility wrapper around bs_fmp_sdk.FileMakerClient.

    The rest of this service expects get_records(layout_name, limit), ping(),
    check_layout(), logout(), and context-manager behavior.
    """

    def __init__(self, config: FileMakerConfig) -> None:
        self._config = config
        self._client = FileMakerClient(_to_sdk_config(config))

    def get_records(self, layout_name: str, limit: int | None = None) -> list[dict[str, Any]]:
        """
        Fetch records from a FileMaker layout.

        Returns plain dictionaries keyed by FileMaker field name.
        """
        if limit is None:
            limit = self._config.fetch_limit

        logger.debug("Fetching records from FM layout '%s' (limit=%d)", layout_name, limit)
        records = self._client.get_records(layout_name=layout_name, limit=limit)
        logger.info("Fetched %d records from FM layout '%s'.", len(records), layout_name)
        return records

    def check_layout(self, layout_name: str) -> bool:
        """Return True if the layout exists and is accessible. Does not raise."""
        return self._client.check_layout(layout_name)

    def ping(self) -> bool:
        """Return True if FM Server is reachable and credentials are valid."""
        return self._client.ping()

    def logout(self) -> None:
        self._client.logout()

    def __enter__(self) -> "FileMakerAdapter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.logout()


def _to_sdk_config(config: FileMakerConfig) -> SdkFileMakerConfig:
    return SdkFileMakerConfig(
        host=config.host,
        user=config.user,
        password=config.password,
        database=config.database,
        fetch_limit=config.fetch_limit,
        timeout=config.timeout,
        verify_ssl=config.verify_ssl,
        api_version=config.api_version,
    )
