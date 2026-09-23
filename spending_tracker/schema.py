"""Canonical transaction schema shared by the parser, Excel store and dashboard.

V1/V2 stored six columns (Date, Description, Amount, Type, Source Line, Added At).
V3 adds provenance and date-precision columns so historical rows migrated from the
old hand-maintained workbook stay traceable, and V4 adds Category.  Older workbooks
are upgraded in place, never rewritten from scratch, so no transaction is lost.
"""

from __future__ import annotations

import pandas as pd


VALID_TYPES = ["Expense", "Income", "Rent", "Investment"]

TRANSACTION_COLUMNS = [
    "Date",
    "Description",
    "Amount",
    "Type",
    "Category",
    "Source Line",
    "Source Period",
    "Source Sheet",
    "Source Reference",
    "Date Precision",
    "Added At",
]

# Columns that were present before V3; used to recognise legacy workbooks.
LEGACY_COLUMNS = ["Date", "Description", "Amount", "Type", "Source Line", "Added At"]

TEXT_COLUMNS = [
    "Description",
    "Type",
    "Category",
    "Source Line",
    "Source Period",
    "Source Sheet",
    "Source Reference",
    "Date Precision",
    "Added At",
]

# Date Precision values.  "Exact" means the source recorded a real transaction date.
# "Month" means only a month was known, "Period" only a school term / labelled block,
# and "Unknown" means no date information existed at all.
PRECISION_EXACT = "Exact"
PRECISION_MONTH = "Month"
PRECISION_PERIOD = "Period"
PRECISION_UNKNOWN = "Unknown"
DATE_PRECISIONS = [PRECISION_EXACT, PRECISION_MONTH, PRECISION_PERIOD, PRECISION_UNKNOWN]


def empty_transactions_frame() -> pd.DataFrame:
    frame = pd.DataFrame({column: pd.Series(dtype="object") for column in TRANSACTION_COLUMNS})
    frame["Amount"] = pd.Series(dtype="float64")
    return frame


def normalize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with every schema column present and consistently typed."""
    if df is None:
        return empty_transactions_frame()

    normalized = df.copy()
    for column in TRANSACTION_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    extra = [column for column in normalized.columns if column not in TRANSACTION_COLUMNS]
    normalized = normalized[TRANSACTION_COLUMNS + extra]

    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
    normalized["Amount"] = pd.to_numeric(normalized["Amount"], errors="coerce")
    for column in TEXT_COLUMNS:
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()

    missing_precision = normalized["Date Precision"].eq("")
    normalized.loc[missing_precision & normalized["Date"].notna(), "Date Precision"] = PRECISION_EXACT
    normalized.loc[missing_precision & normalized["Date"].isna(), "Date Precision"] = PRECISION_UNKNOWN
    return normalized
