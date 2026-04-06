"""
FileMaker Data API adapter for project_sync_service.

Derived from and hardening the patterns in development/reference/FMP.py:
  - Retry workflow with token refresh handling
  - Per-layout server context switching
  - Configurable timeout and SSL controls
  - Typed errors instead of generic exceptions
  - No pandas dependency — returns plain list[dict]

Do NOT import from development/reference/ at runtime.
"""
from __future__ import annotations

import logging
import warnings
from typing import Any

import fmrest
from urllib3.exceptions import InsecureRequestWarning

from .config import FileMakerConfig

logger = logging.getLogger(__name__)


class FileMakerError(Exception):
    """Raised for FileMaker API errors that cannot be recovered from."""


class FileMakerAuthError(FileMakerError):
    """Raised when FM credentials are invalid (error 212)."""


class FileMakerLayoutError(FileMakerError):
    """Raised when a layout cannot be found or accessed (error 105)."""


class FileMakerAdapter:
    """
    Thread-safe-ish (single-threaded usage) FileMaker Data API adapter.
    Manages a single fmrest.Server connection, switching layouts as needed.
    """

    MAX_RETRIES = 3

    def __init__(self, config: FileMakerConfig) -> None:
        self._config = config
        self._server: fmrest.Server | None = None
        warnings.filterwarnings("ignore", category=InsecureRequestWarning)
        # Apply timeout globally for fmrest module
        fmrest.utils.TIMEOUT = config.timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_records(self, layout_name: str, limit: int | None = None) -> list[dict[str, Any]]:
        """
        Fetch all records from a FileMaker layout.
        Returns a list of plain dicts keyed by FM field name.
        """
        if limit is None:
            limit = self._config.fetch_limit

        logger.debug("Fetching records from FM layout '%s' (limit=%d)", layout_name, limit)
        foundset = self._call("get_records", layout_name, limit=limit)

        if foundset is None:
            logger.info("FM layout '%s' returned no records (empty foundset).", layout_name)
            return []

        records = self._foundset_to_dicts(foundset)
        logger.info("Fetched %d records from FM layout '%s'.", len(records), layout_name)
        return records

    def check_layout(self, layout_name: str) -> bool:
        """Return True if the layout exists and is accessible. Does not raise."""
        try:
            self._ensure_server(layout_name)
            return True
        except FileMakerLayoutError:
            return False
        except Exception as exc:
            logger.warning("Layout check failed for '%s': %s", layout_name, exc)
            return False

    def ping(self) -> bool:
        """Return True if FM Server is reachable and credentials are valid."""
        try:
            # Pick any layout — we just need a successful login
            self._ensure_server(next(iter(["projects_table"])))
            return True
        except FileMakerAuthError:
            raise
        except Exception:
            return False

    def logout(self) -> None:
        if self._server and self._server._token:
            try:
                self._server.logout()
            except Exception:
                pass
            self._server = None

    def __enter__(self) -> "FileMakerAdapter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.logout()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_server(self, layout_name: str) -> fmrest.Server:
        """Return a logged-in fmrest.Server for the given layout, creating/switching as needed."""
        if self._server is None or self._server.layout != layout_name:
            # Logout from the old session if there was one with a different layout
            if self._server is not None and self._server._token:
                try:
                    self._server.logout()
                except Exception:
                    pass

            self._server = fmrest.Server(
                url=self._config.host,
                user=self._config.user,
                password=self._config.password,
                database=self._config.database,
                layout=layout_name,
                api_version=self._config.api_version,
                verify_ssl=self._config.verify_ssl,
            )
            fmrest.utils.TIMEOUT = self._config.timeout
            self._login()
        elif not self._server._token:
            self._login()

        return self._server

    def _login(self) -> None:
        """Attempt login with retries, raising typed errors on failure."""
        for attempt in range(self.MAX_RETRIES):
            try:
                success = self._server.login()
                if success:
                    return
            except fmrest.exceptions.FileMakerError as exc:
                if "212" in str(exc):
                    raise FileMakerAuthError(
                        f"FileMaker authentication failed — check FM_USER/FM_PASSWORD. ({exc})"
                    ) from exc
                if "105" in str(exc):
                    raise FileMakerLayoutError(
                        f"FileMaker layout not found or not accessible: '{self._server.layout}'. ({exc})"
                    ) from exc
                if attempt == self.MAX_RETRIES - 1:
                    raise FileMakerError(f"FM login failed after {self.MAX_RETRIES} attempts: {exc}") from exc
            except Exception as exc:
                if attempt == self.MAX_RETRIES - 1:
                    raise FileMakerError(f"FM login error after {self.MAX_RETRIES} attempts: {exc}") from exc
            logger.warning("FM login attempt %d/%d failed; retrying…", attempt + 1, self.MAX_RETRIES)

    def _call(self, method_name: str, layout_name: str, **kwargs: Any) -> Any:
        """
        Call a fmrest.Server method with retry logic.
        Handles bad-token (952) errors by re-logging in.
        Returns None for empty result sets (FM error 401).
        """
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                server = self._ensure_server(layout_name)
                method = getattr(server, method_name)
                return method(**kwargs)
            except fmrest.exceptions.FileMakerError as exc:
                exc_str = str(exc)
                if "401" in exc_str:
                    # Successful query with no results
                    return None
                if "952" in exc_str:
                    # Bad/expired token — force re-login on next iteration
                    logger.info("FM token expired (952); re-logging in (attempt %d).", attempt + 1)
                    if self._server and self._server._token:
                        try:
                            self._server.logout()
                        except Exception:
                            pass
                    self._server = None
                    last_exc = exc
                    continue
                if "212" in exc_str:
                    raise FileMakerAuthError(f"FM auth error during {method_name}: {exc}") from exc
                if "105" in exc_str:
                    raise FileMakerLayoutError(
                        f"FM layout '{layout_name}' not accessible during {method_name}: {exc}"
                    ) from exc
                last_exc = exc
                logger.warning(
                    "FM error on attempt %d/%d for %s on layout '%s': %s",
                    attempt + 1, self.MAX_RETRIES, method_name, layout_name, exc,
                )
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Error on attempt %d/%d for %s on layout '%s': %s",
                    attempt + 1, self.MAX_RETRIES, method_name, layout_name, exc,
                )

        raise FileMakerError(
            f"FM {method_name} on layout '{layout_name}' failed after {self.MAX_RETRIES} attempts."
        ) from last_exc

    @staticmethod
    def _foundset_to_dicts(foundset: Any) -> list[dict[str, Any]]:
        """Convert a fmrest Foundset to a list of plain dicts."""
        records = []
        for record in foundset:
            records.append(dict(record))
        return records
