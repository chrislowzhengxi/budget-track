"""Warn about likely duplicate entries without blocking them.

Typing "uber 12" twice on the same day is usually a slip, but it is sometimes two
real rides, so this module only ever *reports* matches; the caller decides.
Historical-migration de-duplication is separate and deterministic - see
:mod:`spending_tracker.migration`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from spending_tracker.categories import normalize_merchant


@dataclass(frozen=True)
class DuplicateWarning:
    """A pending row that matches something already in the tracker (or the batch)."""

    row_index: int
    description: str
    amount: float
    transaction_date: date | None
    transaction_type: str
    matches: int
    source: str  # "workbook" or "batch"

    @property
    def message(self) -> str:
        where = "already in the tracker" if self.source == "workbook" else "repeated in this batch"
        date_text = self.transaction_date.isoformat() if self.transaction_date else "no date"
        return (
            f"{self.description} ${self.amount:,.2f} on {date_text} is {where} "
            f"({self.matches} match{'es' if self.matches != 1 else ''})."
        )


def duplicate_key(
    transaction_date: object, description: object, amount: object, transaction_type: object
) -> tuple[str, str, float, str]:
    """Identity used for the warning: date + normalized description + amount + type."""
    return (
        _date_text(transaction_date),
        normalize_merchant(description),
        _amount(amount),
        str(transaction_type or "").strip(),
    )


def _date_text(value: object) -> str:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or value != value:
        return ""
    return str(value).strip()[:10]


def _amount(value: object) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _as_date(value: object) -> date | None:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def existing_keys(frame: pd.DataFrame) -> dict[tuple[str, str, float, str], int]:
    counts: dict[tuple[str, str, float, str], int] = {}
    if frame is None or frame.empty:
        return counts
    for record in frame.to_dict("records"):
        key = duplicate_key(
            record.get("Date"), record.get("Description"), record.get("Amount"), record.get("Type")
        )
        counts[key] = counts.get(key, 0) + 1
    return counts


def find_duplicates(
    pending: Sequence[Mapping[str, object]] | pd.DataFrame, existing: pd.DataFrame
) -> list[DuplicateWarning]:
    """Duplicate warnings for rows about to be saved.

    Matches against the workbook and against earlier rows of the same batch.
    """
    records = pending.to_dict("records") if isinstance(pending, pd.DataFrame) else list(pending)
    known = existing_keys(existing)
    seen: dict[tuple[str, str, float, str], int] = {}
    warnings: list[DuplicateWarning] = []

    for index, record in enumerate(records):
        key = duplicate_key(
            record.get("Date"), record.get("Description"), record.get("Amount"), record.get("Type")
        )
        if not key[1] or key[2] <= 0:
            continue

        in_workbook = known.get(key, 0)
        in_batch = seen.get(key, 0)
        if in_workbook or in_batch:
            warnings.append(
                DuplicateWarning(
                    row_index=index,
                    description=str(record.get("Description") or ""),
                    amount=key[2],
                    transaction_date=_as_date(record.get("Date")),
                    transaction_type=key[3],
                    matches=in_workbook + in_batch,
                    source="workbook" if in_workbook else "batch",
                )
            )
        seen[key] = in_batch + 1

    return warnings


__all__ = ["DuplicateWarning", "duplicate_key", "existing_keys", "find_duplicates"]
