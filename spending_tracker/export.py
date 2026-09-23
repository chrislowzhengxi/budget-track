"""CSV export of the normalized transactions."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from spending_tracker.schema import TRANSACTION_COLUMNS, normalize_transactions


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Schema-ordered copy with ISO dates, ready for CSV."""
    frame = normalize_transactions(df)[TRANSACTION_COLUMNS].copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    frame["Amount"] = pd.to_numeric(frame["Amount"], errors="coerce").round(2)
    return frame


def transactions_csv(df: pd.DataFrame) -> str:
    return export_frame(df).to_csv(index=False)


def export_filename(now: datetime | date | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d")
    return f"transactions-{stamp}.csv"


def write_csv(df: pd.DataFrame, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transactions_csv(df), encoding="utf-8")
    return path


__all__ = ["export_filename", "export_frame", "transactions_csv", "write_csv"]
