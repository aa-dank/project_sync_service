"""project_sync_service package."""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("project-sync-service")
except PackageNotFoundError:
    __version__ = "0.0.0"
