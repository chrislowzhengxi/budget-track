"""Search, edit, delete and save transactions in the tracker workbook.

Every write goes through :func:`save_transactions`, which backs the workbook up
first and appends a line to a plain-text audit log next to it.  The historical
source workbook is never a target here - this module only ever sees the tracker copy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
import json
from pathlib import Path

import pandas as pd

from spending_tracker.categories import categorize_frame
from spending_tracker.excel_store import backup_workbook, load_transactions, replace_transactions
from spending_tracker.schema import TRANSACTION_COLUMNS, normalize_transactions


AUDIT_FILENAME = "transaction_audit.log"
EDITABLE_COLUMNS = ["Date", "Description", "Amount", "Type", "Category"]


def audit_log_path(workbook_path: Path) -> Path:
    return Path(workbook_path).parent / AUDIT_FILENAME


def record_audit(
    workbook_path: Path, action: str, details: Mapping[str, object] | None = None, now: datetime | None = None
) -> Path:
    path = audit_log_path(workbook_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": (now or datetime.now()).replace(microsecond=0).isoformat(sep=" "),
        "action": action,
        "workbook": str(workbook_path),
        "details": _jsonable(details or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def read_audit(workbook_path: Path, limit: int | None = None) -> list[dict[str, object]]:
    path = audit_log_path(workbook_path)
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries.reverse()
    return entries[:limit] if limit else entries


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if value != value:  # NaN
        return None
    return str(value)


def save_transactions(
    workbook_path: Path,
    frame: pd.DataFrame,
    action: str,
    details: Mapping[str, object] | None = None,
    make_backup: bool = True,
) -> int:
    """Replace the Transactions sheet with ``frame`` after backing the workbook up."""
    workbook_path = Path(workbook_path)
    backup = backup_workbook(workbook_path) if make_backup else None
    written = replace_transactions(workbook_path, frame)
    payload = dict(details or {})
    payload["rows_after"] = written
    if backup:
        payload["backup"] = str(backup)
    record_audit(workbook_path, action, payload)
    return written


def search_transactions(
    frame: pd.DataFrame,
    text: str | None = None,
    types: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Filter transactions by description text, Type, Category and date range."""
    if frame is None or frame.empty:
        return frame.copy() if frame is not None else pd.DataFrame(columns=TRANSACTION_COLUMNS)

    result = frame.copy()
    if text:
        needle = text.strip().lower()
        haystack = (
            result["Description"].fillna("").astype(str).str.lower()
            + " "
            + result.get("Source Line", pd.Series("", index=result.index)).fillna("").astype(str).str.lower()
        )
        result = result[haystack.str.contains(needle, regex=False)]
    if types:
        result = result[result["Type"].astype(str).isin(list(types))]
    if categories:
        result = result[result["Category"].fillna("").astype(str).isin(list(categories))]
    if start is not None or end is not None:
        dates = pd.to_datetime(result["Date"], errors="coerce")
        if start is not None:
            result = result[dates.dt.date >= start]
            dates = pd.to_datetime(result["Date"], errors="coerce")
        if end is not None:
            result = result[dates.dt.date <= end]
    return result


def update_transaction(frame: pd.DataFrame, row_index: object, changes: Mapping[str, object]) -> pd.DataFrame:
    """Return a copy of ``frame`` with one row's editable fields updated."""
    if row_index not in frame.index:
        raise KeyError(f"No transaction with index {row_index!r}")

    updated = frame.copy()
    for column, value in changes.items():
        if column not in EDITABLE_COLUMNS:
            raise ValueError(f"Column {column!r} is not editable")
        if column == "Amount":
            amount = float(value)
            if amount <= 0:
                raise ValueError("Amount must be greater than zero")
            updated.loc[row_index, column] = amount
        elif column == "Date":
            updated["Date"] = pd.to_datetime(updated["Date"], errors="coerce")
            updated.loc[row_index, column] = pd.to_datetime(value)
        else:
            updated.loc[row_index, column] = value
    return normalize_transactions(updated)


def delete_transactions(frame: pd.DataFrame, row_indexes: Iterable[object]) -> pd.DataFrame:
    """Return a copy of ``frame`` without the given rows."""
    wanted = list(row_indexes)
    missing = [index for index in wanted if index not in frame.index]
    if missing:
        raise KeyError(f"No transaction with index {missing!r}")
    return frame.drop(index=wanted).reset_index(drop=True)


def recategorize(
    workbook_path: Path,
    overwrite: bool = False,
    user_rules: Mapping[str, str] | None = None,
    make_backup: bool = True,
) -> dict[str, object]:
    """Fill in (or refresh) the Category column of the tracker workbook.

    With ``overwrite=False`` an existing non-blank Category is left alone, so manual
    corrections survive.
    """
    frame = load_transactions(workbook_path)
    if frame.empty:
        return {"rows": 0, "changed": 0, "written": 0}

    before = frame["Category"].fillna("").astype(str).tolist()
    updated = categorize_frame(frame, overwrite=overwrite, user_rules=user_rules)
    after = updated["Category"].fillna("").astype(str).tolist()
    changed = sum(1 for old, new in zip(before, after, strict=True) if old != new)
    if not changed:
        return {"rows": len(frame), "changed": 0, "written": 0}

    written = save_transactions(
        workbook_path,
        updated,
        action="recategorize",
        details={"overwrite": overwrite, "changed": changed},
        make_backup=make_backup,
    )
    return {"rows": len(frame), "changed": changed, "written": written}


__all__ = [
    "AUDIT_FILENAME",
    "EDITABLE_COLUMNS",
    "audit_log_path",
    "delete_transactions",
    "read_audit",
    "recategorize",
    "record_audit",
    "save_transactions",
    "search_transactions",
    "update_transaction",
]
