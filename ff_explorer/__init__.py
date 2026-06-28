"""
FF Explorer — Files/Folders Explorer
Juan García Sánchez, 2023-2026
License: GPLv3
"""

import logging
from importlib.metadata import version, PackageNotFoundError

# Library best-practice: attach a NullHandler to the top-level package logger
# so that "No handlers could be found for logger 'ff_explorer'" warnings never
# appear in applications that do not configure logging themselves.
logging.getLogger(__name__).addHandler(logging.NullHandler())

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
    configure_logging,
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
    "configure_logging",
]
