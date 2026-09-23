"""Default file locations for this personal setup.

The historical workbook is read-only input; every write goes to the tracker copy
under ``outputs/`` or to the small JSON config files under ``data/``.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE_WORKBOOK = Path("/Users/chrislowzx/Downloads/Expenses/Chris 2023-2025 Spendings.xlsx")
DEFAULT_TRACKER_WORKBOOK = Path("outputs/Chris 2023-2025 Spendings - tracker copy.xlsx")
DEFAULT_OUTPUT_DIR = Path("outputs")
DEFAULT_DATA_DIR = Path("data")

__all__ = [
    "DEFAULT_DATA_DIR",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SOURCE_WORKBOOK",
    "DEFAULT_TRACKER_WORKBOOK",
    "PROJECT_ROOT",
]
