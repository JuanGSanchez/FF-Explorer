"""
FF Explorer — Files/Folders Explorer
Juan García Sánchez, 2023-2026
License: GPLv3
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__: str = version("ff-explorer")
except PackageNotFoundError:  # package not installed (editable / dev environment)
    __version__ = "0.0.0.dev"

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    RemovalReport,
    CompressionReport,
    FFExplorerError,
    EmptySeedError,
    list_entries,
    entry_metadata,
    save_listing,
    remove_entries,
    compress_entries,
)

__all__ = [
    "__version__",
    "EntryKind",
    "MatchEntry",
    "RemovalReport",
    "CompressionReport",
    "FFExplorerError",
    "EmptySeedError",
    "list_entries",
    "entry_metadata",
    "save_listing",
    "remove_entries",
    "compress_entries",
]
